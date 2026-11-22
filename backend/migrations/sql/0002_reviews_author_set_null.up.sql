-- Контент удалённых пользователей сохраняется: отзывы остаются с author NULL,
-- как темы и комментарии (решение тимлида). API помечает таких авторов deleted_user.

ALTER TABLE reviews ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE reviews DROP CONSTRAINT reviews_user_id_fkey;
ALTER TABLE reviews ADD CONSTRAINT reviews_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL;
