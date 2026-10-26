"""Prepare paper-flow datasets and run one bounded, actual federated round."""
import json
import time
from pathlib import Path
import httpx


def main():
    base='http://127.0.0.1:15000';report={'datasets':{},'before':{},'after':{}}
    with httpx.Client(timeout=600,trust_env=False) as client:
        def call(method,path,body=None):
            r=client.request(method,base+path,json=body);r.raise_for_status();return r.json()
        def command(action):
            result=call('POST','/ui/command',{'action':action})
            if result.get('all_succeeded') is False:raise RuntimeError(str(result)[:1000])
            return result
        enabled=call('GET','/ui/monitor')['enabled']
        call('PUT','/ui/monitor',{'enabled':False})
        try:
            stamp=int(time.time())
            for i,node in enumerate('abc'):
                print('prepare profiles',node,flush=True);entries=[]
                for j,profile in enumerate(('balanced','non_iid','transition')):
                    result=call('POST',f'/ui/datasets/{node}/generate',{'dataset_id':f'{profile}-{node}-{stamp}',
                        'profile':profile,'per_class':12,'seed':631+29*i+101*j})
                    entries.append(result)
                # Keep training at the endpoint; use different fault frequencies on A/B/C.
                call('PUT',f'/ui/datasets/{node}/selection',{'dataset_id':entries[1]['dataset_id']})
                report['datasets'][node]=entries
            command('sync_all')
            for node in 'abc':report['before'][node]=call('POST',f'/ui/datasets/{node}/evaluate')
            print('train and upload on three endpoints',flush=True)
            trained=command('train_all')
            report['training']={node:item['result']['metrics'] for node,item in trained['nodes'].items()}
            assert all(item['result']['ack']['checksum_valid'] for item in trained['nodes'].values())
            print('aggregate and distribute',flush=True)
            aggregation=command('aggregate');command('sync_all')
            report['algorithm']=aggregation['algorithm'];report['model_version']=aggregation['model']['version']
            for node in 'abc':report['after'][node]=call('POST',f'/ui/datasets/{node}/evaluate')
            hashes={result['model_sha256'] for result in report['after'].values()}
            assert len(hashes)==1,'端侧加载模型不一致'
            report['passed']=True
        finally:
            call('PUT','/ui/monitor',{'enabled':enabled})
            Path('runtime/paper-dataset-round.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS dataset preparation, evaluation and federated round',flush=True)


if __name__=='__main__':main()
