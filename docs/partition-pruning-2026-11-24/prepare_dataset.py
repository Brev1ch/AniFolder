"""Prepare synthetic cross-partition data in a disposable migrated PostgreSQL 16 DB."""
import asyncio, json, os
from datetime import timedelta
from pathlib import Path
import asyncpg

async def main():
    db=await asyncpg.connect(os.environ['REVIEW_DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'))
    uid=await db.fetchval("INSERT INTO users(username,email,password_hash) VALUES ('pruning_probe','pruning_probe@example.com','x') RETURNING id")
    if await db.fetchval("SELECT to_regclass('comments_p' || to_char(now() + interval '1 year', 'YYYY'))") is None:
        await db.execute('SELECT ensure_partitions(12)')
    topic=await db.fetchval("INSERT INTO topics(author_id,title,body) VALUES ($1,'Pruning probe','Synthetic data') RETURNING id",uid)
    data={'postgresql':await db.fetchval('SHOW server_version'),'settings':dict(await db.fetchrow("SELECT current_setting('enable_seqscan') AS enable_seqscan, current_setting('random_page_cost') AS random_page_cost"))}
    for kind,period,table,owner_column,owner in [('activity','month','user_activity','user_id',uid),('comments','year','comments','topic_id',topic)]:
        boundary=await db.fetchval(f"SELECT date_trunc('{period}',now())+interval '1 {period}'")
        times=[boundary,boundary+timedelta(seconds=1),boundary-timedelta(microseconds=1)]*3
        for t in times:
            if kind=='activity':
                await db.execute("INSERT INTO user_activity(user_id,type,payload,created_at) VALUES ($1,'scored','{}',$2)",owner,t)
            else:
                await db.execute("INSERT INTO comments(topic_id,body,created_at) VALUES ($1,'Synthetic comment',$2)",owner,t)
        rows=[dict(r) for r in await db.fetch(f'SELECT id,created_at,tableoid::regclass::text AS partition FROM {table} WHERE {owner_column}=$1 ORDER BY created_at DESC,id DESC',owner)]
        assert len({r['partition'] for r in rows})==2
        data[kind]={'owner':owner,'boundary':boundary,'rows':rows}
    await db.execute('ANALYZE')
    Path(__file__).with_name('dataset.json').write_text(json.dumps(data,indent=2,default=str)+'\n')
    await db.close()

asyncio.run(main())
