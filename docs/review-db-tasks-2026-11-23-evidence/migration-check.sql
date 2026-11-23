\set ON_ERROR_STOP on
SELECT version_num FROM alembic_version;
SELECT a.attnotnull AS user_id_not_null, c.confdeltype AS fk_delete_action
FROM pg_attribute a JOIN pg_constraint c ON c.conrelid = a.attrelid AND a.attnum = ANY(c.conkey)
WHERE a.attrelid = 'reviews'::regclass AND a.attname = 'user_id' AND c.contype = 'f';
BEGIN;
DO $$
DECLARE uid bigint; rid bigint; n bigint;
BEGIN
    SELECT count(*) INTO n FROM reviews;
    INSERT INTO users(username,email,password_hash) VALUES ('migration_probe','migration_probe@example.test','not-a-real-password-hash') RETURNING id INTO uid;
    INSERT INTO reviews(user_id,anime_id,score,text) SELECT uid,id,8,'Synthetic migration probe' FROM anime ORDER BY id LIMIT 1 RETURNING id INTO rid;
    DELETE FROM users WHERE id=uid;
    ASSERT EXISTS (SELECT 1 FROM reviews WHERE id=rid AND user_id IS NULL), 'Review must survive author deletion with NULL user_id';
    ASSERT (SELECT count(*) FROM reviews) = n+1, 'Existing reviews must remain';
    RAISE NOTICE 'PASS: 0002 author deletion preserves review and existing rows';
END $$;
ROLLBACK;
