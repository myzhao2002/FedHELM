import os
import time
import uuid
import json
import math
import httpx
from fastapi.responses import JSONResponse
from pathlib import Path
from threading import Lock,Event,Thread
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .contracts import (Resources, Observation, Model, RunRequest, InferenceRequest,
                        Plan, Feedback, Case, Update)
from .common import request, audit
from .tracking import tracked,step
from .mock_model import diagnose, plan

paper_profile=os.getenv('PAPER_PROFILE')=='1'
collector_stop=Event()
collector_thread=None

@asynccontextmanager
async def lifespan(app):
    global collector_thread
    if paper_profile:
        collector_stop.clear()
        collector_thread=Thread(target=collector_loop,daemon=True,name='end-telemetry')
        collector_thread.start()
    try:yield
    finally:
        collector_stop.set()
        if collector_thread:collector_thread.join(timeout=3)

app = FastAPI(title='FedHELM end-node agent', version='2.0.0',lifespan=lifespan)

@app.exception_handler(httpx.HTTPStatusError)
async def upstream_error(_request, exc):
    try:
        detail = exc.response.json().get('detail', '上游服务拒绝请求')
    except (ValueError, AttributeError):
        detail = '上游服务拒绝请求'
    return JSONResponse(status_code=exc.response.status_code, content={'detail': detail})
node = os.getenv('NODE_ID', 'a')
tier = os.getenv('TIER', 'A')
edge = os.getenv('EDGE_URL', 'http://127.0.0.1:8000')
federation = os.getenv('FEDERATION_URL', 'http://127.0.0.1:8001')
workload = os.getenv('WORKLOAD_URL', 'http://127.0.0.1:8201')
local_llm = os.getenv('LOCAL_LLM_URL', 'http://127.0.0.1:8003')
state = Resources(node_id=node, tier=tier)
resource_override={}
validation_seconds_setting=min(300,max(0,float(os.getenv('VALIDATION_SECONDS','300' if paper_profile else '0'))))
current_model = Model()
saved_model=Path(os.getenv('DATA_DIR','runtime/default'))/'model.json'
if saved_model.exists():
    current_model=Model.model_validate_json(saved_model.read_text(encoding='utf-8'))
cache = []
run_lock = Lock()


@app.get('/health')
def health():
    from .common import runtime_info
    import hashlib
    return {'status': 'ok', 'node_id': node, 'tier': tier, 'model_version': current_model.version,
            'training_backend':os.getenv('TRAINING_BACKEND','mock'),'simulated': True,
            'validation_seconds':validation_seconds_setting,'paper_profile':paper_profile,'model_training_samples':current_model.training_samples,'collector_running':bool(collector_thread and collector_thread.is_alive()),'model_adapter':current_model.adapter,'model_sha256':hashlib.sha256(current_model.model_dump_json().encode()).hexdigest(),
            **runtime_info('agent-'+node,node.upper()),'host_info':__import__('fedhelm.host_info',fromlist=['snapshot']).snapshot()}

@app.get('/artifacts',summary='查看本端运行模型、数据样本和本地操作日志')
def artifacts():
    directory=Path(os.getenv('DATA_DIR','runtime/default'))
    def tail(name):
        path=directory/name
        if not path.exists(): return []
        with path.open('rb') as stream:
            size=path.stat().st_size
            stream.seek(max(0,size-1024*1024))
            if size>1024*1024: stream.readline()
            lines=stream.read().decode('utf-8',errors='replace').splitlines()[-50:]
        rows=[]
        for line in lines:
            try: rows.append(json.loads(line))
            except ValueError: pass
        return rows
    return {'telemetry':telemetry_status() if paper_profile else None,'policy':__import__('fedhelm.policy',fromlist=['statistics']).statistics() if paper_profile else {},'node':node,'runtime':health(),'active_model':current_model.model_dump(),
            'dataset_preview':tail('dataset-v2.jsonl' if paper_profile else 'dataset.jsonl'),'local_logs':tail('events.jsonl'),
            'preview_limit':50,'note':'数据与日志仅预览最近50条；原始完整文件保留端侧，不上传训练原始数据到联邦聚合器。'}


