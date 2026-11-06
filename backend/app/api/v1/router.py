"""Сборка роутеров API v1."""

from fastapi import APIRouter

from app.api.v1 import anime, auth, genres

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(anime.router)
api_router.include_router(genres.router)
