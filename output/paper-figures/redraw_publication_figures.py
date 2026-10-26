"""Regenerate publication-style FedHELM Figs. 1–2 as editable SVG and PNG."""
from pathlib import Path
from html import escape
import math
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
S = 2
INK = '#202a33'
MID = '#66737d'
RULE = '#aeb8c0'
BLUE = '#315b7d'
BLUE_BG = '#eef3f7'
TEAL = '#397367'
TEAL_BG = '#edf4f1'
GOLD = '#8b6b3e'
GOLD_BG = '#f6f2e9'
PALE = '#f5f7f8'
WHITE = '#ffffff'
FONT = 'C:/Windows/Fonts/times.ttf'
FONT_B = 'C:/Windows/Fonts/timesbd.ttf'


class Canvas:
    def __init__(self, w, h, stem):
        self.w, self.h, self.stem = w, h, stem
        self.im = Image.new('RGB', (w*S, h*S), WHITE)
        self.d = ImageDraw.Draw(self.im)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                    '<rect width="100%" height="100%" fill="#ffffff"/>',
                    '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="context-stroke"/></marker></defs>']

    def box(self, x, y, w, h, fill=WHITE, stroke=RULE, lw=1.5, dash=None):
        self.d.rectangle((x*S, y*S, (x+w)*S, (y+h)*S), fill=fill, outline=stroke, width=max(1, round(lw*S)))
        ds = f' stroke-dasharray="{dash}"' if dash else ''
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{lw}"{ds}/>')

    def line(self, pts, color=INK, lw=1.6, arrow=True, dash=None):
        p = [(int(x*S), int(y*S)) for x, y in pts]
        if dash:
            for (x1, y1), (x2, y2) in zip(p, p[1:]):
                dx, dy = x2-x1, y2-y1
                n = max(1, int(math.hypot(dx, dy)/(10*S)))
                for i in range(n):
                    if i % 2 == 0:
                        a, b = i/n, min(i+1, n)/n
                        self.d.line((x1+dx*a, y1+dy*a, x1+dx*b, y1+dy*b), fill=color, width=max(1, round(lw*S)))
        else:
            self.d.line(p, fill=color, width=max(1, round(lw*S)), joint='curve')
        coords = ' '.join(f'{x},{y}' for x, y in pts)
        ds = f' stroke-dasharray="{dash}"' if dash else ''
        mark = ' marker-end="url(#arrow)"' if arrow else ''
        self.svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{lw}"{ds}{mark}/>')
        if arrow:
            x2, y2 = pts[-1]; x1, y1 = pts[-2]
            a = math.atan2(y2-y1, x2-x1); L, W = 9, 4
            tri = [(x2,y2),(x2-L*math.cos(a)+W*math.sin(a),y2-L*math.sin(a)-W*math.cos(a)),
                   (x2-L*math.cos(a)-W*math.sin(a),y2-L*math.sin(a)+W*math.cos(a))]
            self.d.polygon([(int(x*S),int(y*S)) for x,y in tri], fill=color)

    def text(self, x, y, text, size=22, color=INK, bold=False, anchor='middle'):
        font = ImageFont.truetype(FONT_B if bold else FONT, size*S)
        anchor_map = {'middle':'mm', 'start':'lm', 'end':'rm'}
        self.d.text((x*S, y*S), text, font=font, fill=color, anchor=anchor_map[anchor])
        self.svg.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" dominant-baseline="central" font-family="Times New Roman, Times, serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(text)}</text>')

    def label(self, x, y, lines, size=19, color=INK, bold=False, gap=None, anchor='middle'):
        gap = gap or size+7
        first = y - (len(lines)-1)*gap/2
        for i, t in enumerate(lines): self.text(x, first+i*gap, t, size, color, bold, anchor)

    def titled_box(self, x, y, w, h, title, detail, accent=INK, fill=WHITE, title_size=23, body_size=19):
        self.box(x,y,w,h,fill,accent,1.5)
        self.text(x+w/2,y+32,title,title_size,accent,True)
        self.line([(x+14,y+57),(x+w-14,y+57)],RULE,.8,False)
        self.label(x+w/2,y+57+(h-57)/2+2,detail,body_size,INK,False,body_size+8)

    def save(self):
        self.svg.append('</svg>')
        (OUT/(self.stem+'.svg')).write_text('\n'.join(self.svg), encoding='utf-8')
        self.im.save(OUT/(self.stem+'.png'))


