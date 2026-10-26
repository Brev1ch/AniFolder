-- AniFolder: начальная схема БД (PostgreSQL 16).
-- Соответствует разделу «Схема базы данных» в README.md.
-- Применяется миграцией Alembic 0001_initial; можно выполнить и вручную через psql.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ===================================================================
-- Типы
-- ===================================================================

CREATE TYPE list_status AS ENUM (
    'planned',      -- запланировано
    'watching',     -- смотрю
    'completed',    -- просмотрено
    'on_hold',      -- отложено
    'dropped'       -- брошено
);

CREATE TYPE activity_type AS ENUM (
    'list_added',       -- добавил тайтл в список
    'status_changed',   -- сменил статус
    'progress_updated', -- обновил число просмотренных эпизодов
    'scored',           -- поставил оценку
    'reviewed',         -- написал отзыв
    'topic_created',    -- создал тему
    'commented'         -- написал комментарий
);

-- Общая функция для полей updated_at
CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- ===================================================================
-- Пользователи и авторизация
-- ===================================================================

CREATE TABLE users (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      varchar(32)  NOT NULL,
    email         varchar(254) NOT NULL,
    password_hash varchar(255) NOT NULL,
    avatar_url    varchar(512),
    bio           text,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT users_username_format CHECK (username ~ '^[A-Za-z0-9_]{3,32}$'),
    CONSTRAINT users_bio_length      CHECK (char_length(bio) <= 2000)
);
-- Уникальность без учёта регистра: «Naruto_Fan» и «naruto_fan» — один логин
CREATE UNIQUE INDEX users_username_lower_key ON users (lower(username));
CREATE UNIQUE INDEX users_email_lower_key    ON users (lower(email));

CREATE TABLE refresh_tokens (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash varchar(64) NOT NULL UNIQUE,     -- SHA-256 в hex, сам токен не храним
    expires_at timestamptz NOT NULL,
    revoked    boolean     NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX refresh_tokens_user_id_idx ON refresh_tokens (user_id);

-- ===================================================================
-- Каталог (заполняется Catalog Sync Worker из AniList)
-- ===================================================================

CREATE TABLE anime (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    anilist_id   bigint       NOT NULL UNIQUE,  -- id в AniList, ключ для upsert при синхронизации
    mal_id       bigint       UNIQUE,           -- idMal из того же ответа AniList; NULL, если AniList его не знает.
                                                -- Нужен ML: открытые датасеты оценок размечены по MAL id
    title_ru     varchar(512),                  -- в AniList русских названий нет: заполняется вручную или NULL
    title_en     varchar(512) NOT NULL,         -- title.english, а если его нет — title.romaji
    kind         varchar(16),                   -- format из AniList в нижнем регистре: tv, tv_short, movie, ova, ona, special, music
    status       varchar(16)  NOT NULL,         -- наши значения; соответствие статусам AniList — в docs/database.md
    episodes     integer,                       -- NULL, пока число эпизодов неизвестно
    aired_on     date,
    description  text,
    poster_url   varchar(512),
    synced_at    timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT anime_status_valid    CHECK (status IN ('announced', 'ongoing', 'released', 'hiatus', 'cancelled')),
    CONSTRAINT anime_episodes_nonneg CHECK (episodes >= 0)
);
CREATE INDEX anime_title_ru_trgm_idx ON anime USING gin (title_ru gin_trgm_ops);
CREATE INDEX anime_title_en_trgm_idx ON anime USING gin (title_en gin_trgm_ops);
CREATE INDEX anime_kind_aired_on_idx ON anime (kind, aired_on);

-- id жанра — наш собственный: в AniList жанры приходят строками без id.
-- Естественный ключ — name_en; синхронизация делает upsert по нему и не трогает name_ru.
CREATE TABLE genres (
    id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name_en varchar(64) NOT NULL UNIQUE,
    name_ru varchar(64)                    -- NULL, пока перевода нет: фронтенд показывает name_en
);

-- Словарь переводов жанров AniList.
-- Если AniList добавит новый жанр, синхронизация создаст его с name_ru = NULL.
INSERT INTO genres (name_en, name_ru) VALUES
    ('Action', 'Экшен'),             ('Adventure', 'Приключения'),
    ('Comedy', 'Комедия'),           ('Drama', 'Драма'),
    ('Ecchi', 'Этти'),               ('Fantasy', 'Фэнтези'),
    ('Horror', 'Ужасы'),             ('Mahou Shoujo', 'Махо-сёдзё'),
    ('Mecha', 'Меха'),               ('Music', 'Музыка'),
    ('Mystery', 'Детектив'),         ('Psychological', 'Психологическое'),
    ('Romance', 'Романтика'),        ('Sci-Fi', 'Фантастика'),
    ('Slice of Life', 'Повседневность'), ('Sports', 'Спорт'),
    ('Supernatural', 'Сверхъестественное'), ('Thriller', 'Триллер');

CREATE TABLE anime_genres (
    anime_id bigint  NOT NULL REFERENCES anime (id) ON DELETE CASCADE,
    genre_id integer NOT NULL REFERENCES genres (id) ON DELETE CASCADE,
    PRIMARY KEY (anime_id, genre_id)
);
CREATE INDEX anime_genres_genre_id_idx ON anime_genres (genre_id, anime_id);

-- Заранее посчитанные агрегаты (пересчитывает refresh_anime_stats() раз в 10 минут)
CREATE TABLE anime_stats (
    anime_id       bigint PRIMARY KEY REFERENCES anime (id) ON DELETE CASCADE,
    scores_count   integer      NOT NULL DEFAULT 0,
    avg_score      numeric(4,2),                 -- NULL, если оценок нет
    in_lists_count integer      NOT NULL DEFAULT 0,
    updated_at     timestamptz  NOT NULL DEFAULT now()
);

-- ===================================================================
-- Списки и оценки
-- ===================================================================

CREATE TABLE user_anime (
    user_id          bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    anime_id         bigint      NOT NULL REFERENCES anime (id) ON DELETE CASCADE,
    status           list_status NOT NULL,
    score            smallint,
    episodes_watched integer     NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, anime_id),
    CONSTRAINT user_anime_score_range       CHECK (score BETWEEN 1 AND 10),
    CONSTRAINT user_anime_episodes_nonneg   CHECK (episodes_watched >= 0)
);
CREATE INDEX user_anime_user_status_idx ON user_anime (user_id, status, updated_at DESC);
CREATE INDEX user_anime_anime_id_idx    ON user_anime (anime_id);

