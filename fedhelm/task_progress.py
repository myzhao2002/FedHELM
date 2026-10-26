"""Milestone progress from durable events, never elapsed-time animation."""
from datetime import datetime


def elapsed(a, b):
    return max(0, round((datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds(), 3)) if a and b else None


def progress(steps):
    fault = any(s['stage'] in ('故障注入','检测异常','采集观测','轻量诊断','处置结果') for s in steps)
    if not fault:
        return None
    definitions = [('故障出现',['故障注入','检测异常']),('观测采集',['采集观测']),
                   ('端侧诊断',['轻量诊断']),('选择模型',['模型选择']),('处置方案',['生成方案']),
                   ('执行修复',['修复动作返回']),('恢复验证',['恢复验证','处置结果'])]
    result = next((s for s in reversed(steps) if s['stage']=='处置结果'),None)
    failures = [s for s in steps if s['stage'] in ('操作失败','恢复失败') or
                (s['stage']=='恢复验证' and (s.get('payload',{}).get('success') is False or '未通过' in s['detail']))]
    last_failure = failures[-1] if failures else None
    success = bool(result and result.get('payload',{}).get('feedback',{}).get('success'))
    failed = bool(last_failure and (not result or last_failure['seq']>result['seq'])) or bool(result and not success)
    if last_failure and any(s['seq']>max(last_failure['seq'],result['seq'] if result else 0) and s['stage']=='检测异常' for s in steps):
        failed=False  # Scheduler has started another attempt.
        success=False
    phases=[]
    for title,stages in definitions:
        records=[s for s in steps if s['stage'] in stages]
        # Legacy runs did not record executor return; show this limitation explicitly.
        inferred=False
        if title=='执行修复' and not records:
            records=[s for s in steps if s['stage']=='恢复验证']
            inferred=bool(records)
        done=bool(records)
        if title=='执行修复' and records and records[-1].get('payload',{}).get('applied') is False:
            done=False
        if title=='恢复验证':
            done=success
        phases.append({'title':title,'state':'done' if done else 'pending',
                       'time':records[0 if title=='故障出现' else -1]['time'] if records else None,'inferred':inferred})
    # Older/manual tasks can omit an earlier stage. Missing evidence is not a failed action.
    for index,phase in enumerate(phases):
        if phase['state']=='pending' and phase['time'] is None and any(p['time'] for p in phases[index+1:]):
            phase['state']='unrecorded'
    current=next((p for p in phases if p['state']=='pending'),None)
    if current:
        current['state']='failed' if failed else 'waiting'
    cancelled=next((s for s in reversed(steps) if s['stage'] in ('人工终止','被新实验替代')),None)
    if cancelled and current:
        current['state']='cancelled'
    finished = cancelled['time'] if cancelled else result['time'] if result else last_failure['time'] if failed and last_failure else None
    started=steps[0]['time'] if steps else None
    return {'phases':phases,'completed':sum(p['state']=='done' for p in phases),'total':len(phases),
            'status':cancelled['stage'] if cancelled else '失败 / 等待重试或人工检查' if failed else '恢复验证通过' if success else '等待后续事件',
            'started_at':started,'finished_at':finished,'duration_seconds':elapsed(started,finished),
            'last_event_at':steps[-1]['time'] if steps else None,
            'case_stored':any(s['stage']=='案例入库' for s in steps),
            'note':'进度为已记录里程碑数；等待不代表后台仍在运行。耗时包含巡检等待，仅为测试床短时HTTP验证。'}