@app.put('/resources')
def set_resources(body: Resources):
    global state,resource_override
    if body.node_id != node or body.tier != tier:
        raise HTTPException(400, 'node_id and tier cannot be changed')
    if paper_profile:
        resource_override={k:getattr(body,k) for k in ('rtt_ms','bandwidth_mbps','edge_available')}
        state=state.model_copy(update={**resource_override,'source':'measured shared host; controlled network override'})
    else:state=body
    return request('POST', edge, '/resources', state.model_dump())


def measured_resources():
    import psutil
    global state
    started=time.perf_counter()
    try:
        response=request('GET',edge,'/health',timeout=2)
        queue=response.get('inference_queue',0)
        available=True
    except Exception:available=False;queue=0
    state=Resources(node_id=node,tier=tier,cpu_usage=psutil.cpu_percent()/100,
        memory_available_mb=int(psutil.virtual_memory().available/1024/1024),
        cpu_cores=psutil.cpu_count() or 1,bandwidth_mbps=50,
        rtt_ms=(time.perf_counter()-started)*1000,edge_available=available,edge_queue=queue,
        source='measured shared host; HTTP RTT includes server processing')
    if resource_override:state=state.model_copy(update={**resource_override,'source':'measured shared host; controlled network override'})
    from .host_info import snapshot as host_snapshot
    host=host_snapshot()
    if host.get('container_memory_available_mb') is not None:
        state.memory_available_mb=min(state.memory_available_mb,host['container_memory_available_mb'])
        state.source+='; available memory bounded by cgroup quota'
    return state


@app.delete('/resource-override',summary='清除网络实验覆盖并恢复实测资源输入')
def clear_override():
    resource_override.clear()
    return request('POST',edge,'/resources',measured_resources().model_dump())


def collector_loop():
    from .telemetry import append
    initialized=False
    while not collector_stop.wait(float(os.getenv('COLLECT_INTERVAL','2'))):
        if not initialized:
            try:
                sync()
                initialized=True
            except Exception as exc:
                audit('initial_sync_wait',{'error_type':type(exc).__name__})
                continue
        if not run_lock.acquire(blocking=False):continue
        try:
            obs=Observation.model_validate(request('GET',workload,'/observe?event_id=collector',timeout=8))
            append(obs)
            request('POST',edge,'/resources',measured_resources().model_dump(),timeout=2)
        except Exception as exc:
            audit('collector_error',{'message':str(exc)[:250]})
        finally:run_lock.release()


@app.get('/telemetry',summary='查看端侧持续采集的实测窗口与异常证据')
def telemetry_status():
    from .telemetry import window,detect,FIELDS
    from .policy import statistics
    rows=window()
    return {'node':node,'latest':{k:v for k,v in rows[-1].items() if k!='time'} if rows else None,
            'window':rows,'anomaly':detect(rows),'resources':state.model_dump(),'policy_statistics':statistics(),
            'fields':FIELDS,'source':'actual workload requests and process counters','injector_label_access':False}


@app.post('/sync')
@tracked('模型下载与加载')
def sync():
    global current_model, cache
    with run_lock:
        step('请求全局模型',{'destination':federation})
        current_model = Model.model_validate(request('GET', federation, '/model',timeout=90))
        step('接收模型参数',{'version':current_model.version,'adapter':current_model.adapter,'parameter_count':len(current_model.parameters)})
        cache = request('GET', edge, '/memory/snapshot')['cases']
        directory=Path(os.getenv('DATA_DIR','runtime/default'))
        directory.mkdir(parents=True,exist_ok=True)
        temporary=directory/'model.tmp'
        temporary.write_text(current_model.model_dump_json(),encoding='utf-8')
        temporary.replace(directory/'model.json')
        step('模型落盘并加载',{'path':str(directory/'model.json'),'version':current_model.version})
        request('POST', edge, '/resources', state.model_dump())
        return {'model': current_model.model_dump(), 'cached_cases': len(cache), 'simulated': True}


