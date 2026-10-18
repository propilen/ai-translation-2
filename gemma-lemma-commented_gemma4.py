# intercept.py
# Имя файла скрипта для mitmproxy. Сам комментарий ни на что не влияет.
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from urllib.parse import unquote, parse_qs
# unquote — декодирует URL-encoded текст, например %D0%BC -> русская буква.
# parse_qs — разбирает form-urlencoded тело запроса в словарь параметров.

from mitmproxy.http import Response
# Response нужен, чтобы вручную создать HTTP-ответ и вернуть его вместо ответа Google Translate.

from mitmproxy import ctx
# ctx — контекст mitmproxy. Через него читаются опции ctx.options и пишутся логи ctx.log.

import json
# json нужен для чтения JSON-запросов и формирования JSON-ответов.

import requests
# requests нужен для отправки запроса к локальной модели / LM Studio / OpenAI-compatible API.

import time
# time используется для замера времени выполнения запроса к модели.

import hashlib
# hashlib был нужен для кеша переводов, но сейчас кеш закомментирован.

import difflib
# difflib используется для нечёткого сравнения строк через SequenceMatcher.

import re
# re используется для регулярных выражений, например для токенизации русского текста.

import subprocess
# subprocess запускает внешний скрипт LOOK-UTF.py для fuzzy lookup / TM-поиска.

import os
# os используется для установки переменной окружения NO_PROXY.

import spacy
# spaCy используется для лемматизации английского и немецкого текста.

import pymorphy3
# pymorphy3 используется для морфологического анализа и лемматизации русского текста.


# 🔥 FIX: отключаем прокси для requests (иначе рекурсия через mitm)
os.environ["NO_PROXY"] = "*"
# Говорим requests не использовать прокси.
# Это важно, потому что иначе запрос из этого скрипта к LM Studio может снова попасть в mitmproxy.
# Тогда может возникнуть рекурсия: mitmproxy перехватил запрос -> requests отправил запрос через mitmproxy -> снова перехват.


#translation_cache = {}
# Раньше здесь был словарь кеша переводов.
# Сейчас он закомментирован, поэтому кеширование отключено.

morph_ru = None
# Глобальная переменная для русского морфологического анализатора pymorphy3.
# Сначала None, потом в init_nlp() сюда кладётся pymorphy3.MorphAnalyzer().

nlp_en = None
# Глобальная переменная для английской модели spaCy.
# Сначала None, потом сюда загружается en_core_web_sm.

nlp_de = None
# Глобальная переменная для немецкой модели spaCy.
# Сначала None, потом сюда загружается de_core_news_sm.

glossary_terms = []
# Глобальный список терминов глоссария.
# После загрузки TSV сюда попадают словари с source, target, lemmas и length.


# =========================
# MITMPROXY OPTIONS
# =========================
# Раздел настроек mitmproxy.
# Эти настройки можно передавать из командной строки через --set.


def load(loader):
    # Специальная функция mitmproxy.
    # mitmproxy вызывает её при загрузке скрипта.
    # loader позволяет зарегистрировать собственные параметры.

    loader.add_option("mt_glossary", str, "", "Path to TSV glossary: source<TAB>target")
    # Регистрирует параметр mt_glossary.
    # Тип: str.
    # Значение по умолчанию: пустая строка.
    # Назначение: путь к TSV-глоссарию.

    loader.add_option("mt_source_lang", str, "en", "Source language: en/de/ru")
    # Регистрирует параметр mt_source_lang.
    # Значение по умолчанию: en.
    # Используется как язык источника по умолчанию.

    loader.add_option("mt_target_lang", str, "ru", "Target language")
    # Регистрирует параметр mt_target_lang.
    # Значение по умолчанию: ru.
    # Используется как язык перевода по умолчанию.

    loader.add_option("mt_fuzzy_threshold", str, "0.86", "Fuzzy matching threshold, 0..1")
    # Регистрирует параметр mt_fuzzy_threshold.
    # Это порог похожести для fuzzy-сравнения терминов.
    # Хранится как строка, потом преобразуется в float.

    loader.add_option("mt_model_url", str, "https://gemma.ruserver.netcraze.pro/v1/chat/completions", "Model API URL")
    # Регистрирует адрес API модели.
    # В твоём случае это LM Studio или совместимый с OpenAI API сервер.

    loader.add_option("mt_db", str, "", "Path to local database file")
    # Регистрирует параметр mt_db.
    # В текущем коде этот параметр объявлен, но дальше практически не используется.


