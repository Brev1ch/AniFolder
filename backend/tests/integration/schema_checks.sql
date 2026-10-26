-- Проверки поведения схемы. Выполняется в транзакции и откатывается — данные не меняет.
-- Запуск на БД с применённой миграцией:
--   psql "$DATABASE_URL_SYNC" -v ON_ERROR_STOP=1 -f backend/tests/integration/schema_checks.sql
-- Любая упавшая проверка завершит скрипт ошибкой.

\set ON_ERROR_STOP on
BEGIN;

-- Фикстуры
INSERT INTO users (username, email, password_hash) VALUES
    ('check_alice', 'alice@check.test', 'x'),
    ('check_bob',   'bob@check.test',   'x');
INSERT INTO anime (anilist_id, title_en, status, episodes) VALUES (-1, 'Check Anime', 'released', 12);

CREATE TEMP TABLE ids ON COMMIT DROP AS
SELECT (SELECT id FROM users WHERE username = 'check_alice') AS alice,
       (SELECT id FROM users WHERE username = 'check_bob')   AS bob,
       (SELECT id FROM anime WHERE anilist_id = -1)          AS anime;

-- Хелпер: выполняет SQL и проверяет, что он упал с нужным SQLSTATE
CREATE FUNCTION pg_temp.expect_error(sql text, state text, label text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE sql;
    RAISE EXCEPTION 'FAIL: % — ожидалась ошибка %, но запрос прошёл', label, state;
EXCEPTION WHEN OTHERS THEN
    IF SQLSTATE <> state THEN
        RAISE EXCEPTION 'FAIL: % — ожидалась ошибка %, получена % (%)', label, state, SQLSTATE, SQLERRM;
    END IF;
    RAISE NOTICE 'ok: %', label;
END;
$$;

-- 1. Ограничения пользователей
SELECT pg_temp.expect_error(
    $q$INSERT INTO users (username, email, password_hash) VALUES ('CHECK_ALICE', 'other@check.test', 'x')$q$,
    '23505', 'username уникален без учёта регистра');
SELECT pg_temp.expect_error(
    $q$INSERT INTO users (username, email, password_hash) VALUES ('other', 'ALICE@check.test', 'x')$q$,
    '23505', 'email уникален без учёта регистра');
SELECT pg_temp.expect_error(
    $q$INSERT INTO users (username, email, password_hash) VALUES ('bad name!', 'b@check.test', 'x')$q$,
    '23514', 'формат username');

-- 1а. Каталог: id AniList, статусы, жанры
SELECT pg_temp.expect_error(
    $q$INSERT INTO anime (title_en, status) VALUES ('No id', 'released')$q$,
    '23502', 'anilist_id обязателен');
SELECT pg_temp.expect_error(
    $q$INSERT INTO anime (anilist_id, title_en, status) VALUES (-1, 'Dup', 'released')$q$,
    '23505', 'anilist_id уникален');
SELECT pg_temp.expect_error(
    $q$INSERT INTO anime (anilist_id, title_en, status) VALUES (-2, 'Raw status', 'RELEASING')$q$,
    '23514', 'статусы AniList как есть не принимаются, только наши');
SELECT pg_temp.expect_error(
    $q$INSERT INTO anime (anilist_id, mal_id, title_en, status) VALUES (-3, -100, 'A', 'released'), (-4, -100, 'B', 'released')$q$,
    '23505', 'mal_id уникален');
DO $$ BEGIN
    -- тайтлы без idMal не конфликтуют друг с другом
    INSERT INTO anime (anilist_id, title_en, status) VALUES (-10, 'No MAL 1', 'ongoing'), (-11, 'No MAL 2', 'hiatus');
    ASSERT (SELECT count(*) FROM anime WHERE anilist_id IN (-10, -11) AND mal_id IS NULL) = 2;
    RAISE NOTICE 'ok: несколько тайтлов без mal_id';
END $$;
DO $$ BEGIN
    -- upsert жанра по name_en не затирает перевод
    INSERT INTO genres (name_en) VALUES ('Action') ON CONFLICT (name_en) DO NOTHING;
    INSERT INTO genres (name_en) VALUES ('Check New Genre');
    ASSERT (SELECT name_ru FROM genres WHERE name_en = 'Action') = 'Экшен', 'перевод жанра на месте';
    ASSERT (SELECT name_ru FROM genres WHERE name_en = 'Check New Genre') IS NULL, 'новый жанр без перевода';
    RAISE NOTICE 'ok: upsert жанров не затирает переводы';
END $$;

-- 2. Оценки в диапазоне 1..10
SELECT pg_temp.expect_error(
    format($q$INSERT INTO user_anime (user_id, anime_id, status, score) VALUES (%s, %s, 'completed', 11)$q$,
           (SELECT alice FROM ids), (SELECT anime FROM ids)),
    '23514', 'user_anime.score <= 10');
SELECT pg_temp.expect_error(
    format($q$INSERT INTO reviews (user_id, anime_id, score, text) VALUES (%s, %s, 0, 'x')$q$,
           (SELECT alice FROM ids), (SELECT anime FROM ids)),
    '23514', 'reviews.score >= 1');

-- 3. Один отзыв на тайтл от пользователя
INSERT INTO reviews (user_id, anime_id, score, text) SELECT alice, anime, 8, 'Хорошо' FROM ids;
SELECT pg_temp.expect_error(
    format($q$INSERT INTO reviews (user_id, anime_id, score, text) VALUES (%s, %s, 9, 'Ещё раз')$q$,
           (SELECT alice FROM ids), (SELECT anime FROM ids)),
    '23505', 'один отзыв на тайтл');

-- 4. Статистика тайтла: оценки помечают тайтл «грязным», refresh пересчитывает
DELETE FROM anime_stats_dirty;
INSERT INTO user_anime (user_id, anime_id, status, score)
SELECT alice, anime, 'completed'::list_status, 8 FROM ids UNION ALL
SELECT bob,   anime, 'watching'::list_status,  NULL FROM ids;
DO $$ BEGIN
    ASSERT (SELECT count(*) FROM anime_stats_dirty) = 1, 'тайтл должен попасть в очередь пересчёта';
END $$;
SELECT refresh_anime_stats();
DO $$
DECLARE s anime_stats;
BEGIN
    SELECT * INTO s FROM anime_stats WHERE anime_id = (SELECT anime FROM ids);
    ASSERT s.scores_count = 1 AND s.avg_score = 8.00 AND s.in_lists_count = 2,
        format('статистика после вставки: %s', s);
    ASSERT NOT EXISTS (SELECT 1 FROM anime_stats_dirty), 'очередь должна опустеть';
    RAISE NOTICE 'ok: пересчёт статистики после вставки';
END $$;

UPDATE user_anime SET score = 6 WHERE user_id = (SELECT bob FROM ids);
DELETE FROM user_anime WHERE user_id = (SELECT alice FROM ids);
SELECT refresh_anime_stats();
DO $$
DECLARE s anime_stats;
BEGIN
    SELECT * INTO s FROM anime_stats WHERE anime_id = (SELECT anime FROM ids);
    ASSERT s.scores_count = 1 AND s.avg_score = 6.00 AND s.in_lists_count = 1,
        format('статистика после изменения и удаления: %s', s);
    RAISE NOTICE 'ok: пересчёт статистики после UPDATE и DELETE';
END $$;

-- 5. updated_at обновляется триггером
DO $$
BEGIN
    -- now() в транзакции постоянен, поэтому проверяем, что триггер перезаписывает любое значение на now()
    UPDATE user_anime SET episodes_watched = 3, updated_at = '2000-01-01'
     WHERE user_id = (SELECT bob FROM ids);
    ASSERT (SELECT updated_at FROM user_anime WHERE user_id = (SELECT bob FROM ids)) = now(),
        'updated_at должен выставляться триггером';
    RAISE NOTICE 'ok: updated_at';
END $$;

-- 6. Сообщество: счётчики темы и проверка родителя комментария
INSERT INTO topics (author_id, anime_id, title, body, created_at, last_comment_at)
SELECT alice, anime, 'Тема A', 'Текст', now() - interval '1 hour', now() - interval '1 hour' FROM ids;
INSERT INTO topics (author_id, title, body) SELECT bob, 'Тема B', 'Текст' FROM ids;

CREATE TEMP TABLE t ON COMMIT DROP AS
SELECT (SELECT id FROM topics WHERE title = 'Тема A') AS a,
       (SELECT id FROM topics WHERE title = 'Тема B') AS b;

INSERT INTO comments (topic_id, author_id, body) SELECT t.a, ids.bob, 'Первый' FROM t, ids;
INSERT INTO comments (topic_id, author_id, parent_id, body)
SELECT t.a, ids.alice, (SELECT id FROM comments WHERE body = 'Первый'), 'Ответ' FROM t, ids;

DO $$
DECLARE tp topics;
BEGIN
    SELECT * INTO tp FROM topics WHERE id = (SELECT a FROM t);
    ASSERT tp.comments_count = 2, format('comments_count = %s', tp.comments_count);
    ASSERT tp.last_comment_at > now() - interval '1 minute', 'last_comment_at должен сдвинуться';
    RAISE NOTICE 'ok: счётчики темы при вставке';
END $$;

SELECT pg_temp.expect_error(
    format($q$INSERT INTO comments (topic_id, body, parent_id) VALUES (%s, 'x', %s)$q$,
           (SELECT b FROM t), (SELECT id FROM comments WHERE body = 'Первый')),
    '23503', 'родитель комментария из другой темы');
SELECT pg_temp.expect_error(
    format($q$INSERT INTO comments (topic_id, body, parent_id) VALUES (%s, 'x', 999999999)$q$, (SELECT a FROM t)),
    '23503', 'несуществующий родитель комментария');

DELETE FROM comments WHERE body = 'Ответ';
DO $$ BEGIN
    ASSERT (SELECT comments_count FROM topics WHERE id = (SELECT a FROM t)) = 1, 'счётчик при удалении';
    RAISE NOTICE 'ok: счётчик темы при удалении';
END $$;

-- 7. Удаление пользователя: личные данные удаляются, темы и комментарии остаются без автора
INSERT INTO user_activity (user_id, type, anime_id) SELECT bob, 'scored', anime FROM ids;
INSERT INTO recommendations (user_id, anime_id, relevance, model_version) SELECT bob, anime, 0.9, 'check' FROM ids;
INSERT INTO refresh_tokens (user_id, token_hash, expires_at) SELECT bob, 'check-hash', now() + interval '30 days' FROM ids;
DELETE FROM users WHERE username = 'check_bob';
DO $$ BEGIN
    ASSERT NOT EXISTS (SELECT 1 FROM user_anime      WHERE user_id = (SELECT bob FROM ids)), 'user_anime';
    ASSERT NOT EXISTS (SELECT 1 FROM user_activity   WHERE user_id = (SELECT bob FROM ids)), 'user_activity';
    ASSERT NOT EXISTS (SELECT 1 FROM recommendations WHERE user_id = (SELECT bob FROM ids)), 'recommendations';
    ASSERT NOT EXISTS (SELECT 1 FROM refresh_tokens  WHERE user_id = (SELECT bob FROM ids)), 'refresh_tokens';
    ASSERT (SELECT author_id FROM topics WHERE title = 'Тема B') IS NULL, 'тема осталась без автора';
    ASSERT (SELECT author_id FROM comments WHERE body = 'Первый') IS NULL, 'комментарий остался без автора';
    RAISE NOTICE 'ok: каскады при удалении пользователя';
END $$;

-- 8. Партиции: свежая активность попадает в месячную партицию, а не в DEFAULT
DO $$ BEGIN
    INSERT INTO user_activity (user_id, type) SELECT alice, 'reviewed' FROM ids;
    ASSERT (SELECT tableoid::regclass::text FROM user_activity
            WHERE user_id = (SELECT alice FROM ids) ORDER BY id DESC LIMIT 1)
           = 'user_activity_p' || to_char(now(), 'YYYY_MM'), 'активность не в месячной партиции';
    PERFORM ensure_partitions();  -- повторный вызов не должен падать
    RAISE NOTICE 'ok: партиции';
END $$;

\echo 'Все проверки схемы пройдены'
ROLLBACK;
