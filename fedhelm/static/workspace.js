/* Full-page incident workspace and shared navigation. The API remains unchanged for actions. */
let workspaceTaskId=query.get('task'),workspaceDetail=null,workspaceTab=query.get('view')||'overview';
let taskList={items:[],total:0,counts:{}},taskFilter={node:query.get('node')||'',status:query.get('status')||'',kind:query.get('kind')||'fault',search:query.get('search')||'',page:Math.max(1,+query.get('page')||1),size:[10,20,50].includes(+query.get('size'))?+query.get('size'):20};
let workspacePolling=false,workspaceSeq=null;
const stateNames={waiting:'待处理 / 等待后续',failed:'恢复失败',resolved:'已恢复',cancelled:'已终止',recorded:'操作记录'};
const taskLink=id=>'/tasks?task='+encodeURIComponent(id);
const kv=entries=>`<dl class="facts">${entries.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('')}</dl>`;

function operationResultHtml(result,operation){
  const summary=kv([['操作',esc(name(operation))],['执行情况',result.all_succeeded===false?badge('部分节点失败','bad'):badge('请求已完成')],
    ['任务记录',result.task_id?`<a class="text-link" href="${taskLink(result.task_id)}">查看操作时间线 ↗</a>`:'已保存'],
    ['下一步',operation==='train_all'?'进入聚合步骤':operation==='aggregate'?'下发并同步到各端':operation==='sync_all'?'可继续训练或返回监控':'查看结果与日志']]);
  const nodes=result.nodes?table(['节点','结果','返回信息'],Object.entries(result.nodes).map(([n,r])=>[esc(name(n)),badge(r.ok?'完成':'失败',r.ok?'':'bad'),r.ok?esc(r.result?.version!=null?'模型 v'+r.result.version:r.result?.model_version!=null?'模型 v'+r.result.model_version:'服务已返回；完整内容见下方'):esc(r.error)])):'';
  return summary+nodes+`<details><summary>展开完整返回数据</summary>${json(result)}</details>`;
}

async function loadTaskWorkspace(){
  if(workspaceTaskId){workspaceDetail=await api('/ui/task/'+encodeURIComponent(workspaceTaskId));return;}
  const params=new URLSearchParams(Object.entries(taskFilter).filter(([,v])=>v!==''));
  taskList=await api('/ui/tasks?'+params);
}

function taskWorkspacePage(){
  if(workspaceTaskId)return taskDetailPage();
  const count=taskList.counts||{};
  return `<div class="workspace-toolbar"><div><strong>故障与处置</strong><span class="muted">从节点异常到恢复验证，按事件查看</span></div><a class="button-link primary" href="/inject">＋ 创建故障实验</a></div>`+
    `<div class="status-strip">${[['','全部',Object.values(count).reduce((a,b)=>a+b,0)],['waiting','待处理',count.waiting||0],['failed','失败',count.failed||0],['resolved','已恢复',count.resolved||0],['cancelled','已终止',count.cancelled||0]].map(([id,label,value])=>`<button class="${taskFilter.status===id?'selected':''}" data-task-status="${id}">${label}<b>${value}</b></button>`).join('')}</div>`+
    panel('事件列表',`<form id="task-filter-form" class="task-filter"><label>节点<select id="task-node"><option value="">全部节点</option>${[...endNodes(),'edge'].map(n=>`<option value="${n}" ${n===taskFilter.node?'selected':''}>${name(n)}</option>`).join('')}</select></label><label>记录类型<select id="task-kind">${[['fault','故障事件'],['operation','系统操作'],['all','全部记录']].map(([id,t])=>`<option value="${id}" ${id===taskFilter.kind?'selected':''}>${t}</option>`).join('')}</select></label><label class="search-field">搜索<input id="task-search" placeholder="故障、阶段或任务编号" value="${esc(taskFilter.search)}"></label><button type="submit" class="primary">筛选</button><button type="button" id="task-reset">重置</button></form>`+
    table(['故障 / 任务','节点','状态','最近阶段','创建时间','事件数'],taskList.items.map(t=>[
      `<a class="task-title-link" href="${taskLink(t.task)}">${esc(t.root_cause&&t.root_cause!=="healthy"?name(t.root_cause):human(t.title))} <span>↗</span></a><small class="mono">${esc(t.task.slice(0,12))}</small>`,
      `<a href="/node/${t.node}">${esc(name(t.node))}</a>`,badge(stateNames[t.status],t.status==='failed'?'bad':t.status==='resolved'?'':'neutral'),
      esc(t.latest_stage),time(t.started_at),t.event_count]))+
    `<div class="pager"><span>共 ${taskList.total} 条 · 第 ${taskFilter.page} / ${Math.max(1,Math.ceil(taskList.total/taskFilter.size))} 页</span><div class="pager-controls"><label>每页 <select id="task-size">${[10,20,50].map(v=>`<option ${v===taskFilter.size?'selected':''}>${v}</option>`).join('')}</select></label><button data-task-page="${taskFilter.page-1}" ${taskFilter.page<=1?'disabled':''}>上一页</button><button data-task-page="${taskFilter.page+1}" ${taskFilter.page*taskFilter.size>=taskList.total?'disabled':''}>下一页</button></div></div>`);
}

