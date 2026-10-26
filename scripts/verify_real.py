"""Exercise real training and testbed through the same console APIs as the UI."""
import argparse
import json
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:13000')
    parser.add_argument('--output',default='runtime/k8s-verification.json')
    args=parser.parse_args()
    report={'url':args.url,'operations':[]}
    with httpx.Client(timeout=600,trust_env=False) as c:
        monitor=c.get(args.url+'/ui/monitor').json()['enabled']
        c.put(args.url+'/ui/monitor',json={'enabled':False}).raise_for_status()
        try:
            def command(action,**kwargs):
                print(action,kwargs,flush=True)
                response=c.post(args.url+'/ui/command',json={'action':action,**kwargs})
                response.raise_for_status()
                result=response.json()
                if result.get('all_succeeded') is False:
                    raise RuntimeError(result)
                report['operations'].append({'action':action,**kwargs,'result':result})
                return result
            synchronized=command('sync_all')
            for n in 'abc':
                collected=command('collect',node=n)
                assert collected['data_source'] in ('process','kubernetes')
            results=command('train_all')
            for v in results['nodes'].values():
                r=v['result']
                assert r['training_backend']=='torch'
                assert any(abs(d)>1e-8 for d in r['update']['delta'])
                assert r['metrics']['validation_count']>0
            inbox=c.get(args.url+'/ui/status').json()['federation_round']
            assert {u['node_id'] for u in inbox['updates']}==set('abc')
            assert all(u['persisted'] and u['delta_norm']>0 for u in inbox['updates'])
            report['upload_inbox']=inbox
            aggregate=command('aggregate')
            old=synchronized['nodes']['a']['result']['model']
            expected=[v+sum(aggregate['weights'][n]*results['nodes'][n]['result']['update']['delta'][j] for n in 'abc') for j,v in enumerate(old['parameters'])]
            assert aggregate['model']['version']==old['version']+1
            assert all(abs(a-b)<1e-10 for a,b in zip(expected,aggregate['model']['parameters']))
            assert aggregate['training_backend']=='torch'
            command('sync_all')
            for n,fault,mode in [('a','service_down','local'),('b','config_error','edge'),('c','pool_exhausted','lightweight')]:
                command('inject',node=n,fault=fault)
                result=command('run',node=n,mode=mode)
                assert result['observation']['healthy'] is False
                assert result['plan']['root_cause']==fault,result
                assert result['feedback']['success'],result
                assert all(s['response_codes']==[200]*3 for s in result['feedback']['samples'])
                command('submit',node=n)
            report['final_status']=c.get(args.url+'/ui/status').json()
            final=report['final_status']
            assert not final['federation_round']['updates']
            assert all(final['services']['agent-'+n]['model_sha256']==final['federation_round']['model_sha256'] for n in 'abc')
            report['status']='passed'
        finally:
            c.put(args.url+'/ui/monitor',json={'enabled':monitor}).raise_for_status()

    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS:',out,flush=True)


if __name__=='__main__':
    main()
