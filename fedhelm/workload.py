"""Synthetic workload: mutable failure state, NOT OS-level fault injection."""
import os
from threading import RLock
from fastapi import FastAPI, HTTPException
from .contracts import Injection, Observation, Plan
from .common import audit

app = FastAPI(title='FedHELM synthetic workload', version='0.1.0')
node = os.getenv('NODE_ID', 'a')
service = f'service-{node}'
fault = 'healthy'
lock = RLock()


@app.get('/health')
def health():
    return {'status': 'ok', 'simulated': True}


@app.post('/inject')
def inject(body: Injection):
    global fault
    if body.fault in ('thread_pool_exhausted','dependency_timeout'):
        raise HTTPException(400,'新增故障仅支持实际业务后端')
    with lock:
        fault = body.fault
        audit('injection', body.model_dump())
        return {'fault': fault, 'simulated': True}


@app.get('/observe', response_model=Observation)
def observe(event_id: str):
    with lock:
        logs = {'healthy': [], 'service_down': ['process unavailable'],
                'config_error': ['invalid configuration'], 'pool_exhausted': ['connection timeout']}
        return Observation(event_id=event_id, node_id=node, service_id=service,
                           healthy=fault == 'healthy', error_rate=0 if fault == 'healthy' else 1,
                           latency_ms=20 if fault == 'healthy' else 1500,
                           pool_usage=.99 if fault == 'pool_exhausted' else .2, logs=logs[fault])


@app.post('/execute')
def execute(body: Plan):
    global fault
    if body.node_id != node or body.service_id != service or body.parameters:
        raise HTTPException(400, 'wrong target or unsupported parameters')
    with lock:
        expected = {'healthy': 'none', 'service_down': 'restart_service',
                    'config_error': 'restore_config', 'pool_exhausted': 'reset_pool'}
        applied = body.action == expected[fault]
        if applied:
            fault = 'healthy'
        result = {'applied': applied, 'event_id': body.event_id, 'simulated': True}
        audit('execution', {**body.model_dump(), **result})
        return result


from .chinese import localize
localize(app, 'FedHELM · 模拟业务与故障注入')