def choose_mode(diagnosis, forced):
    if forced == 'local' and (tier != 'A' or state.memory_available_mb < 1024):
        raise HTTPException(409, 'local mode requires an A node with available memory')
    if forced == 'edge' and not state.edge_available:
        raise HTTPException(503, 'edge unavailable; event requires review')
    if forced:
        return forced, 'explicit demo override'
    if diagnosis.confidence < .55:
        if not state.edge_available:
            raise HTTPException(503, 'low confidence and edge unavailable; no action executed')
        return 'edge', 'low confidence escalation'
    if tier == 'A' and state.memory_available_mb >= 1024 and state.rtt_ms > 100:
        return 'local', 'mock policy: slow network on capable node'
    return 'lightweight', 'mock policy: confident candidate; prefer lightweight'


@app.post('/run')
def run(body: RunRequest):
    with run_lock:
        event = body.event_id or str(uuid.uuid4())
        intervention=request('GET',workload,'/health').get('intervention_revision') if paper_profile else None
        def trace(stage, detail, payload=None):
            try:
                request('POST', edge, '/ui/events', {'node':node,'event_id':event,'stage':stage,'detail':detail,'payload':payload or {}},timeout=2)
            except Exception:
                pass
        obs = Observation.model_validate(request('GET', workload, f'/observe?event_id={event}'))
        trace('采集观测', f'健康={obs.healthy}，错误率={obs.error_rate:.0%}，时延={obs.latency_ms:.1f}ms', obs.model_dump())
        from .fault_catalog import extension_diagnosis
        extension = None if paper_profile else extension_diagnosis(obs,current_model)
        if paper_profile:
            from .temporal import diagnose as temporal_diagnose
            from .telemetry import window,vector
            event_window=[vector(Observation.model_validate({k:v for k,v in r.items() if k!='time'})) for r in window()[-19:]]+[vector(obs)]
            diagnosis=temporal_diagnose(obs,current_model,window())
            extension=None
            if diagnosis.root_cause=='healthy' and not obs.healthy:
                diagnosis.root_cause='unknown'
                diagnosis.confidence=0.0
                diagnosis.evidence.append('模型正常判断与实际请求失败冲突，禁止按正常执行')
        elif extension:
            diagnosis = extension
        elif os.getenv('TRAINING_BACKEND')=='torch':
            if current_model.adapter!=('temporal-transformer-v2' if paper_profile else 'torch-mlp-v1'):
                raise HTTPException(409,'请先同步全局轻量模型')
            from .learning import diagnose as neural_diagnose
            diagnosis = neural_diagnose(obs,current_model)
        else:
            diagnosis = diagnose(obs, current_model)
        trace('轻量诊断', f'根因={diagnosis.root_cause}，诊断来源={"显式日志规则" if extension else current_model.adapter}，分值={diagnosis.confidence:.1%}，模型v{current_model.version}', diagnosis.model_dump())
        def similar(d):
            if d['embedding_version']!=diagnosis.embedding_version or len(d['embedding'])!=len(diagnosis.embedding):
                return False
            denominator=math.sqrt(sum(v*v for v in d['embedding'])*sum(v*v for v in diagnosis.embedding))
            return denominator>0 and sum(a*b for a,b in zip(d['embedding'],diagnosis.embedding))/denominator>=.82
        initial_diagnosis=diagnosis.model_dump()
        policy_details={}
        mode_started=time.perf_counter()
        if paper_profile:
            from .policy import fuse,choose
            diagnosis,matched,memory_score=fuse(diagnosis,cache)
            try:mode,policy_details=choose(diagnosis,state,body.force_mode,memory_score)
            except ValueError as exc:raise HTTPException(409,str(exc)) from exc
            reason='资源代价最小化；详情见调度证据'
            trace('记忆融合', '分类概率与记忆投票融合',diagnosis.model_dump())
        else:
            mode, reason = choose_mode(diagnosis, body.force_mode)
        trace('模型选择', f'{mode}：{reason}',policy_details)
        inference = InferenceRequest(observation=obs, diagnosis=diagnosis,
            retrieved_cases=[Case.model_validate(c) for c in cache
                if similar(c['diagnosis'])][:3])
        used_case = None
        if mode == 'lightweight':
            result = plan(obs, diagnosis, mode, reason + '; bootstrap test template')
            for c in cache:
                d = c['diagnosis']
                if similar(d) and c['plan']['root_cause']==diagnosis.root_cause:
                    result.action = c['plan']['action']
                    result.reason = reason + '; reused verified case ' + c['case_id']
                    used_case = c['case_id']
                    break
        else:
            try:
                result = Plan.model_validate(request('POST', edge if mode == 'edge' else local_llm,
                    '/diagnose' if mode == 'edge' else '/infer', inference.model_dump()))
            except Exception as exc:
                raise HTTPException(503, 'model adapter unavailable; no action executed') from exc
        if result.event_id != event or result.node_id != node or result.service_id != obs.service_id:
            raise HTTPException(502, 'invalid plan correlation or target')
        if paper_profile:
            from .policy import review_reasons
            reasons=review_reasons(result,matched,obs.healthy)
            trace('最终置信校验','；'.join(reasons) if reasons else '最终诊断通过置信度与记忆一致性检查',
                  {'mode':mode,'root_cause':result.root_cause,'confidence':result.confidence,'reasons':reasons})
            if reasons and mode!='edge':
                if not state.edge_available:raise HTTPException(409,'最终诊断未通过校验且边缘不可达，未执行修复')
                trace('升级复核','所选模式返回后校验未通过，升级边缘',{'previous_mode':mode,'reasons':reasons})
                reviewed=diagnosis.model_copy(update={'root_cause':result.root_cause,'confidence':result.confidence})
                inference=inference.model_copy(update={'diagnosis':reviewed})
                result=Plan.model_validate(request('POST',edge,'/diagnose',inference.model_dump()))
                mode='edge'
                policy_details.update(selected='edge',post_inference_escalation=True,review_reasons=reasons)
                if result.event_id!=event or result.node_id!=node or result.service_id!=obs.service_id:
                    raise HTTPException(502,'invalid review plan correlation or target')
            if result.confidence<.55 or result.root_cause=='unknown' or (result.root_cause=='healthy' and not obs.healthy):
                trace('操作失败','边缘复核仍无足够证据，未执行修复',result.model_dump())
                raise HTTPException(409,'最终复核证据不足，未执行修复')
        if paper_profile and mode in ('local','edge'):
            diagnosis=diagnosis.model_copy(update={'root_cause':result.root_cause,'confidence':result.confidence,
                'source':'language-model-api-review' if os.getenv('MODEL_API_CONFIG') else 'language-model-api-mock-review','probabilities':{},'evidence':diagnosis.evidence+[result.reason]})
            trace('语言模型复核','模型接口返回最终根因与方案，保留端侧初诊供对照',{'initial':initial_diagnosis,'final':diagnosis.model_dump()})
        trace('生成方案', f'动作={result.action}；{result.reason}', result.model_dump())
        trace('执行修复', f'仅操作本节点测试业务：{result.action}')
        if paper_profile and result.root_cause=='unknown':
            trace('操作失败','证据不足，等待人工检查；未执行修复',diagnosis.model_dump())
            raise HTTPException(409,'当前模型无法可靠诊断，未执行修复；请先采集训练或接入真实LLM')
        inference_seconds=time.perf_counter()-mode_started
        execution = request('POST', workload, '/execute', result.model_dump(),timeout=90)
        trace('修复动作返回', '执行器已返回；正在验证业务是否恢复', execution)
        samples = []
        validation_seconds=validation_seconds_setting
        verify_start=time.monotonic()
        stable_since=None
        changed=False
        deadline=max(3,validation_seconds)
        success=False
        from .recovery import healthy, recovered
        while time.monotonic()-verify_start<=deadline:
            time.sleep(1 if paper_profile else .05)
            sample=Observation.model_validate(request('GET', workload, f'/observe?event_id={event}'))
            samples.append(sample)
            elapsed=time.monotonic()-verify_start
            if healthy(sample):
                if stable_since is None:stable_since=elapsed
            else:stable_since=None
            if paper_profile:
                changed=request('GET',workload,'/health').get('intervention_revision')!=intervention
            if paper_profile:
                trace('验证采样',f'样本{len(samples)}，已观察{time.monotonic()-verify_start:.1f}s，恢复截止{deadline:g}s',sample.model_dump())
            success=execution['applied'] and recovered(samples,elapsed,stable_since,deadline,changed)
            if success or changed:break
        trace('恢复验证', '三次HTTP观测全部通过' if success else '恢复验证未通过', {'success':success,'samples':[s.model_dump() for s in samples]})
        feedback = Feedback(event_id=event, success=success, samples=samples,
                            criterion=f'执行后{deadline:g}秒内恢复；连续健康至少2秒且至少3个观测；人工/新注入干预={changed}；error_rate<=.05，latency<=500ms')
        if paper_profile:
            from .policy import update as update_policy
            from .feedback_data import retain
            retain(event,event_window,success)
            update_policy(mode,diagnosis.root_cause,inference_seconds,len(inference.model_dump_json().encode()) if mode=='edge' else 0,success)
        # Label confirmation belongs to the external synthetic test harness, not diagnosis.
        case = Case(case_id=event, source_node=node, diagnosis=diagnosis, plan=result, feedback=feedback)
        response = {'initial_diagnosis':initial_diagnosis,'policy':policy_details,'observation': obs.model_dump(), 'diagnosis': diagnosis.model_dump(),
                    'plan': result.model_dump(), 'execution': execution, 'feedback': feedback.model_dump(),
                    'case_candidate': case.model_dump(), 'used_case': used_case, 'simulated': True}
        audit('event', response)
        try:
            request('POST',edge,'/ui/events',{'node':node,'event_id':event,'stage':'处置结果','detail':'恢复成功' if success else '恢复失败','payload':response},timeout=3)
        except Exception:
            pass
        return response


