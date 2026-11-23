"""Live HTTP smoke against a disposable migrated/seeded database; creates synthetic data.
REVIEW_DATABASE_URL must point to that database. Tokens/passwords are never printed.
"""
import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path
import asyncpg
import httpx

async def main():
    url = os.environ['REVIEW_DATABASE_URL']
    backend = Path(__file__).resolve().parents[2]/'backend'
    env = dict(os.environ, DATABASE_URL=url, JWT_SECRET=secrets.token_hex(32), PYTHONPATH=str(backend))
    log = open('/tmp/anifolder-nikita-live-api.log','w')
    process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18036'],cwd=backend,env=env,stdout=log,stderr=subprocess.STDOUT)
    db = await asyncpg.connect(url.replace('postgresql+asyncpg://','postgresql://'))
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:18036',timeout=10) as client:
            for _ in range(100):
                try:
                    if (await client.get('/health/readiness')).status_code == 200: break
                except httpx.ConnectError: pass
                await asyncio.sleep(0.1)
            else: raise AssertionError('Local API readiness failed')
            async def request(method,path,expected=200,**kwargs):
                response=await client.request(method,path,**kwargs)
                assert response.status_code==expected,(method,path,response.status_code)
                print('PASS',method,path.split('?')[0],response.status_code)
                return response.json()
            await request('GET','/api/v1/users/user1/list',params={'status':'completed'})
            activity=await request('GET','/api/v1/users/user1/activity',params={'limit':5})
            assert activity['next_cursor']
            next_activity=await request('GET','/api/v1/users/user1/activity',params={'limit':5,'cursor':activity['next_cursor']})
            assert not ({x['id'] for x in activity['items']} & {x['id'] for x in next_activity['items']})
            aid=await db.fetchval('SELECT anime_id FROM reviews GROUP BY anime_id ORDER BY count(*) DESC,anime_id LIMIT 1')
            reviews=await request('GET',f'/api/v1/anime/{aid}/reviews',params={'limit':5})
            next_reviews=await request('GET',f'/api/v1/anime/{aid}/reviews',params={'limit':5,'page':2})
            assert not ({x['id'] for x in reviews['items']} & {x['id'] for x in next_reviews['items']})
            await request('GET','/api/v1/topics')
            await request('GET','/api/v1/topics',params={'anime_id':10})
            tid=await db.fetchval('SELECT topic_id FROM comments GROUP BY topic_id ORDER BY count(*) DESC,topic_id LIMIT 1')
            comments=await request('GET',f'/api/v1/topics/{tid}/comments',params={'limit':5})
            assert comments['next_cursor']
            next_comments=await request('GET',f'/api/v1/topics/{tid}/comments',params={'limit':5,'cursor':comments['next_cursor']})
            assert not ({x['id'] for x in comments['items']} & {x['id'] for x in next_comments['items']})
            username='smoke_'+secrets.token_hex(4)
            auth=await request('POST','/api/v1/auth/register',201,json={'username':username,'email':username+'@example.com','password':secrets.token_hex(12)})
            headers={'Authorization':'Bearer '+auth['access_token']}
            pairs=await db.fetch('SELECT anime_id FROM user_anime WHERE user_id=1 AND score IS NOT NULL ORDER BY anime_id LIMIT 5')
            for score,row in enumerate(pairs,1):
                await request('PUT',f'/api/v1/me/list/{row[0]}',headers=headers,json={'status':'completed','score':score})
            compatibility=await request('GET','/api/v1/users/user1/compatibility',headers=headers)
            assert compatibility['common_titles']==5
            own=await request('GET',f'/api/v1/users/{username}/compatibility',headers=headers)
            assert own['common_titles']==5 and own['compatibility']==1.0
            review=await request('POST',f'/api/v1/anime/{aid}/reviews',201,headers=headers,json={'score':8,'text':'Synthetic migration smoke review'})
            topic=await request('POST','/api/v1/topics',201,headers=headers,json={'title':'Synthetic migration smoke topic','body':'Synthetic local smoke data'})
            comment=await request('POST',f'/api/v1/topics/{topic["id"]}/comments',201,headers=headers,json={'body':'Synthetic local smoke comment'})
            await db.execute('DELETE FROM users WHERE id=$1',auth['user']['id'])
            listed=await request('GET',f'/api/v1/anime/{aid}/reviews')
            retained=next(x for x in listed['items'] if x['id']==review['id'])
            assert retained['user_id'] is None and retained['username']=='deleted_user'
            orphan_comments=await request('GET',f'/api/v1/topics/{topic["id"]}/comments')
            assert orphan_comments['items'][0]['author_id'] is None and orphan_comments['items'][0]['username']=='deleted_user'
            print('PASS migration 0002: deleted author review survives via live API; NULL author + deleted_user')
            print('PASS cursor pages do not overlap; compatibility threshold/self checked')
    finally:
        await db.close()
        process.terminate()
        process.wait(timeout=10)
        log.close()

asyncio.run(main())
