"""Deterministic test doubles; no LLM inference or neural training occurs here."""
from .contracts import Diagnosis, Model, Observation, Plan

LABELS = ['healthy', 'service_down', 'config_error', 'pool_exhausted']
ACTIONS = ['none', 'restart_service', 'restore_config', 'reset_pool']


def diagnose(obs: Observation, model: Model) -> Diagnosis:
    if not obs.healthy and 'process unavailable' in obs.logs:
        idx = 1
    elif 'invalid configuration' in obs.logs:
        idx = 2
    elif obs.pool_usage > .9:
        idx = 3
    else:
        idx = 0
    embedding = [float(i == idx) for i in range(4)]
    return Diagnosis(event_id=obs.event_id, root_cause=LABELS[idx],
                     confidence=max(.1, min(.95, .7 + model.parameters[idx])),
                     embedding=embedding, model_version=model.version,
                     evidence=obs.logs or ['health checks normal'])


def plan(obs, diagnosis, mode, reason):
    return Plan(event_id=obs.event_id, node_id=obs.node_id, service_id=obs.service_id,
                mode=mode, root_cause=diagnosis.root_cause,
                confidence=diagnosis.confidence,
                action=({'thread_pool_exhausted':'reset_workers','dependency_timeout':'restore_dependency','unknown':'none'}.get(diagnosis.root_cause) or ACTIONS[LABELS.index(diagnosis.root_cause)]), reason=reason)
