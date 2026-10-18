# LinguaFlow: локальный сервис перевода DOCX

Автономный NLP Worker для Java Desktop (JSON Lines, Windows standalone, неизменённые алгоритмы глоссария) описан в [nlp-worker/README.md](nlp-worker/README.md). Он работает отдельно от веб-сервиса.

## Установка на новый Windows-сервер

Запустите PowerShell **от имени администратора** в папке распакованного проекта:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1 -ListenOnLan -OpenFirewall
```

Инсталлятор копирует сервис в `C:\LinguaFlow`, создаёт виртуальное окружение,
устанавливает Python 3.11 (если его нет), Java 17, Python-зависимости, модели spaCy
для английского и немецкого, а также Okapi Framework 1.48.0. Он создаёт
`C:\LinguaFlow\start_linguaflow.bat` для запуска сервиса. API-ключи намеренно не
переносятся: задайте их на странице `settings.html` после запуска.

При необходимости можно задать другие пути:

```powershell
.\install_windows.ps1 -InstallPath 'D:\LinguaFlow' -WorkspaceRoot '\\server\translations' -OkapiPath 'D:\Okapi' -ListenOnLan -OpenFirewall
```

`-ListenOnLan` запускает сервер на всех сетевых интерфейсах, а `-OpenFirewall`
создаёт правило для TCP-порта 8000 в профиле Private.

## Запуск на Windows

1. Создайте виртуальное окружение: `python -m venv .venv`.
2. Установите зависимости: `.venv\Scripts\python -m pip install -r requirements.txt`.
3. Установите модели spaCy (один раз):
   `.venv\Scripts\python -m spacy download en_core_web_sm` и `.venv\Scripts\python -m spacy download de_core_news_sm`.
4. Проверьте наличие `C:\Users\propi\Documents\Okapi\tikal.exe` и доступ на запись в `C:\ai_trans`.
5. Запустите сервер двойным щелчком по `start_server.bat` или командой `.venv\Scripts\python run_server.py`.
6. Откройте `http://127.0.0.1:8000`.

Каждое задание создаёт папку `C:\ai_trans\ГГГГ.ММ.ДД_ЧЧ.ММ.СС` с подпапками `in`, `xliff`, `out`, `gloss`.

## Модель перевода

По умолчанию используется прямой OpenAI-совместимый endpoint LM Studio: `http://192.168.2.105:1234/v1/chat/completions`. Если в LM Studio загружена одна модель, сервис выберет её автоматически. Если загружено несколько моделей, укажите её идентификатор в `TRANSLATION_MODEL`. Для OpenAI или другого совместимого провайдера задайте перед запуском:

```powershell
$env:TRANSLATION_API_URL = 'https://api.openai.com/v1/chat/completions'
$env:TRANSLATION_API_KEY = '...'
$env:TRANSLATION_MODEL = 'gpt-4.1-mini'
.venv\Scripts\python run_server.py
```

По умолчанию пакет содержит 5 сегментов: это снижает риск тайм-аута на текущем LLM-сервере. При 504 пакет сразу делится на меньшие, без повторения такого же запроса. Число сегментов можно изменить переменной `TRANSLATION_BATCH_SIZE` (максимум 10), лимит ответа — `TRANSLATION_MAX_TOKENS` (по умолчанию 2000).

Полный список переменных: `TRANSLATION_WORKSPACE`, `TIKAL_EXE`, `TRANSLATION_API_URL`, `TRANSLATION_MODEL`, `TRANSLATION_API_KEY`, `TRANSLATION_REQUEST_TIMEOUT`, `TRANSLATION_API_RETRIES`, `TRANSLATION_BATCH_SIZE`, `TRANSLATION_MAX_TOKENS`.

## Память переводов (TMX → SQLite)

Раздел доступен из общего меню после входа. Памяти общие для пользователей сервиса.
При запуске через `start_server_2_0.bat` папка заданий по умолчанию — `C:\ai_trans_2_0`.


