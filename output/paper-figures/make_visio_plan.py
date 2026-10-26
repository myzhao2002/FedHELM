import json
from pathlib import Path
OUT=Path(__file__).parent
S=[];C=[];W=1698;H=1072
def box(i,x,y,w,h,text='',fill='#FFFFFF',line='#555555',font=25,bold=False,kind='rectangle',container=False):
    a=dict(id=i,x=(x+w/2)/100,y=(H-y-h/2)/100,width=w/100,height=h/100,text=text,fill=fill,line=line,fontFamily='Arial',fontSize=font*.72,fontColor='#161616',bold=bold,kind=kind,lineWeight=1.0)
    if kind!='text':a.update(stencil='BASIC_M.VSSX',master='Rounded Rectangle' if kind=='rounded-rectangle' else 'Circle' if kind=='ellipse' else 'Rectangle')
    if container:a.update(shapeIntent='container',allowOverlap=True)
    S.append(a);return i
def txt(i,x,y,w,h,text,font=25,bold=False):return box(i,x,y,w,h,text,font=font,bold=bold,kind='text')
def path(i,pts,color='#181818',arrow=False,dash=False):
    # Invisible route helpers allow precise recreation of the straight reference geometry.
    for suffix,p in [('s',pts[0]),('t',pts[-1])]:
        box(i+suffix,p[0]-.01,p[1]-.01,.02,.02,kind='text');S[-1]['shapeIntent']='route-helper'
    C.append(dict(id=i,kind='polyline',**{'from':i+'s','to':i+'t'},points=[q for x,y in pts for q in [x/100,(H-y)/100]],line=color,arrow=arrow,dashed=dash,lineWeight=1.4,allowedOverlaps=[]))

box('ends',32,213,590,715,fill='#F1F1F1',kind='rounded-rectangle',container=True)
box('edge',923,213,743,715,fill='#F1F1F1',kind='rounded-rectangle',container=True)
txt('brand',30,95,243,65,'FedHELM',49,True)
txt('separator',283,92,35,70,'|',48)
txt('title',324,101,540,55,'Edge–end system architecture',34)
txt('end_title',49,231,535,48,'Heterogeneous end nodes',33,True)
txt('edge_title',1005,231,450,47,'Edge node (GPU)',33,True)
txt('online',998,276,390,31,'Online inference & control',22)
for i,y,h,title in [('a',293,159,'Tier A · Strong'),('b',473,137,'Tier B · Medium'),('c',632,137,'Tier C · Weak')]:
    box('tier_'+i,60,y,535,h,kind='rounded-rectangle',container=True)
    txt('title_'+i,191,y+7,365,39,title,29,True)
    box('light_'+i,200,y+56,281,42,'Lightweight model',fill='#DDEAF7',line='#DDEAF7',font=26,kind='rounded-rectangle')
txt('plus',487,345,36,46,'+',29)
txt('slm',191,399,345,36,'Quantized SLM',27)

box('functions',60,790,535,115,fill='#F1F1F1',line='#999999',kind='rounded-rectangle',container=True)
txt('func_title',76,792,285,39,'Local functions',31,True)
txt('sense',77,833,200,35,'Fault sensing',25)
txt('train',77,865,200,35,'Local training',25)
txt('diagnosis',324,833,261,35,'Lightweight diagnosis',24)
txt('execution',324,865,261,35,'Remediation execution',24)

box('controller',950,319,323,228,kind='rounded-rectangle',container=True)
txt('controller_title',966,332,290,40,'Resource controller',28,True)
box('alg1',972,381,279,64,'Adaptive mode selection\nAlg. 1',fill='#E3EDF7',line='#E3EDF7',font=23,bold=True,kind='rounded-rectangle')
txt('resource',971,458,282,34,'Resource / network states',23)
txt('modes',967,497,292,37,'Lightweight / Local / Edge',22,True)
box('llm',1316,319,324,228,fill='#E0ECF6',kind='rounded-rectangle',container=True)
txt('llm_title',1333,339,290,47,'Edge LLM service',30,True)
txt('llm_model',1330,394,296,37,'Qwen2.5-7B / vLLM',25)
txt('llm_infer',1340,438,275,38,'Full inference',27)
txt('llm_memory',1329,491,298,32,'Memory-augmented',23)

