"""Real HTTP fault, automatic recovery and persisted progress acceptance check."""
import json
import time
from pathlib import Path
import httpx


def main():
    base='http://127.0.0.1:14000'
    report=[]
    with httpx.Client(timeout=120,trust_env=False) as c:
        previous=c.get(base+'/ui/monitor').json()['enabled']
        c.put(base+'/ui/monitor',json={'enabled':True}).raise_for_status()
        try:
            for fault in ('thread_pool_exhausted','dependency_timeout'):
                for _ in range(20):
                    r=c.post(base+'/ui/command',json={'action':'inject','node':'b','fault':fault})
                    if r.status_code!=409:
                        break
                    time.sleep(.5)
                r.raise_for_status()
                task=r.json()['task_id']
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    d=c.get(base+'/ui/task/'+task).json()
                    if d['progress']['case_stored']:
                        break
                    time.sleep(1)
                assert d['progress']['completed']==7 and d['progress']['case_stored'],d
                result=next(s['payload'] for s in d['steps'] if s['stage']=='处置结果')
                assert result['observation']['response_codes']==[503]*3
                assert result['diagnosis']['root_cause']==fault
                assert result['diagnosis']['embedding_version']=='explicit-fault-rules-v1'
                assert result['feedback']['success']
                assert all(s['response_codes']==[200]*3 for s in result['feedback']['samples'])
                report.append({'fault':fault,'task_id':task,**d})
                print('PASS',fault,task,flush=True)
        finally:
            c.put(base+'/ui/monitor',json={'enabled':previous}).raise_for_status()
    Path('runtime/fault-extension-verification.json').write_text(json.dumps({'passed':True,'tasks':report},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
