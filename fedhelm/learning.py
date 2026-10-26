"""Real CPU PyTorch encoder/classifier; bootstrap data is explicitly synthetic."""
import json
import math
import random
from pathlib import Path
import torch
from torch import nn
from .contracts import Diagnosis, Model, Observation

torch.set_num_threads(1)
LABELS = ['healthy','service_down','config_error','pool_exhausted']
ADAPTER = 'torch-mlp-v1'
DIM = 160  # Linear(8,12), tanh, Linear(12,4)


def network():
    return nn.Sequential(nn.Linear(8,12), nn.Tanh(), nn.Linear(12,4))


def features(obs):
    text = ' '.join(obs.logs)
    return [float(obs.healthy),obs.error_rate,min(obs.latency_ms/500,2),obs.pool_usage,
            float('process unavailable' in text),float('invalid configuration' in text),
            float('connection timeout' in text),1-obs.error_rate]


def unpack(model):
    net = network()
    torch.nn.utils.vector_to_parameters(torch.tensor(model.parameters,dtype=torch.float32),net.parameters())
    return net


def pack(net):
    return torch.nn.utils.parameters_to_vector(net.parameters()).detach().tolist()


def macro_f1(net, rows):
    if not rows:
        return 0.
    with torch.no_grad():
        predictions = net(torch.tensor([r['features'] for r in rows],dtype=torch.float32)).argmax(1).tolist()
    scores=[]
    for label in range(4):
        tp=sum(p==label and r['label']==label for p,r in zip(predictions,rows))
        fp=sum(p==label and r['label']!=label for p,r in zip(predictions,rows))
        fn=sum(p!=label and r['label']==label for p,r in zip(predictions,rows))
        scores.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
    return sum(scores)/4


def fit(net,rows,epochs=60):
    x=torch.tensor([r['features'] for r in rows],dtype=torch.float32)
    y=torch.tensor([r['label'] for r in rows],dtype=torch.long)
    optimizer=torch.optim.AdamW(net.parameters(),lr=.015)
    losses=[]
    for _ in range(epochs):
        optimizer.zero_grad()
        loss=nn.functional.cross_entropy(net(x),y)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    return losses


def bootstrap():
    torch.manual_seed(631)
    rng=random.Random(631)
    rows=[]
    for label in range(4):
        for _ in range(40):
            obs=Observation(event_id='bootstrap',node_id='bootstrap',service_id='bootstrap',healthy=label==0,
                error_rate=0 if label==0 else 1, latency_ms=rng.uniform(1,40) if label!=3 else rng.uniform(80,200),
                pool_usage=1 if label==3 else rng.uniform(0,.3),
                logs=[['','process unavailable','invalid configuration','connection timeout'][label]])
            rows.append({'features':features(obs),'label':label})
    net=network()
    fit(net,rows,120)
    return Model(adapter=ADAPTER,parameters=pack(net))


def diagnose(obs,model):
    net=unpack(model)
    vector=features(obs)
    with torch.no_grad():
        probabilities=net(torch.tensor([vector],dtype=torch.float32)).softmax(1)[0]
    label=int(probabilities.argmax())
    # Stable telemetry space for memory, deliberately independent of trained encoder versions.
    return Diagnosis(event_id=obs.event_id,root_cause=LABELS[label],confidence=float(probabilities[label]),
        embedding=vector,embedding_version='telemetry-features-v1',model_version=model.version,
        evidence=obs.logs or ['HTTP requests succeeded'])


def train(model,rows):
    training=[r for r in rows if r['split']=='train']
    validation=[r for r in rows if r['split']=='validation']
    if not training or not validation:
        raise ValueError('请先采集训练与验证数据')
    if {r['event_id'] for r in training} & {r['event_id'] for r in validation}:
        raise ValueError('训练与验证事件不能重叠')
    net=unpack(model)
    before=macro_f1(net,validation)
    losses=fit(net,training)
    parameters=pack(net)
    return {'delta':[a-b for a,b in zip(parameters,model.parameters)],
            'quality':macro_f1(net,validation),'before_f1':before,
            'sample_count':len(training),'validation_count':len(validation),
            'label_histogram':[sum(r['label']==label for r in training) for label in range(4)],
            'loss_before':losses[0],'loss_after':losses[-1], 'epochs':len(losses)}