@app.post('/train')
@tracked('本地训练与增量上传')
def train():
    with run_lock:
        if os.getenv('TRAINING_BACKEND')=='torch':
            if paper_profile:
                from .temporal import train as fit_model
            else:
                from .learning import train as fit_model
            dataset=Path(os.getenv('DATA_DIR','runtime/default'))/('dataset-v2.jsonl' if paper_profile else 'dataset.jsonl')
            from .datasets import training_rows,active
            imported_rows=training_rows() if paper_profile else None
            if (not dataset.exists() and imported_rows is None) or current_model.adapter!=('temporal-transformer-v2' if paper_profile else 'torch-mlp-v1'):
                raise HTTPException(409,'请先采集数据并同步模型')
            rows=imported_rows if imported_rows is not None else [json.loads(line) for line in dataset.read_text(encoding='utf-8').splitlines() if line]
            calibration_path=dataset.parent/'calibrated-datasets.json'
            calibrated=json.loads(calibration_path.read_text(encoding='utf-8')) if calibration_path.exists() else []
            selected_id=active() if paper_profile else None
            calibrate=paper_profile and selected_id is not None and selected_id not in calibrated
            result=fit_model(current_model,rows,calibrate=calibrate) if paper_profile else fit_model(current_model,rows)
            result['dataset_id']=active() if paper_profile else None
            result['data_sources']=sorted({r.get('source','unknown') for r in rows})
            step('梯度训练完成',{k:v for k,v in result.items() if k!='delta'})
            update=Update(node_id=node,base_version=current_model.version,
                **{k:result[k] for k in ('sample_count','delta','label_histogram','quality')})
            if paper_profile:
                from .compression import encode
                packet=encode(update.delta)
                wire={k:getattr(update,k) for k in ('node_id','base_version','sample_count','label_histogram','quality')}
                wire['packet']=packet.model_dump()
                step('上传模型增量',{'base_version':update.base_version,'sample_count':update.sample_count,
                    'compression':'top50-int8-block256','dimensions':len(update.delta),'retained':len(packet.indices),
                    'wire_bytes':len(json.dumps(wire).encode()),'sha256':packet.sha256})
                acknowledgement=request('POST',federation,'/updates/compressed',wire,timeout=120)
            else:
                step('上传模型增量',{'base_version':update.base_version,'sample_count':update.sample_count,'delta':update.delta})
                acknowledgement=request('POST',federation,'/updates',update.model_dump())
            step('收到上传回执',acknowledgement)
            if calibrate:
                calibrated.append(selected_id)
                calibration_path.write_text(json.dumps(calibrated),encoding='utf-8')
            (dataset.parent/'last-update.json').write_text(update.model_dump_json(),encoding='utf-8')
            audit('real_training',result)
            return {'update':update.model_dump(),'ack':acknowledgement,'metrics':{k:v for k,v in result.items() if k!='delta'},
                    'training_backend':'torch','simulated':True,'note':'实际PyTorch训练；验证事件与训练事件分离'}
        # Deliberately synthetic update generator; a future trainer replaces this adapter.
        idx = {'A': 1, 'B': 2, 'C': 3}[tier]
        histogram = [2, 2, 2, 2]
        histogram[idx] = 8
        delta = [.001] * 4
        delta[idx] = .01
        update = Update(node_id=node, base_version=current_model.version, sample_count=sum(histogram),
                        delta=delta, label_histogram=histogram, quality=.7)
        acknowledgement = request('POST', federation, '/updates', update.model_dump())
        return {'update': update.model_dump(), 'ack': acknowledgement, 'simulated': True,
                'note': 'Generated test delta, no gradient training or measured validation quality'}


