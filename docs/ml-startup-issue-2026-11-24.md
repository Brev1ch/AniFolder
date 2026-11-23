# ML-сервис: медленный запуск — issue для Сергея

Дата замеров: 2026-11-23/24. Контур: seed-база backend (49 773 записи user_anime,
1 006 пользователей, 500 тайтлов), PostgreSQL 14 на localhost, Python 3.10
(venv изолированный, только для диагностики).

## Симптом

Сервис рекомендаций «долго запускается»: тянет тяжёлые зависимости и данные,
хотя инференс (`/internal/v1/recommendations/*`) читает только PostgreSQL и
модель для этого не нужна.

## Замеры (логи и цифры)

### Установка зависимостей (чистый venv, колёса из PyPI)

```
service-зависимости (fastapi/uvicorn/sqlalchemy/psycopg):  20.4 c (скачивание-bound)
train-зависимости (implicit/numpy/scipy/pandas/pyarrow):   15.5 c
```

### Импорт приложения — вот главное

`python -X importtime -c "from app.main import app"`, два прогона:

```
import time: 2737 | 1142031 | app.main
import time: 2544 | 1066541 | app.main
```

Топ вкладов (второй прогон, микросекунды):

```
569948  app.training.train        ← тянется из main.py при старте
420420    pandas
294822  fastapi
148409  app.recsys.als            ← implicit
148030    implicit
```

**~1,1 c из ~1,8 c старта — это импорт обучающего стека (pandas 420 мс, implicit 148 мс),
который для выдачи рекомендаций не нужен.**

### Запуск uvicorn (фактический лог)

```
$ DATABASE_URL=... uvicorn app.main:app --port 8001
INFO:     Started server process [17014]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8001
INFO:     127.0.0.1:38786 - "GET /health HTTP/1.1" 200 OK
INFO:     127.0.0.1:38800 - "GET /health/readiness HTTP/1.1" 200 OK
```

Замер от старта процесса до первого ответа:

```
до /health:            1.76 c
до /health/readiness:  1.82 c
```

### Обучение (для контраста)

`POST /internal/v1/train` на seed-данных: **2.8 c** (ALS factors=64, iters=20).
На реальных данных будет сильно больше — это отдельный повод для расписания
и инкрементальности, к старту сервиса не относится.

## Диагноз

1. **Импорт тренировочного стека на старте инференса.** Цепочка
   `ml/app/main.py` → `app.training.train` → `pandas`; `app.training.train` →
   `app.recsys.als` → `implicit` (+scipy/numpy). Всё это module-level и
   выполняется при каждом старте процесса, хотя `/internal/v1/recommendations/*`
   до них не дотрагивается.
2. **Тяжёлый образ.** `ml/Dockerfile` ставит `requirements.txt` целиком
   (implicit+numpy+scipy+pandas+pyarrow ≈ сотни МБ в образе), а
   `requirements-service.txt` — достаточный для сервинга — не используется.
3. **Пины requirements-service.txt не ставятся на Python 3.10**
   (`pydantic-settings==2.16.1` — только с 3.12). README это знает, но пины
   хрупкие: версии «под текущее окружение», а не диапазоны.
4. **Нет логов длительности этапов старта** — при следующем «медленном
   запуске» нечего будет приложить к issue, как это сделано здесь.

## Задание (приоритет по пунктам)

1. **Ленивые импорты в обучающем пути.** Убрать module-level `import pandas`
   и `from implicit...` из цепочки, которую тянет `app.main`: перенести внутрь
   `run_training` / функций recsys. Критерий: `python -c "from app.main import app"`
   в окружении **без** implicit/pandas/scipy работает, старт до readiness < 0.7 c.
2. **Тонкий serving-образ.** Dockerfile сервиса ставит `requirements-service.txt`
   (+ нужное для чтения БД); обучение — отдельная цель/образ с полным стеком.
   Критерий: размер образа сервиса заметно меньше текущего, `docker run` +
   readiness зелёный без implicit в образе.
3. **Логи длительности старта.** В lifespan: время инициализации engine,
   время до готовности; одна строка в лог вида `startup: ready in 0.42s`.
4. **Пины.** Либо расширить пины requirements-service.txt до диапазонов,
   ставящихся и на 3.10, либо явно зафиксировать «Python ≥ 3.12» в шапке файла.
5. **Опционально**: расписание переобучения и замер длительности train на
   данных, близких к боевым (README: «автоматическое расписание пока не настроено»).

## Что готово для проверки

- Команды замеров — в этом документе, воспроизводимы.
- Backend-сторона (выдача рекомендаций, фильтрация списка) не менялась
  и покрыта тестами (110 passed).
