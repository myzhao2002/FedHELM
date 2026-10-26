"""Separate test operator site. It shares no injected label with diagnosis requests."""
import os
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict
from .registry import cluster,NodeId
from .contracts import Injection
from .common import request

app=FastAPI(title='FedHELM 独立故障实验站')
@app.get('/health')
def health():return {'service':'fault-injector','status':'ok','separate_origin':True}
@app.get('/')
def page():return FileResponse(Path(__file__).parent/'static'/'injector.html',headers={'Cache-Control':'no-store'})
@app.get('/api/config')
def config():
    from .fault_catalog import catalog
    conf=cluster()
    return {'nodes':[{'id':n.id,'tier':n.tier} for n in conf.nodes],'edge_url':conf.console_url or conf.edge_url,'faults':catalog()['faults']}
@app.get('/api/status')
def status():
    try:return request('GET',cluster().edge_url,'/ui/cluster',timeout=30)
    except Exception:raise HTTPException(503,'管理平台尚未连接') from None
class Experiment(Injection):
    node:NodeId
@app.post('/api/inject')
def inject(body:Experiment):
    try:return request('POST',cluster().edge_url,'/internal/experiment',{'node':body.node,'fault':body.fault},timeout=90)
    except Exception as exc:raise HTTPException(502,'故障注入请求未完成，请查看管理平台日志（'+type(exc).__name__+'）') from None