from pydantic import BaseModel,Field
class ValidationSettings(BaseModel):
    seconds:float=Field(ge=0,le=300)

@app.put('/validation-settings',summary='设置恢复观察时长，支持论文300秒窗口')
@tracked('设置恢复观察时长')
def validation_settings(body:ValidationSettings):
    global validation_seconds_setting
    validation_seconds_setting=body.seconds
    audit('validation_settings',body.model_dump())
    return {'seconds':validation_seconds_setting,'applies_to':'下一次处置，当前任务不变'}

@app.post('/datasets/evaluate',summary='使用当前数据集独立测试分区评估本端模型')
@tracked('独立测试集评估')
def evaluate_dataset():
    from .datasets import training_rows,active
    from .temporal import evaluate
    import hashlib
    with run_lock:
        rows=training_rows()
        if rows is None:raise HTTPException(409,'请先选择包含测试分区的数据集')
        try:result=evaluate(current_model,rows)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        result.update(dataset_id=active(),model_sha256=hashlib.sha256(current_model.model_dump_json().encode()).hexdigest(),evaluated_at=time.time())
        folder=Path(os.getenv('DATA_DIR','runtime/default'))/'evaluations';folder.mkdir(parents=True,exist_ok=True)
        destination=folder/f'{active()}-v{current_model.version}-{time.time_ns()}.json'
        destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        result['stored_at']=str(destination)
        return result