def architecture():
    c=Canvas(2000,1030,'figure-1-fedhelm-architecture-v2')
    # The communication channel is left open; draw routes before the panels.
    # End-to-edge request/response and coordination channels.
    routes=[
        ([(850,202),(1140,202)],BLUE,['Resource / network state'],995,185,'right'),
        ([(1140,244),(850,244)],BLUE,['Routing priors / support'],995,263,'left'),
        ([(850,352),(1140,352)],BLUE,['Compressed fault context'],995,335,'right'),
        ([(1140,397),(850,397)],BLUE,['Diagnosis and action plan'],995,418,'left'),
        ([(850,546),(1140,546)],TEAL,['Model update + label stats'],995,529,'right'),
        ([(1140,586),(850,586)],TEAL,['Global encoder parameters'],995,605,'left'),
        ([(850,725),(1140,725)],GOLD,['Verified fault cases'],995,708,'right'),
        ([(1140,765),(850,765)],GOLD,['Memory summary'],995,785,'left'),
    ]
    for pts,col,lab,lx,ly,direction in routes:
        c.line(pts,col,1.8,True)
        c.text(lx,ly,lab[0],15,col,False)
    # System boundary headings.
    c.box(35,72,850,880,WHITE,RULE,1.4)
    c.box(1100,72,865,880,WHITE,RULE,1.4)
    c.text(65,105,'Heterogeneous end nodes',29,INK,True,'start')
    c.text(1130,105,'Edge node (GPU)',29,INK,True,'start')
    # Tiers.
    c.titled_box(70,135,780,130,'Tier A  |  strong  |  5 nodes',
        ['Fault encoder + classifier  ·  Local training','Quantized SLM: 1.5B parameters, 4-bit'],BLUE,BLUE_BG,23,19)
    c.titled_box(70,285,780,112,'Tier B  |  medium  |  6 nodes',
        ['Fault encoder + classifier  ·  Local training'],BLUE,WHITE,23,19)
    c.titled_box(70,417,780,112,'Tier C  |  weak  |  5 nodes',
        ['Fault encoder + classifier  ·  Local training'],BLUE,WHITE,23,19)
    # Algorithm 1 belongs to event-level mode selection at the end node.
    c.titled_box(70,552,780,116,'Algorithm 1  |  resource-aware adaptive inference',
        ['Feasible modes · latency / energy / traffic · event difficulty','Select Lightweight, Local (Tier A), or Edge'],BLUE,BLUE_BG,22,18)
    c.box(70,693,780,205,PALE,RULE,1.1)
    c.text(94,724,'End-side functions',22,INK,True,'start')
    for x,y,t in [(105,770,'Fault sensing'),(465,770,'Lightweight diagnosis'),
                  (105,824,'Remediation execution'),(465,824,'SLO feedback validation')]:
        c.box(x,y-18,330,40,WHITE,RULE,1)
        c.text(x+165,y,t,19,INK,False)
    c.text(460,876,'Raw logs, metrics, and traces stay at the end nodes.',17,MID,False)
    # Four edge components.
    c.titled_box(1140,145,785,128,'Resource controller',
        ['Collect compute, memory, bandwidth, latency','Maintain global priors and assist mode routing'],MID,PALE,23,19)
    c.titled_box(1140,302,785,145,'Edge LLM service',
        ['Qwen2.5-7B instruction model served by vLLM','Memory-augmented root-cause review and action planning'],BLUE,BLUE_BG,24,20)
    c.titled_box(1140,478,785,132,'Fault-aware aggregator  |  Algorithm 2',
        ['Contribution-weighted aggregation of encoder + classifier','Diversity · validation quality · update stability'],TEAL,TEAL_BG,22,19)
    c.titled_box(1140,640,785,145,'Federated fault memory',
        ['Validated fault–action entries · vector index','Cross-node retrieval and compact knowledge summaries'],GOLD,GOLD_BG,23,19)
    # Edge-internal data dependencies.
    c.line([(1925,710),(1945,710),(1945,374),(1925,374)],GOLD,1.7,True)
    c.text(1900,620,'Retrieval',15,GOLD)
    # Footer and key.
    c.text(1135,835,'Only the fault encoder and classifier are federated; SLM / LLM weights stay frozen.',18,MID,False,'start')
    c.line([(80,982),(145,982)],BLUE,2,True); c.text(160,982,'Inference and resource coordination',18,INK,False,'start')
    c.line([(570,982),(635,982)],TEAL,2,True); c.text(650,982,'Federated model exchange',18,INK,False,'start')
    c.line([(1110,982),(1175,982)],GOLD,2,True); c.text(1190,982,'Validated fault knowledge',18,INK,False,'start')
    c.save()