function eventTimeline(steps){return `<div class="event-timeline">${steps.map(s=>`<article class="event-row ${s.stage.includes('失败')?'event-failed':''}"><div class="event-time"><time>${esc(preciseTime(s.time))}</time><span>${esc(name(s.node))}</span></div><span class="event-dot"></span><div class="event-body"><h3>${esc(s.stage)}</h3><p>${esc(human(s.detail))}</p>${Object.keys(s.payload||{}).length?`<details data-seq="${s.seq}"><summary>展开输入、输出与证据</summary>${json(s.payload)}</details>`:''}</div></article>`).join('')}</div>`;}

function taskDetailPage(){
  const d=workspaceDetail;if(!d)return '<div class="empty">正在读取任务…</div>';
  const steps=d.steps,p=d.progress,first=steps[0],result=steps.findLast(s=>s.stage==='处置结果'&&s.payload?.feedback)?.payload;
  const title=human(steps.find(s=>s.stage==='故障注入')?.detail||first?.detail||'任务详情');
  const diag=result?.diagnosis||steps.findLast(s=>s.stage==='轻量诊断')?.payload;
  const decision=result?.policy||steps.findLast(s=>s.stage==='模型选择')?.payload;
  const observations=steps.filter(s=>['采集观测','验证采样'].includes(s.stage)&&typeof s.payload?.latency_ms==='number');
  const tabs=[['overview','处置概览'],['timeline','完整时间线'],['observations','监控证据'],['diagnosis','诊断与调度'],['verification','修复与验证']];
  let body='';
  if(workspaceTab==='overview')body=(p?progressHtml(p):'<p class="hint">系统操作记录，逐步骤结果见完整时间线。</p>')+
    `<div class="detail-columns">${panel('本次处置结果',kv([
      ['最终根因',diag?esc(name(diag.root_cause)):'等待诊断'],['端侧初诊',result?.initial_diagnosis?esc(name(result.initial_diagnosis.root_cause)):'见诊断阶段'],
      ['处置模式',result?esc(name(result.plan.mode)):'等待方案'],['执行动作',result?esc(name(result.plan.action)):'等待执行'],
      ['模型版本',diag?'v'+esc(diag.model_version):'—'],['案例收录',p?.case_stored?badge('已入库'):'暂无入库记录']]))}
      ${panel('最新事件',eventTimeline(steps.slice(-4)),`<button data-detail-tab="timeline">查看全部 ${steps.length} 步 →</button>`)}</div>`;
  if(workspaceTab==='timeline')body=panel('事件时间线',eventTimeline(steps),`<span class="muted">${steps.length} 条记录 · 时间精确到毫秒</span>`);
  if(workspaceTab==='observations')body=panel('本次任务观测',`<p class="panel-body hint">仅展示该任务实际保存的采集与验证样本；连续节点监控可在节点页面查看。</p><div class="panel-body grid">${[['latency_ms','请求时延 · ms',1],['error_rate','错误率 · %',100],['pool_usage','连接池占用 · %',100]].map(([f,t,m])=>`<div><h3>${t}</h3>${chart(observations.map(s=>({time:s.time,payload:s.payload})),f,m)}</div>`).join('')}</div>`+
    table(['阶段','采样时间','HTTP状态','错误率','时延'],observations.map(s=>[esc(s.stage),preciseTime(s.time),esc(s.payload.response_codes?.join(' / ')),(s.payload.error_rate*100).toFixed(1)+'%',s.payload.latency_ms.toFixed(1)+' ms'])));
  if(workspaceTab==='diagnosis')body=panel('初诊与最终诊断',kv([['初诊根因',esc(name(result?.initial_diagnosis?.root_cause||diag?.root_cause||'unknown'))],['最终根因',esc(name(diag?.root_cause||'unknown'))],['诊断来源',esc(diag?.source||'等待诊断')],['最终分值',diag?(diag.confidence*100).toFixed(1)+'%':'—']]))+
    panel('三模式代价与选择',table(['模式','综合代价','预计时延','预计能耗','条件质量','选用'],Object.entries(decision?.costs||{}).map(([mode,v])=>[esc(name(mode)),v.cost.toFixed(4),v.latency_seconds.toFixed(3)+' s',v.estimated_energy_j.toFixed(3)+' J',(v.conditional_quality*100).toFixed(1)+'%',decision.selected===mode?badge('选用'):'—'])))+
    panel('诊断与复核证据',eventTimeline(steps.filter(s=>['轻量诊断','记忆融合','模型选择','最终置信校验','升级复核','语言模型复核','生成方案'].includes(s.stage))));
  if(workspaceTab==='verification')body=panel('恢复验证',result?`<div class="panel-body"><h3>${result.feedback.success?'业务恢复验证通过':'业务尚未恢复'}</h3><p>${esc(result.feedback.criterion)}</p>${result.feedback.success&&!p?.case_stored?`<button data-review-task="${esc(workspaceTaskId)}" data-review-root="${esc(result.diagnosis.root_cause)}">人工确认根因并收录案例</button>`:p?.case_stored?badge('成功案例已入库'):''}</div>`:'<div class="empty">尚无恢复验证结果</div>')+
    panel('执行与验证记录',eventTimeline(steps.filter(s=>['执行修复','修复动作返回','验证采样','恢复验证','恢复失败','处置结果','案例入库','操作失败'].includes(s.stage))));
  return `<div class="task-workspace"><a class="back-link" href="/tasks">← 返回任务列表</a><div class="incident-heading"><div><div class="eyebrow">事件详情 · ${esc(name(first?.node))}</div><h2>${esc(title)}</h2><div class="mono muted">${esc(workspaceTaskId)}</div></div><div class="row-actions">${first?`<a class="button-link" href="/node/${first.node}">查看节点</a>`:''}<a class="button-link" href="/inject">新建实验</a></div></div><div class="incident-meta">${badge(p?.status||steps.at(-1)?.stage||'等待记录',p?.status.includes('失败')?'bad':'')}<span>开始 ${esc(time(first?.time))}</span><span>耗时 ${duration(p?.duration_seconds)}</span><span class="poll-label">● 每2秒读取事件</span></div><div class="tabs detail-tabs">${tabs.map(([id,t])=>`<button data-detail-tab="${id}" class="${workspaceTab===id?'selected':''}">${t}</button>`).join('')}</div><div id="task-detail-panel">${body}</div></div>`;
}