from .datasets import DatasetImport,GenerateRequest
from .contracts import Fault
class ConfirmFeedback(BaseModel):
    event_id:str=Field(min_length=1,max_length=100)
    label:Fault

@app.post('/feedback/confirm',summary='确认本地根因并加入固定分区训练语料')
def confirm_feedback(body:ConfirmFeedback):
    from .feedback_data import confirm
    with run_lock:
        try:return confirm(body.event_id,body.label)
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc

@app.get('/datasets',summary='查看本端离线数据集与当前训练选择')
def list_datasets():
    from .datasets import listing
    return listing()

@app.get('/datasets/preview/{dataset_id}',summary='预览标准事件数据，每类一个代表事件')
def preview_dataset(dataset_id:str):
    from .datasets import directory,DatasetImport
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',dataset_id):raise HTTPException(422,'非法数据集ID')
    p=directory()/(dataset_id+'.json')
    if not p.exists():raise HTTPException(404,'数据集不存在')
    body=DatasetImport.model_validate_json(p.read_text(encoding='utf-8'))
    representatives={}
    for record in body.records:representatives.setdefault(record.label,record)
    return {'dataset_id':dataset_id,'records':[r.model_dump() for r in representatives.values()]}

@app.get('/datasets/schema',summary='下载统一时序数据集JSON格式定义')
def dataset_schema():return DatasetImport.model_json_schema()