def running():
    # Специальная функция mitmproxy.
    # Вызывается, когда mitmproxy уже запустился и скрипт готов работать.

    init_nlp()
    # Загружает NLP-инструмент для языка mt_source_lang.

    load_global_glossary()
    # Загружает TSV-глоссарий в память.


# =========================
# NLP
# =========================
# Раздел лемматизации и токенизации.


def init_nlp():
    # Инициализирует нужный NLP-инструмент в зависимости от языка источника.

    global morph_ru, nlp_en, nlp_de
    # Объявляем, что внутри функции будем менять глобальные переменные.

    source_lang = ctx.options.mt_source_lang.lower()
    # Берём язык источника из настроек mitmproxy и приводим к нижнему регистру.

    if source_lang == "ru":
        # Если язык источника русский...

        morph_ru = pymorphy3.MorphAnalyzer()
        # Создаём русский морфологический анализатор.

    elif source_lang == "en":
        # Если язык источника английский...

        nlp_en = spacy.load("en_core_web_sm", disable=["parser", "ner"])
        # Загружаем английскую модель spaCy.
        # parser отключён, потому что синтаксический анализ не нужен.
        # ner отключён, потому что распознавание именованных сущностей не нужно.

    elif source_lang == "de":
        # Если язык источника немецкий...

        nlp_de = spacy.load("de_core_news_sm", disable=["parser", "ner"])
        # Загружаем немецкую модель spaCy с отключёнными parser и ner.

    else:
        # Если язык не ru, en или de...

        raise ValueError("mt_source_lang must be en/de/ru")
        # Прерываем выполнение с ошибкой.


def tokenize_ru(text):
    # Токенизирует русский текст простым регулярным выражением.

    return re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text.lower())
    # text.lower() приводит текст к нижнему регистру.
    # re.findall(...) извлекает последовательности букв и цифр.
    # Пунктуация, пробелы и спецсимволы отбрасываются.
    # Важно: регулярка также допускает латиницу и цифры.


def lemmatize_ru(text):
    # Лемматизирует русский текст.

    return [morph_ru.parse(w)[0].normal_form for w in tokenize_ru(text)]
    # tokenize_ru(text) разбивает текст на токены.
    # morph_ru.parse(w) возвращает варианты разбора слова.
    # [0] берёт самый вероятный вариант.
    # normal_form берёт начальную форму слова.
    # Например: "машины" -> "машина".


def lemmatize_en(text):
    # Лемматизирует английский текст через spaCy.

    doc = nlp_en(text.lower())
    # Прогоняет текст через английскую модель spaCy.

    return [t.lemma_.lower() for t in doc if not t.is_punct and not t.is_space]
    # Для каждого токена берётся lemma_.
    # Пунктуация и пробелы исключаются.
    # Леммы приводятся к нижнему регистру.


def lemmatize_de(text):
    # Лемматизирует немецкий текст через spaCy.

    doc = nlp_de(text.lower())
    # Прогоняет текст через немецкую модель spaCy.

    return [t.lemma_.lower() for t in doc if not t.is_punct and not t.is_space]
    # Возвращает список лемм без пунктуации и пробелов.


def lemmatize(text, lang):
    # Общая функция лемматизации.
    # Выбирает конкретный лемматизатор по языку.

    lang = lang.lower()
    # Приводим язык к нижнему регистру.

    if lang == "ru":
        # Если язык русский...

        return lemmatize_ru(text)
        # Используем pymorphy3.

    if lang == "en":
        # Если язык английский...

        return lemmatize_en(text)
        # Используем английскую spaCy-модель.

    if lang == "de":
        # Если язык немецкий...

        return lemmatize_de(text)
        # Используем немецкую spaCy-модель.

    raise ValueError("lang must be en/de/ru")
    # Если передали другой язык, выбрасываем ошибку.


# =========================
# GLOSSARY
# =========================
# Раздел загрузки TSV-глоссария.


