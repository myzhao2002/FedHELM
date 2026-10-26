"""Paper-profile integration: real data, compressed aggregation, blind diagnosis."""
import argparse
import json
import time
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:15000');parser.add_argument('--train',action='store_true')
    args=parser.parse_args();base=args.url;port=int(base.rsplit(':',1)[1]);report={'checks':[]}
    with httpx.Client(timeout=600,trust_env=False) as c:
        def command(action,**kwargs):
            for _ in range(10):
                r=c.post(base+'/ui/command',json={'action':action,**kwargs})
                if r.status_code!=409 or '另一个操作' not in r.text:break
                time.sleep(.5)
            r.raise_for_status()
            result=r.json()
            if result.get('all_succeeded') is False:raise RuntimeError(str(result)[:1500])
            return result
        old=c.get(base+'/ui/monitor').json()['enabled']
        c.put(base+'/ui/monitor',json={'enabled':False}).raise_for_status()
        try:
            command('sync_all')
            if args.train:
                for node in 'abc':
                    print('collect',node,flush=True);r=command('collect',node=node)
                    assert r['training']==12 and r['validation']==6
                for node in 'abc':
                    print('train',node,flush=True);r=command('train',node=node)
                    assert r['ack']['checksum_valid'] and r['ack']['compression']=='top50-int8-block256'
                    report['checks'].append({'training_node':node,'metrics':r['metrics'],'receipt':r['ack']})
                print('aggregate',flush=True);r=command('aggregate');report['algorithm']=r['algorithm']
                assert sum(r['weights'].values())>.999
                command('sync_all')
            # Bypass the dashboard injector: it never sees this experiment label.
            for fault in ('service_down','config_error','pool_exhausted','thread_pool_exhausted','dependency_timeout'):
                workload=f'http://127.0.0.1:{port+201}'
                print('blind diagnosis',fault,flush=True)
                c.post(workload+'/inject',json={'fault':fault}).raise_for_status()
                # Build a genuine current-incident window without sharing the label with the agent.
                time.sleep(9)
                r=command('run',node='a')
                attempts=[{'diagnosis':r['diagnosis'],'feedback':r['feedback'],'policy':r['policy']}]
                if not r['feedback']['success']:
                    # Same bounded escalation as the automatic scheduler; no label is sent.
                    r=command('run',node='a',mode='edge')
                    attempts.append({'diagnosis':r['diagnosis'],'feedback':r['feedback'],'policy':r['policy']})
                result={'fault_for_evaluation_only':fault,'diagnosis':r['diagnosis'],'feedback':r['feedback'],'policy':r['policy']}
                result['attempts']=attempts
                report['checks'].append(result)
                assert r['diagnosis']['root_cause']==fault,result
                assert r['feedback']['success'],result
                assert r['initial_diagnosis']['source']=='temporal-transformer-v2'
                assert r['diagnosis']['source'] in ('temporal-transformer-v2','language-model-api-mock-review')
                # Evaluator confirms only AFTER independent diagnosis and recovery.
                case=r['case_candidate'];case['root_cause_confirmed']=True;case['label_source']='testbed_injector'
                c.post(base+'/memory/cases',json=case).raise_for_status()
                c.post(base+'/ui/events',json={'node':'a','event_id':case['case_id'],'stage':'案例入库','detail':'盲测完成后由独立评估器核对根因','payload':{'source':'testbed_injector'}}).raise_for_status()
            report['passed']=True
        finally:
            c.post(f'http://127.0.0.1:{port+201}/inject',json={'fault':'healthy'})
            c.put(base+'/ui/monitor',json={'enabled':old})
            Path('runtime/paper-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS paper profile',flush=True)


if __name__=='__main__':main()
