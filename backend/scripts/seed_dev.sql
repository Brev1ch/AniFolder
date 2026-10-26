-- Тестовые данные для локальной разработки. НЕ запускать на проде.
-- Запуск: psql "$DATABASE_URL_SYNC" -v ON_ERROR_STOP=1 -f backend/scripts/seed_dev.sql
--
-- Создаёт: 500 тайтлов, 1000 пользователей (пароль у всех: password),
-- ~39 000 записей в списках, отзывы, темы, комментарии, активность.
-- Жанры (словарь переводов) создаёт сама миграция, сид их только использует.
-- Каталог синтетический: anilist_id и mal_id начинаются с 900 000 000, чтобы не пересекаться
-- с реальными тайтлами из синхронизации. У каждого 7-го тайтла mal_id = NULL, как бывает в AniList.
-- Скрипт идемпотентен только на пустой БД; для перезаливки сначала TRUNCATE (см. конец файла).

BEGIN;

SELECT setseed(0.42);  -- одинаковые данные при каждом запуске

-- Тайтлы
INSERT INTO anime (anilist_id, mal_id, title_ru, title_en, kind, status, episodes, aired_on, description, poster_url)
SELECT 900000000 + g,
       CASE WHEN g % 7 = 0 THEN NULL ELSE 900000000 + g END,
       'Тестовое аниме ' || g,
       'Test Anime ' || g,
       (ARRAY['tv','tv','tv','movie','ova','ona','special'])[1 + floor(random() * 7)::int],
       CASE WHEN g % 25 = 0 THEN 'announced' WHEN g % 10 = 0 THEN 'ongoing' ELSE 'released' END,
       CASE WHEN g % 25 = 0 THEN NULL ELSE (ARRAY[1,12,13,24,25,26,50])[1 + floor(random() * 7)::int] END,
       date '1995-01-01' + floor(random() * 11000)::int,
       'Описание тестового тайтла №' || g || '.',
       NULL
FROM generate_series(1, 500) AS g;

-- 1–3 жанра на тайтл
INSERT INTO anime_genres (anime_id, genre_id)
SELECT a.id, g.id
FROM anime a
CROSS JOIN LATERAL (
    SELECT id FROM genres
    WHERE a.id IS NOT NULL               -- связь с внешней строкой: выборка заново для каждого тайтла
    ORDER BY random()
    LIMIT 1 + floor(random() * 3)::int
) g;

-- Пользователи. password_hash = bcrypt("password")
INSERT INTO users (username, email, password_hash, bio, created_at)
SELECT 'user' || g,
       'user' || g || '@example.com',
       '$2a$12$9YnKJX4mdji25p/VOc756eY.desPcrTqv.cTQFhgxiJCIxoSUthlS',
       CASE WHEN g % 3 = 0 THEN 'Люблю аниме, тестовый профиль №' || g END,
       now() - make_interval(days => floor(random() * 365)::int)
FROM generate_series(1, 1000) AS g;

-- Списки: у каждого пользователя 10–70 тайтлов. Популярность тайтлов неравномерная
-- (power-law), чтобы матрица была похожа на реальную и ALS было на чём учиться.
-- (Случайные значения считаются в обычном SELECT, а не в LATERAL-подзапросах:
--  планировщик может закэшировать LATERAL по параметру (Memoize) и выдать всем одинаковый результат.)
INSERT INTO user_anime (user_id, anime_id, status, score, episodes_watched, created_at, updated_at)
SELECT user_id, anime_id, status,
       CASE WHEN status IN ('completed', 'dropped', 'watching') AND random() < 0.8
            THEN least(10, greatest(1, round(6.5 + random() * 3.5 - (anime_id % 7) * 0.4)))::smallint
       END,
       0, t, t
FROM (
    SELECT u.id AS user_id,
           pick.anime_id,
           (ARRAY['completed','completed','completed','watching','planned','planned','on_hold','dropped']::list_status[])
               [1 + floor(random() * 8)::int] AS status,
           u.created_at + (now() - u.created_at) * random() AS t
    FROM users u
    CROSS JOIN LATERAL (
        SELECT DISTINCT (1 + floor(500 * power(random(), 2.2)))::bigint AS anime_id
        FROM generate_series(1, 10 + floor(random() * 60)::int)
        WHERE u.id IS NOT NULL           -- уникальная для каждого пользователя корреляция
    ) pick
) s;

