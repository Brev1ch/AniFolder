"""Сборка роутеров API v1."""

from fastapi import APIRouter

from app.api.v1 import anime, auth, community, genres, me_list, recommendations, reviews, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(anime.router)
api_router.include_router(genres.router)
api_router.include_router(recommendations.router)
api_router.include_router(me_list.router)
api_router.include_router(users.router)
api_router.include_router(reviews.router)
api_router.include_router(community.router)
