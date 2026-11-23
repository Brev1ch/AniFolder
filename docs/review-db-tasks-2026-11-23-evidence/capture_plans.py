"""Read-only EXPLAIN capture for actual current-main service statements.
Run from backend with PYTHONPATH=. and REVIEW_DATABASE_URL set to a seeded disposable DB.
"""
import asyncio
import json
import os
import platform
from datetime import date, datetime
from pathlib import Path

import asyncpg
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.models.user import User
from app.models.enums import ListStatus
from app.services import library_service, review_service, community_service
from app.services.cursor import encode_cursor

OUT = Path(__file__).resolve().parent
URL = os.environ['REVIEW_DATABASE_URL']
SOURCE = {
    'list': 'backend/app/services/library_service.py:196-225',
    'activity': 'backend/app/services/library_service.py:228-262',
    'reviews': 'backend/app/services/review_service.py:42-70',
    'topics': 'backend/app/services/community_service.py:42-70',
    'comments': 'backend/app/services/community_service.py:96-131',
    'compatibility': 'backend/app/services/library_service.py:265-301',
}

async def main():
    db = await asyncpg.connect(URL.replace('postgresql+asyncpg://', 'postgresql://'))
    await db.execute('ANALYZE')
    env = {'postgresql': await db.fetchval('SHOW server_version'), 'python': platform.python_version(),
           'source_commit': 'db5ae5290eef50ded2dac07fe4d1c682311fdb09', 'dataset': 'unmodified seed_dev.sql after migration 0002',
           'settings': dict(await db.fetchrow("SELECT current_setting('random_page_cost') AS random_page_cost, current_setting('enable_seqscan') AS enable_seqscan, current_setting('work_mem') AS work_mem")),
           'counts': {t: await db.fetchval('SELECT count(*) FROM '+t) for t in ['users','anime','user_anime','user_activity','reviews','topics','comments']}}
    env['partitions'] = [dict(r) for r in await db.fetch("SELECT tableoid::regclass::text AS partition, count(*) AS rows FROM user_activity GROUP BY 1 UNION ALL SELECT tableoid::regclass::text, count(*) FROM comments GROUP BY 1 ORDER BY 1")]
    anime_id = await db.fetchval('SELECT anime_id FROM reviews GROUP BY anime_id ORDER BY count(*) DESC, anime_id LIMIT 1')
    topic_id = await db.fetchval('SELECT topic_id FROM comments GROUP BY topic_id ORDER BY count(*) DESC, topic_id LIMIT 1')
    engine = create_async_engine(URL)
    captured = []
    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            captured.append((statement, tuple(parameters)))
    summary = []
    transcript = []
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, 1)
        async def scenario(group, name, operation):
            captured.clear()
            result = await operation()
            statements = list(captured)
            transcript.append('\n=== '+name+' ===\nSource: '+SOURCE[group])
            items = []
            for number, (sql, params) in enumerate(statements, 1):
                textplan = await db.fetch('EXPLAIN (ANALYZE, BUFFERS) '+sql, *params)
                jsonplan = await db.fetchval('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+sql, *params)
                plan = json.loads(jsonplan)[0]
                transcript.extend(['\nStatement '+str(number), sql, 'Parameters: '+repr(params), '\n'.join(r[0] for r in textplan)])
                items.append({'statement': number, 'sql': sql, 'parameters': params, 'plan': plan})
            summary.append({'group': group, 'name': name, 'source': SOURCE[group], 'sql_count': len(statements), 'statements': items})
            return result
        await scenario('list','list/status=completed/page=1',lambda: library_service.get_user_list(session,'user1',ListStatus.COMPLETED,1,20))
        await scenario('list','list/all-statuses/page=1',lambda: library_service.get_user_list(session,'user1',None,1,20))
        feed = await scenario('activity','activity/first',lambda: library_service.get_activity(session,'user1',None,5))
        assert feed.next_cursor is not None
        await scenario('activity','activity/next',lambda: library_service.get_activity(session,'user1',feed.next_cursor,5))
        await scenario('reviews','reviews/first',lambda: review_service.list_reviews(session,anime_id,1,5))
        await scenario('reviews','reviews/page=2',lambda: review_service.list_reviews(session,anime_id,2,5))
        await scenario('topics','topics/global',lambda: community_service.list_topics(session,None,1,20))
        await scenario('topics','topics/anime=10',lambda: community_service.list_topics(session,10,1,20))
        comments = await scenario('comments','comments/first',lambda: community_service.list_comments(session,topic_id,None,5))
        assert comments.next_cursor is not None
        await scenario('comments','comments/next',lambda: community_service.list_comments(session,topic_id,comments.next_cursor,5))
        await scenario('compatibility','compatibility/user1-user2',lambda: library_service.get_compatibility(session,user,'user2'))
        await scenario('compatibility','compatibility/self',lambda: library_service.get_compatibility(session,user,'user1'))
    (OUT/'environment.json').write_text(json.dumps(env,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'query-plans-pg16.txt').write_text('\n'.join(transcript)+'\n',encoding='utf-8')
    (OUT/'query-plans-pg16.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    for item in summary:
        print(item['name'], 'SQL count=',item['sql_count'])
        for stmt in item['statements']:
            def walk(n):
                yield n
                for c in n.get('Plans',[]): yield from walk(c)
            nodes = list(walk(stmt['plan']['Plan']))
            print(' ', stmt['statement'], '; '.join(n['Node Type']+(' '+n['Index Name'] if 'Index Name' in n else '') for n in nodes if 'Scan' in n['Node Type'] or n['Node Type'] in ['Sort','Incremental Sort','Merge Append']), 'time_ms=',stmt['plan']['Execution Time'])
    await engine.dispose()
    await db.close()

asyncio.run(main())