def load_global_glossary():
    # Загружает глоссарий из TSV-файла в глобальный список glossary_terms.

    global glossary_terms
    # Указываем, что будем менять глобальную переменную glossary_terms.

    path = ctx.options.mt_glossary
    # Берём путь к TSV-файлу из настроек mitmproxy.

    source_lang = ctx.options.mt_source_lang.lower()
    # Берём язык источника из настроек mitmproxy.
    # ВАЖНО: в этой версии кода именно этот язык используется для лемматизации глоссария.

    glossary_terms = []
    # Очищаем список терминов перед загрузкой.

    if not path:
        # Если путь к глоссарию не задан...

        ctx.log.warn("[MT] No glossary file provided")
        # Пишем предупреждение в лог mitmproxy.

        return
        # Выходим из функции.

    with open(path, encoding="utf-8") as f:
        # Открываем TSV-файл в UTF-8.

        for line_no, line in enumerate(f, start=1):
            # Проходим по строкам файла.
            # line_no — номер строки, начиная с 1.
            # line — содержимое строки.

            line = line.strip()
            # Убираем пробелы и переводы строк по краям.

            if not line or line.startswith("#"):
                # Если строка пустая или начинается с #...

                continue
                # Пропускаем её.

            parts = line.split("\t")
            # Разделяем строку по табуляции.
            # Ожидается формат: source<TAB>target.

            if len(parts) < 2:
                # Если в строке меньше двух колонок...

                ctx.log.warn(f"[MT] Bad glossary line {line_no}: {line}")
                # Пишем предупреждение с номером плохой строки.

                continue
                # Пропускаем эту строку.

            source = parts[0].strip()
            # Берём первую колонку как исходный термин.
            # strip() убирает лишние пробелы.

            target = parts[1].strip()
            # Берём вторую колонку как перевод термина.

            if not source or not target:
                # Если source или target пустые...

                continue
                # Пропускаем строку.

            lemmas = lemmatize(source, source_lang)
            # Лемматизируем исходный термин по языку mt_source_lang.
            # Например: "машины" -> ["машина"].

            if not lemmas:
                # Если лемматизация дала пустой список...

                continue
                # Пропускаем термин.

            glossary_terms.append({
                "source": source,
                "target": target,
                "lemmas": lemmas,
                "length": len(lemmas)
            })
            # Добавляем термин в глобальный список.
            # source — исходный термин из TSV.
            # target — перевод из TSV.
            # lemmas — лемматизированная форма source.
            # length — количество лемм, нужно для поиска многословных терминов.

    glossary_terms.sort(key=lambda x: x["length"], reverse=True)
    # Сортируем термины по длине от длинных к коротким.
    # Это помогает сначала находить многословные термины.

    ctx.log.info(f"[MT] Loaded glossary terms: {len(glossary_terms)}")
    # Пишем в лог количество загруженных терминов.


# =========================
# FUZZY LOOKUP
# =========================
# Раздел обращения к внешнему скрипту LOOK-UTF.py.


def lookup_fuzzy(query):
    # Ищет похожие фразы/переводы через внешний скрипт LOOK-UTF.py.

    try:
        # Начинаем блок, в котором возможны ошибки.

        result = subprocess.run(
            # Запускаем внешний процесс.

            ["python", "LOOK-UTF.py", query],
            # Команда:
            # python LOOK-UTF.py "<текст запроса>"

            capture_output=True,
            # Забираем stdout и stderr в объект result.

            text=True,
            # Просим вернуть stdout/stderr как строки, а не bytes.

            encoding="utf-8"
            # Указываем кодировку UTF-8.
        )

        lines = result.stdout.splitlines()
        # Берём stdout внешнего скрипта и разбиваем его на строки.

        matches = []
        # Сюда будут складываться найденные fuzzy-совпадения.

        for line in lines:
            # Проходим по каждой строке вывода LOOK-UTF.py.

            line = line.strip()
            # Убираем пробелы по краям.

            if not line.startswith("["):
                # Если строка не начинается с [, значит она не похожа на результат...

                continue
                # Пропускаем строку.

            try:
                # Пытаемся распарсить одну строку результата.

                score_end = line.find("]")
                # Ищем позицию закрывающей скобки ].
                # Ожидаемый формат примерно: [95.0] source -> target.

                score = float(line[1:score_end])
                # Берём число между [ и ] и превращаем в float.

                rest = line[score_end + 1:].strip()
                # Берём оставшуюся часть строки после ].

                if "->" not in rest:
                    # Если нет разделителя source -> target...

                    continue
                    # Пропускаем строку.

                src, tgt = rest.split("->", 1)
                # Делим строку на source и target только по первому ->.

                matches.append({
                    "source": src.strip(),
                    "target": tgt.strip(),
                    "score": score
                })
                # Добавляем найденное совпадение в список.

            except Exception:
                # Если конкретная строка плохо распарсилась...

                continue
                # Просто пропускаем её.

        matches.sort(key=lambda x: x["score"], reverse=True)
        # Сортируем совпадения по score от большего к меньшему.

        return matches[:3]
        # Возвращаем максимум 3 лучших совпадения.

    except Exception as e:
        # Если весь запуск LOOK-UTF.py упал...

        ctx.log.warn(f"[MT] LOOK error: {e}")
        # Пишем предупреждение в лог.

        return []
        # Возвращаем пустой список.


