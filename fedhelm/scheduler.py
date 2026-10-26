"""Low frequency, single-flight supervision of the three project workloads."""
import time
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Literal
from .registry import node_ids,LocationId

guard = Lock()
events = deque(maxlen=500)
enabled = True
stopping = Event()
worker = None
nodes = {n: {'state': '等待巡检', 'attempts': 0, 'next_retry': 0} for n in node_ids()}
incidents = {}

class Trace(BaseModel):
    node: LocationId
    event_id: str
    stage: str
    detail: str
    payload: dict = {}

def emit(node, event_id, stage, detail, payload=None):
    from .history import record
    record(node,event_id,stage,detail,payload)
    with guard:
        events.append({'id': str(uuid.uuid4()), 'time': datetime.now(timezone.utc).isoformat(),
                       'node': node, 'event_id': event_id, 'stage': stage, 'detail': detail})

def snapshot():
    from .history import query
    persisted=[{'id':r['seq'],'time':r['time'],'node':r['node'],'event_id':r['task'],'stage':r['stage'],'detail':r['detail']} for r in reversed(query(limit=500,include_payload=False))]
    with guard:
        return {'enabled': enabled, 'interval_seconds': 10, 'max_attempts': 2,
                'nodes': {n: dict(s) for n,s in nodes.items()}, 'events': persisted}

def reset(node):
    with guard:
        nodes[node].update(attempts=0, next_retry=0, state='等待巡检')

def tick():
    from . import dashboard as d
    for n in node_ids():
        if stopping.is_set() or not enabled:
            return
        if not d.control_lock.acquire(blocking=False):
            return
        incident = None
        try:
            if not enabled:
                return
            anomaly=None
            if os.getenv('PAPER_PROFILE')=='1':
                telemetry=d.request('GET',d.address('agent',n),'/telemetry',timeout=12)
                obs=telemetry['latest'];anomaly=telemetry['anomaly']
                if not obs:continue
            else:
                obs = d.request('GET', d.address('workload', n), '/observe?event_id=monitor', timeout=12)
            from .history import metric
            metric(n,obs)
            with guard:
                nodes[n]['checked_at'] = datetime.now(timezone.utc).isoformat()
                nodes[n]['observation'] = obs
            if (not anomaly['anomalous']) if anomaly is not None else (obs['healthy'] and obs['error_rate'] <= .05):
                incidents.pop(n,None)
                with guard:
                    nodes[n].update(state='正常', attempts=0, next_retry=0)
                continue
            with guard:
                attempts = nodes[n]['attempts']
                retry = nodes[n]['next_retry']
            if attempts >= 2 or time.monotonic() < retry:
                continue
            incident = incidents.setdefault(n,str(uuid.uuid4()))
            emit(n, incident, '检测异常', '；'.join(anomaly['reasons']) if anomaly else f"错误率 {obs['error_rate']:.0%}，开始自动处置",{'anomaly':anomaly,'observation':obs})
            with guard:
                nodes[n].update(state='自动诊断处置中', attempts=attempts+1, next_retry=time.monotonic()+60)
            # Sync once per incident to pick up global model and verified memory.
            d.request('POST', d.address('agent', n), '/sync', timeout=120)
            emit(n, incident, '模型同步', '已加载全局轻量模型与故障记忆')
            retry_mode = 'edge' if attempts > 0 and os.getenv('PAPER_PROFILE') == '1' else None
            if retry_mode:
                emit(n, incident, '升级复核', '上次处置未恢复，重新采集指标并请求边缘复核')
            result = d.request('POST', d.address('agent', n), '/run', {'force_mode': retry_mode,'event_id':incident}, timeout=660)
            d.last[n] = {'result': result, 'truth': d.truth.get(n)}
            ok = result['feedback']['success']
            if ok:
                incidents.pop(n,None)
                d.truth.pop(n,None)
            with guard:
                nodes[n]['state'] = '已恢复' if ok else ('等待人工检查' if attempts+1>=2 else '恢复失败，60秒后重试')
            emit(n, result['observation']['event_id'], '处置完成' if ok else '恢复失败',
                 '真实HTTP恢复验证通过' if ok else '验证未通过；最多尝试两次，不无限重启')
            record = d.last[n]
            if ok and record['truth'] and record['truth'] != 'healthy' and result['diagnosis']['root_cause'] == record['truth']:
                from .contracts import Case
                from .edge import store_case
                case = Case.model_validate(result['case_candidate'])
                case.root_cause_confirmed = True
                case.label_source = 'testbed_injector' if obs.get('workload_backend') in ('process','kubernetes') else 'synthetic_injector'
                store_case(case)
                emit(n, case.case_id, '案例入库', '恢复验证通过且与注入真值一致，已收录成功案例')
        except Exception as exc:
            with guard:
                nodes[n]['state'] = '等待人工检查' if nodes[n]['attempts']>=2 else '服务不可达或处置失败'
            detail = str(exc)
            if getattr(exc, 'response', None) is not None:
                try: detail = str(exc.response.json().get('detail', detail))
                except (ValueError, AttributeError): pass
            emit(n, incident or str(uuid.uuid4()), '操作失败', detail[:350])
        finally:
            d.control_lock.release()

def loop():
    while not stopping.wait(10):
        if enabled:
            tick()
        else:
            sample_only()

def sample_only():
    from . import dashboard as d
    from .history import metric
    if os.getenv('PAPER_PROFILE')=='1':
        for n in node_ids():
            try:
                t=d.request('GET',d.address('agent',n),'/telemetry',timeout=4)
                if t['latest']:
                    metric(n,t['latest'])
                    with guard:nodes[n].update(observation=t['latest'],anomaly=t['anomaly'],checked_at=datetime.now(timezone.utc).isoformat())
            except Exception:pass
        return
    if not d.control_lock.acquire(blocking=False):
        return
    try:
        for n in node_ids():
            try:
                obs=d.request('GET',d.address('workload',n),'/observe?event_id=monitor',timeout=12)
                metric(n,obs)
                with guard:
                    nodes[n].update(observation=obs,checked_at=datetime.now(timezone.utc).isoformat())
            except Exception:
                pass
    finally:
        d.control_lock.release()

def start():
    global worker, enabled
    enabled = os.getenv('AUTO_MONITOR','1') == '1'
    stopping.clear()
    worker = Thread(target=loop, name='fedhelm-monitor', daemon=True)
    worker.start()

def stop():
    stopping.set()
    if worker:
        worker.join(timeout=1)
