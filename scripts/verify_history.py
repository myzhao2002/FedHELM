import json
import time
from pathlib import Path
import httpx

def main():
    with httpx.Client(base_url='http://127.0.0.1:14000',timeout=150,trust_env=False) as c:
        def command(action,**kw):
            r=c.post('/ui/command',json={'action':action,**kw});r.raise_for_status()
            result=r.json()
            assert result.get('all_succeeded',True),result
            return result
        initial=c.get('/ui/history?node=a').json()['records']
        cursor=initial[0]['seq'] if initial else 0
        command('inject',node='a',fault='service_down')
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            h=c.get('/ui/history?node=a').json()
            chains=[t for t in h['tasks'] if t['latest']>cursor and any(s['stage']=='故障注入' for s in t['steps'])]
            if chains and any(s['stage']=='案例入库' for s in chains[0]['steps']):
                chain=chains[0]
                assert {'故障注入','检测异常','轻量诊断','模型选择','执行修复','恢复验证','处置结果','案例入库'} <= {s['stage'] for s in chain['steps']}
                assert next(s for s in chain['steps'] if s['stage']=='处置结果')['payload']['feedback']['success']
                break
            time.sleep(2)
        else: raise AssertionError(h)
        c.put('/ui/monitor',json={'enabled':False}).raise_for_status()
        try:
            command('sync_all')
            command('train_all')
            command('aggregate')
            command('sync_all')
        finally:
            c.put('/ui/monitor',json={'enabled':True}).raise_for_status()
        h=c.get('/ui/history').json()
        stages={s['stage'] for t in h['tasks'] for s in t['steps']}
        assert {'梯度训练完成','上传模型增量','收到上传回执','请求全局模型','接收模型参数','模型落盘并加载','完成全局模型聚合与保存'} <= stages,stages
        a=c.get('/ui/node/a/artifacts').json()
        assert a['dataset_preview'] and a['active_model']['adapter']=='torch-mlp-v1'
        assert c.get('/ui/cases?node=a').json()['total']>0
        report={'status':'passed','fault_task':chain,'history':h,'model_version':a['active_model']['version']}
        Path('runtime/history-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: durable task chain, diagnosis, training/upload/aggregation/download records, data previews and cases',flush=True)

if __name__=='__main__':main()
