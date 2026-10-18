# Автономный NLP Worker

Отдельный процесс для Java Desktop: UTF-8 JSON Lines через stdin/stdout, один запрос и один ответ на строку. `worker.py` обрабатывает протокол, `protocol.py` валидирует запросы и хранит подготовленные глоссарии. Лемматизация, чтение TSV и поиск вызываются **непосредственно из `backend/nlp_glossary.py`**; алгоритм и веб-сервис не меняются. `java-client/` содержит асинхронный Java API, консольную демонстрацию и smoke test; `tests/` сравнивает worker с прямыми вызовами; `build_windows.ps1` собирает дистрибутив.

## Протестированное окружение

Windows x64, Python 3.11.9, pymorphy3 2.0.6, pymorphy3-dicts-ru 2.4.417150.4580142, spaCy 3.8.16, `en_core_web_sm` 3.8.0, `de_core_news_sm` 3.8.0, Java/Javac 25.0.1. Для сборки выбран Nuitka 4.2.2. Объём готового дистрибутива и потребление памяти не приводятся до измерения на собранном EXE.

## Запуск из исходников и сборка

В корне репозитория:

```powershell
.\.venv\Scripts\python.exe nlp-worker\worker.py
```

Каждый запрос вводится одной строкой JSON. Для сборки используйте Windows x64, Python 3.11 x64, C-компилятор (здесь используется Visual Studio/MSVC `cl 14.5`) и отдельное виртуальное окружение либо уже настроенную `.venv`. Скрипт проверяет точные версии основных библиотек и моделей и завершится с ошибкой, если они отличаются. Сборка может скачивать служебные компоненты Nuitka; готовый worker работает офлайн.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r nlp-worker\requirements-build.txt
.\.venv\Scripts\python.exe -m pip install "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
.\.venv\Scripts\python.exe -m pip install "https://github.com/explosion/spacy-models/releases/download/de_core_news_sm-3.8.0/de_core_news_sm-3.8.0-py3-none-any.whl"
powershell -NoProfile -ExecutionPolicy Bypass -File nlp-worker\build_windows.ps1
```

Скрипт использует Nuitka standalone с плагином spaCy, включает обе языковые модели, словари pymorphy3 и ресурсы пакетов. Итоговый каталог — `nlp-worker/dist/worker.dist/`; **переносить его целиком**, запускать `nlp-worker.exe` внутри каталога. Python и виртуальное окружение на клиентском ПК не требуются, если EXE успешно проходит проверку в чистой Windows-среде. Сборка запускает `ping` на готовом EXE. Для полного теста:

```powershell
$env:NLP_WORKER_EXE = (Resolve-Path nlp-worker\dist\worker.dist\nlp-worker.exe).Path
.\.venv\Scripts\python.exe -B -m unittest discover -s nlp-worker/tests -v
```

Тест с `NLP_WORKER_EXE` выполняет те же проверки как на исходном Python-процессе, так и на EXE. Запуск на ПК без установленного Python следует проверить отдельно: временно удалить Python из `PATH` или использовать чистую виртуальную машину. Дистрибутив собран для Windows x64; наличие совместимого системного runtime и ограничений безопасности ОС проверяется при развёртывании.

## Протокол

Поле `id` — непустая строка или целое число, задаётся клиентом и возвращается без изменений. Клиент должен присваивать уникальный `id` каждому запросу. Процесс последовательно обрабатывает много запросов. `ping` не загружает модели; нужный язык инициализируется при первой лемматизации или загрузке глоссария и затем переиспользуется. Языки: `ru`, `en`, `de`. `lang` должен совпадать с языком загруженного глоссария. `threshold` — конечное число от 0 до 1, по умолчанию `0.86`.

| action | Поля | Успешный ответ, помимо `id` и `ok:true` |
| --- | --- | --- |
| `ping` | — | `status:"ready"` |
| `lemmatize` | `lang`, `text` | `lemmas:[...]` |
| `lemmatize_batch` | `lang`, `texts:[...]` | `lemmas:[[...], ...]` |
| `load_glossary` | `glossary_id`, `lang`, `path` к TSV | `count:число` |
| `find_terms` | `glossary_id`, `lang`, `text`, необязательный `threshold` | `terms:[{"source":"...","target":"..."}]` |
| `find_terms_batch` | `glossary_id`, `lang`, `texts:[...]`, необязательный `threshold` | `terms:[[...], ...]` |
| `unload_glossary` | `glossary_id` | `unloaded:true` |
| `shutdown` | — | `status:"shutdown"`, затем процесс завершится |

Пример последовательных строк:

```json
{"id":1,"action":"ping"}
{"id":2,"action":"lemmatize","lang":"ru","text":"красивыми автомобилями"}
{"id":3,"action":"load_glossary","glossary_id":"audi","lang":"de","path":"C:\\glossaries\\audi.tsv"}
{"id":4,"action":"find_terms","glossary_id":"audi","lang":"de","text":"Die Fahrzeuge werden überprüft","threshold":0.86}
{"id":5,"action":"find_terms_batch","glossary_id":"audi","lang":"de","texts":["Die Fahrzeuge","Die Motoren"]}
{"id":6,"action":"unload_glossary","glossary_id":"audi"}
{"id":7,"action":"shutdown"}
```

TSV читается с `utf-8-sig`; пустые и начинающиеся с `#` строки пропускаются, используются первые два поля, порядок и сортировка терминов совпадают с `load_glossary()`. Перезагрузка того же `glossary_id` заменяет его только после успешной подготовки. Поиск возвращает `[]`, если совпадений нет. Пакетный ответ сохраняет один список на каждый входной сегмент.