# =========================
# GLOSSARY MATCHING (FIX)
# =========================
# Раздел поиска терминов глоссария в тексте.


def similarity(a, b):
    # Считает похожесть двух строк.

    if a == b:
        # Если строки полностью совпали...

        return 1.0
        # Возвращаем максимальную похожесть.

    return difflib.SequenceMatcher(None, a, b).ratio()
    # Иначе считаем похожесть через SequenceMatcher.
    # Результат от 0.0 до 1.0.


def token_matches(text_token, term_token, threshold):
    # Проверяет, совпадает ли токен из текста с токеном термина.

    if text_token == term_token:
        # Если токены совпадают точно...

        return True
        # Это совпадение.

    if len(text_token) <= 3 or len(term_token) <= 3:
        # Если один из токенов слишком короткий...

        return False
        # Fuzzy-сравнение не применяем.
        # Это защита от ложных совпадений коротких слов.

    return similarity(text_token, term_token) >= threshold
    # Возвращаем True, если похожесть выше или равна порогу.


def match_term_at(words, start_index, term, threshold):
    # Проверяет, начинается ли термин term в списке words с позиции start_index.

    lemmas = term["lemmas"]
    # Берём леммы термина из глоссария.

    if start_index + len(lemmas) > len(words):
        # Если термин не помещается в оставшийся хвост текста...

        return False
        # Совпадения быть не может.

    for offset, term_lemma in enumerate(lemmas):
        # Проходим по каждой лемме термина.
        # offset — смещение от start_index.
        # term_lemma — очередная лемма термина.

        word = words[start_index + offset]
        # Берём соответствующее слово из текста.

        if not token_matches(word, term_lemma, threshold):
            # Если слово из текста не совпало с леммой термина...

            return False
            # Весь термин не совпал.

    return True
    # Если все слова совпали, термин найден в этой позиции.


def find_glossary_terms(text, lang):
    # Ищет термины глоссария в переданном тексте.

    if not glossary_terms:
        # Если глоссарий пустой...

        return None
        # Ничего искать.

    words = lemmatize(text, lang)
    # Лемматизируем входной текст по языку lang.
    # Получаем список нормальных форм слов.

    threshold = float(ctx.options.mt_fuzzy_threshold)
    # Берём fuzzy-порог из настроек mitmproxy и превращаем строку в число.

    found = []
    # Сюда будут складываться найденные термины.

    occupied = [False] * len(words)
    # Массив занятых позиций.
    # Нужен, чтобы один и тот же фрагмент текста не был использован несколькими терминами.

    i = 0
    # Индекс текущего слова в тексте.

    while i < len(words):
        # Идём по всем словам текста.

        if occupied[i]:
            # Если текущая позиция уже занята найденным термином...

            i += 1
            # Переходим к следующей позиции.

            continue
            # Пропускаем остальную логику цикла.

        best = None
        # Лучший термин, найденный на текущей позиции.
        # Нужен, если несколько терминов подходят одновременно.

        for term in glossary_terms:
            # Перебираем все термины глоссария.

            length = term["length"]
            # Длина термина в леммах.

            if i + length > len(words):
                # Если термин не помещается начиная с позиции i...

                continue
                # Пропускаем этот термин.

            if any(occupied[i:i + length]):
                # Если хотя бы одна позиция диапазона уже занята...

                continue
                # Не используем этот термин.

            if match_term_at(words, i, term, threshold):
                # Проверяем, совпадает ли термин с текстом начиная с позиции i.

                if best is None or term["length"] > best["length"]:
                    # Если ещё нет лучшего термина
                    # или текущий термин длиннее найденного ранее...

                    best = term
                    # Запоминаем его как лучший.

        if best:
            # Если на текущей позиции найден термин...

            found.append({
                "source": best["source"],
                "target": best["target"]
            })
            # Добавляем source и target найденного термина в список результатов.

            for j in range(i, i + best["length"]):
                # Проходим по позициям слов, которые покрывает термин.

                occupied[j] = True
                # Помечаем эти позиции как занятые.

            i += best["length"]
            # Перепрыгиваем сразу за найденный термин.

        else:
            # Если термин на текущей позиции не найден...

            i += 1
            # Просто переходим к следующему слову.

    unique = {}
    # Словарь для удаления дублей.
    # Ключ — source, значение — target.

    for item in found:
        # Проходим по найденным терминам.

        unique[item["source"]] = item["target"]
        # Если один и тот же source встретился несколько раз, он останется один.

    return [{"source": s, "target": t} for s, t in unique.items()] or None
    # Возвращаем список словарей вида:
    # [{"source": "...", "target": "..."}]
    # Если список пустой, возвращаем None.


