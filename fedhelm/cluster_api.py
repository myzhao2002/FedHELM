import os
import time
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter,Query,Header,HTTPException
from typing import Literal
from pydantic import BaseModel,Field
from .registry import cluster,NodeId,endpoint
from .common import request
from . import model_api,traffic

router=APIRouter(tags=['集群拓扑与模型配置'])
guard=Lock();cached={};cached_at=0

@router.get('/ui/registry',summary='获取逻辑节点、承载位置和独立注入站地址')
def registry():return cluster().model_dump()

def observe_node(entry):
    result=entry.model_dump();result.update(online=False,business_healthy=None,services=[])
    try:
        health=request('GET',entry.agent_url,'/health',timeout=3)
        result.update(online=True,hostname=health.get('hostname'),k8s_node=health.get('k8s_node'),model_version=health.get('model_version'),
                      model_adapter=health.get('model_adapter'),storage=health.get('storage'),host_info=health.get('host_info'),deployment_mode=health.get('deployment_mode'))
        result['services'].append({'name':'agent-'+entry.id,'online':True,'pid':health.get('pid'),'role':'采集 / 诊断 / 调度 / 训练'})
        telemetry=request('GET',entry.agent_url,'/telemetry',timeout=3)
        latest=telemetry.get('latest');result.update(telemetry=telemetry,business_healthy=latest.get('healthy') if latest else None)
        result['services'].append({'name':'business-'+entry.id,'online':latest.get('healthy') if latest else None,
                                   'pid':latest.get('business_pid') if latest else None,'role':'独立测试业务'})
        result['observed_at']=latest.get('observed_at') if latest else None
    except Exception as exc:result['error']=type(exc).__name__
    return result

@router.get('/ui/cluster',summary='集群逻辑拓扑与实测节点状态，四秒缓存')
def snapshot():
    global cached,cached_at
    with guard:
        if time.monotonic()-cached_at>4:
            conf=cluster()
            with ThreadPoolExecutor(max_workers=8) as pool:nodes=list(pool.map(observe_node,conf.nodes))
            cached={'name':conf.name,'sampled_at':time.time(),'edge':{'id':'edge','hostname':__import__('socket').gethostname(),
                    'placement':'kubernetes' if os.getenv('K8S_NODE_NAME') else 'local-process','k8s_node':os.getenv('K8S_NODE_NAME'),'host_info':__import__('fedhelm.host_info',fromlist=['snapshot']).snapshot()},
                    'nodes':nodes,'providers':model_api.public()['providers'],'injector_url':conf.injector_public_url or conf.injector_url}
            cached_at=time.monotonic()
        return cached

@router.get('/ui/traffic',summary='实际遥测、诊断、模型和知识传输元数据')
def transfers(after:int=Query(0,ge=0)):return {'events':traffic.recent(after),'server_time':time.time()}

@router.get('/ui/model-api',summary='查看脱敏后的大小模型API配置')
def providers():return model_api.public()

@router.put('/ui/model-api/{role}',summary='保存模型API配置，密钥不回显；留空保留已有密钥')
def save_provider(role:Literal['edge','local'],body:model_api.Provider):
    result=model_api.save(role,body)
    from .scheduler import emit
    emit('edge',str(__import__('uuid').uuid4()),'模型API配置','更新'+role+'模型接口',{'role':role,'mode':body.mode,'model':body.model,'has_key':result['providers'][role]['has_key']})
    return result

class Transfer(BaseModel):
    source:str
    target:str
    kind:Literal['model_upload','model_download','memory_download']
    bytes_count:int=Field(ge=0,le=100_000_000)

@router.post('/internal/traffic',include_in_schema=False)
def report_transfer(body:Transfer,token:str|None=Header(None,alias='X-Fedhelm-Internal')):
    import secrets
    expected=os.getenv('INTERNAL_TOKEN','')
    if not expected or not token or not secrets.compare_digest(expected,token):raise HTTPException(403,'内部身份校验失败')
    from .registry import validate_location
    validate_location(body.source);validate_location(body.target)
    traffic.record(body.source,body.target,body.kind,bytes_count=body.bytes_count)
    return {'accepted':True}
