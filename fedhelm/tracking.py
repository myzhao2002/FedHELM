"""Record mutation attempts locally and publish their results to the edge history."""
import os
import uuid
import functools
from contextvars import ContextVar
from .common import request,audit
active_task=ContextVar('operation_task',default=None)

def step(stage,payload=None):
    body={'node':os.getenv('NODE_ID','edge'),'event_id':active_task.get() or str(uuid.uuid4()),
          'stage':stage,'detail':stage,'payload':payload or {}}
    audit('operation',body)
    if os.getenv('EDGE_URL'):
        try: request('POST',os.environ['EDGE_URL'],'/ui/events',body,timeout=2)
        except Exception: pass

def tracked(title):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args,**kwargs):
            task=str(uuid.uuid4())
            token=active_task.set(task)
            def log(stage,payload):
                body={'node':os.getenv('NODE_ID','edge'),'event_id':task,'stage':stage,'detail':title,'payload':payload}
                audit('operation',body)
                if not os.getenv('EDGE_URL'):
                    return
                try:
                    request('POST',os.getenv('EDGE_URL','http://127.0.0.1:8000'),'/ui/events',body,timeout=2)
                except Exception:
                    pass
            log('开始'+title,{})
            try:
                value=fn(*args,**kwargs)
                log('完成'+title,value)
                return value
            except Exception as exc:
                log('失败'+title,{'error':str(getattr(exc,'detail',exc))})
                raise
            finally:
                active_task.reset(token)
        return wrapped
    return decorate