def workflow():
    c=Canvas(2000,1120,'figure-2-fedhelm-workflow-v2')
    c.text(50,52,'Per-event diagnosis and remediation',25,INK,True,'start')
    # Workflow routes first, so they remain behind the nodes.
    c.line([(315,250),(365,250)],INK,1.8,True)
    c.line([(635,250),(690,250)],BLUE,1.8,True)
    c.line([(1110,250),(1160,250)],BLUE,1.8,True)
    c.line([(1465,250),(1515,250)],INK,1.8,True)
    c.line([(1725,250),(1770,250)],INK,1.8,True)
    # Feedback branches.
    c.line([(1880,335),(1880,440),(1730,440),(1730,508)],TEAL,1.8,True)
    c.text(1800,424,'Recovered',17,TEAL)
    # Retrieval loop back to inference modes.
    c.line([(1390,555),(1280,555),(1280,382),(900,382),(900,370)],GOLD,1.7,True)
    c.text(1170,430,'Retrieved validated cases',17,GOLD)
    # Fault feedback and local training lane.
    c.text(50,630,'Round-based federated learning (runs independently of individual incidents)',25,INK,True,'start')
    xs=[55,425,795,1165,1535]
    widths=[320]*5
    titles=['Local data + feedback','Local model training','Update compression','Algorithm 2 aggregation','Global model distribution']
    bodies=[['Node-local labeled events','No raw telemetry upload'],
            ['Fault encoder + classifier','2 local epochs'],
            ['Magnitude Top-50% sparsity','INT8 block quantization'],
            ['Diversity · quality · stability','Contribution-weighted update'],
            ['Updated encoder + classifier','Synchronize to end nodes']]
    for i,(x,w,t,b) in enumerate(zip(xs,widths,titles,bodies)):
        accent=TEAL
        c.titled_box(x,704,w,146,t,b,accent,TEAL_BG if i==3 else WHITE,21,18)
        if i<4: c.line([(x+w,777),(xs[i+1],777)],TEAL,1.8,True)
    # Feedback to local training and distribution back to nodes.
    c.line([(1880,335),(1935,335),(1935,682),(215,682),(215,704)],TEAL,1.7,True,'10 7')
    c.text(990,661,'Outcome labels feed later local training rounds',17,TEAL)
    c.line([(1695,850),(1695,904),(165,904),(165,896)],TEAL,1.7,True,'10 7')
    c.text(950,890,'Distribute only ω = (encoder, classifier); language-model weights remain frozen',18,TEAL)
    # Stage boxes.
    c.titled_box(55,165,260,170,'Fault sensing',
        ['Logs · metrics · traces','Alerts + local context','Structured fault event'],INK,WHITE,23,19)
    c.titled_box(365,165,270,170,'Local representation',
        ['Fault encoder + classifier','Candidate roots + confidence','Resource / EWMA state'],BLUE,BLUE_BG,22,18)
    # Three inference modes.
    c.box(690,120,420,285,WHITE,BLUE,1.5)
    c.text(900,150,'Algorithm 1  |  mode selection',22,BLUE,True)
    c.text(900,179,'Minimize event-level cost over feasible modes',17,MID)
    for x,t,b in [(710,'Lightweight','All tiers'),(840,'Local','Tier A only'),(970,'Edge','7B + memory')]:
        c.titled_box(x,212,120,112,t,[b],BLUE,BLUE_BG if t=='Edge' else WHITE,18,16)
    c.text(900,365,'Low confidence or memory conflict → Edge review',17,BLUE)
    c.titled_box(1160,165,305,170,'Constrained remediation',
        ['Rank actions in the allowed set','Generate execution parameters','Execute at the end node'],INK,WHITE,21,18)
    c.titled_box(1515,165,210,170,'Feedback validation',
        ['Observe recovery','Within 5 min?','No human intervention?'],TEAL,TEAL_BG,20,17)
    c.titled_box(1770,165,190,170,'Outcome',
        ['Success / failure','Update mode EWMA'],MID,PALE,20,17)
    # Verified case memory is separate from parameter aggregation.
    c.titled_box(1390,508,520,102,'Federated fault memory',
        ['Store verified cases · vector retrieval · share summaries'],GOLD,GOLD_BG,22,18)
    c.text(1650,960,'Online diagnosis, memory updates, and federated rounds have separate triggers.',18,MID)
    # Legend.
    c.line([(70,1040),(135,1040)],INK,1.8,True); c.text(150,1040,'Per-event control flow',17,INK,False,'start')
    c.line([(500,1040),(565,1040)],TEAL,1.8,True,'10 7'); c.text(580,1040,'Training / feedback exchange',17,INK,False,'start')
    c.line([(1040,1040),(1105,1040)],GOLD,1.8,True); c.text(1120,1040,'Verified knowledge',17,INK,False,'start')
    c.save()


if __name__ == '__main__':
    architecture()
    workflow()
    print('Wrote publication figures in', OUT)
