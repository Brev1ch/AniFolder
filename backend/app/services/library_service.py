"""Списки пользователя (upsert/удаление), профили со статистикой и лента активности.

Контракт ответов — docs/api.md (разделы «Список пользователя», «Профили», «Лента
активности»). Персональные данные не кэшируются в Redis: они часто меняются и
принадлежат одному пользователю.
"""

import logging
import statistics

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import errors
from app.models.anime import Anime
from app.models.enums import ActivityType, ListStatus
from app.models.library import UserActivity, UserAnime
from app.models.user import User
from app.schemas.anime import AnimeCard
from app.schemas.library import (
    ActivityFeedResponse,
    ActivityItemResponse,
    CompatibilityResponse,
    UserAnimeListResponse,
    UserListAnime,
    UserListEntryPut,
    UserListEntryResponse,
    UserProfileResponse,
    UserProfileStats,
)
from app.services.cursor import decode_cursor, encode_cursor

logger = logging.getLogger(__name__)

# Минимум общих оценённых тайтлов, ниже которого compatibility не считаем (null)
COMPATIBILITY_MIN_COMMON = 5

# Upsert записи списка. WHERE у DO UPDATE отсекает записи без изменений: тогда
# RETURNING пустой, триггер dirty-статистики не стреляет впустую, а запись читаем как есть.
_UPSERT_SQL = """
    INSERT INTO user_anime (user_id, anime_id, status, score, episodes_watched)
    VALUES (:user_id, :anime_id, :status, :score, :episodes)
    ON CONFLICT (user_id, anime_id) DO UPDATE SET
        status = EXCLUDED.status,
        score = EXCLUDED.score,
        episodes_watched = EXCLUDED.episodes_watched
    WHERE user_anime.status IS DISTINCT FROM EXCLUDED.status
       OR user_anime.score IS DISTINCT FROM EXCLUDED.score
       OR user_anime.episodes_watched IS DISTINCT FROM EXCLUDED.episodes_watched
    RETURNING status, score, episodes_watched, updated_at
"""


async def _get_user_by_username(session: AsyncSession, username: str) -> User:
    """Поиск строго по lower(username) — иначе не встанет индекс users_username_lower_key."""
    user = await session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise errors.AppError(404, errors.USER_NOT_FOUND, f"Пользователь {username} не найден")
    return user


def _build_events(
    user_id: int,
    anime_id: int,
    old: UserAnime | None,
    new_status: ListStatus,
    new_score: int | None,
    new_episodes: int,
) -> list[UserActivity]:
    """События ленты по сравнению старой и новой записи (docs/api.md «Лента активности»)."""
    specs: list[tuple[ActivityType, dict]] = []
    if old is None:
        specs.append((ActivityType.LIST_ADDED, {"status": new_status.value}))
        if new_score is not None:
            specs.append((ActivityType.SCORED, {"score": new_score}))
        return [UserActivity(user_id=user_id, anime_id=anime_id, type=t, payload=p) for t, p in specs]

    # Смена статуса и прогресс в одном запросе: по контракту progress_updated пишется
    # только без смены статуса, поэтому при смене статуса прогресс не эмитим отдельно.
    if old.status != new_status:
        specs.append((ActivityType.STATUS_CHANGED, {"from": old.status.value, "to": new_status.value}))
    elif old.episodes_watched != new_episodes:
        specs.append((ActivityType.PROGRESS_UPDATED, {"episodes_watched": new_episodes}))
    # Оценка менялась в любую сторону, включая снятие (new_score=None)
    if new_score != old.score:
        specs.append((ActivityType.SCORED, {"score": new_score}))
    return [UserActivity(user_id=user_id, anime_id=anime_id, type=t, payload=p) for t, p in specs]


