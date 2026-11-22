-- Откат: отзывы без автора удаляются (dev-only), затем восстанавливается NOT NULL
-- и каскадное удаление, как в 0001.

DELETE FROM reviews WHERE user_id IS NULL;

ALTER TABLE reviews DROP CONSTRAINT reviews_user_id_fkey;
ALTER TABLE reviews ADD CONSTRAINT reviews_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;

ALTER TABLE reviews ALTER COLUMN user_id SET NOT NULL;
