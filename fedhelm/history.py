"""Durable operator history; raw training datasets remain on their owning agents."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

@contextmanager
def db():
    directory=Path(os.getenv('DATA_DIR','runtime/edge'))
    directory.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(directory/'history.sqlite',timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    try:
        with con:
            con.execute('CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY, time TEXT, node TEXT, task TEXT, stage TEXT, detail TEXT, payload TEXT)')
            con.execute('CREATE INDEX IF NOT EXISTS records_node_task ON records(node,task,seq)')
            con.execute('CREATE INDEX IF NOT EXISTS records_task ON records(task,seq)')
            con.execute('CREATE TABLE IF NOT EXISTS metrics (seq INTEGER PRIMARY KEY,time TEXT,node TEXT,payload TEXT)')
            con.execute('CREATE INDEX IF NOT EXISTS metrics_node_seq ON metrics(node,seq)')
            yield con
    finally:
        con.close()

def record(node,task,stage,detail,payload=None):
    with db() as con:
        con.execute('INSERT INTO records(time,node,task,stage,detail,payload) VALUES (?,?,?,?,?,?)',
            (datetime.now(timezone.utc).isoformat(),node,task,stage,detail,json.dumps(payload or {},ensure_ascii=False)))

def metric(node,obs):
    with db() as con:
        con.execute('INSERT INTO metrics(time,node,payload) VALUES (?,?,?)',
                    (datetime.now(timezone.utc).isoformat(),node,json.dumps(obs)))
        con.execute('DELETE FROM metrics WHERE node=? AND seq NOT IN (SELECT seq FROM metrics WHERE node=? ORDER BY seq DESC LIMIT 2000)',(node,node))

def query(node=None,before=None,limit=100,task=None,include_payload=True):
    filters=[];args=[]
    for key,value in [('node',node),('task',task)]:
        if value:
            filters.append(key+'=?');args.append(value)
    if before:
        filters.append('seq<?');args.append(before)
    where=' WHERE '+' AND '.join(filters) if filters else ''
    with db() as con:
        columns='*' if include_payload else "seq,time,node,task,stage,detail,'{}' AS payload"
        if include_payload == 'summary':
            columns="seq,time,node,task,stage,detail,CASE WHEN stage='处置结果' THEN json_object('feedback',json_object('success',json_extract(payload,'$.feedback.success'))) ELSE '{}' END AS payload"
        rows=con.execute('SELECT '+columns+' FROM records'+where+' ORDER BY seq DESC LIMIT ?',[*args,limit]).fetchall()
    return [{**dict(r),'payload':json.loads(r['payload'])} for r in rows]

def series(node,compact=False):
    with db() as con:
        rows=con.execute('SELECT * FROM metrics WHERE node=? ORDER BY seq DESC LIMIT 180',(node,)).fetchall()
    items=[{**dict(r),'payload':json.loads(r['payload'])} for r in reversed(rows)]
    if compact:
        for item in items:
            item['payload']={k:v for k,v in item['payload'].items() if k in ('latency_ms','error_rate','pool_usage','healthy','observed_at','metrics')}
    return items

def tasks(node=None,before=None,include_payload=True):
    where=' WHERE node=?' if node else ''
    args=[node] if node else []
    having=' HAVING MAX(seq)<?' if before else ''
    if before: args.append(before)
    with db() as con:
        ids=con.execute('SELECT task,MAX(seq) AS latest FROM records'+where+' GROUP BY task'+having+' ORDER BY latest DESC LIMIT 30',args).fetchall()
    return [{'task':r['task'],'latest':r['latest'],'steps':list(reversed(query(node,limit=300,task=r['task'],include_payload=include_payload)))} for r in ids]


def task_page(node=None,status='',kind='fault',search='',page=1,size=20):
    """Lightweight task summaries: never send model arrays as part of a list."""
    with db() as con:
        rows=con.execute('''WITH grouped AS (
            SELECT task,MIN(seq) AS first,MAX(seq) AS last,COUNT(*) AS event_count,
            MAX(CASE WHEN stage IN ('故障注入','检测异常','采集观测','轻量诊断','处置结果') THEN 1 ELSE 0 END) AS is_fault,
            MIN(CASE WHEN stage='故障注入' THEN seq END) AS injection,
            MAX(CASE WHEN stage='处置结果' THEN seq END) AS result,
            MAX(CASE WHEN stage IN ('恢复失败','操作失败') OR stage LIKE '失败%' THEN seq ELSE 0 END) AS failure,
            MAX(CASE WHEN stage='检测异常' THEN seq ELSE 0 END) AS retry,
            MAX(CASE WHEN stage IN ('人工终止','被新实验替代') THEN seq ELSE 0 END) AS cancelled,
            MAX(CASE WHEN stage='案例入库' THEN 1 ELSE 0 END) AS case_stored
            FROM records GROUP BY task)
            SELECT g.*,f.node,f.time AS started_at,l.time AS updated_at,l.stage AS latest_stage,
            COALESCE(i.detail,f.detail) AS title,
            json_extract(r.payload,'$.diagnosis.root_cause') AS root_cause,
            json_extract(r.payload,'$.feedback.success') AS success
            FROM grouped g JOIN records f ON f.seq=g.first JOIN records l ON l.seq=g.last
            LEFT JOIN records i ON i.seq=g.injection LEFT JOIN records r ON r.seq=g.result
            ORDER BY g.last DESC''').fetchall()
    aliases={'service_down':'服务停止','config_error':'配置错误','pool_exhausted':'连接池耗尽',
             'thread_pool_exhausted':'线程池耗尽','dependency_timeout':'依赖超时','healthy':'正常'}
    terms=[search.casefold()]+[key for key,title in aliases.items() if search and search in title]
    items=[]
    for row in rows:
        item=dict(row)
        if node and item['node']!=node:continue
        if kind=='fault' and not item['is_fault']:continue
        if kind=='operation' and item['is_fault']:continue
        haystack=' '.join(str(item.get(k) or '') for k in ('task','title','root_cause','latest_stage')).casefold()
        if search and not any(term in haystack for term in terms):continue
        result=item['result'] or 0
        if item['cancelled']:state='cancelled'
        elif item['retry']>max(result,item['failure']):state='waiting'
        elif item['failure']>result or (result and not item['success']):state='failed'
        elif result and item['success']:state='resolved'
        elif item['is_fault']:state='waiting'
        else:state='recorded'
        item['status']=state
        items.append(item)
    counts={key:sum(i['status']==key for i in items) for key in ('resolved','failed','waiting','cancelled','recorded')}
    if status:items=[i for i in items if i['status']==status]
    total=len(items)
    return {'items':items[(page-1)*size:page*size],'total':total,'page':page,'size':size,'counts':counts}

def page_records(node=None,kind='',search='',page=1,size=20,stage='',include_payload=True):
    filters=[];args=[]
    if node: filters.append('node=?');args.append(node)
    if stage: filters.append('stage=?');args.append(stage)
    if kind:
        choices={'upload':['上传模型增量','收到上传回执'],
                 'download':['请求全局模型','接收模型参数','模型落盘并加载'],
                 'aggregate':['开始全局模型聚合与保存','完成全局模型聚合与保存','失败全局模型聚合与保存']}
        stages=sum(choices.values(),[]) if kind=='transfer' else choices[kind]
        filters.append('stage IN ('+','.join('?' for _ in stages)+')');args.extend(stages)
    if search:
        filters.append('(instr(detail,?)>0 OR instr(task,?)>0 OR instr(stage,?)>0)');args.extend([search]*3)
    where=' WHERE '+' AND '.join(filters) if filters else ''
    with db() as con:
        total=con.execute('SELECT COUNT(*) FROM records'+where,args).fetchone()[0]
        columns='*' if include_payload else "seq,time,node,task,stage,detail,'{}' AS payload"
        rows=con.execute('SELECT '+columns+' FROM records'+where+' ORDER BY seq DESC LIMIT ? OFFSET ?',[*args,size,(page-1)*size]).fetchall()
        stages=[r[0] for r in con.execute('SELECT DISTINCT stage FROM records ORDER BY stage')]
        versions={}
        if kind:
            expression="COALESCE(json_extract(payload,'$.version'),json_extract(payload,'$.base_version'),json_extract(payload,'$.model.version'),json_extract(payload,'$.update.base_version'))"
            for task in {r['task'] for r in rows}:
                row=con.execute('SELECT '+expression+' FROM records WHERE task=? AND '+expression+' IS NOT NULL ORDER BY seq DESC LIMIT 1',(task,)).fetchone()
                if row: versions[task]=row[0]
    return {'total':total,'page':page,'size':size,'stages':stages,
            'items':[{**dict(r),'payload':json.loads(r['payload']),'model_version':versions.get(r['task'])} for r in rows]}

def model_versions(include_payload=True):
    from .contracts import Model
    import hashlib
    versions={}
    with db() as con:
        rows=con.execute("SELECT seq,node,time,payload FROM records WHERE json_type(payload,'$.model')='object' ORDER BY seq DESC")
        for r in rows:
            try: model=Model.model_validate(json.loads(r['payload'])['model'])
            except Exception: continue
            digest=hashlib.sha256(model.model_dump_json().encode()).hexdigest()
            if digest not in versions:
                versions[digest]={'version':model.version,'adapter':model.adapter,'sha256':digest,
                    'parameter_count':len(model.parameters),'last_seen':r['time'],'record_seq':r['seq'],
                    'storage':'history.sqlite'}
                if include_payload:versions[digest]['model']=model.model_dump()
    return list(versions.values())
