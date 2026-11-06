# API AniFolder Backend

Контракт REST API для фронтенда и ML. Базовый префикс: `/api/v1`. OpenAPI генерируется
автоматически и доступен по `/docs` (эталон для уже реализованных эндпоинтов,
этот документ — для согласований и будущих этапов).

Статусы: ✅ реализовано · 🚧 контракт согласован, реализация на этапах 3+

## Общие правила

- Авторизация: `Authorization: Bearer <access_token>`. Access-токен живёт 15 минут,
  обновляется через `POST /auth/refresh` (refresh-токен — 30 дней).
- Все тела и ответы — JSON, кодировка UTF-8.
- Даты — ISO 8601 (`2002-10-03`, `2024-01-15T12:30:00Z`).

### Ошибки

Единый формат для всех эндпоинтов:

```json
{
  "error": {
    "code": "ANIME_NOT_FOUND",
    "message": "Аниме с id=123 не найдено"
  }
}
```

При 422 в `details` массив ошибок валидации: `{type, loc, msg}` (значения полей не возвращаются).

### Пагинация

- Каталог — постраничная: `page` (с 1) и `limit` (≤ 50), ответ `{items, total, page, limit}`.
- Ленты и комментарии — курсорная: 🚧 запрос `cursor` + `limit`, ответ `{items, next_cursor}`,
  `next_cursor = null` — записи кончились. Курсор opaque, клиент не парсит.

## Здоровье сервиса ✅

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | Liveness: процесс жив |
| GET | `/health/readiness` | Readiness: БД доступна. 200 `{"status":"ok"}` / 503 `{"status":"unavailable"}` |

## Auth ✅

### POST /auth/register

Запрос:

```json
{ "username": "naruto_fan", "email": "user@example.com", "password": "password123" }
```

- `username`: `^[A-Za-z0-9_]{3,32}$` (совпадает с CHECK в БД), регистр при проверке занятости не важен.
- `email`: ≤ 254 символов, валидный email, регистр при проверке занятости не важен.
- `password`: 8–72 символа (bcrypt обрезает после 72 байт).

