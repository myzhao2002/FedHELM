"""Deployment-neutral endpoint inventory. IDs are not Kubernetes Node names."""
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,AfterValidator,model_validator

class Endpoint(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-z][a-z0-9-]{0,31}$')
    tier:Literal['A','B','C']
    agent_url:str
    workload_url:str
    host:str='local-host'
    placement:str='local-process'
    cpu_limit:float=Field(default=.5,gt=0)
    memory_mb:int=Field(default=384,ge=64)
    @model_validator(mode='after')
    def urls(self):
        from urllib.parse import urlsplit
        for value in (self.agent_url,self.workload_url):
            u=urlsplit(value)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('节点地址必须是不含凭据的HTTP(S)服务地址')
        return self

class Cluster(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str='FedHELM 仿真集群'
    edge_url:str='http://127.0.0.1:15000'
    federation_url:str='http://127.0.0.1:15001'
    llm_edge_url:str='http://127.0.0.1:15002'
    llm_local_url:str='http://127.0.0.1:15003'
    injector_url:str='http://127.0.0.1:15090'
    console_url:str=''
    injector_public_url:str=''
    nodes:list[Endpoint]=Field(min_length=1,max_length=64)
    @model_validator(mode='after')
    def unique(self):
        if len({n.id for n in self.nodes})!=len(self.nodes):raise ValueError('节点编号重复')
        urls=[u for n in self.nodes for u in (n.agent_url,n.workload_url)]
        if len(urls)!=len(set(urls)):raise ValueError('节点服务地址重复')
        return self

@lru_cache(maxsize=4)
def read_config(path):return Cluster.model_validate_json(Path(path).read_text(encoding='utf-8'))

def cluster():
    path=os.getenv('CLUSTER_CONFIG')
    if path:return read_config(path)
    return Cluster(nodes=[Endpoint(id=n,tier=n.upper(),agent_url=os.getenv(f'AGENT_{n.upper()}_URL',f'http://127.0.0.1:{8101+i}'),
                                  workload_url=os.getenv(f'WORKLOAD_{n.upper()}_URL',f'http://127.0.0.1:{8201+i}')) for i,n in enumerate('abc')])
def node_ids():return [n.id for n in cluster().nodes]
def endpoint(node):
    for item in cluster().nodes:
        if item.id==node:return item
    raise ValueError('未配置的节点编号')
def validate_node(value):endpoint(value);return value
def validate_location(value):
    if value!='edge':endpoint(value)
    return value
NodeId=Annotated[str,AfterValidator(validate_node)]
LocationId=Annotated[str,AfterValidator(validate_location)]
