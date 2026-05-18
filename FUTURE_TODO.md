# AI Brainstorm — задачи на будущее

Чеклисты для планирования. Отмечайте выполненное: `- [x]`.

Блоки ниже можно **свернуть и развернуть** (клик по заголовку).

---

<details open>
<summary><strong>1. Форматы файлов</strong> — расширить поддержку загрузки в контекст</summary>

### Уже есть (для ориентира)

PDF, DOCX, RTF, ODT, EPUB, DOC (частично), PPTX/PPT, XLSX/XLS, JSON, CSV, TXT/MD/YAML/XML, HTML, изображения (OCR), аудио (транскрипт).

### Недостающие форматы — добавить в первую очередь

- [ ] **DOC (Word 97–2003)** — стабильное извлечение в Docker (LibreOffice headless или `antiword` в образе)
- [ ] **PPT (старый PowerPoint)** — конвертация в PPTX/PDF на backend, а не попытка читать как PPTX
- [ ] **MOBI / AZW / AZW3** — электронные книги Kindle (`mobi`, `ebooklib`/calibre)
- [ ] **SRT / VTT** — субтитры как файлы (прямой текст в контекст без YouTube API)
- [ ] **EML / MSG** — письма (тема, тело, вложения-метаданные)
- [ ] **IPYNB** — Jupyter Notebook (ячейки markdown + code outputs как текст)
- [ ] **TEX / BIB** — академические тексты и библиография
- [ ] **HEIC / HEIF** — фото с iPhone (конвертация в JPEG перед OCR)
- [ ] **SVG** — извлечение текста и alt/title из разметки
- [ ] **PARQUET / FEATHER** — табличные датасеты (краткое описание схемы + sample rows)

### Форматы — второй приоритет

- [ ] **ZIP / 7Z** — распаковка и обработка поддерживаемых файлов внутри (лимит размера и глубины)
- [ ] **Numbers / Key / Pages** — через экспорт пользователем или конвертер (сложно нативно)
- [ ] **Google NotebookLM export** — парсер, когда появится образец файла (JSON/ZIP)
- [ ] **FB2** — русскоязычные книги
- [ ] **DJVU** — сканы (OCR через djvulibre или конвертация в PDF)
- [ ] **WARC** — архивы веб-страниц (для исследовательских сценариев)

### Качество существующих форматов

- [ ] EPUB: оглавление и метаданные (title, author) в начале текста
- [ ] DOCX: таблицы и сноски, не только параграфы
- [ ] PPTX: заметки спикера (`notes slide`)
- [ ] PDF: улучшить порядок колонок на сложной вёрстке
- [ ] Excel: именованные диапазоны / несколько листов с лимитом по символам на лист

</details>

---

<details>
<summary><strong>2. Источники контекста</strong> — URL, YouTube, аудио, ссылки</summary>

- [ ] YouTube: fallback на распознавание речи видео (yt-dlp + Whisper), если нет субтитров
- [ ] YouTube: плейлисты (несколько видео одной ссылкой)
- [ ] URL: кэш успешно загруженных страниц (TTL, dedup по URL)
- [ ] URL: поддержка PDF по прямой ссылке (скачать → `file_extract`)
- [ ] URL: опциональный proxy / User-Agent rotation для «капризных» сайтов
- [ ] Аудио: пакетная транскрипция длинных файлов с прогрессом в UI
- [ ] Аудио: выбор языка транскрипции в UI
- [ ] Подкасты: RSS → эпизоды → транскрипт (отдельный тип источника)
- [ ] Вставка «сырого текста» большим блоком без файла (paste source)

</details>

---

<details>
<summary><strong>3. NotebookLM-подобный опыт</strong> — RAG, цитаты, обзоры</summary>

- [ ] Чанкинг источников и векторный индекс (локально или pgvector)
- [ ] Ответы с цитатами «источник + фрагмент» в UI
- [ ] Отдельный режим «только по загруженным источникам» (grounded brainstorm)
- [ ] Audio Overview / краткий подкаст по источникам (TTS + сценарий)
- [ ] Mind map / structured summary по всем источникам
- [ ] Сохранение «notebook» (набор источников + история) между сессиями

</details>

---

<details>
<summary><strong>4. Google и облачные интеграции</strong></summary>

- [ ] OAuth: Google Drive — импорт Docs/Slides/Sheets без ручного экспорта
- [ ] OAuth: выбор файлов из Drive в UI
- [ ] Notion / Confluence — импорт страницы по URL (API)
- [ ] Dropbox / OneDrive — ссылки на файлы (опционально)

</details>

---

<details>
<summary><strong>5. Backend и API</strong></summary>

- [ ] `POST /context/import` — загрузка нескольких файлов одним запросом (multipart batch)
- [ ] Webhook: уведомление по завершении длинной транскрипции / импорта URL
- [ ] Персистентные jobs для extract/import (как debate jobs)
- [ ] OpenAPI: примеры для всех типов источников
- [ ] Метрики Prometheus: время extract, ошибки по типу файла
- [ ] Redis для jobs при нескольких воркерах uvicorn

</details>

---

<details>
<summary><strong>6. Безопасность и лимиты</strong></summary>

- [ ] SSRF: периодический re-resolve DNS при редиректах
- [ ] Антивирус / magic-byte проверка загружаемых файлов
- [ ] Квоты на пользователя (если появится multi-user)
- [ ] Аудит-лог импорта URL (без сохранения полного HTML)
- [ ] Сканирование ZIP на zip-bomb (max uncompressed size)

</details>

---

<details>
<summary><strong>7. UI (Streamlit)</strong></summary>

- [ ] Превью извлечённого текста перед запуском brainstorm
- [ ] Список источников с иконкой типа и статусом (ok / warning / error)
- [ ] Drag-and-drop зона для всех типов в одном месте
- [ ] Синхронизация типов файлов только из `/health` (убрать дублирование default-списка)
- [ ] Прогресс-бар для долгих файлов (аудио, большой PDF)
- [ ] Тёмная тема / компактный layout

</details>

---

<details>
<summary><strong>8. Тесты, CI, документация</strong></summary>

- [ ] Фикстуры: по одному минимальному файлу на каждый формат в `tests/fixtures/`
- [ ] Интеграционные тесты `/context/import` с mock httpx
- [ ] CI: установка Tesseract + ffmpeg в GitHub Actions
- [ ] Документ «Матрица форматов»: формат → библиотека → ограничения
- [ ] README: раздел «Источники как NotebookLM» со скриншотами UI

</details>

---

<details>
<summary><strong>9. DevOps и продакшен</strong></summary>

- [ ] Docker: multi-stage образ с LibreOffice для DOC/PPT
- [ ] `requirements-audio.txt` в опциональный профиль compose
- [ ] Healthcheck: проверка Tesseract / ffmpeg / ключей Whisper
- [ ] Secrets только через env / vault, не в логах extract
- [ ] Horizontal scaling: вынести тяжёлый extract в worker-очередь (Celery/RQ)

</details>

---

<details>
<summary><strong>10. Продукт и модели</strong></summary>

- [ ] Выбор модели для «лёгкого» извлечения метаданных (title/summary источника)
- [ ] Авто-сжатие слишком длинного контекста через synthesis-модель перед brainstorm
- [ ] A/B: full vs light debate с учётом размера контекста
- [ ] Локализация сообщений об ошибках (EN/RU переключатель)

</details>

---

*Последнее обновление списка: май 2026. При закрытии задачи переносите пункт в CHANGELOG или PR description.*
