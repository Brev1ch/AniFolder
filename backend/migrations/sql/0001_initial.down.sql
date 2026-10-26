-- Откат начальной схемы AniFolder. Удаляет ВСЕ данные.

DROP FUNCTION IF EXISTS ensure_partitions(integer);

DROP TABLE IF EXISTS recommendations;
DROP TABLE IF EXISTS comments;          -- вместе со всеми партициями
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS user_activity;     -- вместе со всеми партициями
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS anime_stats_dirty;
DROP TABLE IF EXISTS user_anime;
DROP TABLE IF EXISTS anime_stats;
DROP TABLE IF EXISTS anime_genres;
DROP TABLE IF EXISTS genres;
DROP TABLE IF EXISTS anime;
DROP TABLE IF EXISTS refresh_tokens;
DROP TABLE IF EXISTS users;

DROP FUNCTION IF EXISTS update_topic_counters();
DROP FUNCTION IF EXISTS check_comment_parent();
DROP FUNCTION IF EXISTS refresh_anime_stats();
DROP FUNCTION IF EXISTS mark_anime_stats_dirty();
DROP FUNCTION IF EXISTS set_updated_at();

DROP TYPE IF EXISTS activity_type;
DROP TYPE IF EXISTS list_status;

-- pg_trgm не удаляем: расширение может использоваться не только нами