async def upsert_entry(
    session: AsyncSession, user_id: int, anime_id: int, body: UserListEntryPut
) -> UserListEntryResponse:
    """Добавить в список или обновить запись. Пропущенные поля сохраняют прежнее
    значение; явный score=null снимает оценку (см. UserListEntryPut)."""
    anime = await session.scalar(select(Anime).where(Anime.id == anime_id))
    if anime is None:
        raise errors.AppError(404, errors.ANIME_NOT_FOUND, f"Аниме с id={anime_id} не найдено")

    old = await session.scalar(
        select(UserAnime).where(UserAnime.user_id == user_id, UserAnime.anime_id == anime_id)
    )

    new_status = body.status
    # "score" в model_fields_set: не передан — сохранить прежнее; передан null — снять
    if "score" in body.model_fields_set:
        new_score: int | None = body.score
    else:
        new_score = old.score if old else None
    new_episodes = (
        body.episodes_watched if body.episodes_watched is not None
        else (old.episodes_watched if old else 0)
    )
    # Граница прогресса проверяется только для явно переданного значения:
    # иначе смена статуса откатилась бы из-за прогресса, посаженного до правки каталога.
    if body.episodes_watched is not None and anime.episodes is not None \
            and body.episodes_watched > anime.episodes:
        raise errors.AppError(
            422, errors.VALIDATION_ERROR,
            f"Прогресс {body.episodes_watched} больше числа эпизодов тайтла ({anime.episodes})",
        )

    params = {
        "user_id": user_id,
        "anime_id": anime_id,
        "status": new_status.value,
        "score": new_score,
        "episodes": new_episodes,
    }
    row = (await session.execute(text(_UPSERT_SQL), params)).first()
    if row is None:
        # UPDATE отклонён WHERE-фильтром (значения совпадают) — читаем существующую запись
        result = await session.execute(
            select(UserAnime.status, UserAnime.score, UserAnime.episodes_watched, UserAnime.updated_at)
            .where(UserAnime.user_id == user_id, UserAnime.anime_id == anime_id)
        )
        row = result.one()

    session.add_all(_build_events(user_id, anime_id, old, new_status, new_score, new_episodes))
    await session.commit()

    # updated_at обновляет триггер set_updated_at(); RETURNING уже видит новое значение
    return UserListEntryResponse(
        anime_id=anime_id,
        status=ListStatus(row.status),
        score=row.score,
        episodes_watched=row.episodes_watched,
        updated_at=row.updated_at,
        anime=AnimeCard.model_validate(anime),
    )


async def remove_entry(session: AsyncSession, user_id: int, anime_id: int) -> None:
    anime_exists = await session.scalar(select(Anime.id).where(Anime.id == anime_id))
    if anime_exists is None:
        raise errors.AppError(404, errors.ANIME_NOT_FOUND, f"Аниме с id={anime_id} не найдено")
    entry = await session.scalar(
        select(UserAnime).where(UserAnime.user_id == user_id, UserAnime.anime_id == anime_id)
    )
    if entry is None:
        raise errors.AppError(404, errors.LIST_ENTRY_NOT_FOUND, f"Аниме с id={anime_id} не найдено в списке")
    await session.delete(entry)
    await session.commit()


async def get_profile(session: AsyncSession, username: str) -> UserProfileResponse:
    user = await _get_user_by_username(session, username)

    status_counts = dict(
        (await session.execute(
            select(UserAnime.status, func.count())
            .where(UserAnime.user_id == user.id)
            .group_by(UserAnime.status)
        )).all()
    )
    scores_count, mean_score = (await session.execute(
        select(func.count(UserAnime.score), func.avg(UserAnime.score))
        .where(UserAnime.user_id == user.id)
    )).one()

    stats = UserProfileStats(
        planned=status_counts.get(ListStatus.PLANNED, 0),
        watching=status_counts.get(ListStatus.WATCHING, 0),
        completed=status_counts.get(ListStatus.COMPLETED, 0),
        on_hold=status_counts.get(ListStatus.ON_HOLD, 0),
        dropped=status_counts.get(ListStatus.DROPPED, 0),
        scores_count=scores_count,
        mean_score=round(mean_score, 1) if mean_score is not None else None,
    )
    return UserProfileResponse(
        id=user.id, username=user.username, avatar_url=user.avatar_url,
        bio=user.bio, created_at=user.created_at, stats=stats,
    )