-- Прогресс просмотра согласован со статусом
UPDATE user_anime ua
SET episodes_watched = CASE
        WHEN ua.status = 'completed' THEN coalesce(a.episodes, 0)
        WHEN ua.status = 'planned'   THEN 0
        ELSE floor(random() * coalesce(nullif(a.episodes, 0), 12))::int
    END
FROM anime a
WHERE a.id = ua.anime_id;

-- Отзывы: на ~5% просмотренных тайтлов с оценкой
INSERT INTO reviews (user_id, anime_id, score, text, created_at, updated_at)
SELECT user_id, anime_id, score,
       'Тестовый отзыв пользователя ' || user_id || ' на тайтл ' || anime_id || '. Оценка: ' || score || '/10.',
       updated_at, updated_at
FROM user_anime
WHERE status = 'completed' AND score IS NOT NULL AND random() < 0.05;

-- Темы: 30 общих + по одной на каждый 10-й тайтл
INSERT INTO topics (author_id, anime_id, title, body, created_at, last_comment_at)
SELECT 1 + floor(random() * 1000)::bigint,
       CASE WHEN g <= 30 THEN NULL ELSE (g - 30) * 10 END,
       CASE WHEN g <= 30 THEN 'Общая тема №' || g ELSE 'Обсуждение тайтла ' || (g - 30) * 10 END,
       'Текст первого сообщения темы №' || g || '.',
       t, t
FROM generate_series(1, 80) AS g,
     LATERAL (SELECT now() - make_interval(days => 30 + floor(random() * 60)::int) + g * interval '0 s' AS t) ts;

-- Комментарии (по 0–25 на тему); счётчики тем обновит триггер.
-- Даты в пределах последних 30 дней → попадают в существующие партиции.
INSERT INTO comments (topic_id, author_id, body, created_at)
SELECT t.id,
       1 + floor(random() * 1000)::bigint,
       'Комментарий №' || n || ' в теме ' || t.id,
       now() - make_interval(mins => floor(random() * 43000)::int) + n * interval '0 s'
FROM topics t
CROSS JOIN LATERAL generate_series(1, floor(random() * 26)::int + (t.id * 0)::int) AS n;

-- Немного ответов на комментарии (родитель из той же темы)
INSERT INTO comments (topic_id, author_id, parent_id, body, created_at)
SELECT c.topic_id, 1 + floor(random() * 1000)::bigint, c.id,
       'Ответ на комментарий ' || c.id, c.created_at + interval '5 min'
FROM comments c
WHERE random() < 0.15 AND c.created_at < now() - interval '5 min';

-- Активность за последние ~25 дней (чтобы попасть в партиции текущего месяца и прошлого — в DEFAULT не пишем)
INSERT INTO user_activity (user_id, type, anime_id, payload, created_at)
SELECT ua.user_id,
       CASE WHEN ua.score IS NOT NULL THEN 'scored' ELSE 'list_added' END::activity_type,
       ua.anime_id,
       jsonb_build_object('status', ua.status, 'score', ua.score),
       date_trunc('month', now()) + (now() - date_trunc('month', now())) * random()
FROM user_anime ua
WHERE random() < 0.3;

-- Рекомендации-заглушки, пока ML-сервис не готов: популярное, чего нет в списке
INSERT INTO recommendations (user_id, anime_id, relevance, model_version)
SELECT u.id, a.id, (1.0 - a.id / 1000.0)::real, 'seed-popular'
FROM users u
CROSS JOIN LATERAL (
    SELECT id FROM anime
    WHERE NOT EXISTS (SELECT 1 FROM user_anime x WHERE x.user_id = u.id AND x.anime_id = anime.id)
    ORDER BY id
    LIMIT 20
) a;

-- Статистика тайтлов (триггеры уже отметили все «грязные» тайтлы)
SELECT refresh_anime_stats() AS anime_stats_refreshed;

COMMIT;

ANALYZE;

-- Перезаливка:
-- (genres не очищаем: это словарь переводов из миграции)
-- TRUNCATE users, anime, anime_stats_dirty RESTART IDENTITY CASCADE;
