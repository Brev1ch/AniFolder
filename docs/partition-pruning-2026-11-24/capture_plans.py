"""Capture actual service query plans; run with before/after PYTHONPATH on the same DB.
REVIEW_DATABASE_URL is supplied externally and never written to evidence.
"""
import asyncio, json, os, sys
from datetime import datetime
from pathlib import Path
import asyncpg
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession,create_async_engine
from app.services import library_service,community_service
from app.services.cursor import encode_cursor

OUT=Path(__file__).resolve().parent

async def main():
    label=sys.argv[1]
    assert label in ['before','after']
    dataset=json.loads((OUT/'dataset.json').read_text())
    url=os.environ['REVIEW_DATABASE_URL']
    db=await asyncpg.connect(url.replace('postgresql+asyncpg://','postgresql://'))
    engine=create_async_engine(url)
    captured=[]
    @event.listens_for(engine.sync_engine,'before_cursor_execute')
    def capture(conn,cursor,sql,params,context,executemany):
        if sql.lstrip().startswith('SELECT') and ('FROM user_activity ' in sql or 'FROM comments ' in sql):
            captured.append((sql,tuple(params)))
    records=[]; transcript=[]
    async with AsyncSession(engine,expire_on_commit=False) as session:
        for kind in ['activity','comments']:
            rows=dataset[kind]['rows']
            # First page; same-time tie in the newer partition; cursor in older partition.
            for name,index in [('first',None),('boundary-tie',4),('older-partition',7)]:
                cursor=None if index is None else encode_cursor(datetime.fromisoformat(rows[index]['created_at']),rows[index]['id'])
                captured.clear()
                if kind=='activity': result=await library_service.get_activity(session,'pruning_probe',cursor,5)
                else: result=await community_service.list_comments(session,dataset[kind]['owner'],cursor,5)
                assert len(captured)==1
                sql,params=captured[0]
                plan=json.loads(await db.fetchval('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+sql,*params))[0]
                textplan='\n'.join(r[0] for r in await db.fetch('EXPLAIN (ANALYZE, BUFFERS) '+sql,*params))
                def relations(node):
                    names=[node['Relation Name']] if 'Relation Name' in node else []
                    for child in node.get('Plans',[]): names.extend(relations(child))
                    return names
                record={'kind':kind,'case':name,'sql':sql,'parameters':params,'ids':[r.id for r in result.items],'next_cursor':result.next_cursor,'relations':relations(plan['Plan']),'plan':plan}
                records.append(record)
                transcript.extend(['\n=== '+label+' / '+kind+' / '+name+' ===',sql,'Parameters: '+repr(params),textplan])
    (OUT/f'plans-{label}-pg16.json').write_text(json.dumps(records,indent=2,default=str)+'\n')
    (OUT/f'plans-{label}-pg16.txt').write_text('\n'.join(transcript)+'\n')
    for r in records: print(label,r['kind'],r['case'],'ids=',r['ids'],'partitions=',r['relations'])
    await engine.dispose(); await db.close()

asyncio.run(main())
