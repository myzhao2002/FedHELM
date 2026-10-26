from pathlib import Path

# Reuse the vector/raster primitives without regenerating earlier drafts.
source=(Path(__file__).parent/'draw_figures.py').read_text(encoding='utf-8').split('\nf=Figure(')[0]
source=source.replace('timesbd.ttf','arialbd.ttf').replace('times.ttf','arial.ttf').replace('Times New Roman, Times, serif','Arial, Helvetica, sans-serif')
exec(compile(source,'drawing_primitives','exec'))

f=Figure(1800,1030)
f.rect(35,35,600,875,stroke=GREY,lw=1.8)
f.text(65,76,'Heterogeneous end nodes',29,True,anchor='start')
f.rect(1015,35,750,875,stroke=GREY,lw=1.8)
f.text(1045,76,'Edge node (GPU)',29,True,anchor='start')

def node(y,h,title,lines):
    f.box(65,y,530,h,title,lines,color=INK,size=24)
    f.line([(595,y+h/2),(655,y+h/2)],GREY,lw=1.2,arrow=False)

node(115,135,'Tier A · Strong',[
    'Fault encoder + classifier',
    'Quantized SLM (1.5B, 4-bit)',
    'Local / Lightweight / Edge'])
node(275,95,'Tier B · Medium',[
    'Fault encoder + classifier',
    'Lightweight / Edge'])
node(395,95,'Tier C · Weak',[
    'Fault encoder + classifier',
    'Lightweight / Edge'])

f.text(65,530,'Functions available at each end node',21,True,anchor='start')
f.box(65,555,530,115,'Adaptive mode selection (Alg. 1)',[
    'Resource constraints · Event difficulty',
    'EWMA statistics · Retrieved fault memory'],color=BLUE,size=23,fill='#f5f8fa')
f.box(65,690,530,165,'Local sensing and remediation',[
    'Logs / metrics / traces / alerts / context',
    'Local training · Knowledge cache',
    'Action execution · Recovery validation'],size=23)
f.line([(595,613),(655,613)],GREY,lw=1.2,arrow=False)
f.line([(595,772),(655,772)],GREY,lw=1.2,arrow=False)
f.line([(655,160),(655,820)],GREY,lw=1.5,arrow=False)
f.text(337,884,'Raw observations and training data stay local.',20,color=GREY)

f.box(1045,115,530,135,'Edge LLM service',[
    'Qwen2.5-7B / vLLM',
    'Root-cause diagnosis and action planning'],BLUE,size=25)
f.box(1045,305,530,135,'Resource controller',[
    'Resource and network-state collection',
    'Global priors and decision support'],GREY,size=25)
f.box(1045,495,530,135,'Fault-aware aggregator (Alg. 2)',[
    'Contribution-weighted federated optimization',
    'Encoder and classifier parameters'],TEAL,size=25)
f.box(1045,685,530,135,'Federated fault memory',[
    'Vector index of verified fault–action cases',
    'Knowledge retrieval and distribution'],AMBER,size=25)

def transfer(y,label,out=True,color=INK,dash=False):
    start,end=(655,1045) if out else (1045,655)
    f.line([(start,y),(end,y)],color,lw=1.7,dash=dash)
    f.text(850,y-19,label,21,color=color)

transfer(160,'Compressed context',color=BLUE)
transfer(225,'Diagnosis / action plan',False,BLUE)
transfer(350,'Resource / network states',color=GREY,dash=True)
transfer(415,'Mode-selection support',False,GREY,True)
transfer(540,'Model updates + statistics',color=TEAL,dash=True)
transfer(605,'Global model parameters',False,TEAL,True)
transfer(730,'Verified fault cases',color=AMBER)
transfer(795,'Knowledge summaries',False,AMBER)

# The edge LLM retrieves knowledge locally; end-side knowledge is a distinct path.
f.line([(1575,752),(1625,752),(1625,185),(1575,185)],AMBER,lw=1.4)
f.text(1690,468,'Memory',20,color=AMBER)
f.text(1690,495,'retrieval',20,color=AMBER)
f.text(1365,879,'SLM / LLM weights remain frozen.',21,color=GREY)

legend=[(95,BLUE,False,'Inference'),(435,GREY,True,'Resource coordination'),(910,TEAL,True,'Federated model exchange'),(1460,AMBER,False,'Fault knowledge')]
for x,c,d,t in legend:
    f.line([(x,961),(x+65,961)],c,lw=1.7,dash=d)
    f.text(x+80,961,t,21,color=INK,anchor='start')
f.text(900,1006,'Shared end-side interfaces represent all three tiers; arrows identify the destination of each exchange.',20,color=GREY)
f.save('figure-1-architecture-en-v2')