# =========================
# REQUEST PARSING (FIX)
# =========================
# Раздел извлечения текста и языков из HTTP-запроса.


def extract_text_from_request(flow):
    # Извлекает text, source_lang и target_lang из запроса Google Translate.

    source_lang = ctx.options.mt_source_lang or "auto"
    # Значение языка источника по умолчанию.
    # Берётся из настроек mitmproxy.
    # Если там пусто, используется "auto".

    target_lang = ctx.options.mt_target_lang or "ru"
    # Значение языка перевода по умолчанию.
    # Если настройка пустая, используется "ru".

    text = ""
    # Переменная для текста, который нужно перевести.

    method = flow.request.method.upper()
    # Берём HTTP-метод запроса и приводим к верхнему регистру.
    # Например: GET или POST.

    if method == "GET":
        # Если запрос GET...

        text = unquote(flow.request.query.get("q", ""))
        # Берём параметр q из query string.
        # Это текст для перевода.
        # unquote декодирует URL-encoding.

        source_lang = flow.request.query.get("source", source_lang)
        # Берём source из query string.
        # Если его нет, оставляем значение по умолчанию.

        target_lang = flow.request.query.get("target", target_lang)
        # Берём target из query string.
        # Если его нет, оставляем значение по умолчанию.

        return text, source_lang, target_lang
        # Возвращаем извлечённые значения.

    if method == "POST":
        # Если запрос POST...

        content_type = flow.request.headers.get("Content-Type", "").lower()
        # Берём Content-Type запроса и приводим к нижнему регистру.

        content = flow.request.content
        # Берём тело запроса как bytes.

        if "application/x-www-form-urlencoded" in content_type:
            # Если тело запроса в формате HTML-формы...

            try:
                # Пробуем распарсить тело.

                body_str = content.decode("utf-8")
                # Декодируем bytes в строку UTF-8.

                params = parse_qs(body_str, keep_blank_values=True)
                # Разбираем строку формы в словарь.
                # keep_blank_values=True сохраняет пустые значения.

                text = unquote(params.get("q", [""])[0])
                # Берём первый параметр q.
                # Если q нет, используем пустую строку.

                source_lang = params.get("source", [source_lang])[0]
                # Берём первый source.
                # Если source нет, оставляем дефолт.

                target_lang = params.get("target", [target_lang])[0]
                # Берём первый target.
                # Если target нет, оставляем дефолт.

            except Exception as e:
                # Если парсинг формы упал...

                print(f"[MT] Failed to parse form request: {e}")
                # Печатаем ошибку.

        elif "application/json" in content_type:
            # Если тело запроса в JSON...

            try:
                # Пробуем распарсить JSON.

                body_json = json.loads(content.decode("utf-8"))
                # Декодируем bytes в строку и парсим JSON.

                text = unquote(body_json.get("q", ""))
                # Берём поле q из JSON.

                source_lang = body_json.get("source", source_lang)
                # Берём поле source из JSON.

                target_lang = body_json.get("target", target_lang)
                # Берём поле target из JSON.

            except Exception as e:
                # Если JSON не распарсился...

                print(f"[MT] Failed to parse JSON request: {e}")
                # Печатаем ошибку.

    return text, source_lang, target_lang
    # Возвращаем результат.
    # Если ничего не нашли, text будет пустой строкой.