Откройте раздел «Память переводов» с главной страницы (`/memories.html`).
Мастер предлагает выбрать TMX, задать название и описание (необязательно),
указать точные коды языков из `xml:lang` и подтвердить импорт.
Для многоязычного TMX импортируется только выбранная пара. Дубликаты пар
объединяются; сегменты без нужных языков или с пустым текстом пропускаются.
После импорта показываются счётчики. Некорректный XML не оставляет частичной базы.

Памяти сохраняются в подпапке `memories` настроенной папки заданий, каждая в
отдельном SQLite-файле, и доступны после перезапуска. Изменение папки заданий
переключает также каталог памятей. SQLite можно скачать из раздела поиска.

Выберите память, введите текст оригинала и минимальный процент сходства.
Результаты отсортированы по сходству; показываются лучшие 50 совпадений.
100% означает совпадение после Unicode-нормализации, приведения регистра и
свёртки пробелов. Fuzzy использует нормализованное Indel-сходство RapidFuzz
по всему сегменту, а не семантический или подстрочный поиск. При обычном пороге
сходства сервис сначала выбирает кандидатов через trigram-индекс, затем точно
проверяет их RapidFuzz. При пороге ниже 50% используется полный просмотр,
поскольку безопасно сузить такую широкую выдачу нельзя. Встроенные TMX-коды
форматирования исключаются из поискового текста.

Поиск слов и фраз использует SQLite FTS5. Индексы для ранее загруженной памяти
создаются автоматически при первом поиске; этот первый запрос может выполняться
дольше и увеличивает размер SQLite-файла. Дальнейшие добавления и удаления сегментов
обновляют индексы автоматически. База работает в режиме WAL, поэтому чтение не блокируется
обычной записью; перед скачиванием WAL переносится в основной SQLite-файл.

Конвертер также доступен отдельно:

```powershell
python -m backend.translation_memory input.tmx output.sqlite --source en-US --target ru-RU --name "Моя память"
```

Существующий выходной файл не перезаписывается. Перед запуском обновите
зависимости: `python -m pip install -r requirements.txt`.
Проверки: `python -m unittest discover -s tests`.



## API памяти переводов

Базовый адрес локального сервиса: `http://127.0.0.1:8000`. Все ответы и запросы используют JSON, кроме импорта TMX, который использует `multipart/form-data`.

Для внешней интеграции передавайте API-ключ одним из способов:

```http
Authorization: Bearer lf_tm_...
```

```http
X-API-Key: lf_tm_...
```

Ключ действует только для маршрутов `/api/memories`. Права задаёт администратор:

| Право | Что разрешает |
| --- | --- |
| `can_read` | Список памятей, поиск, скачивание SQLite |
| `can_write` | Импорт TMX и запись отдельных сегментов |

Ключ, ограниченный одной памятью, видит только её. Такой ключ с правом записи может дополнять только эту память; создать новую память он не может. Ошибка авторизации возвращается с кодом `401`, недостаток права или доступ к другой памяти — `403`.

### 1. Список памятей

`GET /api/memories`

Требуется право чтения. Возвращает массив памятей с идентификаторами и языковыми кодами.

```bash
curl -H "Authorization: Bearer lf_tm_..." http://127.0.0.1:8000/api/memories
```

Пример элемента ответа:

```json
{
  "id": "a1b2c3d4-1111-2222-3333-444444444444",
  "name": "Немецко-русская память",
  "source_language": "de-DE",
  "target_language": "ru-RU",
  "count": 41815
}
```

### 2. Поиск сегментов

`GET /api/memories/{memory_id}/search`

Требуется право чтения. Поле `q` сохранено для совместимости и ищет по оригиналу. Для новых интеграций используйте `source_q` и `target_q`: можно передать одно поле или оба одновременно. При заполнении обоих полей сегмент должен удовлетворять обоим условиям.

| Параметр | Значение по умолчанию | Описание |
| --- | --- | --- |
| `source_q` | пусто | Запрос по оригиналу |
| `target_q` | пусто | Запрос по переводу |
| `q` | пусто | Устаревший эквивалент `source_q` |
| `mode` | `fuzzy` | `fuzzy`, `words`, `phrase` или `all` |
| `threshold` | `70` | Минимальное сходство 0–100; влияет только на Fuzzy |
| `limit` | `50` | Число результатов, от 1 до 200 |
| `respect_case` | `false` | Учитывать регистр |
| `use_regex` | `false` | Интерпретировать `source_q` и `target_q` как регулярные выражения Python |

