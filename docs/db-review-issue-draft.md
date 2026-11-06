# Черновик GitHub issue — не опубликован

**Заголовок:** [db-review] Исправить ID и курсор catalog sync, изоляцию тестов; согласовать range-фильтр годов

**Предлагаемая метка:** `db-review` (наличие метки в репозитории не проверялось; `[db-review]` также включён в заголовок).

**Репозиторий:** Drain-Doglazer/AniFolder. **Проверенный commit:** `1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58`, рабочая ветка `nikita/db-n1-n2-review`.

Нужны согласование Фёдора и назначение исполнителя. Ни одна предлагаемая правка не внесена. Ниже — готовое тело issue; метаданные выше не означают создание issue.

---

## Основание и ограничения

Проверены N1/N2 из плана стыковки. [Отчёт](review-n1-n2-2026-11-06.md) содержит историю диагностики; актуальные выводы начинаются с раздела «Актуальный результат N1/N2 на upstream/main».

Доказательства: [воспроизведения](review-n1-n2-evidence/reproductions-pg18.txt), [код воспроизведений](review-n1-n2-evidence/reproduce.py), [полный pytest](review-n1-n2-evidence/pytest-pg18.txt), [планы всех шести сценариев](review-n1-n2-evidence/query-plans-pg18.txt), [сравнение годов](review-n1-n2-evidence/year-comparison-pg18.txt).

Материалы подготовлены к публикации в ветке nikita/db-n1-n2-review форка Brev1ch/AniFolder. Перед созданием issue проверить доступность ссылки на отчёт в этой ветке; относительные ссылки из тела issue заменить полными URL соответствующих файлов. Ссылки на исходники ниже закреплены на проверенном commit.

Окружение: PostgreSQL 18.6 / Python 3.14.4; SQLAlchemy 2.0.57, asyncpg 0.32.0, pytest 9.2.0, pytest-asyncio 1.4.1.post1, PyJWT 2.15.1 ([полный список](review-n1-n2-evidence/dependencies.txt)). Целевые PostgreSQL 16 / Python 3.12 ещё не проверены. Alembic на пустой временной БД и SQL-проверки схемы прошли. Штатные тесты выполнялись в отдельной копии: только два DROP DATABASE заменены SELECT 1, CREATE и Alembic сохранены ([точный патч копии](review-n1-n2-evidence/test-fixture-safety.patch)). Существующие базы не удалялись. При повторении обычный pytest нельзя направлять на общий сервер: conftest выполняет DROP anifolder_test WITH (FORCE).

## 1. P1: направление словаря ID нарушает импорт и замену жанров

