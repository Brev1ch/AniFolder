-- Generated from captured actual service statements at db5ae5290eef50ded2dac07fe4d1c682311fdb09.
-- Read-only. Run after migrations 0001/0002 + seed_dev.sql + ANALYZE on a disposable DB.
-- Cursor timestamps and synthetic IDs belong to the recorded seed run.
\set ON_ERROR_STOP on

\echo '=== list/status=completed/page=1 ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username, users.email, users.password_hash, users.avatar_url, users.bio, users.created_at
FROM users
WHERE lower(users.username) = 'user1'::VARCHAR;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS count_1
FROM user_anime
WHERE user_anime.user_id = 1::BIGINT AND user_anime.status = 'completed'::list_status;
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_anime.user_id, user_anime.anime_id, user_anime.status, user_anime.score, user_anime.episodes_watched, user_anime.created_at, user_anime.updated_at, anime.id, anime.anilist_id, anime.mal_id, anime.title_ru, anime.title_en, anime.kind, anime.status AS status_1, anime.episodes, anime.aired_on, anime.description, anime.poster_url, anime.synced_at
FROM user_anime JOIN anime ON anime.id = user_anime.anime_id
WHERE user_anime.user_id = 1::BIGINT AND user_anime.status = 'completed'::list_status ORDER BY user_anime.updated_at DESC, user_anime.anime_id DESC
 LIMIT 20::INTEGER OFFSET 0::INTEGER;

\echo '=== list/all-statuses/page=1 ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username, users.email, users.password_hash, users.avatar_url, users.bio, users.created_at
FROM users
WHERE lower(users.username) = 'user1'::VARCHAR;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS count_1
FROM user_anime
WHERE user_anime.user_id = 1::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_anime.user_id, user_anime.anime_id, user_anime.status, user_anime.score, user_anime.episodes_watched, user_anime.created_at, user_anime.updated_at, anime.id, anime.anilist_id, anime.mal_id, anime.title_ru, anime.title_en, anime.kind, anime.status AS status_1, anime.episodes, anime.aired_on, anime.description, anime.poster_url, anime.synced_at
FROM user_anime JOIN anime ON anime.id = user_anime.anime_id
WHERE user_anime.user_id = 1::BIGINT ORDER BY user_anime.updated_at DESC, user_anime.anime_id DESC
 LIMIT 20::INTEGER OFFSET 0::INTEGER;

\echo '=== activity/first ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username, users.email, users.password_hash, users.avatar_url, users.bio, users.created_at
FROM users
WHERE lower(users.username) = 'user1'::VARCHAR;
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_activity.id, user_activity.created_at, user_activity.user_id, user_activity.type, user_activity.anime_id, user_activity.payload
FROM user_activity
WHERE user_activity.user_id = 1::BIGINT ORDER BY user_activity.created_at DESC, user_activity.id DESC
 LIMIT 6::INTEGER;
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id, anime.anilist_id, anime.mal_id, anime.title_ru, anime.title_en, anime.kind, anime.status, anime.episodes, anime.aired_on, anime.description, anime.poster_url, anime.synced_at
FROM anime
WHERE anime.id IN (320::BIGINT, 12::BIGINT, 177::BIGINT, 375::BIGINT, 381::BIGINT);

\echo '=== activity/next ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username, users.email, users.password_hash, users.avatar_url, users.bio, users.created_at
FROM users
WHERE lower(users.username) = 'user1'::VARCHAR;
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_activity.id, user_activity.created_at, user_activity.user_id, user_activity.type, user_activity.anime_id, user_activity.payload
FROM user_activity
WHERE user_activity.user_id = 1::BIGINT AND (user_activity.created_at, user_activity.id) < ('2026-11-13 01:29:06.704054+00:00'::TIMESTAMP WITH TIME ZONE, 4::BIGINT) ORDER BY user_activity.created_at DESC, user_activity.id DESC
 LIMIT 6::INTEGER;
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id, anime.anilist_id, anime.mal_id, anime.title_ru, anime.title_en, anime.kind, anime.status, anime.episodes, anime.aired_on, anime.description, anime.poster_url, anime.synced_at
FROM anime
WHERE anime.id IN (64::BIGINT, 14::BIGINT, 15::BIGINT, 241::BIGINT, 24::BIGINT);

\echo '=== reviews/first ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id
FROM anime
WHERE anime.id = 1::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS count_1
FROM reviews
WHERE reviews.anime_id = 1::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT reviews.id, reviews.user_id, reviews.anime_id, reviews.score, reviews.text, reviews.created_at, reviews.updated_at, users.username
FROM reviews LEFT OUTER JOIN users ON users.id = reviews.user_id
WHERE reviews.anime_id = 1::BIGINT ORDER BY reviews.created_at DESC, reviews.id DESC
 LIMIT 5::INTEGER OFFSET 0::INTEGER;

