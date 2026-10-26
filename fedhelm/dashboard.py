"""Local operator console; fixed upstream addresses, no arbitrary URL proxy."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import httpx
from fastapi import APIRouter, HTTPException, Query, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .common import request
from .contracts import Fault, Injection
from .registry import node_ids,endpoint,NodeId,LocationId,cluster

router = APIRouter(tags=['可视化控制台'])
control_lock = Lock()
truth = {}
last = {}


def address(role, node=''):
    if role == 'federation':
        return os.getenv('FEDERATION_URL', 'http://127.0.0.1:8001')
    if role == 'llm':
        return os.getenv('LLM_URL', 'http://127.0.0.1:8002')
    if role == 'local':
        return os.getenv('LOCAL_LLM_URL', 'http://127.0.0.1:8003')
    if os.getenv('CLUSTER_CONFIG'):return getattr(endpoint(node),role+'_url')
    offset = 'abc'.index(node)
    return os.getenv(f'{role.upper()}_{node.upper()}_URL', f'http://127.0.0.1:{(8101 if role == "agent" else 8201)+offset}')


@router.get('/', include_in_schema=False)
def index():
    return FileResponse(Path(__file__).parent / 'static' / 'console.html',headers={'Cache-Control':'no-store'})

@router.get('/inject', include_in_schema=False)
def injection_page():
    if os.getenv('SEPARATE_INJECTOR')=='1':
        from fastapi.responses import RedirectResponse
        return RedirectResponse(cluster().injector_public_url or cluster().injector_url)
    return index()

@router.get('/lab', include_in_schema=False)
def lab_page():
    return index()

@router.get('/ui/monitor', summary='查看自动调度状态与处置时间线')
def monitor_status():
    from .scheduler import snapshot
    return snapshot()

class MonitorControl(BaseModel):
    enabled: bool

@router.put('/ui/monitor', summary='启用或暂停自动巡检', description='暂停后不再发起新处置，已开始的处置会完成验证。不会自动训练或注入故障。')
def monitor_control(body: MonitorControl):
    from . import scheduler
    scheduler.enabled = body.enabled
    scheduler.emit('edge',str(uuid.uuid4()),'自动处置开关','启用' if body.enabled else '暂停')
    return scheduler.snapshot()

from .scheduler import Trace
@router.post('/ui/events', summary='记录端节点实际处置步骤')
def trace(body: Trace):
    from .scheduler import emit
    emit(body.node, body.event_id, body.stage, body.detail,body.payload)
    return {'accepted': True}

@router.get('/node/{node}',include_in_schema=False)
def node_page(node: LocationId):
    return index()

@router.get('/history',include_in_schema=False)
def history_page():
    return index()

@router.get('/assets/{asset}',include_in_schema=False)
def console_asset(asset:Literal['console.css','console.js','workspace.js','workspace.css','cluster.js','cluster.css']):
    return FileResponse(Path(__file__).parent/'static'/asset)

@router.get('/topology',include_in_schema=False)
@router.get('/settings',include_in_schema=False)
@router.get('/datasets',include_in_schema=False)
@router.get('/paper',include_in_schema=False)
@router.get('/telemetry',include_in_schema=False)
@router.get('/algorithms',include_in_schema=False)
@router.get('/models',include_in_schema=False)
@router.get('/storage',include_in_schema=False)
@router.get('/logs',include_in_schema=False)
@router.get('/tasks',include_in_schema=False)
@router.get('/memory',include_in_schema=False)
@router.get('/resources',include_in_schema=False)
def module_page():
    return index()


@router.get('/ui/tasks',summary='按节点、状态、类型筛选并分页查看任务摘要')
def task_list(node:LocationId|None=None,
              status:Literal['','waiting','failed','resolved','cancelled','recorded']='',
              kind:Literal['fault','operation','all']='fault',search:str=Query('',max_length=100),
              page:int=Query(1,ge=1),size:int=Query(20,ge=5,le=100)):
    from .history import task_page
    return task_page(node,status,kind,search,page,size)

@router.get('/ui/records',summary='筛选与分页查询操作或模型传输日志')
def records_page(node:LocationId|None=None,kind:Literal['','transfer','upload','download','aggregate']='',
                 search:str=Query('',max_length=100),stage:str=Query('',max_length=100),
                 page:int=Query(1,ge=1),size:int=Query(20,ge=5,le=100)):
    from .history import page_records
    return page_records(node,kind,search,page,size,stage,include_payload=False)

@router.get('/ui/model-versions',summary='查看已记录的模型版本快照')
def recorded_models():
    from .history import model_versions
    return {'models':model_versions(include_payload=False),'note':'仅列出历史记录中实际保存的模型快照，不推测缺失版本。'}

from .datasets import DatasetImport,GenerateRequest
class ValidationSettings(BaseModel):
    seconds:float=__import__('pydantic').Field(ge=0,le=300)

@router.put('/ui/validation/{node}',summary='设置端侧恢复验证时间，3秒联调或300秒论文窗口')
def node_validation(node:NodeId,body:ValidationSettings):
    return request('PUT',address('agent',node),'/validation-settings',body.model_dump())

@router.get('/ui/datasets/{node}',summary='查看指定端节点数据集')
def node_datasets(node:NodeId):
    return request('GET',address('agent',node),'/datasets')

@router.get('/ui/datasets/{node}/preview/{dataset_id}',summary='预览指定端数据集的样本时序')
def dataset_preview(node:NodeId,dataset_id:str):
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',dataset_id):raise HTTPException(422,'非法数据集ID')
    return request('GET',address('agent',node),'/datasets/preview/'+dataset_id)

@router.get('/ui/dataset-schema',summary='获取后续数据集接入所需的标准JSONSchema')
def dataset_schema():return DatasetImport.model_json_schema()

@router.post('/ui/datasets/{node}/import',summary='向指定端导入标准JSON数据集')
def dataset_import(node:NodeId,body:DatasetImport):
    return request('POST',address('agent',node),'/datasets/import',body.model_dump(),timeout=30)

@router.post('/ui/datasets/{node}/generate',summary='生成虚构时序训练数据，不改变在线业务')
def dataset_generate(node:NodeId,body:GenerateRequest):
    return request('POST',address('agent',node),'/datasets/generate',body.model_dump(),timeout=30)

@router.put('/ui/datasets/{node}/selection',summary='切换本端训练数据集')
def dataset_selection(node:NodeId,body:dict):
    return request('PUT',address('agent',node),'/datasets/selection',body,timeout=30)


@router.post('/ui/datasets/{node}/evaluate',summary='评估指定端当前模型的独立测试分区')
def dataset_evaluate(node:NodeId):
    return request('POST',address('agent',node),'/datasets/evaluate',timeout=120)

class CaseReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    task_id:str
    confirmed_root_cause:Fault

@router.post('/ui/review-case',summary='人工确认实际诊断根因并收录成功案例')
def review_case(body:CaseReview):
    from .history import query
    from .contracts import Case
    from .edge import store_case
    from .scheduler import emit
    records=query(task=body.task_id,limit=1000)
    result=next((r['payload'] for r in records if r['stage']=='处置结果'),None)
    if not result or not result['feedback']['success']:
        raise HTTPException(409,'只能审核恢复验证成功的完整任务')
    if body.confirmed_root_cause=='unknown' or result['diagnosis']['root_cause']!=body.confirmed_root_cause:
        raise HTTPException(409,'确认根因必须与该成功案例的诊断一致；误诊请保留评估记录，不自动收录')
    case=Case.model_validate(result['case_candidate'])
    case.root_cause_confirmed=True;case.label_source='operator'
    ack=store_case(case)
    try:
        ack['training_sample']=request('POST',address('agent',case.source_node),'/feedback/confirm',
                                       {'event_id':case.case_id,'label':body.confirmed_root_cause},timeout=10)
    except Exception:
        ack['training_sample']={'accepted':False,'reason':'案例已保存；端侧样本确认待重试，可再次确认此案例'}
    emit(case.source_node,case.case_id,'案例入库','操作员确认根因；不依赖注入标签',{'label_source':'operator'})
    return ack

@router.get('/ui/telemetry',summary='查看各端实测窗口、异常证据与采集来源')
def telemetry_data():
    result={}
    for n in node_ids():
        try:result[n]=request('GET',address('agent',n),'/telemetry',timeout=4)
        except Exception as exc:result[n]={'error':str(exc)[:150]}
    return {'nodes':result,'paper_profile':os.getenv('PAPER_PROFILE')=='1'}

@router.get('/ui/algorithm',summary='查看论文重构算法状态与实现边界')
def algorithm_data():
    return {'federation':request('GET',address('federation'),'/algorithm',timeout=5),
            'encoder':{'layers':6,'hidden':32,'classes':6,'max_window':20,'parameters':77542,
                       'input':'12项白名单数值遥测；无注入类型、无日志关键词'},
            'limitations':['紧凑六层模型，非论文22.6M规模','大小语言模型经API调用；实际配置见模型API页面',
                            'CPU和内存按承载环境实测；容器配额单列；带宽先验、能耗估计',
                            '实际验证窗口可配置，默认3秒，论文为300秒','SQLite精确余弦检索；尚未接FAISS/Flower']}

@router.get('/ui/fault-catalog',summary='查看论文故障清单与真实注入支持范围')
def fault_catalog():
    from .fault_catalog import catalog
    return catalog()

@router.get('/ui/task/{task_id}',summary='查看单次任务完整步骤')
def task_details(task_id:str):
    from .history import query
    from .task_progress import progress
    steps=list(reversed(query(task=task_id,limit=1000)))
    return {'steps':steps,'progress':progress(steps)}

@router.get('/ui/history',summary='查询持久化任务链、指标与操作日志')
def history_data(node: LocationId | None=None,before: int | None=Query(None,gt=0),task_before: int | None=Query(None,gt=0)):
    from . import history
    return {'records':history.query(node,before,include_payload=False),'tasks':history.tasks(node,task_before,include_payload='summary'),
            'metrics':{n:history.series(n,compact=True) for n in (node_ids() if not node or node=='edge' else [node])}}

@router.get('/ui/node/{node}/artifacts',summary='查看端侧模型、训练数据和本地日志')
def node_artifacts(node: NodeId):
    return request('GET',address('agent',node),'/artifacts',timeout=10)

@router.get('/ui/cases',summary='分页查看系统成功处置案例')
def case_history(offset:int=Query(0,ge=0),node:NodeId|None=None):
    import json
    from .edge import db
    con=db()
    try:
        where=" WHERE json_extract(payload,'$.source_node')=?" if node else ''
        args=[node] if node else []
        count=con.execute('SELECT COUNT(*) FROM cases'+where,args).fetchone()[0]
        rows=con.execute('SELECT payload FROM cases'+where+' ORDER BY rowid DESC LIMIT 50 OFFSET ?',[*args,offset]).fetchall()
        return {'total':count,'cases':[json.loads(r[0]) for r in rows]}
    finally:
        con.close()


def probe(item):
    name, url = item
    try:
        with httpx.Client(timeout=1.5, trust_env=False) as client:
            response = client.get(url + '/health')
            response.raise_for_status()
            return name, {'online': True, **response.json()}
    except Exception:
        return name, {'online': False}


@router.get('/ui/status', summary='查看全部节点与服务状态', description='读取服务存活状态、业务观测、全局模型版本、持久化更新与服务部署清单。离线状态不会显示为正常。')
def status():
    from .edge import snapshot, resource_snapshot, health
    targets = [('federation', address('federation')), ('llm', address('llm')), ('local', address('local'))]
    for n in node_ids():
        targets.extend([(f'agent-{n}', address('agent', n)), (f'workload-{n}', address('workload', n))])
    with ThreadPoolExecutor(max_workers=12) as pool:
        services = dict(pool.map(probe, targets))
    def observe(n):
        if not services[f'workload-{n}']['online']:
            return n, None
        try:
            return n, request('GET', address('workload', n), '/observe?event_id=dashboard',timeout=2)
        except Exception:
            return n, None
    with ThreadPoolExecutor(max_workers=8) as pool:
        observations = {
            node_id: observation
            for node_id, observation in pool.map(observe, node_ids())
            if observation is not None
        }
    model = None
    if services['federation']['online']:
        try:
            model = request('GET', address('federation'), '/model')
            model.pop('parameters',None)
        except Exception:
            pass
    round_info = None
    if services['federation']['online']:
        try:
            round_info=request('GET',address('federation'),'/round')
        except Exception:
            pass
    inventory=[{'online':True,**health()},*[
        {'service':name,**value} for name,value in services.items()]]
    for n in node_ids():
        obs=observations.get(n) or {}
        controller=services[f'workload-{n}']
        inventory.append({'service':'business-'+n,'logical_node':n.upper(),
            'online':bool(obs.get('healthy')),'status_kind':'business-health',
            'pid':obs.get('business_pid'),'pod_name':obs.get('pod_name'),
            'hostname':controller.get('hostname'),'k8s_node':controller.get('k8s_node'),
            'deployment_mode':controller.get('deployment_mode'),
            'storage':{'directory':str(Path(controller.get('storage',{}).get('directory',''))/'business') if obs.get('workload_backend')=='process' else '/data'}})
    return {'services': services, 'observations': observations, 'model': model,
            'inventory':inventory,'federation_round':round_info,
            'memory': snapshot()['cases'], 'resources': resource_snapshot()['nodes'],
            'edge_node':os.getenv('K8S_NODE_NAME'),'simulated': True}


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['inject', 'run', 'submit', 'sync', 'train', 'aggregate', 'sync_all', 'train_all', 'resources','collect']
    node: NodeId = Field(default_factory=lambda:node_ids()[0])
    fault: Fault = 'service_down'
    mode: Literal['auto', 'lightweight', 'local', 'edge'] = 'auto'
    profile: Literal['normal', 'slow', 'offline'] = 'normal'


@router.post('/ui/command', summary='执行控制台测试操作', description='按按钮执行故障注入、诊断处置、案例提交或联邦操作。训练后端torch执行真实训练；process/kubernetes业务后端实际注入测试工作负载故障，synthetic后端仅模拟。')
def command(body: Command):
    if os.getenv('SEPARATE_INJECTOR')=='1' and body.action=='inject':raise HTTPException(403,'故障注入请使用独立实验站')
    from .scheduler import emit,incidents
    task_id=str(uuid.uuid4())
    n='edge' if body.action in ('aggregate','sync_all','train_all') else body.node
    emit(n,task_id,'操作开始',body.action,body.model_dump())
    try:
        result=execute_command(body,task_id)
        emit(n,task_id,'操作完成' if result.get('all_succeeded',True) else '部分失败',body.action,result)
        return {**result,'task_id':task_id}
    except Exception as exc:
        emit(n,task_id,'操作失败',str(getattr(exc,'detail',exc)),body.model_dump())
        raise

def execute_command(body: Command,task_id):
    from .edge import store_case
    if not control_lock.acquire(timeout=5):
        raise HTTPException(409, '另一个操作正在执行，请稍后重试')
    try:
        n = body.node
        base = address('agent', n)
        if body.action == 'inject':
            result = request('POST', address('workload', n), '/inject', {'fault': body.fault},timeout=90)
            truth[n] = body.fault
            last.pop(n, None)
            from .scheduler import emit, reset
            from .scheduler import incidents
            previous=incidents.pop(n,None)
            if previous:
                emit(n,previous,'人工终止' if body.fault=='healthy' else '被新实验替代',
                     '用户恢复测试业务' if body.fault=='healthy' else '同节点开始新的故障实验',{'next_task':task_id})
            if body.fault!='healthy':
                incidents[n]=task_id
            reset(n)
            emit(n, task_id, '故障注入' if body.fault != 'healthy' else '手动恢复', body.fault, result)
            return result
        if body.action == 'run':
            from .scheduler import incidents
            result = request('POST', base, '/run', {'force_mode': None if body.mode == 'auto' else body.mode,'event_id':incidents.pop(n,task_id)},timeout=660)
            # Associate label with this operation, never with a later injection.
            last[n] = {'result': result, 'truth': truth.pop(n, None)}
            return result
        if body.action == 'submit':
            record = last.get(n)
            if not record or not record['truth'] or record['truth'] == 'healthy':
                raise HTTPException(409, '请先在控制台注入故障，再执行诊断处置，才能核对真值并提交案例')
            from .contracts import Case
            case = Case.model_validate(record['result']['case_candidate'])
            if case.diagnosis.root_cause != record['truth']:
                raise HTTPException(409, '诊断根因与注入真值不一致，不收录案例')
            case.root_cause_confirmed = True
            case.label_source = ('testbed_injector' if record['result']['observation'].get('workload_backend') in ('process','kubernetes') else 'synthetic_injector')
            return store_case(case)
        if body.action in ('sync', 'train'):
            return request('POST', base, '/' + body.action,timeout=660)
        if body.action=='collect':
            truth.pop(n,None)
            last.pop(n,None)
            return request('POST',base,'/collect',timeout=600)
        if body.action == 'aggregate':
            return request('POST', address('federation'), '/aggregate')
        if body.action in ('sync_all', 'train_all'):
            results = {}
            for target in node_ids():
                try:
                    results[target] = {'ok': True, 'result': request('POST', address('agent', target), '/sync' if body.action == 'sync_all' else '/train',timeout=660)}
                except Exception as exc:
                    results[target] = {'ok': False, 'error': str(exc)}
            return {'nodes': results, 'all_succeeded': all(r['ok'] for r in results.values())}
        if body.action == 'resources':
            if os.getenv('PAPER_PROFILE')=='1' and body.profile=='normal':
                return request('DELETE',base,'/resource-override')
            return request('PUT', base, '/resources', {'node_id': n, 'tier': endpoint(n).tier,
                'rtt_ms': 200 if body.profile == 'slow' else 10,
                'edge_available': body.profile != 'offline'})
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get('detail', exc.response.text)
        except Exception:
            detail = exc.response.text
        raise HTTPException(exc.response.status_code, detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, '目标服务未连接，请检查节点状态和启动日志') from exc
    finally:
        control_lock.release()


class IsolatedExperiment(BaseModel):
    node:NodeId
    fault:Injection.model_fields['fault'].annotation

@router.post('/internal/experiment',include_in_schema=False)
def isolated_experiment(body:IsolatedExperiment,token:str|None=Header(None,alias='X-Fedhelm-Internal')):
    import secrets
    expected=os.getenv('INTERNAL_TOKEN','')
    if not expected or not token or not secrets.compare_digest(expected,token):raise HTTPException(403,'实验站身份校验失败')
    task=str(uuid.uuid4())
    from .scheduler import emit
    emit(body.node,task,'实验开始','独立实验站提交故障',{'node':body.node,'fault':body.fault})
    result=execute_command(Command(action='inject',node=body.node,fault=body.fault),task)
    return {**result,'task_id':task,'task_url':(cluster().console_url or cluster().edge_url)+'/tasks?task='+task}

@router.get('/ui/record/{seq}',summary='按需读取单条日志详情')
def record_detail(seq:int):
    from .history import db
    import json
    with db() as con:
        row=con.execute('SELECT payload FROM records WHERE seq=?',(seq,)).fetchone()
    if row is None:raise HTTPException(404,'记录不存在')
    return json.loads(row[0])