CREATE TRIGGER user_anime_set_updated_at
    BEFORE UPDATE ON user_anime
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Очередь тайтлов, чью статистику нужно пересчитать.
-- Пользовательская транзакция только отмечает тайтл (ON CONFLICT DO NOTHING),
-- а сам пересчёт делает фоновая задача — так на популярных тайтлах нет горячих строк.
CREATE TABLE anime_stats_dirty (
    anime_id bigint PRIMARY KEY
);

CREATE FUNCTION mark_anime_stats_dirty() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO anime_stats_dirty VALUES (NEW.anime_id) ON CONFLICT DO NOTHING;
    END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') AND (TG_OP = 'DELETE' OR OLD.anime_id <> NEW.anime_id) THEN
        INSERT INTO anime_stats_dirty VALUES (OLD.anime_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER user_anime_mark_stats_dirty
    AFTER INSERT OR UPDATE OF status, score, anime_id OR DELETE ON user_anime
    FOR EACH ROW EXECUTE FUNCTION mark_anime_stats_dirty();

-- Пересчитывает статистику только для «грязных» тайтлов. Возвращает их число.
-- Вызывать фоновой задачей: SELECT refresh_anime_stats();
CREATE FUNCTION refresh_anime_stats() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    n integer;
BEGIN
    WITH dirty AS (
        DELETE FROM anime_stats_dirty RETURNING anime_id
    ), agg AS (
        SELECT d.anime_id,
               count(ua.score)                     AS scores_count,
               round(avg(ua.score)::numeric, 2)    AS avg_score,
               count(ua.user_id)                   AS in_lists_count
        FROM dirty d
        JOIN anime a ON a.id = d.anime_id          -- тайтл могли удалить
        LEFT JOIN user_anime ua ON ua.anime_id = d.anime_id
        GROUP BY d.anime_id
    )
    INSERT INTO anime_stats AS s (anime_id, scores_count, avg_score, in_lists_count, updated_at)
    SELECT anime_id, scores_count, avg_score, in_lists_count, now() FROM agg
    ON CONFLICT (anime_id) DO UPDATE
        SET scores_count   = EXCLUDED.scores_count,
            avg_score      = EXCLUDED.avg_score,
            in_lists_count = EXCLUDED.in_lists_count,
            updated_at     = EXCLUDED.updated_at;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

-- ===================================================================
-- Отзывы
-- ===================================================================

CREATE TABLE reviews (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    anime_id   bigint      NOT NULL REFERENCES anime (id) ON DELETE CASCADE,
    score      smallint    NOT NULL,
    text       text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reviews_one_per_anime UNIQUE (user_id, anime_id),
    CONSTRAINT reviews_score_range   CHECK (score BETWEEN 1 AND 10),
    CONSTRAINT reviews_text_length   CHECK (char_length(text) BETWEEN 1 AND 20000)
);
CREATE INDEX reviews_anime_created_idx ON reviews (anime_id, created_at DESC);

CREATE TRIGGER reviews_set_updated_at
    BEFORE UPDATE ON reviews
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ===================================================================
-- Лента активности (партиционирование по месяцам)
-- ===================================================================

CREATE TABLE user_activity (
    id         bigint GENERATED ALWAYS AS IDENTITY,
    user_id    bigint        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    type       activity_type NOT NULL,
    anime_id   bigint        REFERENCES anime (id) ON DELETE CASCADE,
    payload    jsonb         NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)          -- ключ партиционирования обязан входить в PK
) PARTITION BY RANGE (created_at);

