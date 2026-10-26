"""Paper equations (4),(5) and memory voting, with explicit measurement provenance."""
import json
import math
import os
from pathlib import Path

MODES=('lightweight','local','edge')
PRIORS={'lightweight':{'time':.15,'energy':.1,'bytes':0.,'accuracy':.7},
        'local':{'time':1.5,'energy':2.,'bytes':0.,'accuracy':.8},
        'edge':{'time':2.,'energy':.5,'bytes':20000.,'accuracy':.9}}


def review_reasons(candidate,cases,healthy=True):
    """Algorithm 1 line 8: check the returned result, not only initial logits."""
    reasons=[]
    if candidate.confidence<.55 or candidate.root_cause=='unknown':reasons.append('最终诊断置信度不足')
    if candidate.root_cause=='healthy' and not healthy:reasons.append('正常判断与实际请求失败冲突')
    votes={}
    for case in cases:
        if case.get('feedback',{}).get('success') and case.get('root_cause_confirmed'):
            label=case['diagnosis']['root_cause']
            votes[label]=votes.get(label,0)+case['diagnosis']['confidence']
    if votes and max(votes,key=votes.get)!=candidate.root_cause:reasons.append('最终根因与相似已确认记忆冲突')
    return reasons


def path():return Path(os.getenv('DATA_DIR','runtime/default'))/'policy-statistics.json'


def statistics():
    return json.loads(path().read_text(encoding='utf-8')) if path().exists() else {}


def similarity(a,b):
    if len(a)!=len(b):return 0.
    d=math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
    return sum(x*y for x,y in zip(a,b))/d if d else 0.


def fuse(diagnosis,cases):
    matching=[]
    for case in cases:
        d=case['diagnosis']
        if d['embedding_version']!=diagnosis.embedding_version:continue
        score=similarity(d['embedding'],diagnosis.embedding)
        if score>=.82:matching.append((score,case))
    matching=sorted(matching,key=lambda x:x[0],reverse=True)[:3]
    if not matching or not diagnosis.probabilities:return diagnosis,[c for _,c in matching],0.
    probabilities=dict(diagnosis.probabilities); votes={k:0. for k in probabilities}
    for score,case in matching:
        label=case['diagnosis']['root_cause']
        if label in votes:votes[label]+=score
    total=sum(votes.values())
    if not total:return diagnosis,[],0.
    memory_label=max(votes,key=votes.get);model_label=max(probabilities,key=probabilities.get)
    diagnosis.memory_conflict=memory_label!=model_label
    fused={k:.65*probabilities[k]+.35*votes[k]/total for k in probabilities}
    label=max(fused,key=fused.get)
    diagnosis.probabilities=fused;diagnosis.confidence=fused[label]
    diagnosis.root_cause=label if fused[label]>=.55 else 'unknown'
    diagnosis.evidence.append('分类概率0.65 + 已验证记忆投票0.35；冲突时升级边缘复核')
    return diagnosis,[c for _,c in matching],matching[0][0]


def choose(diagnosis,resources,forced=None,memory_score=0):
    feasible=['lightweight']
    remote_local=bool(os.getenv('MODEL_API_CONFIG'))
    if resources.tier=='A' and ((remote_local and resources.edge_available) or (not remote_local and resources.memory_available_mb>=1024)):feasible.append('local')
    if resources.edge_available:feasible.append('edge')
    if forced and forced not in feasible:raise ValueError('强制推理模式不满足资源或可达性条件')
    stats=statistics();costs={};details={}
    for mode in feasible:
        entry=stats.get(mode+':'+diagnosis.root_cause,PRIORS[mode])
        z=2*diagnosis.confidence+memory_score+entry['accuracy']-2
        accuracy=1/(1+math.exp(-z))
        if mode=='edge':accuracy=min(1,accuracy+.15)
        if mode=='local':accuracy=min(1,accuracy+.08)
        latency=entry['time']+(resources.rtt_ms/1000 if mode=='edge' else 0)
        communication=entry['bytes']/1_000_000
        if mode=='local' and remote_local:
            local_bytes=max(entry['bytes'],20000.)
            communication=local_bytes/1_000_000
            latency+=resources.rtt_ms/1000+local_bytes*8/(resources.bandwidth_mbps*1_000_000)
        if mode=='edge':
            latency+=entry['bytes']*8/(resources.bandwidth_mbps*1_000_000)
            latency*=1+resources.edge_queue
        cost=.35*latency/8+.25*entry['energy']/12+.20*communication+.20*(1-accuracy)
        costs[mode]=cost;details[mode]={'cost':cost,'latency_seconds':latency,'estimated_energy_j':entry['energy'],'remote_api':mode=='edge' or (mode=='local' and remote_local),
            'upload_bytes':entry['bytes'],'conditional_quality':accuracy,'source':'EWMA' if mode+':'+diagnosis.root_cause in stats else 'cold-start prior'}
    selected=forced or min(costs,key=costs.get)
    escalation=diagnosis.confidence<.55 or diagnosis.memory_conflict or diagnosis.root_cause=='unknown'
    if escalation and not forced:
        if 'edge' not in feasible:raise ValueError('诊断证据不足且边缘不可达，等待人工检查')
        selected='edge'
    return selected,{'selected':selected,'feasible':feasible,'costs':details,'escalation':escalation,
                     'forced':bool(forced),'weights':{'latency':.35,'energy':.25,'communication':.20,'quality':.20},
                     'note':'能耗为估计；带宽为配置先验；占位LLM时的质量项不能视为真实模型准确率'}


def update(mode,label,seconds,upload_bytes,success):
    stats=statistics();key=mode+':'+label;old=stats.get(key,PRIORS[mode]);alpha=.7
    observed={'time':seconds,'energy':seconds*.5,'bytes':float(upload_bytes),'accuracy':float(success)}
    stats[key]={k:alpha*old[k]+(1-alpha)*observed[k] for k in observed}
    stats[key].update(samples=old.get('samples',0)+1,energy_source='estimated at 0.5W, not measured',accuracy_source='recovery-feedback proxy, not root-cause accuracy')
    path().parent.mkdir(parents=True,exist_ok=True);temporary=path().with_suffix('.tmp')
    temporary.write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path())