@app.post('/datasets/import',summary='导入外部或虚构时序数据集，保留数据来源')
@tracked('导入训练数据集')
def import_dataset(body:DatasetImport):
    from .datasets import import_dataset as save
    with run_lock:
        try:result=save(body)
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
        audit('dataset_import',result)
        return result

@app.post('/datasets/generate',summary='生成明确标注的虚构时序样本，不注入实时业务')
def generate_dataset(body:GenerateRequest):
    from .datasets import generate
    return import_dataset(generate(body))

@app.put('/datasets/selection',summary='选择训练数据集；null使用实测采集数据')
@tracked('切换训练数据集')
def select_dataset(body:dict):
    from .datasets import select,listing
    if set(body)!={'dataset_id'}:raise HTTPException(422,'仅接受dataset_id')
    with run_lock:
        try:select(body['dataset_id'])
        except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
        audit('dataset_selection',body)
        return listing()


@app.post('/collect',summary='采集本节点真实故障训练数据',description='在本节点测试业务逐类注入故障并采集HTTP观测，最后恢复正常；每次事件独立划入训练或验证集。')
@tracked('数据采集与保存')
def collect():
    if os.getenv('TRAINING_BACKEND')!='torch':
        raise HTTPException(409,'当前节点未启用真实训练')
    if paper_profile:
        from .temporal import LABELS,ADAPTER
        from .telemetry import vector as features
    else:
        from .learning import features,LABELS
    rows=[]
    with run_lock:
        try:
            for label,fault in enumerate(LABELS):
                for repetition in range(3):
                    request('POST',workload,'/inject',{'fault':fault},timeout=90)
                    event=str(uuid.uuid4())
                    obs=Observation.model_validate(request('GET',workload,f'/observe?event_id={event}'))
                    points=[features(obs)]
                    if paper_profile:
                        for _ in range(3):
                            time.sleep(.05)
                            points.append(features(Observation.model_validate(request('GET',workload,f'/observe?event_id={event}'))))
                    rows.append({'adapter':'temporal-transformer-v2' if paper_profile else 'torch-mlp-v1','window':points,'event_id':event,'features':features(obs),'label':label,
                        'split':'validation' if repetition==2 else 'train','source':obs.workload_backend,
                        'observation':obs.model_dump()})
        finally:
            request('POST',workload,'/inject',{'fault':'healthy'},timeout=90)
        path=Path(os.getenv('DATA_DIR','runtime/default'))/('dataset-v2.jsonl' if paper_profile else 'dataset.jsonl')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a',encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row)+'\n')
    return {'collected':len(rows),'training':len(LABELS)*2,'validation':len(LABELS),'node_id':node,'data_source':rows[0]['source']}


from .chinese import localize
localize(app, 'FedHELM · 端节点故障管理')

from .common import protect_node_service
protect_node_service(app)
