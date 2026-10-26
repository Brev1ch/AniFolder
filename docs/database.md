# База данных

PostgreSQL 16. Схема соответствует разделу «Схема базы данных» в README.

## Быстрый старт

```bash
docker compose -f docker-compose.dev.yml up -d   # PostgreSQL + Redis
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head                              # создать схему
psql postgresql://anifolder:anifolder@localhost:5432/anifolder -f scripts/seed_dev.sql        # тестовые данные
psql postgresql://anifolder:anifolder@localhost:5432/anifolder -f tests/integration/schema_checks.sql  # проверки
```

Тестовые данные: 1000 пользователей (`user1` … `user1000`, пароль `password`), 500 синтетических тайтлов,
~58 000 записей в списках, отзывы, темы, комментарии, заглушки рекомендаций.

## Где что лежит

| Путь | Что это |
|---|---|
| `backend/migrations/sql/0001_initial.up.sql` | Схема целиком: таблицы, индексы, триггеры, функции |
| `backend/migrations/versions/0001_initial.py` | Миграция Alembic, выполняет SQL-файл выше |
| `backend/app/models/` | Модели SQLAlchemy 2.0 (повторяют схему один в один) |
| `backend/app/db/session.py` | Async-движок и зависимость `get_session` для FastAPI |
| `backend/scripts/seed_dev.sql` | Тестовые данные |
| `backend/tests/integration/schema_checks.sql` | Проверки ограничений и триггеров (выполняются в транзакции и откатываются) |

## Что делает сама БД

- **`updated_at`** в `user_anime` и `reviews` выставляет триггер.
- **Счётчики тем** (`topics.comments_count`, `last_comment_at`) ведёт триггер на `comments`.
- **Родитель комментария** проверяет триггер: он должен существовать и быть в той же теме
  (обычный FK невозможен — `comments` партиционирована).
- **Статистика тайтлов.** Изменение `user_anime` только помечает тайтл в `anime_stats_dirty`;
  пересчёт делает `SELECT refresh_anime_stats();` — **вызывать раз в 10 минут** фоновой задачей.
- **Партиции.** `user_activity` — по месяцам, `comments` — по годам. Миграция создаёт их на 3 месяца вперёд,
  дальше **раз в сутки нужно вызывать** `SELECT ensure_partitions();`. DEFAULT-партиции — страховка,
  при нормальной работе пустые.

## Договорённости для команды

**Backend**
- Список: upsert по PK — `insert(UserAnime).on_conflict_do_update(index_elements=["user_id", "anime_id"], ...)`.
- Логин и email уникальны без учёта регистра; искать через `func.lower(User.username) == name.lower()`,
  иначе индекс не используется.
- Связи в моделях объявлены с `lazy="raise"`: подгружать явно через `selectinload(...)`.
- В `refresh_tokens.token_hash` хранить SHA-256 от токена, не сам токен.
- При удалении пользователя его списки, отзывы, активность, токены и рекомендации удаляются,
  а темы и комментарии остаются с `author_id = NULL`.

**Catalog Sync Worker**
- Тайтлы: upsert по `anime.shikimori_id`. Жанры: `genres.id` = id жанра в Shikimori, upsert по PK.
- `anime.status` — только `anons` / `ongoing` / `released` (как в Shikimori); `kind` не ограничен.

**Recommendation Service**
- Читает `user_anime (user_id, anime_id, status, score)`.
- Пишет в `recommendations`: удалить старые строки пользователя и вставить новые в одной транзакции;
  `model_version` — версия модели. Выдача: `ORDER BY relevance DESC LIMIT n` по индексу.
- Сейчас там заглушки `model_version = 'seed-popular'`.

## Новые миграции

Меняйте модели, затем `alembic revision --autogenerate -m "..."` и обязательно просмотрите файл глазами.
Партиции в autogenerate не участвуют (отфильтрованы в `migrations/env.py`). Триггеры и функции
autogenerate не видит — их изменения пишите вручную через `op.execute(...)`.
