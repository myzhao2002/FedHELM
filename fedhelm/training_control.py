"""Durable, bounded federation orchestration; only one endpoint trains at a time."""
import json
import os
import time
import uuid
from pathlib import Path
from threading import Event, RLock, Thread
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .common import request
from .registry import node_ids, endpoint

router = APIRouter(tags=['自动联邦训练'])
guard = RLock()
stop_event = Event()
worker = None
running = False
requested = False

class Settings(BaseModel):
    enabled: bool = False
    interval_seconds: int = Field(default=900, ge=60, le=86400)
    max_rounds: int = Field(default=3, ge=1, le=100)

def path():
    return Path(os.getenv('DATA_DIR', 'runtime/edge')) / 'training-controller.json'

def read():
    with guard:
        if path().exists():
            return json.loads(path().read_text(encoding='utf-8'))
        return dict(settings=Settings().model_dump(), completed=0, phase='等待启用',
                    next_at=0, active=None, nodes={}, error=None)

def write(**changes):
    with guard:
        value=read(); value.update(changes)
        path().parent.mkdir(parents=True, exist_ok=True)
        temp=path().with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8'); temp.replace(path())
        return value

@router.get('/ui/training', summary='查看自动训练轮次、各端进度和暂停原因')
def status():
    return {**read(), 'running': running, 'requested': requested,
            'concurrency': 1, 'epochs': 2, 'participant_policy': '全部配置节点；缺数据或离线时等待，不丢弃更新'}

@router.put('/ui/training', summary='设置自动训练开关、轮次间隔和累计轮次上限')
def configure(body: Settings):
    write(settings=body.model_dump())
    return status()

@router.post('/ui/training/run', summary='请求执行或恢复一轮；后台串行训练，不自动注入故障')
def trigger():
    global requested
    with guard:
        if running or requested: raise HTTPException(409, '训练轮次正在执行或已排队')
        requested=True
    return status()

def event(task, stage, detail, payload=None):
    from .scheduler import emit
    emit('edge', task, stage, detail, payload or {})

def remote(node, method, route, body=None):
    return request(method, endpoint(node).agent_url, route, body, timeout=660)

def federation(route, method='GET'):
    return request(method, os.environ['FEDERATION_URL'], route, timeout=180)

def run_round(manual=False):
    global running
    from .dashboard import control_lock
    with guard:
        if running: return
        running=True
    try:
        state=read(); task=state['active']
        # Resume durable updates without retraining endpoints that already uploaded.
        snapshot=federation('/round')
        if task is None:
            for node in node_ids():
                health=remote(node, 'GET', '/health')
                data=remote(node, 'GET', '/datasets')
                selected=next((d for d in data['datasets'] if d['dataset_id']==data['active_dataset']), None)
                if not selected or not all(selected['splits'].get(k,0) for k in ('train','validation')):
                    write(phase='等待训练数据', error=node+' 尚无已激活的训练/验证集')
                    return
                if health.get('host_info',{}).get('memory_available_mb',1000)<512:
                    write(phase='等待资源', error=node+' 主机可用内存不足512MB'); return
            task={'id':str(uuid.uuid4()), 'base':snapshot['version'], 'started_at':time.time()}
            write(active=task,nodes={},error=None)
            event(task['id'],'联邦轮次开始','串行训练，端侧每轮2个epoch',task)
        task_id=task['id']
        for node in node_ids():
            if stop_event.is_set() or (not manual and not read()['settings']['enabled']):
                write(phase='已暂停，可恢复当前轮次'); return
            snapshot=federation('/round')
            if snapshot['version']>task['base']: break
            uploaded={u['node_id'] for u in snapshot['updates']}
            if node in uploaded: continue
            # Release the shared control lock between clients so fault handling can run.
            if not control_lock.acquire(timeout=2):
                write(phase='等待故障处置完成'); return
            try:
                t=remote(node,'GET','/telemetry')
                if not t.get('latest') or t['anomaly']['anomalous']:
                    write(phase='等待节点恢复',error=node+' 当前存在异常，延后训练'); return
                write(phase='同步并训练 '+node)
                remote(node,'POST','/sync')
                event(task_id,'端侧训练开始',node)
                result=remote(node,'POST','/train')
                nodes=read()['nodes']; nodes[node]={'state':'增量已上传','at':time.time(),
                    'metrics':result.get('metrics',{})}
                write(nodes=nodes)
                event(task_id,'端侧训练上传完成',node,{'metrics':result.get('metrics',{}),'ack':result.get('ack')})
            finally: control_lock.release()
            if stop_event.wait(1): return
        if not control_lock.acquire(timeout=2):
            write(phase='等待聚合锁'); return
        try:
            snapshot=federation('/round')
            if snapshot['version']==task['base']:
                write(phase='边侧聚合')
                result=federation('/aggregate','POST')
                event(task_id,'全局模型已聚合','v'+str(result['model']['version']),{'weights':result.get('weights')})
            snapshot=federation('/round')
            if snapshot['version']<=task['base']: raise RuntimeError('聚合版本没有推进')
            write(phase='下发模型与记忆')
            for node in node_ids():
                result=remote(node,'POST','/sync')
                if result['model']['version']!=snapshot['version']: raise RuntimeError('模型版本确认失败：'+node)
                nodes=read()['nodes']; nodes[node]={**nodes.get(node,{}),'state':'新版本已加载','version':snapshot['version']}
                write(nodes=nodes)
                event(task_id,'端侧版本确认',node,{'version':snapshot['version']})
            write(active=None,completed=read()['completed']+1,phase='本轮完成',error=None,
                  next_at=time.time()+read()['settings']['interval_seconds'])
            event(task_id,'联邦轮次完成','全部节点已确认新版本',{'version':snapshot['version']})
        finally: control_lock.release()
    except Exception as exc:
        write(phase='等待重试',error=type(exc).__name__+': '+str(exc)[:180])
        task=read()['active']
        if task: event(task['id'],'联邦轮次暂停','失败后保留已上传更新，下一次恢复',{'error_type':type(exc).__name__})
    finally:
        running=False

def loop():
    global requested
    while not stop_event.wait(10):
        state=read()
        with guard: manual=requested; requested=False
        auto=state['settings']['enabled'] and state['completed']<state['settings']['max_rounds'] and time.time()>=state['next_at']
        if manual or auto: run_round(manual)

def start():
    global worker
    if worker and worker.is_alive(): return
    stop_event.clear(); worker=Thread(target=loop,daemon=True,name='federated-training'); worker.start()

def stop():
    stop_event.set()
    if worker: worker.join(timeout=2)
