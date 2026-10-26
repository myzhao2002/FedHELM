from pathlib import Path
from html import escape
import math
from PIL import Image, ImageDraw, ImageFont

OUT=Path(__file__).parent
INK='#26333b'; GREY='#657079'; BLUE='#345775'; TEAL='#426c63'; AMBER='#806341'
class Figure:
    def __init__(self,w,h):
        self.w=w;self.h=h;self.scale=2
        self.im=Image.new('RGB',(w*2,h*2),'white');self.d=ImageDraw.Draw(self.im)
        self.svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="white"/>']
    def text(self,x,y,s,size=23,bold=False,color=INK,anchor='middle'):
        font=ImageFont.truetype('C:/Windows/Fonts/'+('timesbd.ttf' if bold else 'times.ttf'),size*2)
        self.d.text((x*2,y*2),s,font=font,fill=color,anchor={'middle':'mm','start':'lm','end':'rm'}[anchor])
        self.svg.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" dominant-baseline="central" font-family="Times New Roman, Times, serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(s)}</text>')
    def rect(self,x,y,w,h,fill='white',stroke=INK,lw=1.5):
        self.d.rectangle((x*2,y*2,(x+w)*2,(y+h)*2),fill=fill,outline=stroke,width=max(1,round(lw*2)))
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{lw}"/>')
    def line(self,points,color=INK,lw=1.6,arrow=True,dash=False):
        pp=[(x*2,y*2) for x,y in points]
        if dash:
            for (x,y),(xx,yy) in zip(pp,pp[1:]):
                length=math.hypot(xx-x,yy-y)
                for k in range(0,int(length),16):
                    a=k/length;b=min(k+9,length)/length
                    self.d.line((x+(xx-x)*a,y+(yy-y)*a,x+(xx-x)*b,y+(yy-y)*b),fill=color,width=round(lw*2))
        else:self.d.line(pp,fill=color,width=round(lw*2))
        self.svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{lw}"'+(' stroke-dasharray="8 5"' if dash else '')+'/>')
        if arrow:
            x,y=points[-1];a,b=points[-2];angle=math.atan2(y-b,x-a)
            p=[(x,y),(x-10*math.cos(angle)+4*math.sin(angle),y-10*math.sin(angle)-4*math.cos(angle)),(x-10*math.cos(angle)-4*math.sin(angle),y-10*math.sin(angle)+4*math.cos(angle))]
            self.d.polygon([(x*2,y*2) for x,y in p],fill=color)
            self.svg.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in p)}" fill="{color}"/>')
    def box(self,x,y,w,h,title,lines=(),color=INK,fill='white',size=23):
        self.rect(x,y,w,h,fill,color)
        total=1+len(lines); gap=min(30,(h-30)/max(1,total-1)); start=y+h/2-(total-1)*gap/2
        while any(ImageFont.truetype('C:/Windows/Fonts/timesbd.ttf',size*2).getlength(t)>2*(w-20) for t in [title,*lines]) and size>16:size-=1
        self.text(x+w/2,start,title,size,True,color)
        for i,t in enumerate(lines):self.text(x+w/2,start+(i+1)*gap,t,size-1,color=color)
    def save(self,name):
        (OUT/(name+'.svg')).write_text('\n'.join(self.svg+['</svg>']),encoding='utf-8')
        self.im.save(OUT/(name+'.png'))

f=Figure(1600,1000)
f.text(40,32,'FedHELM: edge–end architecture',30,True,anchor='start')
f.rect(35,75,1530,280,fill='#f9fafb',stroke=GREY)
f.text(60,108,'EDGE NODE',24,True,anchor='start')
xs=[60,445,830,1215]; titles=['Edge LLM','Fault-aware aggregator','Federated fault memory','Resource controller']
details=[['7B instruction model / vLLM','Diagnosis and action planning','Frozen language-model weights'],['Algorithm 2','Contribution-weighted aggregation','Global encoder and classifier'],['Verified fault–action cases','Vector indexing and retrieval','Shared knowledge summaries'],['Compute, memory and network','State collection and global priors','Support for mode selection']]
for x,t,ls,c in zip(xs,titles,details,[BLUE,TEAL,AMBER,GREY]):f.box(x,145,325,160,t,ls,c)
for x,t in zip(xs,['Inference collaboration','Model collaboration','Knowledge collaboration','Resource coordination']):f.text(x+162,332,t,21,color=GREY)
labels=[('Compressed context;','candidate diagnoses','Root cause;','action plan'),('Quantized / sparse updates;','label and quality statistics','Global encoder','and classifier'),('Verified structured','fault–action cases','Memory summaries;','retrieval results'),('Node resource','and network states','Global priors;','decision support')]
for x,lab,c in zip(xs,labels,[BLUE,TEAL,AMBER,GREY]):
    f.line([(x+30,548),(x+30,355)],c,dash=c==GREY)
    f.line([(x+295,355),(x+295,548)],c,dash=c==GREY)
    f.text(x+160,397,lab[0],21,color=c);f.text(x+160,423,lab[1],21,color=c)
    f.text(x+160,476,lab[2],21,color=c);f.text(x+160,502,lab[3],21,color=c)
