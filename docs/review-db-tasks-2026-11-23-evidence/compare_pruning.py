"""Read-only comparison: tuple cursor alone vs redundant scalar upper bound.
This is a proposed query variant, not a backend change.
"""
import asyncio, os
from pathlib import Path
import asyncpg

async def main():
    db=await asyncpg.connect(os.environ['REVIEW_DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'))
    queries=[
        ('activity','SELECT id, created_at, user_id, type, anime_id, payload FROM user_activity WHERE user_id=$1 AND (created_at,id)<($2,$3)', 'ORDER BY created_at DESC,id DESC LIMIT 6', await db.fetchrow('SELECT created_at,id FROM user_activity WHERE user_id=1 ORDER BY created_at DESC,id DESC OFFSET 4 LIMIT 1'),1),
        ('comments','SELECT id,created_at,topic_id,author_id,parent_id,body FROM comments WHERE topic_id=$1 AND (created_at,id)<($2,$3)', 'ORDER BY created_at DESC,id DESC LIMIT 6', await db.fetchrow('SELECT created_at,id FROM comments WHERE topic_id=61 ORDER BY created_at DESC,id DESC OFFSET 4 LIMIT 1'),61),
    ]
    lines=[]
    for label,base,order,cursor,owner in queries:
        params=(owner,cursor[0],cursor[1])
        original=base+' '+order
        alternative=base+' AND created_at <= $2 '+order
        a=await db.fetch(original,*params)
        b=await db.fetch(alternative,*params)
        assert a==b
        for variant,sql in [('actual tuple cursor',original),('proposed redundant upper bound',alternative)]:
            lines.extend(['\n=== '+label+' / '+variant+' ===',sql,'parameters='+repr(params)])
            lines.extend(r[0] for r in await db.fetch('EXPLAIN (ANALYZE, BUFFERS) '+sql,*params))
        lines.append('PASS: identical page results (scalar <= retains same-time id tie semantics)')
    Path(__file__).with_name('partition-pruning-pg16.txt').write_text('\n'.join(lines)+'\n')
    await db.close()

asyncio.run(main())
