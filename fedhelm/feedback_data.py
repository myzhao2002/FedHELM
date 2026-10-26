"""Local event windows become training data only after root-cause confirmation."""
import hashlib
import json
import os
from pathlib import Path
from .datasets import LABELS

def folder():
    p=Path(os.getenv('DATA_DIR','runtime/default'))/'feedback-events';p.mkdir(parents=True,exist_ok=True);return p

def file(event):
    return folder()/(hashlib.sha256(event.encode()).hexdigest()+'.json')

def retain(event,window,success):
    p=file(event)
    if p.exists():return
    p.write_text(json.dumps({'event_id':event,'window':window[-20:],'success':success,'confirmed':False}),encoding='utf-8')

def confirm(event,label):
    p=file(event)
    if not p.exists():raise ValueError('本端没有该事件窗口，不能生成训练样本')
    value=json.loads(p.read_text(encoding='utf-8'))
    if not value['success'] or label not in LABELS:raise ValueError('仅接收恢复成功且根因已确认的事件')
    if value['confirmed'] and value['label']!=LABELS.index(label):raise ValueError('事件已有不同标签，不能覆盖')
    bucket=int(hashlib.sha256(event.encode()).hexdigest()[:8],16)%10
    value.update(confirmed=True,label=LABELS.index(label),adapter='temporal-transformer-v2',source='confirmed-feedback',
                 split='train' if bucket<7 else 'validation' if bucket==7 else 'test')
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(value),encoding='utf-8');temp.replace(p)
    return {'accepted':True,'event_id':event,'split':value['split'],'retained_at':'end-node'}

def rows():
    values=[json.loads(p.read_text(encoding='utf-8')) for p in folder().glob('*.json')]
    return [v for v in values if v['confirmed']]
