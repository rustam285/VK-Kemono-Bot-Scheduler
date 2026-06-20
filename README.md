# VK + Telegram Post Scheduler

Веб-приложение для автоматизации создания отложенных постов в VK-группе и Telegram-канале. Загружает медиа с Twitter/X, Reddit, YouTube, Bilibili и других платформ, группирует в посты и публикует по расписанию.

## Стек

- **Backend:** Python 3.13, FastAPI, Supabase, VK API, Telethon (MTProto)
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui
- **Медиа:** yt-dlp, gallery-dl, httpx
- **Telegram:** Telethon (MTProto) — отложенные посты в нативном разделе "Запланированные"

## Быстрый старт

### Требования

- Python 3.13
- Node.js 18+
- npm 9+
- uv (опционально, для быстрого обновления yt-dlp/gallery-dl)

### Установка

```bash
git clone https://github.com/rustam285/VK-Kemono-Bot-Scheduler.git
cd VK-Kemono-Bot-Scheduler

# Создать .env из примера и заполнить
cp .env.example .env
# Открыть .env и вписать SUPABASE_URL, SUPABASE_SERVICE_KEY, ENCRYPTION_KEY, VK_TOKEN, VK_GROUP_ID, VK_OWNER_ID

# Установить зависимости
npm install
npm run setup

# Запустить
npm start
```

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000/docs

### Альтернативный запуск (без npm)

```bash
# Windows
start.bat

# Linux / macOS
chmod +x start.sh && ./start.sh
```

## Конфигурация

### .env (инфраструктурные параметры)

| Переменная | Описание |
|------------|----------|
| `SUPABASE_URL` | URL проекта Supabase |
| `SUPABASE_SERVICE_KEY` | service_role ключ Supabase |
| `ENCRYPTION_KEY` | **Обязательный.** Ключ шифрования VK токена (AES-256). Генерация: `python -c "from services.crypto import generate_key; print(generate_key())"` |
| `VK_TOKEN` | Токен VK (bootstrap, для первого запуска) |
| `VK_GROUP_ID` | ID группы VK |
| `VK_OWNER_ID` | ID аккаунта модератора |
| `TG_API_ID` | API ID приложения Telegram (из my.telegram.org) |
| `TG_API_HASH` | API Hash приложения Telegram |
| `TG_PROXY` | SOCKS5/HTTP прокси для MTProto (опционально, для обхода DPI) |
| `LOG_LEVEL` | Уровень логирования (DEBUG/INFO/WARNING/ERROR) |
| `MAX_TEMP_SIZE_GB` | Макс. размер временных файлов (ГБ) |
| `MAX_CONCURRENT_TASKS` | Макс. одновременных задач публикации |

### settings.json (через UI на /settings)

Все операционные настройки (токен VK, таймзона, слоты, задержки) управляются через страницу `/settings` в интерфейсе.

## Функции

### VK
- **Извлечение медиа** из URL (YouTube, Twitter/X, Reddit, Bilibili, прямые ссылки)
- **3-шаговый мастер** создания постов (источники → планирование → предпросмотр)
- **Выбор платформы** — VK, Telegram или обе одновременно
- **Объединение** нескольких источников в один пост
- **Календарь** с цветной кодировкой типов постов (art/fursuit/video)
- **Автоматическое распределение** по временным слотам
- **Cookies** для авторизованных источников (Twitter/X)
- **Дедупликация** URL (предупреждение о дублях)
- **Retry** при ошибках загрузки (автоматическая повторная попытка)
- **Мониторинг** состояния парсеров (yt-dlp/gallery-dl degradation)

### Telegram (MTProto)
- **Отложенные посты** через Telethon — появляются в нативном разделе "Запланированные" Telegram
- **Редактирование и удаление** запланированных постов (с сохранением медиа через `DeleteScheduledMessagesRequest`)
- **Авторизация** через UI настроек (номер телефона → код → 2FA)
- **Поддержка альбомов** (2-10 фото в одном посте)
- **Автоограничение качества** видео для Telegram (≤50 МБ, перекодирование 720p→480p→360p)
- **FloodWait обработка** — автоматическое ожидание при лимитах Telegram
- **Кэширование** запланированных постов (TTL 30 сек)
- **Прокси** для обхода DPI-блокировки MTProto

### Общее
- **Шифрование** VK токена (AES-256, хранится как `enc:...` в settings.json)
- **Health check** с проверкой Supabase (`GET /api/health`)
- **Persistence** задач — восстанавливаются при рестарте сервера
- **Graceful shutdown** — SIGTERM/SIGINT сохраняет данные
- **Адаптивный UI** — мобильная навигация (нижние табы), drawer для деталей дня, карточки вместо таблиц
- **Последовательный запуск** — backend стартует первым, frontend ждёт его готовности

## Структура проекта

```
├── backend/
│   ├── main.py              # FastAPI app
│   ├── startup.py           # Запуск uvicorn (обновление yt-dlp в фоне)
│   ├── config.py            # Конфигурация
│   ├── routers/             # API endpoints
│   │   ├── telegram.py      # Telegram auth + scheduled posts
│   │   └── ...
│   ├── services/
│   │   ├── telegram_api.py  # Telethon MTProto клиент
│   │   ├── publisher.py     # Публикация (VK + TG)
│   │   └── ...
│   ├── models/              # Pydantic модели
│   └── database/
│       ├── create_tables.sql
│       └── add_tg_columns.sql
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── CreatePost/  # 3-шаговый мастер
│       │   ├── Calendar/    # Календарь постов
│       │   ├── Settings/    # Настройки (включая Telegram)
│       │   └── NoMedia/     # Посты без медиа
│       ├── components/      # UI компоненты (shadcn/ui)
│       └── api/             # API клиент (TanStack Query)
├── .env.example
├── package.json
├── wait-for-backend.js      # Ожидание готовности backend
└── start.bat / start.sh
```

## Telegram — Настройка

1. Получите `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org) → API development tools
2. Добавьте в `.env`:
   ```
   TG_API_ID=ваш_id
   TG_API_HASH=ваш_hash
   ```
3. Если MTProto блокируется провайдером — настройте прокси:
   ```
   TG_PROXY=socks5://127.0.0.1:10801
   ```
4. Выполните SQL-миграцию в Supabase (файл `backend/database/add_tg_columns.sql`)
5. Откройте `/settings` → секция "Telegram (MTProto)" → авторизуйтесь
6. Выберите канал для публикации
7. При создании поста выберите платформу: VK, Telegram или Оба

## Лицензия

MIT
