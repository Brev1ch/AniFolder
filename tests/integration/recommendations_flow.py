"""Сквозная проверка на ПУСТОЙ отдельной PostgreSQL БД с суффиксом _ml_integration.

Запуск Python из ml/.venv; --backend-python указывает Python с зависимостями backend.
TEST_DATABASE_URL обязателен. Скрипт применяет реальный Alembic и seed,
поднимает два HTTP-сервера на loopback, вызывает train и проверяет публичную выдачу.
БД не удаляет; общая dev-БД не допускается. Backend pytest/conftest не используется.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import psycopg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ml'))


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_ready(client, base, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('HTTP server exited; see logs')
        try:
            if client.get(base + '/health/readiness').status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError('HTTP server not ready')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-python', required=True)
    args = parser.parse_args()
    url = make_url(os.environ['TEST_DATABASE_URL'])
    assert url.get_backend_name() == 'postgresql'
    assert url.database and url.database.endswith('_ml_integration'), 'Use a dedicated test DB'
    sync_url = url.set(drivername='postgresql').render_as_string(hide_password=False)
    async_url = url.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False)
    with psycopg.connect(sync_url) as connection:
        assert connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0] == 0, 'Test DB must be empty'
    env = {**os.environ, 'DATABASE_URL': async_url, 'OPENBLAS_NUM_THREADS':'1',
           'JWT_SECRET':'integration-only-secret-0123456789abcdef', 'REDIS_URL':'redis://127.0.0.1:1/0'}
    subprocess.run([args.backend_python, '-m', 'alembic', 'upgrade', 'head'],
                   cwd=ROOT/'backend', env=env, check=True)
    with psycopg.connect(sync_url, autocommit=True) as connection:
        connection.execute((ROOT/'backend/scripts/seed_dev.sql').read_text())
    processes = []
    with tempfile.TemporaryDirectory(prefix='anifolder-integration-') as tmp, httpx.Client(timeout=10) as client:
        tmp = Path(tmp)
        handles = []
        try:
            backend_port, ml_port = free_port(), free_port()
            for name, python, port in [('backend',args.backend_python,backend_port),('ml',sys.executable,ml_port)]:
                handle = (tmp/f'{name}.log').open('w+')
                handles.append(handle)
                process = subprocess.Popen([python,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],
                    cwd=ROOT/name, env={**env,'ML_ARTIFACT_DIR':str(tmp/'artifacts')}, stdout=handle,stderr=subprocess.STDOUT)
                processes.append(process)
            backend, ml = f'http://127.0.0.1:{backend_port}', f'http://127.0.0.1:{ml_port}'
            for base, process in zip([backend,ml], processes): wait_ready(client,base,process)
            assert client.get(backend+'/api/v1/me/recommendations').status_code==401
            accounts=[]
            for name in ['integration_warm','integration_cold']:
                response=client.post(backend+'/api/v1/auth/register',json={
                    'username':name,'email':name+'@example.com','password':'integration123'})
                assert response.status_code==201, response.text
                data=response.json()
                accounts.append((data['user']['id'],{'Authorization':'Bearer '+data['access_token']}))
            with psycopg.connect(sync_url) as connection:
                connection.execute("INSERT INTO user_anime (user_id,anime_id,status,score) SELECT %s,id,'completed',8 FROM anime ORDER BY id LIMIT 6",(accounts[0][0],))
            response=client.post(ml+'/internal/v1/train')
            assert response.status_code==202 and response.json()=={'status':'ok'}
            for _ in range(600):
                status=client.get(ml+'/internal/v1/train/status').json()
                if status['status']!='running': break
                time.sleep(0.2)
            assert status['status']=='succeeded', status
            result=status['result']
            assert result['published'] and result['als_trained']
            assert result['routes']['all_time'] >= 1
            for user,headers in accounts:
                internal=client.get(f'{ml}/internal/v1/recommendations/{user}?limit=50')
                public=client.get(backend+'/api/v1/me/recommendations?limit=20',headers=headers)
                assert internal.status_code==public.status_code==200
                assert len(internal.json())==50 and len(public.json())==20
                assert [r['anime_id'] for r in public.json()]==[r['anime_id'] for r in internal.json()[:20]]
                assert all(r['anime']['id']==r['anime_id'] for r in public.json())
            user,headers=accounts[1]
            first=client.get(backend+'/api/v1/me/recommendations',headers=headers).json()[0]['anime_id']
            with psycopg.connect(sync_url) as connection:
                connection.execute("INSERT INTO user_anime (user_id,anime_id,status,score) VALUES (%s,%s,'dropped',2)",(user,first))
            after=client.get(backend+'/api/v1/me/recommendations',headers=headers).json()
            assert len(after)==20 and first not in [r['anime_id'] for r in after]
            assert first in [r['anime_id'] for r in client.get(f'{ml}/internal/v1/recommendations/{user}').json()]
            assert client.get(backend+'/api/v1/me/recommendations?limit=51',headers=headers).status_code==422
            assert client.get(backend+'/api/v1/me/recommendations',headers={'Authorization':'Bearer invalid'}).status_code==401
            with psycopg.connect(sync_url) as connection:
                assert connection.execute('SELECT count(*) FROM recommendations WHERE user_id<=0').fetchone()[0]==0
                assert connection.execute('SELECT count(*) FROM recommendations WHERE model_version=%s',(result['model_version'],)).fetchone()[0]==result['written_rows']
            from app.config import Settings
            from app.db import make_engine
            from app.training.train import LOCK_ID, publish, run_training
            from sqlalchemy import text
            from sqlalchemy.exc import IntegrityError
            import pandas as pd
            engine = make_engine(sync_url)
            try:
                with engine.connect() as connection:
                    before = connection.execute(text('SELECT anime_id,model_version FROM recommendations WHERE user_id=:u ORDER BY anime_id'), {'u':user}).all()
                try:
                    with engine.begin() as connection:
                        publish(connection, {user:[9223372036854775806]}, 'invalid-test', pd.Timestamp.now(tz='UTC').to_pydatetime())
                except IntegrityError:
                    pass
                else:
                    raise AssertionError('Foreign key violation was expected')
                with engine.connect() as connection:
                    assert connection.execute(text('SELECT anime_id,model_version FROM recommendations WHERE user_id=:u ORDER BY anime_id'), {'u':user}).all()==before
                with engine.connect() as holder:
                    holder.execute(text('SELECT pg_advisory_lock(:id)'), {'id':LOCK_ID})
                    holder.commit()
                    try:
                        try:
                            run_training(engine, Settings(_env_file=None, ml_artifact_dir=tmp/'locked'))
                        except RuntimeError:
                            pass
                        else:
                            raise AssertionError('Concurrent training should be rejected')
                    finally:
                        holder.execute(text('SELECT pg_advisory_unlock(:id)'), {'id':LOCK_ID})
                        holder.commit()
            finally:
                engine.dispose()
            print(json.dumps({'result':'passed','flow':'register -> train -> PostgreSQL -> authenticated recommendations -> current-list filtering',
                'site_users':result['site_users'],'written_rows':result['written_rows'],'routes':result['routes'],
                'atomic_rollback':True,'concurrent_training_lock':True},ensure_ascii=False,indent=2))
        except Exception:
            for handle in handles:
                handle.flush(); handle.seek(0)
                print(handle.read()[-6000:],file=sys.stderr)
            raise
        finally:
            for process in processes: process.terminate()
            for process in processes:
                try: process.wait(timeout=20)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            for handle in handles: handle.close()


if __name__=='__main__': main()
