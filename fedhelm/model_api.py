"""Separate model-provider configuration. Keys are never returned to the UI."""
import json
import os
import sqlite3
import time
import re
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel,ConfigDict,Field,model_validator
from fastapi import HTTPException
from .contracts import InferenceRequest,Plan

lock=RLock()
class Provider(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:Literal['disabled','openai-compatible']='disabled'
    base_url:str=''
    model:str=''
    api_key:str=Field(default='',exclude=True,repr=False)
    api_key_env:str=''
    api_key_file:str=''
    deployment:Literal['cloud-api','self-hosted']='cloud-api'
    max_output_tokens:int=Field(default=384,ge=128,le=1024)
    daily_call_limit:int=Field(default=20,ge=1,le=200)
    min_interval_seconds:int=Field(default=3,ge=0,le=60)
    disable_thinking:bool=False
    json_mode:bool=True
    clear_key:bool=Field(default=False,exclude=True)
    timeout_seconds:int=Field(default=60,ge=5,le=180)
    @model_validator(mode='after')
    def valid(self):
        if self.base_url:
            u=urlsplit(self.base_url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('API地址必须是HTTP(S)根地址，不在URL中填写密钥')
        if self.mode!='disabled' and (not self.base_url or not self.model):raise ValueError('启用API需要填写地址和模型名称')
        return self

def path():return Path(os.getenv('MODEL_API_CONFIG','runtime/cluster/model-api.json')).resolve()
def read():
    with lock:
        if path().exists():return json.loads(path().read_text(encoding='utf-8'))
        return {'edge':Provider().model_dump(),'local':Provider().model_dump()}
def public():
    providers=read()
    return {'providers':{role:{**Provider.model_validate(v).model_dump(),'has_key':bool(resolve_key(Provider.model_validate(v), required=False))} for role,v in providers.items()},
            'protocol':'OpenAI-compatible /chat/completions','configured_file':str(path()),'usage':usage(),'prompts':{r:(Path(__file__).parent/'prompts'/(r+'.txt')).read_text(encoding='utf-8') for r in ('edge','local')},'prompt_files':{r:str(Path(__file__).parent/'prompts'/(r+'.txt')) for r in ('edge','local')}}
def save(role,body):
    with lock:
        settings=read();old=settings.get(role,{})
        value=body.model_dump();value['api_key']='' if body.clear_key else body.api_key or old.get('api_key','')
        settings[role]=value;path().parent.mkdir(parents=True,exist_ok=True)
        tmp=path().with_suffix('.tmp');tmp.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path())
    return public()


def resolve_key(config, required=True):
    if config.api_key_file:
        # File is reread for every call; deleting it prevents future requests.
        file=Path(config.api_key_file)
        if not file.is_absolute():file=path().parent/file
        try:return file.read_text(encoding='utf-8').strip()
        except OSError:
            if required:raise HTTPException(503,'密钥文件不存在或无法读取，已停止模型调用') from None
            return ''
    return config.api_key or (os.getenv(config.api_key_env,'') if config.api_key_env else '')


def usage_db():
    filename=path().parent/'model-usage.sqlite';filename.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(filename,timeout=10)
    con.execute('CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,time REAL,day TEXT,role TEXT,model TEXT,status TEXT,prompt_tokens INTEGER DEFAULT 0,completion_tokens INTEGER DEFAULT 0)')
    return con


def today():return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def usage():
    with closing(usage_db()) as con:
        con.row_factory=sqlite3.Row
        return {'day':today(),'timezone':'UTC+08:00','roles':{r:dict(con.execute(
            "SELECT count(*) calls,coalesce(sum(prompt_tokens),0) prompt_tokens,coalesce(sum(completion_tokens),0) completion_tokens,coalesce(sum(status='ok'),0) successes FROM calls WHERE day=? AND role=?",(today(),r)).fetchone()) for r in ('edge','local')}}


def reserve(role,config):
    with closing(usage_db()) as con,con:
        con.execute('BEGIN IMMEDIATE')
        count,last=con.execute('SELECT count(*),max(time) FROM calls WHERE day=? AND role=?',(today(),role)).fetchone()
        if count>=config.daily_call_limit:raise HTTPException(429,'已达到此角色每日调用上限，停止请求；可在配置页调整')
        if last and time.time()-last<config.min_interval_seconds:raise HTTPException(429,'模型请求间隔过短，请稍后再试')
        return con.execute('INSERT INTO calls(time,day,role,model,status) VALUES(?,?,?,?,?)',(time.time(),today(),role,config.model,'started')).lastrowid


def finish(call_id,status,values=None):
    values=values or {}
    with closing(usage_db()) as con,con:
        con.execute('UPDATE calls SET status=?,prompt_tokens=?,completion_tokens=? WHERE id=?',
                    (status,int(values.get('prompt_tokens',0)),int(values.get('completion_tokens',0)),call_id))


def compact_input(body):
    obs=body.observation;diag=body.diagnosis
    def clean(value,limit):
        value=re.sub(r'sk-[A-Za-z0-9_-]+|Bearer\s+\S+', '[REDACTED]',str(value),flags=re.I)
        value=re.sub(r'(api[_-]?key|password|token)\s*[:=]\s*\S+',r'\1=[REDACTED]',value,flags=re.I)
        return value[:limit]
    metric_names=('pool_usage','worker_usage','worker_wait_ms','db_wait_ms','dependency_ms','dependency_error_rate','config_error_rate','cpu_usage','rss_mb')
    value={'observation':{'healthy':obs.healthy,'error_rate':obs.error_rate,'latency_ms':round(obs.latency_ms,3),'pool_usage':obs.pool_usage,
             'process_present':obs.business_pid is not None,'response_codes':obs.response_codes[:6],
             'metrics':{k:round(obs.metrics[k],3) for k in metric_names if k in obs.metrics},
             'logs':[clean(x,160) for x in obs.logs[:3]]},
           'initial_diagnosis':{'root_cause':diag.root_cause,'confidence':round(diag.confidence,3),'memory_conflict':diag.memory_conflict,
             'evidence':[clean(x,160) for x in diag.evidence[:3]]},
           'verified_cases':[{'root_cause':c.diagnosis.root_cause,'action':c.plan.action} for c in body.retrieved_cases[:2] if c.feedback.success and c.root_cause_confirmed]}
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def infer(body:InferenceRequest,role:str):
    config=Provider.model_validate(read()[role])
    if config.mode=='disabled':raise HTTPException(503,detail=f'{role}模型API未配置；没有调用真实模型')
    key=resolve_key(config)
    if config.api_key_file and not key:raise HTTPException(503,'密钥文件为空，已停止模型调用')
    headers={'Authorization':'Bearer '+key} if key else {}
    prompt=(Path(__file__).parent/'prompts'/(role+'.txt')).read_text(encoding='utf-8')
    evidence=compact_input(body)
    if len(prompt)+len(evidence)>6500:raise HTTPException(413,'提示词与证据超过6500字符，停止调用以限制用量')
    payload={'model':config.model,'messages':[{'role':'system','content':prompt},{'role':'user','content':evidence}],
             'temperature':0,'max_tokens':config.max_output_tokens}
    if config.json_mode:payload['response_format']={'type':'json_object'}
    if config.disable_thinking:payload['enable_thinking']=False
    call_id=reserve(role,config);tokens={}
    try:
        with httpx.Client(timeout=config.timeout_seconds,trust_env=False) as client:
            result=client.post(config.base_url.rstrip('/')+'/chat/completions',headers=headers,json=payload)
            result.raise_for_status();response=result.json();tokens=response.get('usage',{})
            value=json.loads(response['choices'][0]['message']['content'])
        allowed={k:value[k] for k in ('root_cause','confidence','action','parameters','reason') if k in value}
        plan=Plan(event_id=body.observation.event_id,node_id=body.observation.node_id,service_id=body.observation.service_id,mode=role,**allowed)
        actions={'healthy':'none','unknown':'none','service_down':'restart_service','config_error':'restore_config','pool_exhausted':'reset_pool',
                 'thread_pool_exhausted':'reset_workers','dependency_timeout':'restore_dependency'}
        if plan.action!=actions[plan.root_cause] or plan.parameters or len(plan.reason)>500:raise ValueError('Invalid single-step plan')
        finish(call_id,'ok',tokens)
        return plan
    except Exception as exc:
        finish(call_id,'failed',tokens)
        status=exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None
        detail={401:'密钥无效或地域不匹配',403:'模型权限或额度不足',429:'服务商限流或额度不足'}.get(status,'调用或JSON方案校验失败')
        raise HTTPException(502,detail=f'模型API{detail}；没有自动重试，未获得可执行方案') from None