Ошибка — `{"id":7,"ok":false,"error":{"code":"GLOSSARY_NOT_FOUND","message":"..."}}`. Коды: `INVALID_JSON`, `INVALID_REQUEST`, `UNKNOWN_ACTION`, `UNSUPPORTED_LANGUAGE`, `NLP_MODEL_ERROR`, `GLOSSARY_FILE_NOT_FOUND`, `GLOSSARY_READ_ERROR`, `GLOSSARY_NOT_FOUND`, `LANGUAGE_MISMATCH`, `INVALID_THRESHOLD`, `INTERNAL_ERROR`. Для повреждённой JSON-строки `id:null`. Ошибка одного запроса не завершает процесс. Диагностика пишется только в stderr. Закрытие stdin также завершает worker.

## Java 25

`java-client` использует Jackson 2.17.3 и Maven. Сборка: `mvn -f nlp-worker/java-client/pom.xml package`. Демонстрация ожидает путь к EXE и TSV:

```powershell
mvn -f nlp-worker/java-client/pom.xml exec:java `
  -Dexec.mainClass=local.linguaflow.nlp.Demo `
  -Dexec.args='C:\path\to\worker.dist\nlp-worker.exe C:\path\to\terms.tsv'
```

`NlpWorkerClient` запускает процесс через `ProcessBuilder`, читает stdout и stderr в отдельных потоках, сопоставляет ответы по `id`, возвращает `CompletableFuture<JsonNode>` и применяет тайм-аут. Создавайте и закрывайте клиент вне Swing EDT; `request()` можно вызывать с EDT, а результат обрабатывайте через `thenAccept`/`whenComplete` с передачей изменений интерфейса в `SwingUtilities.invokeLater`. Вызов `.get()` с EDT запрещён: он блокирует интерфейс. При неожиданном завершении процесса ожидающие запросы получают исключение. `close()` отправляет `shutdown` и при необходимости завершает процесс принудительно. Smoke test охватывает 100 поисковых запросов, вызов с EDT, ошибку протокола и неожиданное завершение процесса.

## Проверки и ограничения

`tests/test_worker.py` сравнивает ответы с прямыми вызовами исходных функций для ru/en/de, пустого текста, Unicode, пунктуации, словоформ, многословных/пересекающихся/повторяющихся и коротких терминов, порогов `0`, `0.85`, `0.86`, `1`; отдельно отправляет 1000 запросов в один процесс. Существующий веб-сервис сохраняет собственный путь вызова NLP и не зависит от worker.

Работа последовательная. Один `glossary_id` привязан к одному языку. Большие словари занимают оперативную память; модели также остаются в процессе после загрузки. Для поиска используется исходный `SequenceMatcher`; скорость поиска зависит от размера глоссария. Протокол не поддерживает параллельное выполнение запросов внутри worker, отмену запроса или потоковую выдачу частичного результата.
