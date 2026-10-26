"""Supervises only its own sandbox business child; gathers real HTTP observations."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import httpx
from fastapi import FastAPI, HTTPException
from .contracts import Injection, Observation, Plan
from .common import audit


class Business:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.process = None
        self.url = None
        self.log_stream = None
        self.lock = threading.RLock()
        self.configure(True)

    def configure(self, enabled):
        temporary = self.directory/'config.tmp'
        temporary.write_text(json.dumps({'database_enabled': enabled}))
        temporary.replace(self.directory/'config.json')

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.stop()
        self.log_stream = (self.directory/'business.log').open('a', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable,'-m','fedhelm.business','--directory',str(self.directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log_stream, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        line = []
        reader = threading.Thread(target=lambda: line.append(self.process.stdout.readline()), daemon=True)
        reader.start()
        reader.join(8)
        if not line or not line[0]:
            self.stop()
            raise RuntimeError('测试业务启动失败，请查看business.log')
        self.url = 'http://127.0.0.1:' + str(json.loads(line[0])['port'])

    def stop(self):
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=3)
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None
        if self.log_stream:
            self.log_stream.close()
            self.log_stream = None
        self.url = None

    def admin(self, action):
        if not self.process or self.process.poll() is not None:
            return False
        with httpx.Client(timeout=2,trust_env=False) as client:
            response = client.post(self.url+'/admin/'+action)
            response.raise_for_status()
        return True

    def inject(self, fault):
        with self.lock:
            # Reset fixture before creating one isolated fault.
            self.configure(True)
            self.start()
            self.admin('reset-pool')
            self.admin('reset-workers')
            self.admin('restore-dependency')
            if fault == 'service_down':
                self.stop()
            elif fault == 'config_error':
                self.configure(False)
            elif fault == 'pool_exhausted':
                self.admin('hold-pool')
            elif fault == 'thread_pool_exhausted':
                self.admin('hold-workers')
            elif fault == 'dependency_timeout':
                self.admin('delay-dependency')

    def execute(self, action):
        with self.lock:
            if action == 'restart_service':
                self.stop()
                self.start()
            elif action == 'restore_config':
                self.configure(True)
            elif action == 'reset_pool':
                return self.admin('reset-pool')
            elif action == 'reset_workers':
                return self.admin('reset-workers')
            elif action == 'restore_dependency':
                return self.admin('restore-dependency')
            elif action != 'none':
                return False
            return True

    def observe(self, event_id, node):
        with self.lock:
            codes, times, errors, spans = [], [], [], []
            alive = bool(self.process and self.process.poll() is None)
            usage = 0.
            metrics = {}
            with httpx.Client(timeout=1,trust_env=False) as client:
                for _ in range(3):
                    started = time.perf_counter()
                    try:
                        if not alive:
                            raise ConnectionError('process unavailable')
                        response = client.get(self.url+'/orders')
                        codes.append(response.status_code)
                        spans.extend(response.json().get('spans',[]))
                        if response.status_code != 200:
                            errors.append(response.json().get('error','request failed'))
                    except (httpx.HTTPError, ConnectionError):
                        codes.append(0)
                        errors.append('process unavailable' if not alive else 'request failed')
                    times.append((time.perf_counter()-started)*1000)
                if alive:
                    try:
                        raw=client.get(self.url+'/metrics').json()
                        from .telemetry import FIELDS
                        metrics={k:float(raw[k]) for k in FIELDS if k in raw}
                        usage=metrics.get('pool_usage',0.)
                    except (httpx.HTTPError, ValueError, KeyError):
                        pass
            return Observation(event_id=event_id,node_id=node,service_id=f'service-{node}',
                healthy=all(c==200 for c in codes),error_rate=sum(c!=200 for c in codes)/len(codes),
                latency_ms=statistics.median(times),pool_usage=usage,logs=list(dict.fromkeys(errors)),
                metrics=metrics,spans=spans,observed_at=time.time(),workload_backend='process',response_codes=codes,business_pid=self.process.pid if alive else None)


node = os.getenv('NODE_ID','a')
business = None


@asynccontextmanager
async def lifespan(app):
    global business
    business = Business(Path(os.getenv('DATA_DIR','runtime/process-workload'))/'business')
    business.start()
    try:
        yield
    finally:
        business.stop()


app = FastAPI(title='FedHELM · 实际测试业务控制器', lifespan=lifespan)
intervention_revision = 0


@app.get('/health')
def health():
    from .common import runtime_info
    return {'status':'ok','simulated':True,'workload_backend':'process','intervention_revision':intervention_revision,
            'business_pid':business.process.pid if business and business.process else None,
            **runtime_info('workload-'+node,node.upper())}


@app.post('/inject')
def inject(body: Injection):
    global intervention_revision
    business.inject(body.fault)
    intervention_revision += 1
    audit('process_injection', body.model_dump())
    return {'fault':body.fault,'workload_backend':'process','simulated':True}


@app.get('/observe',response_model=Observation)
def observe(event_id: str):
    return business.observe(event_id,node)


@app.post('/execute')
def execute(body: Plan):
    if body.node_id != node or body.service_id != f'service-{node}' or body.parameters:
        raise HTTPException(400,'仅允许操作当前测试服务，且参数必须为空')
    applied = business.execute(body.action)
    result = {'applied':applied,'event_id':body.event_id,'workload_backend':'process','simulated':True}
    audit('process_execution',{**body.model_dump(),**result})
    return result


from .chinese import localize
localize(app,'FedHELM · 实际测试业务控制器')
app.description = '受控测试床：独立HTTP进程、SQLite数据库和连接池；指标来自实际HTTP请求。故障人为注入，端侧可使用实际训练的轻量模型，新增故障使用显式日志规则。'
for route in app.routes:
    if route.path == '/inject':
        route.summary = '注入测试故障（实际进程、配置与连接池）'
        route.description = '仅操作此控制器拥有的测试业务：停止子进程、写入错误配置或占住SQLite连接。'
    elif route.path == '/observe':
        route.summary = '采集实际测试业务观测'
        route.description = '发起3次HTTP业务请求，记录响应码、错误率、中位时延、连接池占用与业务进程ID。'
    elif route.path == '/execute':
        route.description = '在当前测试业务执行实际重启、配置恢复或连接池释放；动作执行完成不代表服务恢复，必须继续观测。'

from .common import protect_node_service
protect_node_service(app)
