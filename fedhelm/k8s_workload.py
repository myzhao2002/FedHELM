"""Restricted in-cluster controller for one test Deployment and business Service."""
import os
from pathlib import Path
import ssl
import statistics
import threading
import time
import httpx
from fastapi import FastAPI,HTTPException
from .contracts import Injection,Plan,Observation
from .common import audit

app=FastAPI(title='FedHELM · Kubernetes故障控制器')
node=os.getenv('NODE_ID','a')
namespace=os.getenv('POD_NAMESPACE','fedhelm')
deployment='business-'+node
business='http://'+deployment+':8000'
lock=threading.RLock()


def scale(replicas):
    account=Path('/var/run/secrets/kubernetes.io/serviceaccount')
    token=(account/'token').read_text().strip()
    context=ssl.create_default_context(cafile=str(account/'ca.crt'))
    url='https://kubernetes.default.svc/apis/apps/v1/namespaces/'+namespace+'/deployments/'+deployment+'/scale'
    with httpx.Client(verify=context,timeout=10,trust_env=False) as c:
        r=c.patch(url,headers={'Authorization':'Bearer '+token,'Content-Type':'application/merge-patch+json'},
                  json={'spec':{'replicas':replicas}})
        r.raise_for_status()
        deadline=time.monotonic()+65
        while time.monotonic()<deadline:
            r=c.get(url,headers={'Authorization':'Bearer '+token})
            r.raise_for_status()
            count=r.json().get('status',{}).get('replicas',0)
            reachable=False
            try:
                with httpx.Client(timeout=1,trust_env=False) as b:
                    reachable=b.get(business+'/health').status_code==200
            except httpx.HTTPError:
                pass
            if (replicas==0 and count==0 and not reachable) or (replicas==1 and count==1 and reachable):
                return
            time.sleep(.4)
    raise RuntimeError('Kubernetes工作负载未在65秒内达到目标副本状态')


def admin(action):
    with httpx.Client(timeout=3,trust_env=False) as c:
        r=c.post(business+'/admin/'+action);r.raise_for_status()


@app.get('/health',summary='读取Kubernetes故障控制器状态')
def health():
    from .common import runtime_info
    return {'status':'ok','simulated':True,'workload_backend':'kubernetes','deployment':deployment,
            'pod_name':os.getenv('HOSTNAME'),**runtime_info('workload-'+node,node.upper())}


@app.post('/inject',summary='对本端Kubernetes工作负载注入真实故障')
def inject(body:Injection):
    with lock:
        scale(1)
        admin('restore-config')
        admin('reset-pool')
        admin('reset-workers')
        admin('restore-dependency')
        if body.fault=='service_down':
            scale(0)
        elif body.fault=='config_error':
            admin('break-config')
        elif body.fault=='pool_exhausted':
            admin('hold-pool')
        elif body.fault=='thread_pool_exhausted':
            admin('hold-workers')
        elif body.fault=='dependency_timeout':
            admin('delay-dependency')
        audit('kubernetes_injection',{'fault':body.fault,'deployment':deployment,'namespace':namespace})
        return {'fault':body.fault,'deployment':deployment,'namespace':namespace,'workload_backend':'kubernetes','simulated':True}


@app.post('/execute',summary='执行Kubernetes测试工作负载恢复动作')
def execute(body:Plan):
    if body.node_id!=node or body.service_id!='service-'+node or body.parameters:
        raise HTTPException(400,'禁止操作其他节点或非测试工作负载')
    with lock:
        applied=True
        try:
            if body.action=='restart_service':
                scale(1)
            elif body.action=='restore_config':
                admin('restore-config')
            elif body.action=='reset_pool':
                admin('reset-pool')
            elif body.action=='reset_workers':
                admin('reset-workers')
            elif body.action=='restore_dependency':
                admin('restore-dependency')
        except httpx.HTTPError:
            applied=False
        result={'applied':applied,'event_id':body.event_id,'workload_backend':'kubernetes','simulated':True}
        audit('kubernetes_execution',{**body.model_dump(),**result})
        return result


@app.get('/observe',response_model=Observation,summary='采集Kubernetes业务实际HTTP观测')
def observe(event_id:str):
    with lock:
        codes,times,errors=[],[],[]
        spans=[];metrics={}
        pid,pod,usage=None,None,0.
        with httpx.Client(timeout=1,trust_env=False) as c:
            for _ in range(3):
                start=time.perf_counter()
                try:
                    r=c.get(business+'/orders');codes.append(r.status_code)
                    spans.extend(r.json().get('spans',[]))
                    if r.status_code!=200:
                        errors.append(r.json().get('error','request failed'))
                except httpx.HTTPError:
                    codes.append(0);errors.append('process unavailable')
                times.append((time.perf_counter()-start)*1000)
            try:
                h=c.get(business+'/health').json();pid=h['pid'];pod=h['pod_name']
                raw=c.get(business+'/metrics').json()
                from .telemetry import FIELDS
                metrics={k:float(raw[k]) for k in FIELDS if k in raw}
                usage=metrics.get('pool_usage',0.)
            except (httpx.HTTPError,ValueError,KeyError):
                pass
        return Observation(event_id=event_id,node_id=node,service_id='service-'+node,
            healthy=all(x==200 for x in codes),error_rate=sum(x!=200 for x in codes)/3,
            latency_ms=statistics.median(times),pool_usage=usage,logs=list(dict.fromkeys(errors)),
            metrics=metrics,spans=spans,observed_at=time.time(),workload_backend='kubernetes',response_codes=codes,business_pid=pid,pod_name=pod)

from .common import protect_node_service
protect_node_service(app)