Режимы поиска:

- `fuzzy` — сходство всего сегмента; `100` означает точное совпадение после нормализации регистра и пробелов.
- `words` — все заданные целые слова в любом порядке; пунктуация не учитывается.
- `phrase` — точная последовательность слов с границами слов.
- `all` — объединяет результаты `phrase`, `words` и `fuzzy` без повторов. Сначала точные результаты, затем фраза, слова и Fuzzy; внутри группы — по убыванию сходства.

#### Fuzzy-поиск по оригиналу

```bash
curl -G -H "Authorization: Bearer lf_tm_..." \
  --data-urlencode "source_q=Fahrzeugwartung" \
  --data-urlencode "mode=fuzzy" \
  --data-urlencode "threshold=75" \
  "http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/search"
```

#### Поиск по словам или фразе

```bash
# Все слова в любом порядке
curl -G -H "Authorization: Bearer lf_tm_..." \
  --data-urlencode "source_q=regelmäßige Wartung" \
  --data-urlencode "mode=words" \
  "http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/search"

# Точная фраза в переводе
curl -G -H "Authorization: Bearer lf_tm_..." \
  --data-urlencode "target_q=регулярное техническое обслуживание" \
  --data-urlencode "mode=phrase" \
  "http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/search"
```

#### Поиск одновременно по оригиналу и переводу

```bash
curl -G -H "Authorization: Bearer lf_tm_..." \
  --data-urlencode "source_q=Fahrzeug" \
  --data-urlencode "target_q=автомобиль" \
  --data-urlencode "mode=all" \
  --data-urlencode "threshold=70" \
  "http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/search"
```

#### Поиск регулярным выражением

При `use_regex=true` оба непустых поля запроса считаются регулярными выражениями. Синтаксис проверяется до поиска; ошибочное выражение даёт `422`.

```bash
curl -G -H "Authorization: Bearer lf_tm_..." \
  --data-urlencode "source_q=^Fehler\\s+\d+$" \
  --data-urlencode "target_q=^(Ошибка|Сбой)" \
  --data-urlencode "use_regex=true" \
  --data-urlencode "respect_case=false" \
  "http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/search"
```

Пример ответа поиска:

```json
{
  "mode": "fuzzy",
  "limit": 50,
  "results": [
    {
      "id": 17,
      "source": "Fahrzeugwartung durchführen",
      "target": "Выполнить техническое обслуживание автомобиля",
      "score": 82.4,
      "exact": false,
      "matched_modes": ["fuzzy"]
    }
  ]
}
```

### 3. Записать один сегмент

`POST /api/memories/{memory_id}/segments`

Требуется право записи. Этот метод предназначен для CAT-редакторов и других внешних систем: передайте пару оригинал–перевод в JSON. Необязательные поля `tuid` и `author` сохраняют внешний идентификатор и автора сегмента. `created_at` устанавливает сервер в UTC при первом добавлении. Одинаковая пара `source` + `target` не создаётся повторно: ответ вернёт `duplicate: true`.

```bash
curl -X POST -H "Authorization: Bearer lf_tm_..." -H "Content-Type: application/json" \
  -d '{"source":"Fahrzeugwartung durchführen","target":"Выполнить техническое обслуживание автомобиля","tuid":"editor-458","author":"CAT Editor"}' \
  http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/segments
```

Пример ответа:

```json
{
  "id": 41816,
  "source": "Fahrzeugwartung durchführen",
  "target": "Выполнить техническое обслуживание автомобиля",
  "author": "CAT Editor",
  "created_at": "2026-09-30T12:34:56.789012+00:00",
  "added": true,
  "duplicate": false
}
```

### 4. Удалить сегмент

`DELETE /api/memories/{memory_id}/segments/{segment_id}`

