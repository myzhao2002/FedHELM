import os
from fastapi import FastAPI
from .contracts import InferenceRequest, Plan
from .mock_model import plan

app = FastAPI(title='FedHELM language model gateway', version='0.2.0')


@app.get('/health')
def health():
    from .common import runtime_info
    local=os.getenv('MODEL_MODE','edge')=='local'
    provider={}
    if os.getenv('MODEL_API_CONFIG'):
        from .model_api import public
        value=public()['providers']['local' if local else 'edge']
        provider={'model':value['model'],'provider_mode':value['mode'],'model_deployment':value['deployment'],
                  'key_available':value['has_key'],'daily_call_limit':value['daily_call_limit']}
    return {'status': 'ok', 'adapter': 'api-gateway' if os.getenv('MODEL_API_CONFIG') else 'mock', 'simulated': True,
            **runtime_info('llm-local' if local else 'llm-edge','A' if local else 'edge'),**provider}


@app.post('/infer', response_model=Plan)
def infer(body: InferenceRequest):
    if os.getenv('MODEL_API_CONFIG'):
        from .model_api import infer as api_infer
        return api_infer(body,os.getenv('MODEL_MODE','edge'))
    diagnosis=body.diagnosis
    if os.getenv('PAPER_PROFILE')=='1':
        # Explicit idealized SLM/LLM stand-in. Only observations, never experiment labels.
        obs=body.observation;m=obs.metrics;root=None
        if not obs.healthy:
            if obs.response_codes and all(code==0 for code in obs.response_codes):root='service_down'
            elif m.get('config_error_rate',0)>.5:root='config_error'
            elif obs.pool_usage>.9 and m.get('db_wait_ms',0)>40:root='pool_exhausted'
            elif m.get('worker_wait_ms',0)>250:root='thread_pool_exhausted'
            elif m.get('dependency_error_rate',0)>.5 and m.get('dependency_ms',0)>80:root='dependency_timeout'
        if root:
            diagnosis=diagnosis.model_copy(update={'root_cause':root,'confidence':.9})
    result = plan(body.observation, diagnosis, os.getenv('MODEL_MODE', 'edge'),
                'MOCK adapter: maps candidate cause to a predefined action; no language model loaded')
    if os.getenv('PAPER_PROFILE')=='1':
        result.reason='仿真SLM/LLM接口按实际指标复核；无语言模型权重，接入API后替换此模块'
    for case in body.retrieved_cases:
        if case.plan.root_cause == result.root_cause and case.feedback.success:
            result.action = case.plan.action
            result.reason += '; retrieved case ' + case.case_id
            break
    return result


from .chinese import localize
localize(app, 'FedHELM · 可配置语言模型接口')
