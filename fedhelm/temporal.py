"""Resource-bounded six-layer temporal encoder. Numeric telemetry only, no fault labels at inference."""
import torch
from torch import nn
from .contracts import Model,Diagnosis,Observation
from .telemetry import vector

torch.set_num_threads(1)
LABELS=['healthy','service_down','config_error','pool_exhausted','thread_pool_exhausted','dependency_timeout']
ADAPTER='temporal-transformer-v2'


class Encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.project=nn.Linear(12,32)
        self.position=nn.Parameter(torch.zeros(20,32))
        self.encoder=nn.TransformerEncoder(nn.TransformerEncoderLayer(32,4,128,dropout=0,batch_first=True),6,enable_nested_tensor=False)
        self.norm=nn.LayerNorm(32)
        self.head=nn.Linear(32,6)

    def embed(self,x,mask):
        encoded=self.encoder(self.project(x)+self.position,src_key_padding_mask=mask)
        # The latest valid point queries the complete time window.
        last=(~mask).sum(1)-1
        return self.norm(encoded[torch.arange(encoded.shape[0]),last])

    def forward(self,x,mask):
        return self.head(self.embed(x,mask))


def pack(net):
    return torch.nn.utils.parameters_to_vector(net.parameters()).detach().tolist()


def unpack(model):
    if model.adapter!=ADAPTER:raise ValueError('请先同步时序模型')
    net=Encoder()
    torch.nn.utils.vector_to_parameters(torch.tensor(model.parameters,dtype=torch.float32),net.parameters())
    return net


def bootstrap():
    torch.manual_seed(631)
    return Model(adapter=ADAPTER,parameters=pack(Encoder()),training_samples=0)


def batch(windows):
    data=[]; masks=[]
    for window in windows:
        values=window[-20:]
        if not values:raise ValueError('至少需要一个真实观测点')
        data.append(values+[[0.]*12]*(20-len(values)))
        masks.append([False]*len(values)+[True]*(20-len(values)))
    return torch.tensor(data,dtype=torch.float32),torch.tensor(masks,dtype=torch.bool)


def diagnose(obs,model,window):
    # Encode the complete available event window (up to 20 observed points).
    values=[vector(Observation.model_validate({k:v for k,v in r.items() if k!='time'})) for r in window[-19:]]+[vector(obs)]
    net=unpack(model).eval()
    with torch.no_grad():
        x,mask=batch([values]);embedding=net.embed(x,mask);p=net.head(embedding).softmax(-1)[0]
    confidence=float(p.max()); label=LABELS[int(p.argmax())]
    if not model.training_samples or confidence<.55:label='unknown'
    return Diagnosis(event_id=obs.event_id,root_cause=label,confidence=confidence,
        embedding=embedding[0].tolist(),embedding_version=ADAPTER,model_version=model.version,
        probabilities=dict(zip(LABELS,p.tolist())),source=ADAPTER,
        evidence=[f'仅使用实测时序指标；{len(values)}个观测点，未输入注入标签或错误关键词',
                  '模型尚未完成真实数据训练' if not model.training_samples else f'累计训练样本{model.training_samples}'])


def f1(predicted,labels):
    scores=[]
    for k in range(6):
        tp=sum(a==k and b==k for a,b in zip(predicted,labels))
        fp=sum(a==k and b!=k for a,b in zip(predicted,labels))
        fn=sum(a!=k and b==k for a,b in zip(predicted,labels))
        scores.append(2*tp/max(1,2*tp+fp+fn))
    return sum(scores)/6


def train(model,rows,calibrate=False):
    rows=[r for r in rows if r.get('adapter')==ADAPTER]
    training=[r for r in rows if r['split']=='train'];validation=[r for r in rows if r['split']=='validation']
    if not training or not validation:raise ValueError('请先采集新版本真实时序训练集')
    if {r['event_id'] for r in training}&{r['event_id'] for r in validation}:raise ValueError('训练验证事件重叠')
    net=unpack(model)
    x,mask=batch([r['window'] for r in training]);y=torch.tensor([r['label'] for r in training])
    vx,vm=batch([r['window'] for r in validation]);vy=[r['label'] for r in validation]
    with torch.no_grad():before=f1(net(vx,vm).argmax(-1).tolist(),vy)
    # Initial supervised calibration is explicit; subsequent federated rounds use the paper's E=2.
    epochs=2
    optimizer=torch.optim.AdamW(net.parameters(),lr=.0005)
    losses=[]
    for _ in range(epochs):
        for start in range(0,len(training),32):
            optimizer.zero_grad();loss=nn.functional.cross_entropy(net(x[start:start+32],mask[start:start+32]),y[start:start+32])
            loss.backward();nn.utils.clip_grad_norm_(net.parameters(),1.);optimizer.step();losses.append(float(loss.detach()))
    with torch.no_grad():quality=f1(net(vx,vm).argmax(-1).tolist(),vy)
    return {'delta':[a-b for a,b in zip(pack(net),model.parameters)],'quality':quality,'before_f1':before,
            'sample_count':len(training),'validation_count':len(validation),'label_histogram':[sum(r['label']==k for r in training) for k in range(6)],
            'loss_before':losses[0],'loss_after':losses[-1],'epochs':epochs,
            'calibration':False,'note':'每轮2epoch，batch32，AdamW lr=0.0005；独立事件验证'}


def probe_accuracy(model,probes):
    if not probes:return None
    net=unpack(model).eval()
    with torch.no_grad():
        pred=net.head(torch.tensor([p['embedding'] for p in probes],dtype=torch.float32)).argmax(-1).tolist()
    return sum(LABELS[i]==p['root_cause'] for i,p in zip(pred,probes))/len(probes)


def evaluate(model,rows):
    """Read-only held-out evaluation; never optimize on the test split."""
    testing=[r for r in rows if r['split']=='test']
    if not testing:raise ValueError('所选数据集没有独立测试事件')
    other_ids={r['event_id'] for r in rows if r['split']!='test'}
    if any(r['event_id'] in other_ids for r in testing):raise ValueError('测试事件与训练或验证事件重叠')
    net=unpack(model).eval();predicted=[];probabilities=[]
    with torch.no_grad():
        for start in range(0,len(testing),32):
            x,mask=batch([r['window'] for r in testing[start:start+32]])
            p=net(x,mask).softmax(-1)
            predicted.extend(p.argmax(-1).tolist());probabilities.extend(p.max(-1).values.tolist())
    labels=[r['label'] for r in testing];matrix=[[0]*6 for _ in range(6)]
    for target,pred in zip(labels,predicted):matrix[target][pred]+=1
    return {'model_version':model.version,'adapter':model.adapter,'labels':LABELS,'test_count':len(testing),
            'accuracy':sum(a==b for a,b in zip(labels,predicted))/len(labels),'macro_f1':f1(predicted,labels),
            'confusion_matrix':matrix,'matrix_axes':{'rows':'真实标签','columns':'分类头预测'},
            'events':[{'event_id':r['event_id'],'expected':LABELS[r['label']],'predicted':LABELS[p],
                       'confidence':q,'requires_review':q<.55 or not model.training_samples}
                      for r,p,q in zip(testing,predicted,probabilities)],
            'scope':'仅评估当前轻量分类头；不调用记忆或语言模型，不修改模型，不用于联邦评分'}