txt('federated_caption',945,603,442,33,'Federated model & knowledge update',22)
box('aggregator',957,706,316,179,kind='rounded-rectangle',container=True)
txt('agg_title',967,721,298,39,'Fault-aware aggregator',25,True)
box('weighting',978,766,274,39,'Fault-aware weighting',fill='#E3EDF7',line='#E3EDF7',font=24,bold=True,kind='rounded-rectangle')
txt('alg2',1040,808,153,34,'Alg. 2',25,True)
txt('agg_params',970,845,291,32,'Encoder + classifier updates',21)
box('memory',1316,706,317,179,kind='rounded-rectangle',container=True)
txt('mem_title',1330,721,289,39,'Federated fault memory',24,True)
txt('mem_index',1331,772,285,32,'Vector index + validation',23)
txt('mem_modes',1325,813,299,27,'Shared cases for all modes',20)
txt('mem_summary',1337,847,275,27,'Global memory summary',21)
txt('frozen',1009,940,637,34,'Federate encoder + classifier; keep SLM / LLM frozen',21)

txt('up_label',644,309,267,44,'Context / states',26)
txt('down_label',650,495,257,72,'Mode / diagnosis /\nactions',25)
txt('fed_up',653,593,263,67,'Model updates /\nvalidated cases',25)
txt('fed_down',650,824,270,67,'Global model /\nmemory summary',25)
txt('retrieval',1430,558,126,67,'Retrieved\ncases',21)
path('context',[(629,371),(944,371)],arrow=True)
path('routing',[(1273,422),(1309,422)],arrow=True)
path('results',[(1358,547),(1358,583),(629,583)],arrow=True)
path('controller_return',[(1061,547),(1061,583)])
box('join_black',1057,579,8,8,fill='#181818',line='#181818',kind='ellipse')
path('retrieve',[(1559,706),(1559,553)],arrow=True)
blue='#3195F5'
path('upload_trunk',[(629,669),(1474,669)],color=blue,dash=True)
path('upload_agg',[(1114,669),(1114,699)],color=blue,dash=True,arrow=True)
path('upload_memory',[(1474,669),(1474,699)],color=blue,dash=True,arrow=True)
path('download',[(1474,885),(1474,912),(629,912)],color=blue,dash=True,arrow=True)
path('agg_download',[(1114,885),(1114,912)],color=blue,dash=True)
box('join_blue',1111,909,6,6,fill=blue,line=blue,kind='ellipse')
path('legend_black',[(505,1009),(580,1009)],arrow=True)
txt('legend_black_label',597,985,273,47,'Inference & control',26)
path('legend_blue',[(883,1009),(960,1009)],color=blue,dash=True,arrow=True)
txt('legend_blue_label',979,985,290,47,'Federated exchange',26)

# Editable industrial-device line art. No matching industrial masters in local computer stencils.
def iconrect(i,x,y,w,h,fill='#FFFFFF',rounded=False):
    box(i,x,y,w,h,fill=fill,line='#444444',kind='rounded-rectangle' if rounded else 'rectangle');S[-1]['shapeIntent']='icon';S[-1]['allowOverlap']=True
def circle(i,x,y,d,fill='#FFFFFF'):box(i,x,y,d,d,fill=fill,line='#444444',kind='ellipse');S[-1]['allowOverlap']=True
iconrect('a_front',86,364,79,39,rounded=True)
path('a_roof',[(86,364),(99,343),(151,343),(165,364),(86,364)])
for k in range(8):path('a_fin'+str(k),[(101+k*7,344),(93+k*9,364)])
circle('a_led',96,378,11)
iconrect('a_port1',121,382,13,7);iconrect('a_port2',144,382,13,7)
iconrect('b_board',89,523,69,68,rounded=True);iconrect('b_chip',113,543,25,26,fill='#444444')
iconrect('b_port1',150,531,15,14);iconrect('b_port2',150,568,15,14)
for k in range(7):circle('b_dot'+str(k),94,530+k*8,3,fill='#444444')
iconrect('c_device',85,696,88,34,rounded=True)
for r in range(3):
    for c in range(5):circle(f'c_dot_{r}_{c}',93+c*4,704+r*4,2,fill='#444444')
iconrect('c_port',122,706,10,16,fill='#444444');circle('c_knob',139,707,12,fill='#444444');circle('c_led',156,709,8)
for k in range(3):
    iconrect('server_row'+str(k),953,237+k*15,39,14)
    circle('server_led'+str(k),958,242+k*15,4,fill='#444444')
    iconrect('server_slot'+str(k),980,242+k*15,7,3,fill='#444444')

# Containers, icon details and deliberate bus junctions overlap by design.
for c in C:
    if c['id'].startswith(('a_fin','a_roof')):c['allowedOverlaps']=[s['id'] for s in S if s['id'].startswith('a_')]
    if c['id'] in ('controller_return','results'):c['allowedOverlaps']+=['join_black']
    if c['id'] in ('download','agg_download'):c['allowedOverlaps']+=['join_blue']
plan={'page':{'name':'FedHELM Architecture','width':W/100,'height':H/100},'shapes':S,'connectors':C}
(OUT/'visio-reference-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