CREATE INDEX user_activity_user_created_idx ON user_activity (user_id, created_at DESC);
CREATE TABLE user_activity_default PARTITION OF user_activity DEFAULT;

-- ===================================================================
-- Сообщество
-- ===================================================================

CREATE TABLE topics (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    author_id       bigint       REFERENCES users (id) ON DELETE SET NULL,  -- тема остаётся после удаления аккаунта
    anime_id        bigint       REFERENCES anime (id) ON DELETE CASCADE,   -- NULL = общая тема
    title           varchar(200) NOT NULL,
    body            text         NOT NULL,
    comments_count  integer      NOT NULL DEFAULT 0,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    last_comment_at timestamptz  NOT NULL DEFAULT now(),  -- для новой темы = created_at
    CONSTRAINT topics_title_length CHECK (char_length(title) >= 1),
    CONSTRAINT topics_body_length  CHECK (char_length(body) BETWEEN 1 AND 20000)
);
CREATE INDEX topics_last_comment_idx       ON topics (last_comment_at DESC);
CREATE INDEX topics_anime_last_comment_idx ON topics (anime_id, last_comment_at DESC);
CREATE INDEX topics_author_id_idx          ON topics (author_id);

-- Комментарии партиционированы по годам.
-- Уникальный ключ партиционированной таблицы обязан включать created_at,
-- поэтому на parent_id нельзя повесить обычный FK — целостность проверяет триггер ниже.
CREATE TABLE comments (
    id         bigint GENERATED ALWAYS AS IDENTITY,
    topic_id   bigint      NOT NULL REFERENCES topics (id) ON DELETE CASCADE,
    author_id  bigint      REFERENCES users (id) ON DELETE SET NULL,
    parent_id  bigint,                    -- ответ на комментарий той же темы
    body       text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at),
    CONSTRAINT comments_body_length CHECK (char_length(body) BETWEEN 1 AND 10000)
) PARTITION BY RANGE (created_at);

CREATE INDEX comments_topic_created_idx ON comments (topic_id, created_at);
CREATE INDEX comments_author_id_idx     ON comments (author_id);
CREATE INDEX comments_id_idx            ON comments (id);  -- поиск родителя по id без created_at
CREATE TABLE comments_default PARTITION OF comments DEFAULT;

CREATE FUNCTION check_comment_parent() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.parent_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM comments WHERE id = NEW.parent_id AND topic_id = NEW.topic_id
    ) THEN
        RAISE EXCEPTION 'parent comment % not found in topic %', NEW.parent_id, NEW.topic_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER comments_check_parent
    BEFORE INSERT OR UPDATE OF parent_id, topic_id ON comments
    FOR EACH ROW EXECUTE FUNCTION check_comment_parent();

-- Счётчик комментариев и время последнего комментария в теме
CREATE FUNCTION update_topic_counters() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE topics
           SET comments_count  = comments_count + 1,
               last_comment_at = greatest(last_comment_at, NEW.created_at)
         WHERE id = NEW.topic_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE topics
           SET comments_count = greatest(comments_count - 1, 0)
         WHERE id = OLD.topic_id;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER comments_update_topic_counters
    AFTER INSERT OR DELETE ON comments
    FOR EACH ROW EXECUTE FUNCTION update_topic_counters();

-- ===================================================================
-- Рекомендации (перезаписывает Recommendation Service)
-- ===================================================================

CREATE TABLE recommendations (
    user_id       bigint      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    anime_id      bigint      NOT NULL REFERENCES anime (id) ON DELETE CASCADE,
    relevance     real        NOT NULL,
    model_version varchar(64) NOT NULL,
    generated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, anime_id)
);
CREATE INDEX recommendations_user_relevance_idx ON recommendations (user_id, relevance DESC);

-- ===================================================================
-- Партиции
-- ===================================================================

-- Создаёт месячные партиции user_activity и годовые партиции comments
-- от текущего периода на months_ahead месяцев вперёд. Идемпотентна.
-- Вызывать раз в сутки фоновой задачей: SELECT ensure_partitions();
-- DEFAULT-партиции — страховка: при нормальной работе они остаются пустыми.
CREATE FUNCTION ensure_partitions(months_ahead integer DEFAULT 3) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    m date;
    y date;
    part text;
BEGIN
    FOR i IN 0..months_ahead LOOP
        m := (date_trunc('month', now()) + make_interval(months => i))::date;
        part := format('user_activity_p%s', to_char(m, 'YYYY_MM'));
        IF to_regclass(part) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF user_activity FOR VALUES FROM (%L) TO (%L)',
                part, m, (m + interval '1 month')::date);
        END IF;

        y := date_trunc('year', m)::date;
        part := format('comments_p%s', to_char(y, 'YYYY'));
        IF to_regclass(part) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF comments FOR VALUES FROM (%L) TO (%L)',
                part, y, (y + interval '1 year')::date);
        END IF;
    END LOOP;
END;
$$;

SELECT ensure_partitions();