Требуется право записи. `segment_id` — значение поля `id`, полученное при добавлении сегмента или в результате поиска. Успешное удаление возвращает `204 No Content`; если сегмент уже удалён или не существует, возвращается `404`.

```bash
curl -X DELETE -H "Authorization: Bearer lf_tm_..." \
  http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/segments/41816
```

### 5. Скачать SQLite-память

`GET /api/memories/{memory_id}/download`

Требуется право чтения. Ответ — файл `memory-{memory_id}.sqlite`.

```bash
curl -L -H "Authorization: Bearer lf_tm_..." \
  -o memory.sqlite \
  "http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/download"
```

### 6. Скачать TMX

`GET /api/memories/{memory_id}/download-tmx`

Требуется право чтения. Сервис потоково формирует файл TMX 1.4, поэтому экспорт
большой памяти не загружается целиком в оперативную память. В `tuid` сохраняется
идентификатор сегмента, в `creationid` — автор, а в `creationdate` — дата создания
в формате UTC, если эти метаданные есть в базе.

```bash
curl -L -H "Authorization: Bearer lf_tm_..." \
  -o memory.tmx \
  "http://127.0.0.1:8000/api/memories/a1b2c3d4-1111-2222-3333-444444444444/download-tmx"
```

### 7. Импорт TMX

`POST /api/memories`

Требуется право записи. Обязательны `document`, `source_language`, `target_language`. Для новой памяти можно передать `name` и `description`. Чтобы добавить сегменты в существующую память, передайте `existing_memory_id`; имя и описание в этом случае не меняются. Языковая пара должна совпадать с существующей памятью. Дубликаты пар оригинал–перевод пропускаются.

```bash
# Создать новую память
curl -X POST -H "Authorization: Bearer lf_tm_..." \
  -F "document=@memory.tmx" \
  -F "name=Руководства" \
  -F "description=Импорт от 30 сентября" \
  -F "source_language=de-DE" \
  -F "target_language=ru-RU" \
  http://127.0.0.1:8000/api/memories

# Дополнить существующую память
curl -X POST -H "Authorization: Bearer lf_tm_..." \
  -F "document=@update.tmx" \
  -F "source_language=de-DE" \
  -F "target_language=ru-RU" \
  -F "existing_memory_id=a1b2c3d4-1111-2222-3333-444444444444" \
  http://127.0.0.1:8000/api/memories
```

### Управление API-ключами

Эти методы требуют обычной авторизованной cookie-сессии; административные — прав администратора. Секрет возвращается только при создании или замене и в базе хранится как SHA-256-хеш.

| Метод | Назначение |
| --- | --- |
| `POST /api/memories/{memory_id}/segments` | Записать один сегмент; требуется `can_write` |
| `DELETE /api/memories/{memory_id}/segments/{segment_id}` | Удалить один сегмент; требуется `can_write` |
| `GET /api/auth/api-keys` | Список своих ключей |
| `POST /api/auth/api-keys` | Создать свой ключ: `{ "name": "CAT" , "memory_id": null }` |
| `DELETE /api/auth/api-keys/{key_id}` | Отозвать свой ключ |
| `GET /api/admin/memory-api-keys` | Администратор: список всех ключей |
| `POST /api/admin/memory-api-keys` | Администратор: создать ключ для памяти или всех памятей |
| `PUT /api/admin/memory-api-keys/{key_id}` | Администратор: изменить ключ и права |
| `DELETE /api/admin/memory-api-keys/{key_id}` | Администратор: отозвать ключ |

Пример изменения ключа администратором. Передайте `secret: null`, чтобы сохранить текущий секрет, или новый `lf_tm_…`, чтобы сразу заменить его:

```bash
curl -b cookies.txt -X PUT -H "Content-Type: application/json" \
  -d '{"name":"CAT запись","memory_id":"a1b2c3d4-1111-2222-3333-444444444444","can_read":true,"can_write":true,"secret":null}' \
  http://127.0.0.1:8000/api/admin/memory-api-keys/12
```

Для ключа должно быть включено хотя бы одно право. При замене секрета новый ключ обязан начинаться с `lf_tm_` и не содержать пробелов.

