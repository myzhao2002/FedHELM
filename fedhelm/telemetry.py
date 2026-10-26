"""Allowlisted observations and per-node durable rolling windows. No injector inputs."""
import json
import os
import sqlite3
import statistics
import time
from pathlib import Path

FIELDS = ['availability','error_rate','latency_ms','pool_usage','worker_usage','worker_wait_ms',
          'db_wait_ms','dependency_ms','dependency_error_rate','config_error_rate','cpu_usage','rss_mb']
SCALES = [1,1,500,1,1,350,100,250,1,1,1,512]


def vector(obs):
    m=obs.metrics
    values=[float(obs.healthy),obs.error_rate,obs.latency_ms,obs.pool_usage,
            *[m.get(k,0.) for k in FIELDS[4:]]]
    return [max(0.,min(4.,float(v)/scale)) for v,scale in zip(values,SCALES)]


def database():
    folder=Path(os.getenv('DATA_DIR','runtime/default'));folder.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(folder/'telemetry.sqlite',timeout=10)
    con.execute('CREATE TABLE IF NOT EXISTS samples(seq INTEGER PRIMARY KEY, time REAL, payload TEXT)')
    return con


def append(obs):
    with database() as con:
        con.execute('INSERT INTO samples(time,payload) VALUES (?,?)',(time.time(),obs.model_dump_json()))
        con.execute('DELETE FROM samples WHERE seq < (SELECT MAX(seq)-2000 FROM samples)')
    con.close()


def window(limit=20):
    with database() as con:
        rows=con.execute('SELECT time,payload FROM samples ORDER BY seq DESC LIMIT ?', (limit,)).fetchall()
    con.close()
    return [{'time':t,**json.loads(p)} for t,p in reversed(rows)]


def detect(rows):
    """Detect symptoms, not fault classes; latency-only incidents are included."""
    if not rows:return {'anomalous':False,'reasons':[],'samples':0}
    recent=rows[-3:]
    reasons=[]
    if not rows[-1]['healthy'] or rows[-1]['error_rate']>.05:
        reasons.append('业务请求失败或错误率超过5%')
    if len(recent)>=3 and all(r['latency_ms']>500 for r in recent):
        reasons.append('连续3个采样窗口时延超过500ms')
    baseline=[r['latency_ms'] for r in rows[:-3] if r['healthy']]
    if len(baseline)>=5:
        median=statistics.median(baseline)
        mad=statistics.median(abs(x-median) for x in baseline)
        threshold=max(100,median+6*max(mad,5))
        if len(recent)==3 and all(r['latency_ms']>threshold for r in recent):
            reasons.append(f'时延持续偏离健康基线，阈值{threshold:.1f}ms')
    return {'anomalous':bool(reasons),'reasons':reasons,'samples':len(rows),
            'window_start':rows[0].get('time'),'window_end':rows[-1].get('time')}