const coverage=[
  ['模型规模','部分实现','六层Transformer，32维、77,542参数、六分类','论文为384维、22.6M参数及十类故障','/models'],
  ['输入表征','部分实现','12项数值×20点；日志与业务span留存','未做日志文本与调用链联合编码','/telemetry'],
  ['算法1','机制已实现','可行模式、加权代价、EWMA、最终置信校验','能耗估计、带宽先验、质量为恢复反馈代理','/algorithms'],
  ['算法2','机制已实现','D/Q/S贡献度、探针、方向EWMA、冷启动、压缩聚合','自定义HTTP，未接Flower；由按钮发起训练','/algorithms'],
  ['语言模型与动作','API已接入','Local/Edge兼容API、分角色提示词与调用限额','未加载本地SLM/LLM；单动作白名单，未做多动作排序','/settings'],
  ['联邦故障记忆','部分实现','成功反馈准入、余弦检索、0.65/0.35融合、摘要同步','SQLite检索；上传仍含完整反馈样本，未改为紧凑知识条目与每轮20条批量协议','/memory'],
  ['部署与真实注入','部分实现','16端独立进程（A5/B6/C5）、五类真实业务故障','K8s未部署验证；另五类故障尚未实现','/inject'],
  ['恢复与实验','仿真配置','持续HTTP验证，支持3秒/300秒窗口','节点数已对齐；未开展100轮、消融与统计复现实验','/algorithms']
];
function paperPage(){return `<div class="review-banner"><div><span class="eyebrow">论文对照 · §3–6</span><h2>关键机制已接入，仍有配置与实现差异</h2><p>下面区分实际实现、接口仿真和未完成项。流程演示通过不等于论文实验结果复现。</p></div><a class="button-link" href="/algorithms">查看算法运行 →</a></div>`+panel('逐项核对',table(['模块','当前状态','系统实现','与论文的差异','查看'],coverage.map(([a,b,c,d,url])=>[`<strong>${a}</strong>`,badge(b,b==='机制已实现'?'':'neutral'),c,d,`<a class="text-link" href="${url}">进入模块 ↗</a>`])))+panel('界面参考',`<div class="panel-body"><p>本次重构借鉴事件管理平台的独立详情页、告警状态筛选，以及按节点组织的工作空间。</p><div class="row-actions"><a class="text-link" href="https://support.pagerduty.com/main/docs/incidents" target="_blank" rel="noreferrer">PagerDuty · 事件时间线 ↗</a><a class="text-link" href="https://grafana.com/docs/grafana/latest/alerting/monitor-status/view-alert-state-history/" target="_blank" rel="noreferrer">Grafana · 告警状态历史 ↗</a><a class="text-link" href="https://headlamp.dev/docs/latest/learn/local-cluster/" target="_blank" rel="noreferrer">Headlamp · 节点与工作负载 ↗</a></div></div>`);}