async def get_user_list(
    session: AsyncSession, username: str, status: ListStatus | None, page: int, limit: int
) -> UserAnimeListResponse:
    """Список пользователя по статусам. Выдача идёт по индексу (user_id, status, updated_at DESC)."""
    user = await _get_user_by_username(session, username)

    filters = [UserAnime.user_id == user.id]
    if status is not None:
        filters.append(UserAnime.status == status)
    total = await session.scalar(select(func.count()).select_from(UserAnime).where(*filters))

    rows = (await session.execute(
        select(UserAnime, Anime)
        .join(Anime, Anime.id == UserAnime.anime_id)
        .where(*filters)
        # tiebreak по anime_id: при равных updated_at порядок страниц детерминирован
        .order_by(UserAnime.updated_at.desc(), UserAnime.anime_id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).all()

    items = [
        UserListAnime(
            **AnimeCard.model_validate(anime).model_dump(exclude={"status"}),
            status=entry.status, score=entry.score,
            episodes_watched=entry.episodes_watched, updated_at=entry.updated_at,
        )
        for entry, anime in rows
    ]
    return UserAnimeListResponse(items=items, total=total or 0, page=page, limit=limit)


async def get_activity(
    session: AsyncSession, username: str, cursor: str | None, limit: int
) -> ActivityFeedResponse:
    """Курсорная лента по (created_at, id) DESC: детерминированно внутри равных таймстампов."""
    user = await _get_user_by_username(session, username)

    stmt = select(UserActivity).where(UserActivity.user_id == user.id)
    if cursor is not None:
        cursor_created, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(UserActivity.created_at, UserActivity.id) < (cursor_created, cursor_id)
        )
    rows = list((await session.scalars(
        stmt.order_by(UserActivity.created_at.desc(), UserActivity.id.desc()).limit(limit + 1)
    )).all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)

    anime_ids = {row.anime_id for row in rows if row.anime_id is not None}
    cards: dict[int, AnimeCard] = {}
    if anime_ids:
        for anime in (await session.scalars(select(Anime).where(Anime.id.in_(anime_ids)))).all():
            cards[anime.id] = AnimeCard.model_validate(anime)

    items = [
        ActivityItemResponse(
            id=row.id, type=row.type, anime_id=row.anime_id,
            payload=row.payload, created_at=row.created_at, anime=cards.get(row.anime_id),
        )
        for row in rows
    ]
    return ActivityFeedResponse(items=items, next_cursor=next_cursor)


async def get_compatibility(
    session: AsyncSession, user: User, username: str
) -> CompatibilityResponse:
    """Совпадение вкусов: корреляция Пирсона по общим оценкам с пользователем username.

    Учитываются тайтлы, оценённые обоими (score не NULL). Меньше COMPATIBILITY_MIN_COMMON
    общих оценок — compatibility null. Постоянные оценки одного из двух (нулевая
    дисперсия) тоже дают null: корреляция не определена.
    """
    other = await _get_user_by_username(session, username)

    mine = aliased(UserAnime)
    theirs = aliased(UserAnime)
    pairs = (await session.execute(
        select(mine.score, theirs.score)
        .select_from(mine)
        .join(theirs, theirs.anime_id == mine.anime_id)
        .where(
            mine.user_id == user.id,
            theirs.user_id == other.id,
            mine.score.is_not(None),
            theirs.score.is_not(None),
        )
    )).all()

    common = len(pairs)
    if common < COMPATIBILITY_MIN_COMMON:
        return CompatibilityResponse(common_titles=common, compatibility=None)

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    try:
        value = statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        # у одного из двух все оценки одинаковые — корреляция не определена
        return CompatibilityResponse(common_titles=common, compatibility=None)
    return CompatibilityResponse(common_titles=common, compatibility=round(value, 2))