f.rect(35,550,1530,380,stroke=GREY)
f.text(60,578,'HETEROGENEOUS END NODES',24,True,anchor='start')
f.line([(70,610),(1530,610)],GREY,arrow=False)
for x,t,extra in [(60,'Tier A: 5 nodes (high resource)','Local SLM: 1.5B / 4-bit (frozen)'),(570,'Tier B: 6 nodes (medium resource)','Available modes: Lightweight / Edge'),(1080,'Tier C: 5 nodes (low resource)','Available modes: Lightweight / Edge')]:
    f.line([(x+230,610),(x+230,640)],GREY)
    f.rect(x,640,460,260)
    f.text(x+230,670,t,25,True)
    f.line([(x,696),(x+460,696)],GREY,arrow=False,lw=1)
    f.text(x+230,726,'Services and local observations',23)
    f.text(x+230,767,'Fault encoder + classifier (trainable)',23,True,TEAL)
    f.text(x+230,808,extra,22,color=BLUE)
    f.text(x+230,849,'Mode selection · Local training',22)
    f.text(x+230,880,'Action execution · Feedback validation',22)
f.text(800,967,'Raw observations remain local. Only the encoder and classifier participate in federated optimization.',23)
f.save('figure-1-architecture-en-v1')

g=Figure(1800,1050)
g.text(35,30,'FedHELM: adaptive diagnosis and feedback-driven learning',30,True,anchor='start')
g.text(35,102,'ONLINE DIAGNOSIS AND REMEDIATION',23,True,anchor='start')
g.box(30,260,165,110,'Observations',['Logs / metrics','Traces / alerts','Context'],size=20)
g.box(230,260,155,110,'Local encoding',['Event preparation','Fault representation'],size=20)
g.line([(195,315),(230,315)])
g.rect(420,145,690,325,fill='#f9fafb',stroke=BLUE)
g.text(445,178,'Algorithm 1: resource-aware adaptive inference',24,True,BLUE,anchor='start')
g.text(765,202,'Resource state · EWMA statistics · Retrieved fault memory',19,color=GREY)
g.box(445,265,165,105,'Mode selection',['Feasibility filter','Cost minimization'],BLUE,size=20)
g.line([(385,315),(445,315)],BLUE)
for yy,t,sub in [(244,'Lightweight','Classifier + memory'),(319,'Local','SLM (Tier A only)'),(394,'Edge','Edge LLM')]:
    g.box(650,yy-29,195,58,t,[sub],BLUE,size=20)
    g.line([(610,315),(630,315),(630,yy),(650,yy)],BLUE)
    g.line([(845,yy),(863,yy),(863,315),(887,315)],BLUE)
g.box(887,270,196,90,'Result validation',['Confidence threshold','Memory consistency'],BLUE,size=20)
g.line([(990,360),(990,439),(748,439),(748,423)],BLUE)
g.text(857,454,'Low confidence / conflict: Edge review',19,color=BLUE)
g.box(1140,260,180,110,'Constrained plan',['Action ranking','Execution parameters'],size=21)
g.box(1360,260,160,110,'End-side execution',['Allowed actions'],size=21)
g.box(1560,260,205,110,'Recovery validation',['SLO within 5 min','No manual intervention'],size=21)
g.line([(1083,315),(1140,315)]);g.line([(1320,315),(1360,315)]);g.line([(1520,315),(1560,315)])
g.line([(1670,260),(1670,70),(528,70),(528,145)],GREY,dash=True)
g.text(1150,55,'Update mode statistics (EWMA)',21,color=GREY)

g.text(1130,505,'VERIFIED FAULT MEMORY',22,True,AMBER,anchor='start')
g.box(1470,540,295,90,'Structured experience',['Verified root cause and action'],AMBER,size=22)
g.box(1130,540,260,90,'Federated fault memory',['Vector index and summaries'],AMBER,size=22)
g.line([(1660,370),(1660,540)],AMBER)
g.text(1670,502,'Success',20,color=AMBER,anchor='start')
g.line([(1470,585),(1390,585)],AMBER)
g.line([(1130,585),(1095,585),(1095,230),(1020,230)],AMBER)
g.text(1000,565,'Retrieve for',20,color=AMBER);g.text(1000,592,'subsequent diagnosis',20,color=AMBER)

g.rect(35,710,1410,200,fill='#fafbf9',stroke=TEAL)
g.text(60,739,'FEDERATED MODEL UPDATE (ROUND-BASED)',23,True,TEAL,anchor='start')
for x,w,t,ls in [(60,200,'Local data + feedback',['Labeled local events']),(310,205,'Local training',['Encoder + classifier','2 local epochs']),(565,205,'Update compression',['Top-50% sparsity','8-bit quantization']),(820,290,'Algorithm 2: aggregation',['Diversity / quality / stability','Contribution-based weights']),(1160,260,'Model distribution',['Updated global parameters'])]:g.box(x,775,w,100,t,ls,TEAL,size=21)
for a,b in [(260,310),(515,565),(770,820),(1110,1160)]:g.line([(a,825),(b,825)],TEAL)
g.line([(1765,315),(1784,315),(1784,672),(45,672),(45,825),(60,825)],GREY,dash=True)
g.text(430,655,'Retain validation feedback for local learning',21,color=GREY)
g.line([(1290,875),(1290,962),(15,962),(15,415),(307,415),(307,370)],TEAL)
g.text(820,943,'Update the end-side fault encoder and classifier',23,color=TEAL)
g.text(1620,780,'LLM / SLM weights',22,True,BLUE);g.text(1620,813,'remain frozen',22,color=BLUE)
g.text(900,1014,'Online remediation and federated rounds operate on separate schedules; only verified successful experience enters shared memory.',22)
g.save('figure-2-workflow-en-v1')
