"""Inject only; assert background scheduler performs recovery without /run calls."""
import json
import time
from pathlib import Path
import httpx

def main():
    with httpx.Client(base_url='http://127.0.0.1:14000',timeout=100,trust_env=False) as c:
        reports=[]
        for node,fault in [('b','config_error'),('c','pool_exhausted')]:
            before={e['id'] for e in c.get('/ui/monitor').json()['events']}
            r=c.post('/ui/command',json={'action':'inject','node':node,'fault':fault})
            r.raise_for_status()
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                state=c.get('/ui/monitor').json()
                rows=[e for e in state['events'] if e['node']==node and e['id'] not in before]
                if any(e['stage']=='案例入库' for e in rows):
                    reports.append({'node':node,'fault':fault,'events':rows})
                    print(node+' autonomous recovery verified',flush=True)
                    break
                time.sleep(2)
            else:
                raise AssertionError(rows)
        # Paused monitor must leave an injected fault untouched until resumed.
        c.put('/ui/monitor',json={'enabled':False}).raise_for_status()
        try:
            c.post('/ui/command',json={'action':'inject','node':'a','fault':'config_error'}).raise_for_status()
            time.sleep(12)
            state=c.get('/ui/status').json()
            assert state['observations']['a']['healthy'] is False
            reports.append({'pause_keeps_fault':True})
        finally:
            c.post('/ui/command',json={'action':'inject','node':'a','fault':'healthy'}).raise_for_status()
            c.put('/ui/monitor',json={'enabled':True}).raise_for_status()
        Path('runtime/monitor-verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
        print('pause/resume verified',flush=True)

if __name__=='__main__': main()