Ответ 201:

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "BdT0kC7v...",
  "token_type": "bearer",
  "user": { "id": 1, "username": "naruto_fan", "email": "user@example.com" }
}
```

Ошибки: 409 `USERNAME_TAKEN` · 409 `EMAIL_TAKEN` · 422 `VALIDATION_ERROR`.
Лимит: 3 регистрации в минуту с одного IP (429 `RATE_LIMITED`).

### POST /auth/login

Запрос: `{ "username": "naruto_fan", "password": "password123" }`

Ответ 200 — такой же, как у register. Ошибки: 401 `INVALID_CREDENTIALS` (единый текст для
«нет такого логина» и «неверный пароль»). Лимит: 5 попыток в минуту с одного IP.

### POST /auth/refresh

Запрос: `{ "refresh_token": "BdT0kC7v..." }`

Ответ 200 — новая пара токенов. Старый refresh-токен отзывается. Ошибки:
401 `INVALID_REFRESH_TOKEN` (не нашли) · 401 `REFRESH_TOKEN_EXPIRED` ·
401 `REFRESH_TOKEN_REUSED` (повторное использование — признак компрометации: **все**
сессии пользователя отозваны, нужен повторный вход).

## Каталог ✅

### GET /genres

Ответ 200 — массив:

```json
[
  { "id": 1, "name_ru": "Экшен", "name_en": "Action" },
  { "id": 19, "name_ru": null, "name_en": "Isekai" }
]
```

`name_ru` может быть `null` — показывать `name_en` (так бывает у жанров, появившихся после словаря переводов).

### GET /anime

Параметры: `page`, `limit` (≤ 50, по умолчанию 20), `search`, `genre_id`, `status`
(`announced|ongoing|released|hiatus|cancelled`), `kind`, `year_from`, `year_to`, `sort`
(`popular|date|rating|title`; при заданном `search` — релевантность по pg_trgm).

Ответ 200:

```json
{
  "items": [
    {
      "id": 42,
      "anilist_id": 20,
      "mal_id": 21,
      "title_ru": "Наруто",
      "title_en": "Naruto",
      "kind": "tv",
      "status": "released",
      "episodes": 220,
      "aired_on": "2002-10-03",
      "poster_url": "https://s4.anilist.co/.../large.jpg"
    }
  ],
  "total": 137,
  "page": 1,
  "limit": 20
}
```

Замечания: `title_ru` обычно `null` (в AniList русских названий нет — показывать `title_en`),
`mal_id`, `episodes`, `aired_on`, `poster_url` — nullable.

### GET /anime/{id}

Ответ 200 — карточка списка + описание, жанры и статистика:

```json
{
  "id": 42,
  "anilist_id": 20,
  "mal_id": 21,
  "title_ru": "Наруто",
  "title_en": "Naruto",
  "kind": "tv",
  "status": "released",
  "episodes": 220,
  "aired_on": "2002-10-03",
  "poster_url": "https://s4.anilist.co/.../large.jpg",
  "description": "Коноха. Родился мальчик...",
  "genres": [ { "id": 1, "name_ru": "Экшен", "name_en": "Action" } ],
  "stats": { "scores_count": 154, "avg_score": "8.12", "in_lists_count": 1240 }
}
```

`stats` — `null`, если тайтла ещё не касались пользователи; `avg_score` — строка (Decimal,
до двух знаков). Ошибки: 404 `ANIME_NOT_FOUND`.

## Список пользователя 🚧 (этап 3)

### PUT /me/list/{anime_id} · DELETE /me/list/{anime_id}

Запрос PUT: `{ "status": "watching", "score": 9, "episodes_watched": 12 }`
(`status`: `planned|watching|completed|on_hold|dropped`; `score` 1–10, опционально).

Ответ 200:

```json
{
  "anime_id": 42,
  "status": "watching",
  "score": 9,
  "episodes_watched": 12,
  "updated_at": "2026-11-06T10:20:00Z",
  "anime": { "...": "AnimeCard" }
}
```

Ошибки: 401 · 404 `ANIME_NOT_FOUND` · 422 `VALIDATION_ERROR` (оценка/прогресс вне диапазона).

### GET /me/recommendations

Ответ 200 — массив, отсортированный по `relevance` (backend сам исключает тайтлы из списка пользователя):

```json
[
  { "anime_id": 77, "relevance": 0.94, "anime": { "...": "AnimeCard" } }
]
```

Источник данных — таблица `recommendations`, которую пишет Recommendation Service.
Граница ответственности: ML считает и пишет в БД, backend только читает и фильтрует.

## Профили 🚧 (этап 3–4)

### GET /users/{username}

Ответ 200:

```json
{
  "id": 1,
  "username": "naruto_fan",
  "avatar_url": null,
  "bio": null,
  "created_at": "2026-10-01T12:00:00Z",
  "stats": {
    "planned": 12, "watching": 3, "completed": 48, "on_hold": 2, "dropped": 7,
    "scores_count": 48, "mean_score": "7.6"
  }
}
```

Ошибки: 404 `USER_NOT_FOUND`.

### GET /users/{username}/list?status=watching&page=1&limit=20

Ответ: `{items: UserListAnime[], total, page, limit}`, элемент — AnimeCard + поля записи
списка (см. `UserListAnime` на фронте).

## Лента активности 🚧 (этап 3–4)

### GET /users/{username}/activity?cursor=...&limit=20

Элементы ленты (курсорная пагинация, см. «Пагинация»):

```json
{
  "items": [
    {
      "id": 9812,
      "type": "scored",
      "anime_id": 42,
      "payload": { "score": 9 },
      "created_at": "2026-11-06T10:20:00Z",
      "anime": { "...": "AnimeCard" }
    }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0Ijoi..."
}
```

`type` и `payload` по типу события:

| type | payload | Когда пишется |
|---|---|---|
| `list_added` | `{ "status": "watching" }` | тайтла не было в списке |
| `status_changed` | `{ "from": "planned", "to": "watching" }` | смена статуса у существующей записи |
| `progress_updated` | `{ "episodes_watched": 12 }` | изменился прогресс (без смены статуса) |
| `scored` | `{ "score": 9 }` | выставлена/изменена оценка |
| `reviewed` | `{ "review_id": 123 }` | опубликован отзыв |
| `topic_created` | `{ "topic_id": 5 }` | создана тема (anime_id может быть null) |
| `commented` | `{ "topic_id": 5, "comment_id": 77 }` | комментарий (anime_id может быть null) |

`anime` — `null`, когда событие не про тайтл.

## Отзывы и сообщество 🚧 (этап 4–5)

### GET /anime/{id}/reviews?page=1&limit=20

`{items: Review[], total, page, limit}`; Review: `{id, user_id, username, score, text, created_at}`.

### POST /anime/{id}/reviews

Запрос: `{ "score": 9, "text": "..." }` (текст 1–20000, один отзыв на тайтл на пользователя).
Ошибки: 401 · 404 `ANIME_NOT_FOUND` · 409 `REVIEW_EXISTS`.

### PATCH /reviews/{id} · DELETE /reviews/{id}

Только автор. Ошибки: 401 · 403 `FORBIDDEN` · 404 `REVIEW_NOT_FOUND`.

### GET /topics?anime_id=...&page=1&limit=20 · POST /topics

Topic: `{id, author_id, username, anime_id, title, body, comments_count, created_at, last_comment_at}`.
Сортировка — по `last_comment_at DESC`.

### GET /topics/{id}/comments?cursor=...&limit=50 · POST /topics/{id}/comments

Comment: `{id, topic_id, author_id, username, parent_id, body, created_at}`.
`parent_id` — ответ на комментарий той же темы (проверяет БД).

## Совместимость вкусов 🚧 (этап 6)

### GET /users/{username}/compatibility

Ответ 200:

```json
{ "common_titles": 23, "compatibility": 0.81 }
```

`compatibility` — null, если общих оценок меньше порога (например, 5). Требуется авторизация.

## Справочник кодов ошибок

| HTTP | Код | Эндпоинты |
|---|---|---|
| 401 | `AUTHENTICATION_REQUIRED`, `INVALID_CREDENTIALS`, `TOKEN_EXPIRED`, `INVALID_TOKEN` | auth, защищённые роуты |
| 401 | `INVALID_REFRESH_TOKEN`, `REFRESH_TOKEN_EXPIRED`, `REFRESH_TOKEN_REUSED` | /auth/refresh |
| 403 | `FORBIDDEN` | чужой отзыв (этап 4) |
| 404 | `ANIME_NOT_FOUND`, `USER_NOT_FOUND`, `REVIEW_NOT_FOUND`, `TOPIC_NOT_FOUND` | каталог, профили |
| 409 | `USERNAME_TAKEN`, `EMAIL_TAKEN`, `REVIEW_EXISTS` | register, отзывы |
| 422 | `VALIDATION_ERROR` | везде, где тело/параметры |
| 429 | `RATE_LIMITED` | /auth/login, /auth/register |
| 500 | `INTERNAL_ERROR` | неожиданные сбои |
