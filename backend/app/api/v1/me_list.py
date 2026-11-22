"""Список текущего пользователя: PUT/DELETE /me/list/{anime_id}."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.library import UserListEntryPut, UserListEntryResponse
from app.services import library_service

router = APIRouter(prefix="/me/list", tags=["list"])


@router.put("/{anime_id}", response_model=UserListEntryResponse)
async def put_list_entry(
    body: UserListEntryPut,
    anime_id: Annotated[int, Path(ge=1)],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserListEntryResponse:
    """Добавить тайтл в список или обновить статус, оценку и прогресс."""
    return await library_service.upsert_entry(session, user.id, anime_id, body)


@router.delete("/{anime_id}")
async def delete_list_entry(
    anime_id: Annotated[int, Path(ge=1)],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Убрать тайтл из списка."""
    await library_service.remove_entry(session, user.id, anime_id)
    return {"ok": True}