**Код:** [backend/app/workers/catalog_sync.py, строки 144–153](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/workers/catalog_sync.py#L144-L153).

`RETURNING (Anime.id, Anime.anilist_id)` превращается в `dict`, то есть `internal_id → anilist_id`. Дальше DELETE принимает values за внутренние ID, а links обращается к словарю по anilist_id.

**Минимальное воспроизведение:** на отдельной БД вызвать `apply_media_batch` для `{'id': 800000001, 'status': 'FINISHED', 'genres': ['Action'], 'title': {'english': 'review'}}`, когда назначенный БД id отличается от 800000001. Получен `KeyError: 800000001` на строке 153. Второй вариант: у seed-тайтла internal id=1/anilist_id=900000001 есть один жанр; импорт того же AniList ID с `genres=[]` оставляет 1 связь вместо 0. Оба результата сохранены в логе воспроизведений.

**Последствия:** импорт страницы с жанрами падает и откатывается; пустой снимок жанров не удаляет старые связи. Если внешний ID совпадёт с внутренним ID другого тайтла, DELETE потенциально затронет чужие связи; такой случай отдельно не воспроизводился. Совпадение id=anilist_id в маленьких тестах маскирует дефект.

**Предлагаемое исправление:** явно строить `{anilist_id: internal_id for internal_id, anilist_id in returned_rows}`; DELETE по значениям этого словаря, links — lookup по anilist_id. Сохранить одну транзакцию для upsert тайтлов, словаря и замены связей. Не менять правила сохранения title_ru/name_ru.

**Приёмка:** импорт с заведомо разными ID; повторный upsert; пустой снимок удаляет все связи; связи посторонних тайтлов не меняются; title_ru/name_ru сохраняются; mal_id обновляется, в том числе до NULL.

## 2. P1: курсор после частичного импорта пропускает необработанные тайтлы

**Код:** [сортировка ID, строка 58](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/workers/catalog_sync.py#L58); [инкрементальный порог, строки 246–253](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/workers/catalog_sync.py#L246-L253); [максимум, max_pages и finally, строки 267–285](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/workers/catalog_sync.py#L267-L285).

**Минимальное воспроизведение:** старый Redis-курсор=100. Фейковая страница 1 с `updatedAt=300` успешно применяется; на странице 2 с `updatedAt=200` apply бросает исключение. `run()` пробрасывает ошибку, но из finally сохраняет 300. Следующий запуск запрашивает `updatedAt > 299`, поэтому запись 200 пропущена. Аналогично воспроизведено с `--max-pages=1` без исключения. Фейки изолируют управление курсором от ошибки ID из пункта 1; настоящие AniList/Redis не вызывались.

**Причина:** страницы отсортированы по ID, поэтому максимум updatedAt успешно обработанного префикса не является безопасной границей для оставшейся части. Максимум обновляется после успешного apply: ошибка не в преждевременном сохранении именно упавшей страницы. Перекрытие на секунду не решает проблему.

**Последствия:** часть обновлений больше не попадёт в инкрементальный импорт; потребуется полный импорт или откат курсора. Возможен частично обновлённый каталог при внешне продвинутом курсоре.

**Предлагаемое исправление для согласования:** перенос записи нового курсора из finally в ветку полного успешного завершения; при ошибке fetch/apply, GraphQL errors и остановке по max_pages сохранять прежний курсор. В finally оставить закрытие ресурсов. Отдельно определить безопасную границу для полного прохода при изменении источника во время импорта: кандидат — время начала прохода с перекрытием, если гарантии времени AniList это допускают. Просто перенести текущий max в success-ветку недостаточно для доказательства корректности при конкурентных изменениях источника; этот протокол ещё не проверен.

**Приёмка:** ошибка второй страницы после commit первой, ошибка fetch, max_pages, повторный запуск без пропусков, равные updatedAt на границе, GraphQL errors, Redis недоступен, изменения источника во время полного прохода. Курсор повышается только после доказанно полного успешного обхода.

## 3. P2: rollback сервиса разрушает внешнюю транзакцию теста

**Код:** [backend/tests/conftest.py, строки 86–100](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/tests/conftest.py#L86-L100). Реальные rollback: [auth_service.py:36](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/services/auth_service.py#L36) и [95](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/services/auth_service.py#L95).

**Минимальное воспроизведение:** открыть `connection.begin()`, создать `AsyncSession(bind=connection, expire_on_commit=False)` как в фикстуре; вставить строку и flush; вызвать `session.rollback()`; вставить другую строку и `session.commit()`; выполнить teardown-rollback соединения. После rollback сессии исходная tx уже inactive; вторая строка остаётся видимой из нового соединения. Факт сохранён в логе: `outer transaction active ... False`, `row survives ... True`.

**Последствия:** данные могут переходить между тестами; результат зависит от порядка и того, прошёл ли сервис по ветке rollback. Комментарий про savepoint в фикстуре не соответствует её конфигурации. Этот дефект подтверждён отдельно; он не установлен как причина четырёх падений ниже.

**Предлагаемое исправление:** задать сессии `join_transaction_mode='create_savepoint'` и сохранить внешнюю транзакцию до teardown. Проверить поддержку на целевых SQLAlchemy/asyncpg и добавить тест rollback → commit → teardown → отсутствие строки из другого соединения. Не сбрасывать sequence в качестве замены исправлению изоляции или словаря ID.

**Приёмка:** commit и rollback сервиса не завершают внешнюю tx; тесты изолированы после успешной операции и после исключения; тест с разными ID остаётся обязательным независимо от sequence. Отдельно согласовать явный тестовый DSN и защиту DROP: [conftest.py:42–59](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/tests/conftest.py#L42-L59).

## 4. N1 / запрос №5: рекомендован range-фильтр без новой миграции

**Код:** [backend/app/services/catalog_service.py:59–62](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/services/catalog_service.py#L59-L62); [существующий индекс, SQL:90](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/migrations/sql/0001_initial.up.sql#L90).

**Минимальное воспроизведение:** после миграции, seed и ANALYZE сравнить следующие предикаты с одинаковыми SELECT/ORDER BY/LIMIT:

```sql
-- Исходный вариант
WHERE kind = 'tv'
  AND date_part('year', aired_on) >= 2010
  AND date_part('year', aired_on) <= 2020
-- Предлагаемый вариант
WHERE kind = 'tv'
  AND aired_on >= DATE '2010-01-01'
  AND aired_on < DATE '2021-01-01'
```

Готовые EXPLAIN и проверка эквивалентности: [year-comparison.sql](review-n1-n2-evidence/year-comparison.sql). На 500 seed-тайтлах date_part+kind выбрал Seq Scan; диапазон+kind естественно выбрал Bitmap Index Scan по anime_kind_aired_on_idx с обеими датами в Index Cond. Без kind обе формы выбрали Seq Scan, но оценка числа совпадений улучшилась с 2 до 188 при actual=187. Различий полных результатов — 0. Отдельные планы с enable_seqscan=off в выводе помечены как диагностика, а не естественный выбор planner.

**Последствия текущего варианта:** выражение над aired_on мешает использовать обычный индекс для условия по году; оценки селективности неточны. Тайминги на 500 строках не доказывают ускорения на большом каталоге. Sort после фильтра остаётся.

**Предлагаемое исправление:** для year_from добавить `aired_on >= date(year_from, 1, 1)`; для year_to — `aired_on < date(year_to + 1, 1, 1)`. При отсутствии границы не добавлять её условие. Сохранить NULL-семантику и прежнюю обработку year_from > year_to. API ограничивает годы 1950–2100. Expression-индекс/миграцию 0002 сейчас не добавлять.

**Приёмка:** обе односторонние границы; начало/конец года, високосная дата, NULL, отсутствие границ, обратный диапазон; одинаковые фильтры count/select. Повторить планы на PostgreSQL 16, затем оценить на реальном каталоге ~20k. Индекс без ведущего kind и индекс сортировки обсуждать только по новым измерениям.

## Разбор всех четырёх упавших тестов

Итог сохранённого прогона — 38 passed, 4 failed. Новый прогон для подготовки issue не выполнялся.

| Тест и строка | Наблюдение и классификация | Зависимость от окружения / что согласовать |
|---|---|---|
| [test_catalog_sync.py:81, test_apply_batch_inserts_with_genres](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/tests/unit/test_catalog_sync.py#L81-L104) | Падает на вызове строки 82 с KeyError 1 из worker:153. Реальный дефект словаря ID, пункт 1 | Порядок тестов и состояние identity sequence влияют на проявление: совпадающие ID могут скрыть ошибку. Не доказана зависимость от версии PostgreSQL/Python; независимый пример 800000001 подтверждает дефект |
| [test_catalog_sync.py:107, test_apply_batch_upsert_keeps_title_ru_and_replaces_genres](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/tests/unit/test_catalog_sync.py#L107-L134) | Падает уже на первом apply, строка 108, с тем же KeyError. Реальный дефект worker. До повторного upsert и assert сохранения title_ru тест не дошёл | Та же зависимость от совпадения ID, не установленный дефект версии. Сохранение title_ru отдельно проверено воспроизведением; полноценная замена жанров не проходит |
| [test_catalog.py:68–78, test_anime_list_pagination](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/tests/unit/test_catalog.py#L68-L78) | Тест ждёт Naruto/Naruto Movie; получил Naruto Movie/On Hold Title. При сортировке пяти фикстур порядок Announced Title, Naruto, Naruto Movie, On Hold Title, Sasuke Future. OFFSET=2/LIMIT=2 даёт наблюдаемый результат. Дефект ожидания теста, не backend-пагинации | Коллация может влиять на строковую сортировку в общем случае, но конкретный лог объясняется неверным ожидаемым срезом; версия как причина не подтверждена. Согласовать корректный expected и фиксированную тестовую коллацию |
| [test_auth.py:148–164, test_refresh_success](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/tests/unit/test_auth.py#L148-L164) | На строке 154 совпали access JWT. [security.py:30–39](https://github.com/Drain-Doglazer/AniFolder/blob/1145af7261f694ee6eb1fdcbbdf397e5dfdf4e58/backend/app/core/security.py#L30-L39) не задаёт jti; при одинаковом sub и выдаче в одну секунду закодированные iat/exp совпали. Нестабильное ожидание теста либо несогласованное требование уникальности JWT; сбой refresh-ротации в БД этим assert не доказан | Чувствителен к скорости выполнения, границе секунды и преобразованию datetime в используемой версии PyJWT 2.15.1. Сравнения версий не было, поэтому объявлять это регрессией PyJWT нельзя. Если уникальность access не часть контракта — проверять refresh, claims и БД; иначе добавить jti как согласованное изменение контракта. Sleep только маскирует причину |

Ошибки курсора и изоляции не покрыты четырьмя перечисленными падениями: для них нужны отдельные регрессионные тесты. Ни одно падение не подтверждено как ошибка конкретной версии зависимости. Матрица PostgreSQL 16 / Python 3.12 и согласованные версии зависимостей нужна для окончательной приёмки, а не для отмены воспроизведённых дефектов.

## Решения, которые нужны от Фёдора

- [ ] Согласовать исправление словаря ID и обязательные тесты с несовпадающими ID.
- [ ] Согласовать протокол курсора: без продвижения на частичном проходе; определить безопасную границу при изменении источника.
- [ ] Согласовать savepoint-изоляцию и защиту цели тестовой БД.
- [ ] Согласовать range-фильтр годов без новой миграции.
- [ ] Уточнить контракт уникальности access JWT и корректное ожидание пагинации.
- [ ] Назначить исполнителя и повторную проверку на PostgreSQL 16 / Python 3.12.
