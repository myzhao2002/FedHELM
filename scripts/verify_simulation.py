"""Run generated datasets through calibration, compressed FL and post-cold-start scoring."""
import json
import time
from pathlib import Path
import httpx


def main():
    base='http://127.0.0.1:15000';report={'rounds':[],'datasets':[]}
    with httpx.Client(timeout=600,trust_env=False) as c:
        def call(path,body):
            r=c.post(base+path,json=body);r.raise_for_status();return r.json()
        def command(action,**kwargs):
            result=call('/ui/command',{'action':action,**kwargs})
            assert result.get('all_succeeded',True),str(result)[:1000]
            return result
        c.put(base+'/ui/monitor',json={'enabled':False}).raise_for_status()
        stamp=int(time.time())
        for i,n in enumerate('abc'):
            print('prepare dataset',n,flush=True)
            report['datasets'].append(call('/ui/datasets/'+n+'/generate',{'dataset_id':f'scenario-{n}-{stamp}','seed':631+19*i,'per_class':6}))
        command('sync_all')
        for round_index in range(3):
            print('training round',round_index+1,flush=True)
            updates=command('train_all')
            metrics={n:x['result']['metrics'] for n,x in updates['nodes'].items()}
            for x in updates['nodes'].values():
                assert x['result']['ack']['checksum_valid']
                assert any(abs(v)>1e-9 for v in x['result']['update']['delta'])
            r=command('aggregate');algorithm=r['algorithm']
            report['rounds'].append({'model_version':r['model']['version'],'algorithm':algorithm,'training':metrics})
            command('sync_all')
        final=report['rounds'][-1]
        assert not final['algorithm']['cold_start']
        assert final['algorithm']['probe_count']>0
        for values in final['algorithm']['components'].values():
            assert values['probe_accuracy'] is not None
        status=c.get(base+'/ui/status').json()
        sha=status['federation_round']['model_sha256']
        assert all(status['services']['agent-'+n]['model_sha256']==sha for n in 'abc')
        report.update(passed=True,parameter_sha256=sha)
    Path('runtime/paper-simulation-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS generated-data simulation',flush=True)


if __name__=='__main__':main()
