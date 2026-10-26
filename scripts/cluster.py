"""Windows/Linux local simulation launcher: real endpoints, one directory per device."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
import httpx
from fedhelm.registry import Cluster

def services(conf):
    common={'CLUSTER_CONFIG':os.environ['CLUSTER_CONFIG'],'PAPER_PROFILE':'1','TRAINING_BACKEND':'torch',
            'EXPECTED_NODES':','.join(n.id for n in conf.nodes),'EDGE_URL':conf.edge_url,'FEDERATION_URL':conf.federation_url,
            'LLM_URL':conf.llm_edge_url,'LOCAL_LLM_URL':conf.llm_local_url,'COLLECT_INTERVAL':'8','SEPARATE_INJECTOR':'1'}
    items=[('edge','edge',conf.edge_url,{}),('federation','federation',conf.federation_url,{}),
           ('llm-edge','llm',conf.llm_edge_url,{'MODEL_MODE':'edge'}),('llm-local','llm',conf.llm_local_url,{'MODEL_MODE':'local'}),
           ('injector','injector',conf.injector_url,{})]
    for n in conf.nodes:
        items.extend([(f'workload-{n.id}','real_workload',n.workload_url,{'NODE_ID':n.id}),
                      (f'agent-{n.id}','agent',n.agent_url,{'NODE_ID':n.id,'TIER':n.tier,'WORKLOAD_URL':n.workload_url})])
    return [(name,module,url,{**common,**env}) for name,module,url,env in items]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',default='config/cluster.local.json')
    parser.add_argument('--data-dir',default='runtime/cluster');parser.add_argument('--open-browser',action='store_true')
    parser.add_argument('--check',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];config=(root/args.config).resolve();conf=Cluster.model_validate_json(config.read_text(encoding='utf-8'))
    os.environ['CLUSTER_CONFIG']=str(config);items=services(conf)
    for name,_,url,_ in items:
        u=urlsplit(url)
        if u.hostname not in ('127.0.0.1','localhost'):raise SystemExit('Local launcher requires localhost endpoints; remote deployment uses containers/system services.')
        with socket.socket() as sock:
            try:sock.bind(('127.0.0.1',u.port))
            except OSError:raise SystemExit(f'Port in use: {name} {u.port}. Stop the previous platform first.')
    if args.check:print(f'PASS: {len(conf.nodes)} devices; {len(items)} service endpoints; configuration and ports valid');return
    directory=(root/args.data_dir).resolve();directory.mkdir(parents=True,exist_ok=True)
    token_file=directory/'internal.token'
    if not token_file.exists():token_file.write_text(secrets.token_urlsafe(32),encoding='utf-8')
    token=token_file.read_text(encoding='utf-8').strip()
    provider_file=directory/'model-api.json'
    if not provider_file.exists():
        from fedhelm.model_api import Provider
        provider_file.write_text(json.dumps({role:Provider().model_dump() for role in ('edge','local')},indent=2),encoding='utf-8')
    seed=root/'runtime/paper/federation/model.json'
    if not seed.exists():
        from fedhelm.temporal import bootstrap
        seed=directory/'seed-model.json';seed.write_text(bootstrap().model_dump_json(),encoding='utf-8')
    for name,_,_,_ in items:
        target=directory/name;target.mkdir(exist_ok=True)
        if (name=='federation' or name.startswith('agent-')) and not (target/'model.json').exists():shutil.copyfile(seed,target/'model.json')
    (directory/'launcher.json').write_text(json.dumps({'pid':os.getpid(),'recorded_at':time.time(),'workspace':str(root),'base_port':urlsplit(conf.edge_url).port}),encoding='utf-8')
    children=[];logs=[]
    try:
        for name,module,url,extra in items:
            log=(directory/(name+'.log')).open('a',encoding='utf-8');logs.append(log)
            env={**os.environ,**extra,'DATA_DIR':str(directory/name),'MODEL_API_CONFIG':str(provider_file),
                 'INTERNAL_TOKEN':token,'AUTO_MONITOR':os.getenv('AUTO_MONITOR','1'),'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
            child=subprocess.Popen([sys.executable,'-m','uvicorn',f'fedhelm.{module}:app','--host','127.0.0.1','--port',str(urlsplit(url).port)],
                cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            children.append(child);time.sleep(.15)
        deadline=time.monotonic()+100
        with httpx.Client(timeout=2,trust_env=False) as client:
            for name,_,url,_ in items:
                while True:
                    if any(c.poll() is not None for c in children):raise RuntimeError('Service stopped; inspect runtime/cluster/*.log')
                    try:
                        r=client.get(url+'/health')
                        if r.status_code==200:break
                    except httpx.HTTPError:pass
                    if time.monotonic()>deadline:raise TimeoutError(name)
                    time.sleep(.4)
        print(f'READY: {len(conf.nodes)} devices, {len(items)} endpoints',flush=True)
        print('Console: '+conf.edge_url+'/topology\nFault lab: '+conf.injector_url+'\nCtrl+C stops this process tree.',flush=True)
        if args.open_browser:
            import webbrowser
            webbrowser.open(conf.edge_url+'/topology')
        while all(c.poll() is None for c in children):time.sleep(.5)
        raise RuntimeError('A platform service exited; inspect logs.')
    except KeyboardInterrupt:pass
    finally:
        for c in children:
            if c.poll() is None:c.terminate()
        for c in children:
            try:c.wait(timeout=5)
            except subprocess.TimeoutExpired:c.kill();c.wait()
        for log in logs:log.close()

if __name__=='__main__':main()
