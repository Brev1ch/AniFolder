"""Review reproductions. Run from backend with PYTHONPATH=.; only disposable DB allowed."""
import asyncio
import os
from unittest.mock import patch
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.models.anime import Anime, anime_genres
from app.models.user import User
from app.services import catalog_service
from app.workers import catalog_sync as worker

# Explicit DSN required: set REVIEW_DATABASE_URL to your disposable review database.
URL = os.environ['REVIEW_DATABASE_URL']

class FakeRedis:
    def __init__(self): self.saved = []
    async def ping(self): pass
    async def get(self, key): return '100'
    async def set(self, key, value): self.saved.append(value)
    async def close(self, **kwargs): pass

class FakeSession:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

async def cursor_case(fail):
    redis = FakeRedis()
    class Client:
        async def fetch_page(self, page, cursor):
            return {'data': {'Page': {'media': [{'id': page, 'updatedAt': 300 if page == 1 else 200}], 'pageInfo': {'hasNextPage': page == 1}}}}
        async def close(self): pass
    async def apply(session, medias):
        if fail and medias[0]['id'] == 2: raise RuntimeError('simulated import failure')
        return len(medias)
    with patch.object(worker.Redis, 'from_url', return_value=redis), patch.object(worker, 'AniListClient', Client), patch.object(worker, 'SessionLocal', FakeSession), patch.object(worker, 'apply_media_batch', apply):
        try:
            await worker.run(max_pages=None if fail else 1)
        except RuntimeError as exc:
            print('cursor: propagated error:', str(exc))
    print('cursor', 'failure' if fail else 'max_pages', 'saved=', redis.saved, 'unprocessed updatedAt=200; next updatedAt >', redis.saved[-1] - 1)
    assert redis.saved == [300]

async def main():
    await cursor_case(True)
    await cursor_case(False)
    engine = create_async_engine(URL)
    statements = []
    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for size in [1, 50]:
            statements.clear()
            result = await catalog_service.list_anime(session, page=1, limit=size)
            print('list limit', size, ':', len(statements), 'SQL statements,', len(result.items), 'items')
            assert len(statements) == 2
        statements.clear()
        result = await catalog_service.get_anime_detail(session, 1)
        print('detail:', len(statements), 'SQL statements, genres=', len(result.genres))
        assert len(statements) == 2
    async with engine.connect() as conn:
        tx = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            count_genres = lambda: select(func.count()).select_from(anime_genres).where(anime_genres.c.anime_id == 1)
            before = await session.scalar(count_genres())
            before_ru = await session.scalar(select(Anime.title_ru).where(Anime.id == 1))
            await worker.apply_media_batch(session, [{'id': 900000001, 'status': 'FINISHED', 'genres': [], 'title': {'english': 'review'}}])
            after = await session.scalar(count_genres())
            after_ru = await session.scalar(select(Anime.title_ru).where(Anime.id == 1))
            print('empty genre snapshot:', before, '->', after, '(expected 0); title_ru preserved=', before_ru == after_ru)
            assert before > 0 and after == before
        await tx.rollback()
    async with AsyncSession(engine) as session:
        try:
            await worker.apply_media_batch(session, [{'id': 800000001, 'status': 'FINISHED', 'genres': ['Action'], 'title': {'english': 'review'}}])
        except KeyError as exc:
            print('nonmatching IDs: confirmed KeyError', exc)
            await session.rollback()
        else:
            raise AssertionError('Expected KeyError')
    # Reproduce the fixture default: rollback propagates to its outer transaction.
    async with engine.connect() as conn:
        tx = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            session.add(User(username='review_before_rollback', email='review_before_rollback@example.test', password_hash='x'))
            await session.flush()
            await session.rollback()
            print('fixture outer transaction active after service rollback:', tx.is_active)
            session.add(User(username='review_after_rollback', email='review_after_rollback@example.test', password_hash='x'))
            await session.commit()
        if tx.is_active: await tx.rollback()
    async with AsyncSession(engine) as session:
        exists = await session.scalar(select(User.id).where(User.username == 'review_after_rollback'))
        print('fixture row survives claimed external rollback:', exists is not None)
        assert exists is not None
    await engine.dispose()

asyncio.run(main())
