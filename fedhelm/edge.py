import math
import os
import sqlite3
from pathlib import Path
from threading import RLock,BoundedSemaphore
from fastapi import FastAPI, HTTPException, Request
from .contracts import Case, InferenceRequest, Resources, Search, Plan
from .common import request
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    from . import scheduler
    scheduler.start()
    from . import training_control
    training_control.start()
    yield
    scheduler.stop()
    training_control.stop()

app = FastAPI(title='FedHELM edge coordination', version='0.1.0', lifespan=lifespan)
resources = {}
lock = RLock()
inference_slot=BoundedSemaphore(1)
inference_waiting=0
inference_active=0


def db():
    directory = Path(os.getenv('DATA_DIR', 'runtime/edge'))
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / 'memory.sqlite')
    connection.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return connection


@app.get('/health')
def health():
    from .common import runtime_info
    return {'status': 'ok','inference_queue':inference_waiting,'inference_active':inference_active, 'simulated': True,**runtime_info('edge','edge'),'host_info':__import__('fedhelm.host_info',fromlist=['snapshot']).snapshot()}


@app.post('/resources')
def report(body: Resources):
    with lock:
        resources[body.node_id] = body.model_dump()
    from .traffic import record
    record(body.node_id,'edge','telemetry',bytes_count=len(body.model_dump_json().encode()))
    return {'accepted': True, 'simulated': True}


@app.get('/resources')
def resources_endpoint(request: Request):
    if 'text/html' in request.headers.get('accept', ''):
        from .dashboard import index
        return index()
    return resource_snapshot()


def resource_snapshot():
    with lock:
        return {'nodes': list(resources.values()), 'simulated': True}


@app.post('/diagnose', response_model=Plan)
def diagnose(body: InferenceRequest):
    from .traffic import record
    record(body.observation.node_id,'edge','diagnosis',bytes_count=len(body.model_dump_json().encode()),event_id=body.observation.event_id)
    global inference_waiting,inference_active
    with lock:inference_waiting+=1
    acquired=inference_slot.acquire(timeout=30)
    with lock:
        inference_waiting-=1
        if acquired:inference_active+=1
    if not acquired:raise HTTPException(503,'边缘推理队列等待超时')
    try:
        matches = search(Search(embedding=body.diagnosis.embedding,
                                embedding_version=body.diagnosis.embedding_version))
        body = body.model_copy(update={'retrieved_cases': [Case.model_validate(h['case']) for h in matches['hits']]})
        result = request('POST', os.getenv('LLM_URL', 'http://127.0.0.1:8002'), '/infer', body.model_dump())
        result['mode'] = 'edge'
        checked=Plan.model_validate(result)
        record('edge',body.observation.node_id,'plan',bytes_count=len(checked.model_dump_json().encode()),event_id=checked.event_id)
        return checked
    except Exception as exc:
        raise HTTPException(503, f'model adapter unavailable: {type(exc).__name__}') from exc
    finally:
        with lock:inference_active-=1
        inference_slot.release()


@app.post('/memory/cases')
def store_case(body: Case):
    samples = body.feedback.samples
    verified = (len(samples) >= 3 and all(
        s.event_id == body.plan.event_id and s.node_id == body.source_node
        and s.service_id == body.plan.service_id for s in samples)
        and all(s.healthy and s.error_rate <= .05 and s.latency_ms <= 500 for s in samples[-3:]))
    if (not body.feedback.success or not verified or body.plan.confidence < .6
            or not body.root_cause_confirmed or body.plan.action == 'none'):
        raise HTTPException(422, 'case requires successful verification, confirmed label and confidence >= 0.6')
    connection = db()
    try:
        with connection:
            old = connection.execute('SELECT payload FROM cases WHERE id=?', (body.case_id,)).fetchone()
            if old and old[0] != body.model_dump_json():
                raise HTTPException(409, 'case_id already exists with different content')
            connection.execute('INSERT OR IGNORE INTO cases VALUES (?,?)', (body.case_id, body.model_dump_json()))
    finally:
        connection.close()
    from .traffic import record
    record(body.source_node,'edge','memory',bytes_count=len(body.model_dump_json().encode()),event_id=body.case_id)
    return {'accepted': True, 'case_id': body.case_id, 'simulated': True}


@app.get('/memory/snapshot')
def snapshot():
    connection = db()
    try:
        rows = connection.execute('SELECT payload FROM cases ORDER BY id LIMIT 1000').fetchall()
        cases=[Case.model_validate_json(r[0]).model_dump() for r in rows]
        from collections import Counter
        counts=Counter((c['diagnosis']['root_cause'],c['plan']['action']) for c in cases)
        cases.sort(key=lambda c:(counts[(c['diagnosis']['root_cause'],c['plan']['action'])],c['diagnosis']['confidence']),reverse=True)
        summary=[{'root_cause':root,'action':action,'frequency':count} for (root,action),count in counts.most_common(20)]
        return {'cases':cases[:100],'summary':summary,'simulated':True}
    finally:
        connection.close()


@app.post('/memory/search')
def search(body: Search):
    hits = []
    for item in snapshot()['cases']:
        if item['diagnosis']['embedding_version'] != body.embedding_version:
            continue
        vector = item['diagnosis']['embedding']
        if len(vector)!=len(body.embedding):
            continue
        denom = math.sqrt(sum(v*v for v in vector) * sum(v*v for v in body.embedding))
        similarity = sum(a*b for a, b in zip(vector, body.embedding)) / denom if denom else 0
        if similarity >= .82:
            hits.append({'similarity': similarity, 'case': item})
    return {'hits': sorted(hits, key=lambda h: h['similarity'], reverse=True)[:body.top_k], 'simulated': True}


from .dashboard import router
from .chinese import localize
app.include_router(router)
localize(app, 'FedHELM · 边缘协调与故障记忆')

from .cluster_api import router as cluster_router
app.include_router(cluster_router)
from .training_control import router as training_router
app.include_router(training_router)

from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def safe_configuration_errors(request, exc):
    if request.url.path.startswith('/ui/model-api/'):
        # Pydantic's default error input can include the submitted API key.
        return JSONResponse(status_code=422, content={'detail': [
            {k: e[k] for k in ('loc', 'msg', 'type')} for e in exc.errors()]})
    return await request_validation_exception_handler(request, exc)
