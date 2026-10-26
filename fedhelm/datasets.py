"""Replaceable offline dataset boundary; never used by live telemetry collectors."""
import json
import os
import random
import math
import statistics
import time
import re
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .telemetry import FIELDS,SCALES

LABELS=['healthy','service_down','config_error','pool_exhausted','thread_pool_exhausted','dependency_timeout']


class Frame(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    timestamp:float|None=Field(default=None,description='采样Unix时间，可选；不作为模型特征')
    availability:float=Field(ge=0,le=1,description='业务健康比例，0到1')
    error_rate:float=Field(ge=0,le=1,description='请求错误率，0到1')
    latency_ms:float=Field(ge=0,description='业务请求时延，毫秒')
    pool_usage:float=Field(ge=0,le=1,description='数据库连接池占用比例')
    worker_usage:float=Field(ge=0,le=1,description='工作线程占用比例')
    worker_wait_ms:float=Field(ge=0,description='工作线程等待时长，毫秒')
    db_wait_ms:float=Field(ge=0,description='数据库连接等待，毫秒')
    dependency_ms:float=Field(ge=0,description='下游HTTP依赖耗时，毫秒')
    dependency_error_rate:float=Field(ge=0,le=1,description='下游依赖错误率')
    config_error_rate:float=Field(ge=0,le=1,description='配置校验操作失败比例')
    cpu_usage:float=Field(ge=0,le=1,description='业务进程CPU占用比例')
    rss_mb:float=Field(ge=0,description='业务进程常驻内存，MB')

    def normalized(self):
        return [min(4.,getattr(self,key)/scale) for key,scale in zip(FIELDS,SCALES)]


class Record(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id:str=Field(min_length=1,max_length=100)
    label:Literal['healthy','service_down','config_error','pool_exhausted','thread_pool_exhausted','dependency_timeout']
    split:Literal['train','validation','test']
    series:list[Frame]=Field(min_length=1,max_length=20,description='按时间先后排列，最多20个真实或虚构时点')


class DatasetImport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    source:Literal['synthetic','external','testbed']
    description:str=Field(default='',max_length=500)
    records:list[Record]=Field(min_length=1,max_length=1000)

    @model_validator(mode='after')
    def unique_events(self):
        ids=[r.event_id for r in self.records]
        if len(ids)!=len(set(ids)):raise ValueError('同一事件不可跨训练、验证或测试分区重复使用')
        return self


class GenerateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    seed:int=631
    per_class:int=Field(default=6,ge=3,le=30)
    profile:Literal['balanced','non_iid','transition']='non_iid'


def directory():
    p=Path(os.getenv('DATA_DIR','runtime/default'))/'datasets';p.mkdir(parents=True,exist_ok=True);return p


def active():
    p=directory()/'active.json'
    return json.loads(p.read_text(encoding='utf-8'))['dataset_id'] if p.exists() else None


def select(dataset_id):
    if dataset_id is not None and (not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',dataset_id) or not (directory()/(dataset_id+'.json')).exists()):
        raise ValueError('数据集不存在')
    p=directory()/'active.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps({'dataset_id':dataset_id}),encoding='utf-8');tmp.replace(p)


def import_dataset(body):
    path=directory()/(body.dataset_id+'.json')
    if path.exists():raise ValueError('数据集ID已存在，请换用新ID；原数据不会覆盖')
    path.write_text(body.model_dump_json(),encoding='utf-8')
    select(body.dataset_id)
    return {'accepted':True,'dataset_id':body.dataset_id,'source':body.source,'records':len(body.records),'active':True}


def listing():
    result=[]
    for p in directory().glob('*.json'):
        if p.name=='active.json':continue
        body=DatasetImport.model_validate_json(p.read_text(encoding='utf-8'))
        result.append({'dataset_id':body.dataset_id,'source':body.source,'description':body.description,'records':len(body.records),
                       'splits':{k:sum(r.split==k for r in body.records) for k in ('train','validation','test')},'bytes':p.stat().st_size})
    return {'datasets':result,'active_dataset':active(),'directory':str(directory()),'live_telemetry_separate':True}


def training_rows():
    selected=active()
    if selected is None:return None
    body=DatasetImport.model_validate_json((directory()/(selected+'.json')).read_text(encoding='utf-8'))
    result=[{'adapter':'temporal-transformer-v2','dataset_id':selected,'source':body.source,'event_id':r.event_id,
             'label':LABELS.index(r.label),'split':r.split,'window':[f.normalized() for f in r.series]} for r in body.records]
    from .feedback_data import rows
    ids={r['event_id'] for r in result}
    return result+[r for r in rows() if r['event_id'] not in ids]


def generate(body):
    rng=random.Random(body.seed)
    # Calibrate marginal ranges from existing local testbed measurements when available.
    empirical={}
    measured=directory().parent/'dataset-v2.jsonl'
    if measured.exists():
        for line in measured.read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row.get('adapter')!='temporal-transformer-v2':continue
            for point in row['window']:
                empirical.setdefault(LABELS[row['label']],[]).append(dict(zip(FIELDS,[v*s for v,s in zip(point,SCALES)])))
    baseline=dict(availability=1.,error_rate=0.,latency_ms=40.,pool_usage=.05,worker_usage=.05,
                  worker_wait_ms=.1,db_wait_ms=.1,dependency_ms=25.,dependency_error_rate=0.,
                  config_error_rate=0.,cpu_usage=.005,rss_mb=45.)
    if empirical.get('healthy'):
        baseline={k:statistics.median(p[k] for p in empirical['healthy']) for k in FIELDS}
    records=[];node=os.getenv('NODE_ID','a');bias={'a':2,'b':3,'c':5}.get(node[0],2)
    for label_index,label in enumerate(LABELS):
        factor=1. if body.profile!='non_iid' else (1.8 if label_index==bias else .6 if label_index==(bias+1)%6 else .9)
        count=max(3,round(body.per_class*factor))
        for index in range(count):
            target=dict(baseline)
            if empirical.get(label):
                target=dict(rng.choice(empirical[label]))
            else:
                if label!='healthy':target.update(availability=0.,error_rate=1.)
                if label=='service_down':target={k:(1. if k=='error_rate' else 0.) for k in FIELDS}
                elif label=='config_error':target.update(config_error_rate=1.,latency_ms=3.,dependency_ms=0.)
                elif label=='pool_exhausted':target.update(pool_usage=1.,db_wait_ms=85.,latency_ms=130.)
                elif label=='thread_pool_exhausted':target.update(worker_usage=1.,worker_wait_ms=350.,latency_ms=360.,dependency_ms=0.)
                elif label=='dependency_timeout':target.update(dependency_ms=130.,dependency_error_rate=1.,latency_ms=140.)
            frames=[];onset=rng.randint(3,17 if body.profile=='transition' else 12);load=1.;start=1_780_000_000+body.seed*100+len(records)*60
            transition_ticks=rng.uniform(1,4 if body.profile=='transition' else 3)
            previous=dict(baseline)
            for tick in range(20):
                load=max(.75,min(1.3,.85*load+.15*rng.uniform(.7,1.3)))
                severity=0. if label=='healthy' or tick<onset else min(1.,(tick-onset+1)/transition_ticks)
                frame={}
                for key in FIELDS:
                    expected=baseline[key]*(1-severity)+target[key]*severity
                    if key in ('availability','error_rate','config_error_rate','dependency_error_rate'):
                        value=expected
                    else:
                        correlated=expected*(load if key in ('latency_ms','worker_wait_ms','db_wait_ms','dependency_ms','cpu_usage') else 1)
                        noise=rng.gauss(0,max(expected*.025,.005))
                        value=max(0,.15*previous[key]+.85*correlated+noise)
                    if key in ('availability','error_rate','pool_usage','worker_usage','dependency_error_rate','config_error_rate','cpu_usage'):
                        value=max(0,min(1,value))
                    frame[key]=value
                if label=='service_down' and tick>=onset:
                    frame={k:(1. if k=='error_rate' else 0.) for k in FIELDS}
                elif severity>=.7:
                    frame['availability']=0.;frame['error_rate']=1.
                else:
                    frame['availability']=1.;frame['error_rate']=0.
                if label=='healthy' and rng.random()<.025:
                    frame['latency_ms']*=rng.uniform(1.3,1.8) # healthy transient, not every spike is a fault
                previous=frame
                frames.append(Frame(**frame,timestamp=start+tick*2+rng.uniform(0,.08)))
            holdout=max(1,count//5)
            split='test' if index>=count-holdout else 'validation' if index>=count-2*holdout else 'train'
            records.append(Record(event_id=f'{body.dataset_id}-{label}-{index}',label=label,split=split,series=frames))
    return DatasetImport(dataset_id=body.dataset_id,source='synthetic',
        description=f'seed={body.seed}; profile={body.profile}; AR load correlation; onset and transition; node={node}; calibrated_from_testbed={bool(empirical)}; generated, not observed',records=records)
