"""HTTP federation with durable updates and transactional aggregation."""
import math
import os
import sqlite3
import hashlib
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from fastapi import FastAPI, HTTPException
from .contracts import Model, Update
from .common import audit
from .tracking import tracked

app = FastAPI(title='FedHELM mock federation coordinator', version='0.1.0')
lock = RLock()
pending = {}

@contextmanager
def database():
    connection = sqlite3.connect(model_path().parent/'federation.sqlite')
    try:
        with connection:
            connection.execute('CREATE TABLE IF NOT EXISTS updates (node TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS algorithm_state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS global_model (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            yield connection
    finally:
        connection.close()

def restore_pending():
    with database() as con:
        rows = con.execute('SELECT node,payload FROM updates').fetchall()
    pending.clear()
    pending.update({n:Update.model_validate_json(p) for n,p in rows})


def model_path():
    directory = Path(os.getenv('DATA_DIR', 'runtime/federation'))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / 'model.json'


def load_model():
    with database() as con:
        row = con.execute('SELECT payload FROM global_model WHERE id=1').fetchone()
    if row:
        return Model.model_validate_json(row[0])
    path = model_path()
    if path.exists():
        return Model.model_validate_json(path.read_text())
    if os.getenv('TRAINING_BACKEND')=='torch':
        if os.getenv('PAPER_PROFILE')=='1':
            from .temporal import bootstrap
        else:
            from .learning import bootstrap
        initial=bootstrap()
        path.write_text(initial.model_dump_json())
        return initial
    return Model()


@app.get('/health')
async def health():
    from .common import runtime_info
    return {'status': 'ok', 'simulated': True, 'training_backend':os.getenv('TRAINING_BACKEND','mock'),
            'pending_nodes':sorted(pending), **runtime_info('federation','edge')}

@app.get('/round',summary='查看持久化模型更新与聚合轮次')
def round_status():
    with lock:
        restore_pending()
        current=load_model()
        return {'version':current.version,'adapter':current.adapter,
            'model_sha256':hashlib.sha256(current.model_dump_json().encode()).hexdigest(),
            'updates':[{'node_id':u.node_id,'base_version':u.base_version,'sample_count':u.sample_count,
                       'delta_norm':math.sqrt(sum(v*v for v in u.delta)),'quality':u.quality,
                       'persisted':True} for u in pending.values()]}


@app.get('/model', response_model=Model)
def model():
    with lock:
        return load_model()


@app.post('/updates')
def update(body: Update):
    with lock:
        restore_pending()
        if body.node_id not in os.getenv('EXPECTED_NODES', 'a,b,c').split(','):
            raise HTTPException(400, 'unknown node')
        current=load_model()
        if len(body.label_histogram)!=(6 if current.adapter=='temporal-transformer-v2' else 4):
            raise HTTPException(422,'标签分布维度与模型不符')
        if len(body.delta)!=len(current.parameters):
            raise HTTPException(422,'模型增量维度不匹配')
        if body.base_version != current.version:
            raise HTTPException(409, 'stale model version; synchronize and regenerate update')
        if body.node_id in pending and pending[body.node_id] != body:
            raise HTTPException(409, 'conflicting update for this node and round')
        pending[body.node_id] = body
        with database() as con:
            con.execute('INSERT OR REPLACE INTO updates VALUES (?,?)',(body.node_id,body.model_dump_json()))
        return {'accepted': True, 'persisted':True, 'pending_nodes': sorted(pending), 'simulated': True}


from pydantic import BaseModel,ConfigDict
from .compression import Packet,decode
class CompressedUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    node_id:str
    base_version:int
    sample_count:int
    label_histogram:list[int]
    quality:float
    packet:Packet

@app.post('/updates/compressed',summary='接收Top50%稀疏、分块INT8量化增量并校验')
def compressed_update(body:CompressedUpdate):
    decoded=Update(node_id=body.node_id,base_version=body.base_version,sample_count=body.sample_count,
                   label_histogram=body.label_histogram,quality=body.quality,delta=decode(body.packet))
    result=update(decoded)
    audit('compressed_update',{'node':body.node_id,'base_version':body.base_version,
        'wire_bytes':len(body.model_dump_json().encode()),'sha256':body.packet.sha256,
        'dimensions':body.packet.dimensions,'retained':len(body.packet.indices),'checksum_valid':True})
    return {**result,'compression':'top50-int8-block256','checksum_valid':True,'retained':len(body.packet.indices)}


@app.post('/aggregate')
@tracked('全局模型聚合与保存')
def aggregate():
    with lock:
        restore_pending()
        expected = set(os.getenv('EXPECTED_NODES', 'a,b,c').split(','))
        if set(pending) != expected:
            raise HTTPException(409, f'waiting for nodes: {sorted(expected - set(pending))}')
        old = load_model()
        if any(u.base_version != old.version for u in pending.values()):
            raise HTTPException(409, 'round version mismatch')
        updates = list(pending.values())
        if old.adapter=='temporal-transformer-v2':
            return aggregate_paper(old,updates)
        dimensions=len(old.parameters)
        direction = [sum(u.delta[j] for u in updates) / len(updates) for j in range(dimensions)]
        scores = {}
        for u in updates:
            probs = [v/u.sample_count for v in u.label_histogram if v]
            diversity = -sum(p*math.log(p) for p in probs) / math.log(4)
            denom = math.sqrt(sum(v*v for v in u.delta) * sum(v*v for v in direction))
            cosine = sum(a*b for a,b in zip(u.delta, direction))/denom if denom else 0
            stability = (max(-1, min(1, cosine)) + 1) / 2
            scores[u.node_id] = u.sample_count * (.4*diversity + .35*u.quality + .25*stability)
        total = sum(scores.values())
        weights = {u.node_id: scores[u.node_id]/total if total else 1/len(updates) for u in updates}
        new = Model(version=old.version+1, adapter=old.adapter, training_samples=old.training_samples+sum(u.sample_count for u in updates), parameters=[old.parameters[j] + sum(
            weights[u.node_id]*u.delta[j] for u in updates) for j in range(dimensions)])
        path = model_path()
        # Model advance and inbox consumption commit together; restart cannot reapply the round.
        with database() as con:
            con.execute('INSERT OR REPLACE INTO global_model VALUES (1,?)',(new.model_dump_json(),))
            con.execute('DELETE FROM updates')
        temp = path.with_suffix('.tmp')
        temp.write_text(new.model_dump_json(), encoding='utf-8')
        temp.replace(path)
        pending.clear()
        result = {'model': new.model_dump(), 'weights': weights, 'simulated': True,
                  'training_backend': 'torch' if old.adapter=='torch-mlp-v1' else 'mock',
                  'note': '加权合并端侧更新；torch模式使用实际梯度与验证分数。当前稳定性为当轮余弦，未实现论文EWMA/探针。'}
        audit('aggregation', result)
        return result


def aggregate_paper(old,updates):
    from .temporal import probe_accuracy
    from .common import request
    with database() as con:
        row=con.execute('SELECT payload FROM algorithm_state WHERE id=1').fetchone()
    stats=__import__('json').loads(row[0]) if row else {'round':0,'clients':{},'weights':{}}
    probes=[];probe_status='no compatible verified memory'
    try:
        cases=request('GET',os.environ['EDGE_URL'],'/memory/snapshot',timeout=5)['cases']
        probes=[{'embedding':c['diagnosis']['embedding'],'root_cause':c['diagnosis']['root_cause']}
                for c in cases if c['diagnosis']['embedding_version']=='temporal-transformer-v2'
                and c['root_cause_confirmed'] and c['feedback']['success']][:20]
        if probes:probe_status='verified memory head probes'
    except Exception as exc:probe_status='unavailable: '+str(exc)[:100]
    direction=[sum(stats['weights'].get(u.node_id,1/len(updates))*u.delta[j] for u in updates) for j in range(len(old.parameters))]
    components={};scores={}
    cold=stats['round']<3
    for u in updates:
        prior=stats['clients'].get(u.node_id,{})
        entropy=-sum((n/u.sample_count)*math.log(n/u.sample_count) for n in u.label_histogram if n)/math.log(6)
        fval=.7*prior.get('fval',u.quality)+.3*u.quality
        denom=math.sqrt(sum(d*d for d in direction)*sum(d*d for d in u.delta))
        cosine=max(-1,min(1,sum(a*b for a,b in zip(direction,u.delta))/denom)) if denom else 0
        stability=.6*prior.get('stability',cosine)+.4*cosine
        candidate=Model(adapter=old.adapter,version=old.version,training_samples=old.training_samples+u.sample_count,
                        parameters=[p+d for p,d in zip(old.parameters,u.delta)])
        probe=probe_accuracy(candidate,probes)
        quality=fval if probe is None else .5*fval+.5*probe
        q=(u.sample_count/max(x.sample_count for x in updates))*entropy if cold else .4*entropy+.35*quality+.25*((stability+1)/2)
        scores[u.node_id]=u.sample_count*q
        stats['clients'][u.node_id]={'fval':fval,'stability':stability}
        components[u.node_id]={'diversity':entropy,'validation_ewma':fval,'probe_accuracy':probe,'quality':quality,
                               'stability_ewma':stability,'contribution':q,'sample_count':u.sample_count}
    total=sum(scores.values())
    weights={u.node_id:scores[u.node_id]/total if total else 1/len(updates) for u in updates}
    new=Model(adapter=old.adapter,version=old.version+1,training_samples=old.training_samples+sum(u.sample_count for u in updates),
              parameters=[p+sum(weights[u.node_id]*u.delta[j] for u in updates) for j,p in enumerate(old.parameters)])
    stats.update(round=stats['round']+1,weights=weights,components=components,probe_count=len(probes),probe_status=probe_status,cold_start=cold)
    with database() as con:
        con.execute('INSERT OR REPLACE INTO global_model VALUES(1,?)',(new.model_dump_json(),))
        con.execute('INSERT OR REPLACE INTO algorithm_state VALUES(1,?)',(__import__('json').dumps(stats),))
        con.execute('DELETE FROM updates')
    temp=model_path().with_suffix('.tmp');temp.write_text(new.model_dump_json(),encoding='utf-8');temp.replace(model_path())
    pending.clear()
    result={'model':new.model_dump(),'weights':weights,'algorithm':stats,'training_backend':'torch','simulated':True,
            'note':'6类紧凑模型；前三轮多样性冷启动；无兼容探针时明确退回验证F1，不伪造探针得分'}
    audit('aggregation',result)
    return result

@app.get('/algorithm',summary='查看贡献度评分、EWMA与探针覆盖')
def algorithm_status():
    with database() as con:row=con.execute('SELECT payload FROM algorithm_state WHERE id=1').fetchone()
    return __import__('json').loads(row[0]) if row else {'round':0,'clients':{},'probe_count':0}

from .chinese import localize
localize(app, 'FedHELM · 联邦聚合协调器')