# =========================
# CACHE
# =========================
# Раздел кеша сейчас закомментирован.


#def get_cache_key(text, source_lang, target_lang, glossary=None):
#    # Функция должна была создавать ключ кеша для перевода.
#
#    #key_data = {
#        #"text": text,
#        #"source_lang": source_lang,
#        #"target_lang": target_lang,
#        #"glossary": glossary or []
#    #}
#    # Данные, из которых строится уникальный ключ.
#
#    #key_string = json.dumps(key_data, ensure_ascii=False, sort_keys=True)
#    # Превращаем данные в стабильную JSON-строку.
#    # sort_keys=True нужен, чтобы порядок ключей был одинаковым.
#
#    #return hashlib.md5(key_string.encode("utf-8")).hexdigest()
#    # Возвращаем MD5-хеш строки.
#    # Сейчас не используется, потому что функция закомментирована.


# =========================
# PROMPT
# =========================
# Раздел формирования промпта для модели.


def build_prompt(text, source_lang, target_lang, glossary=None, fuzzy=None):
    # Создаёт текст инструкции, который будет отправлен модели.

    parts = []
    # Список строк промпта.
    # В конце они будут объединены через "\n".

    parts.append("Translate the text exactly. Preserve xliff-tags and placeholders. Use non-breaking space before translated units of measurements.")
    # Инструкция: перевести текст точно.
    parts.append("Before sending result clear text of service messages in angle brackets.")
    parts.append("Translate GUI items and leave original text in round brackets. Example: Menu item = Пункт меню (Menu item).")

    parts.append("Return only translation.")
    # Инструкция: вернуть только перевод, без объяснений.

    parts.append(f"Source: {source_lang}. Target: {target_lang}.")
    # Добавляем языки перевода.

    if glossary:
        # Если есть найденные термины глоссария...

        parts.append("\nGlossary (strict):")
        # Добавляем заголовок строгого глоссария.

        for item in glossary:
            # Проходим по найденным терминам.

            parts.append(f'- "{item["source"]}" -> "{item["target"]}"')
            # Добавляем пару source -> target в промпт.

    if fuzzy:
        # Если есть fuzzy-совпадения из LOOK-UTF.py...

        parts.append("\nFuzzy TM (reference):")
        # Добавляем заголовок fuzzy-памяти переводов.

        for item in fuzzy:
            # Проходим по найденным fuzzy-совпадениям.

            parts.append(f'- "{item["source"]}" -> "{item["target"]}" (score {item["score"]:.1f})')
            # Добавляем найденную пару и score.
            # :.1f означает число с одним знаком после запятой.

    parts.append("\nTEXT:")
    # Добавляем заголовок текста.

    parts.append(text)
    # Добавляем сам текст для перевода.

    return "\n".join(parts)
    # Склеиваем все строки промпта через перенос строки и возвращаем.


# =========================
# TRANSLATE
# =========================
# Раздел отправки запроса к модели.


