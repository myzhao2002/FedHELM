import json
import os
import socket
from pathlib import Path

def runtime_info(service, placement):
    directory=Path(os.getenv('DATA_DIR','runtime/default')).resolve()
    files=[]
    if directory.exists():
        files=[{'name':p.name,'bytes':p.stat().st_size} for p in directory.iterdir() if p.is_file()]
    return {'service':service,'logical_node':placement,'hostname':socket.gethostname(),
            'pid':os.getpid(),'k8s_node':os.getenv('K8S_NODE_NAME'),
            'deployment_mode':'kubernetes' if os.getenv('K8S_NODE_NAME') else 'local-process',
            'storage':{'directory':str(directory),'files':files}}
import httpx


def request(method, base, path, payload=None, timeout=10):
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.request(method, base + path, json=payload,headers={'X-Fedhelm-Internal':os.environ['INTERNAL_TOKEN']} if os.getenv('INTERNAL_TOKEN') else {})
        response.raise_for_status()
        if os.getenv('CLUSTER_CONFIG') and os.getenv('NODE_ID') and path in ('/model','/updates/compressed','/memory/snapshot'):
            try:
                target=os.getenv('EDGE_URL')
                if target:
                    kind={'/model':'model_download','/updates/compressed':'model_upload','/memory/snapshot':'memory_download'}[path]
                    outbound=method=='POST'
                    client.post(target+'/internal/traffic',headers={'X-Fedhelm-Internal':os.getenv('INTERNAL_TOKEN','')},json={
                        'source':os.environ['NODE_ID'] if outbound else 'edge','target':'edge' if outbound else os.environ['NODE_ID'],
                        'kind':kind,'bytes_count':len(response.request.content) if outbound else len(response.content)},timeout=1)
            except Exception:pass
        return response.json()


def protect_node_service(app):
    """Protect remote node actions when an internal token is configured."""
    from fastapi.responses import JSONResponse
    import secrets
    @app.middleware('http')
    async def check(request,call_next):
        token=os.getenv('INTERNAL_TOKEN')
        if token and request.method not in ('GET','HEAD','OPTIONS'):
            supplied=request.headers.get('X-Fedhelm-Internal','')
            if not secrets.compare_digest(token,supplied):return JSONResponse({'detail':'节点服务身份校验失败'},status_code=403)
        return await call_next(request)


def audit(kind, data):
    directory = Path(os.getenv('DATA_DIR', 'runtime/default'))
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'kind': kind, 'data': data}, ensure_ascii=False) + '\n')
