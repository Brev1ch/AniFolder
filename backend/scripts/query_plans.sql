-- Проверка планов запросов каталога на seed-данных.
-- Запуск: psql postgresql://anifolder:anifolder@localhost:5432/anifolder -f backend/scripts/query_plans.sql
-- Перед запуском: alembic upgrade head && psql ... -f backend/scripts/seed_dev.sql
--
-- Что смотреть в плане:
--   Seq Scan на anime — нормально только там, где указано "ожидаемо";
--   в остальных местах ждём Bitmap/Index Scan по индексам из миграции 0001.
-- Осторожно: EXPLAIN (ANALYZE) реально выполняет запросы (здесь все чтения, безопасно).

\echo '=== 1. Список каталога, сортировка popular (join anime_stats) ==='
\echo 'Ожидание: Seq Scan + Sort — индекса по in_lists_count нет. На 20k тайтлов дёшево,'
\echo 'но глубокие OFFSET будут дорожать. Если план неудобен — обсудим индекс.'
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id, anime.title_ru, anime.title_en, anime.kind, anime.status,
       anime.episodes, anime.aired_on, anime.poster_url
FROM anime
LEFT OUTER JOIN anime_stats ON anime_stats.anime_id = anime.id
ORDER BY coalesce(anime_stats.in_lists_count, 0) DESC, anime.id
LIMIT 20 OFFSET 0;

\echo '=== 2. Поиск по названию (pg_trgm) + сортировка по релевантности ==='
\echo 'Ожидание: Bitmap Index Scan по anime_title_en_trgm_idx (title_ru NULL у большинства).'
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id, anime.title_ru, anime.title_en
FROM anime
WHERE (anime.title_ru ILIKE '%Test Anime 7%' OR anime.title_en ILIKE '%Test Anime 7%')
ORDER BY coalesce(greatest(similarity(anime.title_ru, 'Test Anime 7'),
                            similarity(anime.title_en, 'Test Anime 7')), 0.0) DESC,
         anime.id
LIMIT 20;

\echo '=== 3. Count для пагинации при том же поиске ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM anime
WHERE (anime.title_ru ILIKE '%Test Anime%' OR anime.title_en ILIKE '%Test Anime%');

\echo '=== 4. Фильтры: status + kind + жанр (EXISTS по anime_genres) ==='
\echo 'Ожидание: anime_genres — Index Scan по PK (anime_id, genre_id).'
\echo 'По status/kind индексов нет: оцени цену Bitmap Index Scan по anime_kind_aired_on_idx'
\echo 'в варианте с kind впереди; при seq scan на 20k строк — тоже приемлемо, зафиксируем вывод.'
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id, anime.title_en
FROM anime
WHERE anime.status = 'released'
  AND anime.kind = 'tv'
  AND EXISTS (SELECT 1 FROM anime_genres
              WHERE anime_genres.anime_id = anime.id
                AND anime_genres.genre_id = 1)
ORDER BY anime.id
LIMIT 20;

\echo '=== 5. Фильтр по годам: date_part над aired_on ==='
\echo 'Известное ограничение: вычисление над колонке, индекс anime_kind_aired_on_idx не работает.'
\echo 'Если план плохой — обсудим: либо range по aired_on (поддержать в коде),'
\echo 'либо expression-индекс (тогда миграция — к Никите).'
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id, anime.title_en
FROM anime
WHERE date_part('year', anime.aired_on) >= 2010
  AND date_part('year', anime.aired_on) <= 2020
ORDER BY anime.aired_on DESC NULLS LAST, anime.id
LIMIT 20;

\echo '=== 6. Карточка тайтла: три запроса (orm делает selectinload + joinedload) ==='
\echo 'Ожидание: все три — Index Scan по PK.'
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id, anime.anilist_id, anime.mal_id, anime.title_ru, anime.title_en,
       anime.kind, anime.status, anime.episodes, anime.aired_on,
       anime.description, anime.poster_url, anime_stats.scores_count,
       anime_stats.avg_score, anime_stats.in_lists_count
FROM anime
LEFT OUTER JOIN anime_stats ON anime_stats.anime_id = anime.id
WHERE anime.id = 1;

EXPLAIN (ANALYZE, BUFFERS)
SELECT genres.id, genres.name_ru, genres.name_en
FROM genres
JOIN anime_genres ON genres.id = anime_genres.genre_id
WHERE anime_genres.anime_id = 1;

\echo '=== Готово. Пришли планы (или вывод целиком) в тред — разберём вместе. ==='