\echo '=== reviews/page=2 ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT anime.id
FROM anime
WHERE anime.id = 1::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS count_1
FROM reviews
WHERE reviews.anime_id = 1::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT reviews.id, reviews.user_id, reviews.anime_id, reviews.score, reviews.text, reviews.created_at, reviews.updated_at, users.username
FROM reviews LEFT OUTER JOIN users ON users.id = reviews.user_id
WHERE reviews.anime_id = 1::BIGINT ORDER BY reviews.created_at DESC, reviews.id DESC
 LIMIT 5::INTEGER OFFSET 5::INTEGER;

\echo '=== topics/global ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS count_1
FROM topics;
EXPLAIN (ANALYZE, BUFFERS)
SELECT topics.id, topics.author_id, topics.anime_id, topics.title, topics.body, topics.comments_count, topics.created_at, topics.last_comment_at, users.username
FROM topics LEFT OUTER JOIN users ON users.id = topics.author_id ORDER BY topics.last_comment_at DESC, topics.id DESC
 LIMIT 20::INTEGER OFFSET 0::INTEGER;

\echo '=== topics/anime=10 ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS count_1
FROM topics
WHERE topics.anime_id = 10::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT topics.id, topics.author_id, topics.anime_id, topics.title, topics.body, topics.comments_count, topics.created_at, topics.last_comment_at, users.username
FROM topics LEFT OUTER JOIN users ON users.id = topics.author_id
WHERE topics.anime_id = 10::BIGINT ORDER BY topics.last_comment_at DESC, topics.id DESC
 LIMIT 20::INTEGER OFFSET 0::INTEGER;

\echo '=== comments/first ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT topics.id AS topics_id, topics.author_id AS topics_author_id, topics.anime_id AS topics_anime_id, topics.title AS topics_title, topics.body AS topics_body, topics.comments_count AS topics_comments_count, topics.created_at AS topics_created_at, topics.last_comment_at AS topics_last_comment_at
FROM topics
WHERE topics.id = 61::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT comments.id, comments.created_at, comments.topic_id, comments.author_id, comments.parent_id, comments.body
FROM comments
WHERE comments.topic_id = 61::BIGINT ORDER BY comments.created_at DESC, comments.id DESC
 LIMIT 6::INTEGER;
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username
FROM users
WHERE users.id IN (390::BIGINT, 370::BIGINT, 53::BIGINT, 470::BIGINT, 537::BIGINT);

\echo '=== comments/next ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT topics.id AS topics_id, topics.author_id AS topics_author_id, topics.anime_id AS topics_anime_id, topics.title AS topics_title, topics.body AS topics_body, topics.comments_count AS topics_comments_count, topics.created_at AS topics_created_at, topics.last_comment_at AS topics_last_comment_at
FROM topics
WHERE topics.id = 61::BIGINT;
EXPLAIN (ANALYZE, BUFFERS)
SELECT comments.id, comments.created_at, comments.topic_id, comments.author_id, comments.parent_id, comments.body
FROM comments
WHERE comments.topic_id = 61::BIGINT AND (comments.created_at, comments.id) < ('2026-11-17 13:56:54.664371+00:00'::TIMESTAMP WITH TIME ZONE, 1121::BIGINT) ORDER BY comments.created_at DESC, comments.id DESC
 LIMIT 6::INTEGER;
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username
FROM users
WHERE users.id IN (485::BIGINT, 199::BIGINT, 680::BIGINT, 745::BIGINT, 820::BIGINT);

\echo '=== compatibility/user1-user2 ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username, users.email, users.password_hash, users.avatar_url, users.bio, users.created_at
FROM users
WHERE lower(users.username) = 'user2'::VARCHAR;
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_anime_1.score, user_anime_2.score AS score_1
FROM user_anime AS user_anime_1 JOIN user_anime AS user_anime_2 ON user_anime_2.anime_id = user_anime_1.anime_id
WHERE user_anime_1.user_id = 1::BIGINT AND user_anime_2.user_id = 2::BIGINT AND user_anime_1.score IS NOT NULL AND user_anime_2.score IS NOT NULL;

\echo '=== compatibility/self ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT users.id, users.username, users.email, users.password_hash, users.avatar_url, users.bio, users.created_at
FROM users
WHERE lower(users.username) = 'user1'::VARCHAR;
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_anime_1.score, user_anime_2.score AS score_1
FROM user_anime AS user_anime_1 JOIN user_anime AS user_anime_2 ON user_anime_2.anime_id = user_anime_1.anime_id
WHERE user_anime_1.user_id = 1::BIGINT AND user_anime_2.user_id = 1::BIGINT AND user_anime_1.score IS NOT NULL AND user_anime_2.score IS NOT NULL;