openTask=async function(id){location.assign(taskLink(id));};
$('quick').textContent='训练工作台';$('quick').onclick=()=>location.assign('/lab');
if(key==='/topology')document.body.classList.add('topology-screen');
if(key==='/settings'){$('title').textContent='模型API配置';$('crumb').textContent='模型API配置';$('description').textContent='接口地址、模型名称与后端密钥；留空时不调用模型';}
if(key==='/paper'){$('eyebrow').textContent='PAPER REVIEW';$('title').textContent='论文对照';$('crumb').textContent='论文对照';$('description').textContent='实现范围、算法对应与尚未完成项';}
if(key==='/tasks'&&workspaceTaskId){$('title').textContent='故障任务';$('description').textContent='查看诊断、调度和修复的完整证据';document.body.classList.add('incident-page');}

async function updateTaskList(){const params=new URLSearchParams(Object.entries(taskFilter).filter(([,v])=>v!==''));window.history.replaceState(null,'','/tasks?'+params);await loadTaskWorkspace();render();}
document.addEventListener('submit',async e=>{if(e.target.id!=='task-filter-form')return;e.preventDefault();taskFilter.node=$('task-node').value;taskFilter.kind=$('task-kind').value;taskFilter.search=$('task-search').value;taskFilter.page=1;try{await updateTaskList()}catch(err){toast(err.message)}});
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try{
  if(b.dataset.detailTab){workspaceTab=b.dataset.detailTab;const url=new URL(location.href);url.searchParams.set('view',workspaceTab);window.history.replaceState(null,'',url);$('content').innerHTML=taskDetailPage();}
  else if(b.hasAttribute('data-task-status')){taskFilter.status=b.dataset.taskStatus;taskFilter.page=1;await updateTaskList();}
  else if(b.dataset.taskPage){taskFilter.page=+b.dataset.taskPage;await updateTaskList();}
  else if(b.id==='task-reset'){taskFilter={node:'',status:'',kind:'fault',search:'',page:1,size:20};await updateTaskList();}
}catch(err){toast(err.message)}});
document.addEventListener('change',async e=>{if(e.target.id==='task-size'){taskFilter.size=+e.target.value;taskFilter.page=1;try{await updateTaskList()}catch(err){toast(err.message)}}});

setInterval(async()=>{
  if(key!=='/tasks'||!workspaceTaskId||workspacePolling||$('drawer').open||document.activeElement?.matches('input,select'))return;
  workspacePolling=true;
  try{
    const next=await api('/ui/task/'+encodeURIComponent(workspaceTaskId));const seq=next.steps.at(-1)?.seq;
    if(seq!==workspaceSeq){workspaceSeq=seq;workspaceDetail=next;const expanded=[...document.querySelectorAll('#content details[open]')].map(d=>d.dataset.seq);const y=window.scrollY;
      $('content').innerHTML=taskDetailPage();document.querySelectorAll('#content details').forEach(d=>{d.open=expanded.includes(d.dataset.seq)});window.scrollTo(0,y);}
  }catch(err){$('alert').textContent='事件刷新失败：'+err.message+'；保留上次记录';}finally{workspacePolling=false;}
},2000);

refresh();
setInterval(()=>refresh(),10000);