def translate_text(text, source_lang="auto", target_lang="ru", glossary=None, fuzzy=None, timeout=120):
    # Отправляет текст, глоссарий и fuzzy-подсказки в модель.

    #cache_key = get_cache_key(text, source_lang, target_lang, glossary)
    # Раньше здесь создавался ключ кеша.

    #if cache_key in translation_cache:
    #    # Если перевод уже был в кеше...
    #    #return translation_cache[cache_key]
    #    # Можно было бы вернуть его без обращения к модели.

    prompt = build_prompt(text, source_lang, target_lang, glossary, fuzzy)
    # Формируем промпт для модели.

    user_message = {
        "role": "user",
        "content": prompt,
        "glossary": glossary or [],
        "fuzzy": fuzzy or []
    }
    # Формируем сообщение пользователя в формате OpenAI Chat Completions.
    # role=user — это пользовательское сообщение.
    # content — основной промпт.
    # glossary и fuzzy добавлены отдельными полями, хотя большинство OpenAI-compatible API их просто игнорирует.

    data = {
        "model": "google/gemma-4-31b",
        "messages": [user_message],
        "temperature": 0.2,
        "max_tokens": 2000
    }
    # JSON-тело запроса к модели.
    # model — имя модели.
    # messages — список сообщений.
    # temperature=0.2 делает ответы более стабильными.
    # max_tokens=2000 ограничивает длину ответа.

    try:
        # Начинаем блок отправки HTTP-запроса.

        response = requests.post(
            # Отправляем POST-запрос.

            ctx.options.mt_model_url,
            # URL модели берётся из настроек mitmproxy.

            json=data,
            # requests сам сериализует data в JSON.

            timeout=timeout,
            # Максимальное время ожидания ответа.

            proxies={"http": None, "https": None}
            # Явно отключаем прокси для этого запроса.
        )

        print("[MT] STATUS:", response.status_code)
        # Печатаем HTTP-статус ответа модели.
        print("[MT] RAW:", response.text[:300])
        #print("[MT] RAW:", response.text[:300].encode("ascii", errors="backslashreplace").decode("ascii"))
        # Печатаем первые 300 символов сырого ответа модели.
        # Полезно для отладки.

        if response.status_code == 200:
            # Если API вернул успешный статус...

            translation = response.json()["choices"][0]["message"]["content"].strip()
            # Парсим JSON-ответ.
            # Достаём content из первого choices.
            # strip() убирает пробелы и переносы строк по краям.

            #translation_cache[cache_key] = translation
            # Раньше здесь перевод сохранялся в кеш.

            return translation
            # Возвращаем перевод.

        return None
        # Если статус не 200, считаем перевод неудачным.

    except Exception as e:
        # Если при запросе произошла ошибка...

        ctx.log.warn(f"[MT] error: {e}")
        # Пишем ошибку в лог mitmproxy.

        return None
        # Возвращаем None как признак ошибки.


# =========================
# REQUEST
# =========================
# Главный mitmproxy hook, который вызывается на каждый HTTP-запрос.


def request(flow):
    # mitmproxy вызывает эту функцию для каждого проходящего запроса.
    # flow содержит request и позже может получить response.

    host = flow.request.pretty_host.lower()
    # Получаем host запроса и приводим к нижнему регистру.
    # Например: translation.googleapis.com.

    if ":" in host:
        # Если в host есть порт, например localhost:1234...

        host = host.split(":")[0]
        # Отбрасываем порт и оставляем только имя хоста.

    # ✅ FIX: вернули фильтр пути
    if "translation.googleapis.com" not in host:
        # Если это не запрос к Google Translate API...

        return
        # Ничего не делаем, пропускаем запрос дальше.

    if "/language/translate/v2" not in flow.request.path:
        # Если путь не похож на Google Translate v2 endpoint...

        return
        # Ничего не делаем.

    print("[MT HIT]", flow.request.pretty_url)
    # Печатаем, что нужный запрос пойман.
    # pretty_url — полный URL запроса.

    text, source_lang, target_lang = extract_text_from_request(flow)
    # Извлекаем текст и языки из запроса.

    if not text:
        # Если текст пустой...

        return
        # Сейчас код просто ничего не подменяет и выходит.
        # В старой версии ты возвращал пустой JSON-ответ.

    glossary_lang = ctx.options.mt_source_lang.lower()

    print(f"[MT] Request languages: {source_lang} -> {target_lang}")
    print(f"[MT] Glossary language from options: {glossary_lang}")

    glossary = find_glossary_terms(text, glossary_lang)
    fuzzy = lookup_fuzzy(text)

    translation = translate_text(
        text,
        source_lang,
        target_lang,
        glossary=glossary,
        fuzzy=fuzzy
    )
    # Отправляем текст, языки, глоссарий и fuzzy-подсказки в модель.

    if translation is None:
        # Если модель не вернула перевод...

        translation = "[ERROR] " + text
        # Возвращаем ошибку вместе с исходным текстом.

    flow.response = Response.make(
        # Создаём искусственный HTTP-ответ.
        # Он заменит настоящий ответ Google Translate.

        200,
        # HTTP-статус ответа.

        json.dumps({
            "data": {
                "translations": [
                    {"translatedText": translation}
                ]
            }
        }).encode("utf-8"),
        # Формируем JSON в формате, похожем на Google Translate API.
        # translatedText содержит перевод.
        # В конец добавляется " (gemma)" для пометки, что ответ дала локальная модель.
        # encode("utf-8") превращает строку в bytes.

        {"Content-Type": "application/json"}
        # Заголовок ответа.
        # Сообщает клиенту, что тело ответа — JSON.
    )