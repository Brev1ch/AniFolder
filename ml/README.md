# Recommendation Service

Рабочий контур: данные сайта → ALS/cold-start → топ-50 в PostgreSQL → внутренний API
и `GET /api/v1/me/recommendations` backend. Backend добавляет карточки и исключает
актуальный список пользователя при каждом чтении. Frontend ещё использует свои
заглушки рекомендаций — переключение UI не входит в этот блок.

## Запуск рядом с backend

Нужны Python 3.12 и PostgreSQL со схемой backend. Инфраструктура, миграции и seed —
в `docs/database.md`. ML не создаёт схему и не импортирует каталог самостоятельно.
Из корня репозитория:

```bash
cd ml
python3.12 -m venv .venv  # если окружение ещё не создано
.venv/bin/python -m pip install -r requirements.txt
OPENBLAS_NUM_THREADS=1 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

Для venv без pip: `uv pip install --python .venv/bin/python -r requirements.txt`.
Для тестов/ноутбуков установите `requirements-dev.txt`. `requirements-service.txt`
фиксирует HTTP/DB-зависимости, но сам по себе недостаточен для обучения.
Backend запускается своим окружением на 8000: `uvicorn app.main:app --port 8000`.

Настройки: переменные окружения > `ml/.env` > `backend/.env` > dev-defaults.
Пути dotenv не зависят от cwd; пример — `ml/.env.example`.
`DATABASE_URL` backend с `postgresql+asyncpg` автоматически преобразуется в sync psycopg.

- `ML_ANILIST_DATA_DIR` — необязательный каталог parquet краулера. Если переменная
  не задана, обучение использует только сайт. Указанный отсутствующий каталог — ошибка.
- `ML_ARTIFACT_DIR` — отдельный каталог результатов, по умолчанию `ml/artifacts/service`.

```bash
curl http://127.0.0.1:8001/health/readiness
curl -X POST http://127.0.0.1:8001/internal/v1/train
curl http://127.0.0.1:8001/internal/v1/train/status
curl 'http://127.0.0.1:8001/internal/v1/recommendations/1?limit=20'
# Публичный маршрут: токен берётся из register/login backend.
curl -H "Authorization: Bearer $ACCESS_TOKEN" 'http://127.0.0.1:8000/api/v1/me/recommendations?limit=20'
```

## Обучение и публикация

`POST /internal/v1/train` реально запускает фоновое обучение и возвращает
`202 {"status":"ok"}` — это принятие задания, а не подтверждение его успеха.
Статус: `GET /internal/v1/train/status` → `idle`, `running`, `succeeded` (с результатом)
или `failed` (без SQL/DSN в ошибке). Повторный запрос во время работы → 409.

Один worker Uvicorn. Статус хранится в памяти до перезапуска, устойчивой очереди нет:
при аварийном завершении процесса задание нужно запустить заново. При штатном
завершении сервис дожидается текущего обучения. PostgreSQL advisory lock защищает
от одновременного обучения через CLI/другой процесс; такой конкурентный запуск
завершается ошибкой, а не вторым расчётом. Автоматическое расписание пока не настроено.

CLI из `ml/`:

```bash
# Обучение + файлы, без изменения recommendations:
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.training.train
# Обучение + атомарная публикация в БД:
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.training.train --write
```

1. Согласованный снимок сайта читается в PostgreSQL REPEATABLE READ: users,
   user_anime, anime/anime_stats, anime_genres. Далее read-транзакция закрывается.
2. При подключении AniList `anilist_id` переводится в `anime.id`; отсутствующие в
   каталоге тайтлы отбрасываются. Внешние user_id становятся отрицательными.
   В итоговом отчёте есть external_rows и matched_external_rows; при нулевом
   пересечении лог содержит предупреждение. Seed-каталог синтетический и с нашим
   реальным AniList-снимком не пересекается.
3. Фильтр 5/5, score_coef=0, planned=0.5, остальные веса прежние, оценки <5
   исключаются, без затухания. ALS: factors=64, alpha=5, regularization=0.1,
   iterations=20, seed=42, num_threads=4 — выбор по ноутбукам 04–08.
4. Без истории — all-time popularity. 1–4 записи или пользователь вне ALS —
   genre popularity за 28 дней, beta=1. Короткая выдача дополняется all-time,
   затем каталогом по anime_stats.in_lists_count (ничьи по anime.id). Это fallback
   для малых/пустых данных, отдельно от сравнения моделей в ноутбуках.
5. История на момент обучения исключается при формировании топ-50. Backend
   дополнительно исключает актуальную историю при чтении: это защищает от
   добавлений в список после обучения. Внутренний GET читает сохранённые строки.
6. Результаты рассчитываются для всех пользователей сайта, включая пользователей
   без списков. Внешним отрицательным user_id ничего не публикуется. Все замены
   проходят в одной транзакции: DELETE + INSERT; ошибка вставки откатывает DELETE.
   Удалённые во время обучения пользователи пропускаются, новые попадут в следующий запуск.

`relevance=1/rank` сохраняет порядок выдачи; это **не вероятность**.
`model_version=als-v1-<run id>` обозначает запуск общего ALS/cold-start pipeline.
Артефакты каждого запуска в отдельной папке: `als.npz` (если были данные для ALS),
`recommendations.json`, `summary.json`. ID тайтлов здесь принадлежат сайту; старый
`artifacts/final_evaluation/als_final.npz` с ID AniList напрямую в сервис не загружается.
Артефакты сохраняются до публикации; ошибка их создания не меняет БД. При сбое после
коммита БД её model_version — источник истины: manifest может остаться с published=false.
Ошибка обновления manifest отражается в результате как manifest_update_failed.

## HTTP-контракт

| Метод и путь | Результат |
|---|---|
| `GET /health` | 200 без обращения к БД |
| `GET /health/readiness` | 200 при доступной таблице рекомендаций, иначе 503 |
| `GET /internal/v1/recommendations/{user_id}?limit=20` | `[{"anime_id":42,"relevance":1.0}]` |
| `POST /internal/v1/train` | 202; параллельный запрос — 409 |
| `GET /internal/v1/train/status` | Статус последнего задания в этом процессе |
| Backend `GET /api/v1/me/recommendations?limit=20` | Массив `{anime_id,relevance,anime:AnimeCard}` по Bearer-токену |

user_id положительный bigint, limit 1..50 (default 20). Сортировка relevance DESC,
anime_id ASC; нет строк → `[]`. Внутренний GET не проверяет существование пользователя
отдельно. Ошибки параметров → 422; SQL-сбой ML → 503 DATABASE_UNAVAILABLE.
Публичный backend использует существующую авторизацию и общий формат ошибок.
Фильтрация текущего user_anime в SQL выполняется до LIMIT, без кэша устаревшей выдачи.

## Docker Compose

```bash
docker compose -f docker-compose.dev.yml -f docker-compose.ml.yml up -d --build ml
# Порт ML не опубликован: проверка из контейнера.
docker compose -f docker-compose.dev.yml -f docker-compose.ml.yml exec ml python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8001/health/readiness').read().decode())"
```

Миграции/наполнение общей БД выполняются отдельно по docs/database.md.
Образ работает под непривилегированным пользователем, артефакты в named volume.
По умолчанию контейнер обучается только на данных сайта. Для внешнего датасета
нужно явно смонтировать каталог read-only и задать ML_ANILIST_DATA_DIR.
Внутренний API без пользовательской авторизации: доступен только в сети Compose,
без `ports` и внешнего маршрута nginx. Локальный запуск привязывайте к loopback.

## Проверки

Из `ml/`: `OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q`.
Автономные тесты API/pipeline используют временную SQLite: проверяют SQL-сортировку,
изоляцию пользователей, лимиты, cold/ALS, mapping, замену данных, откат ошибок и задания.

Полный PostgreSQL-тест — `tests/integration/recommendations_flow.py`. Нужна отдельная
**пустая** БД, имя заканчивается на `_ml_integration`, и два окружения Python 3.12
с ML/backend-зависимостями. Из корня:

```bash
TEST_DATABASE_URL=postgresql://anifolder:anifolder@localhost:5433/check_ml_integration \
OPENBLAS_NUM_THREADS=1 ml/.venv/bin/python tests/integration/recommendations_flow.py \
  --backend-python /absolute/path/to/backend/python
```

Тест применяет настоящий Alembic и seed, запускает оба HTTP-сервиса, регистрирует
пользователей, вызывает train, проверяет авторизацию/выдачу/изменение списка,
PostgreSQL rollback и advisory lock. Сам БД не удаляет. Backend pytest/conftest,
который пересоздаёт anifolder_test, не используется.

## Отличия от раннего плана стыковки

Формат таблицы и ответов сохраняется. Cold-start выбран по реальным AniList-данным:
all-time без истории, genre28 beta=1 для короткой истории. Это отличается от
топ-3 жанров с оценками >=7 из S3; в PR нужно явно согласовать это с командой.
ALS уже исследована и сравнивалась по NDCG/recall/coverage, повторная разведка на
синтетическом seed не нужна. Качество на test имеет оговорку о ранее изученном EDA-периоде.
Ошибки импорта каталога из PR #8 не исправлялись: перед наполнением реальными
тайтлами нужно починить worker. Сквозной тест на seed проверяет интеграцию, а не
качество рекомендаций на реальных пользователях.
