import unittest
import tempfile
import os
from unittest.mock import patch
from fedhelm import scheduler as s, dashboard as d

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name})
        self.env.start()
        s.enabled=True
        s.stopping.clear()
        for n in 'abc': s.reset(n)
        s.events.clear()

    def test_healthy_never_runs_or_trains(self):
        with patch.object(d,'request',return_value={'healthy':True,'error_rate':0}) as req:
            s.tick()
        self.assertEqual(req.call_count,3)
        self.assertTrue(all(c.args[0]=='GET' for c in req.call_args_list))

    def test_pause_and_manual_operation_exclude_scheduler(self):
        with patch.object(d,'request') as req:
            s.enabled=False
            s.tick()
            s.enabled=True
            with d.control_lock: s.tick()
        req.assert_not_called()

    def test_paused_sampling_only_observes(self):
        s.enabled=False
        with patch.object(d,'request',return_value={'healthy':False,'error_rate':1}) as req:
            s.sample_only()
        self.assertEqual(req.call_count,3)
        self.assertTrue(all(c.args[0]=='GET' for c in req.call_args_list))

    def test_failures_have_cooldown_and_attempt_limit(self):
        def upstream(method,base,path,*args,**kwargs):
            if path.startswith('/observe'): return {'healthy':False,'error_rate':1}
            raise RuntimeError('adapter offline')
        with patch.object(d,'request',side_effect=upstream) as req:
            s.tick()
            self.assertEqual(s.nodes['a']['attempts'],1)
            s.tick()
            self.assertEqual(s.nodes['a']['attempts'],1)
            for n in 'abc': s.nodes[n]['next_retry']=0
            s.tick()
            self.assertEqual(s.nodes['a']['attempts'],2)
            for n in 'abc': s.nodes[n]['next_retry']=0
            s.tick()
            self.assertEqual(s.nodes['a']['attempts'],2)
            self.assertEqual(s.nodes['a']['state'],'等待人工检查')
        self.assertFalse(any(c.args[2] in ('/train','/collect','/inject') for c in req.call_args_list))

    def test_events_bounded(self):
        for i in range(510): s.emit('a',str(i),'检测',str(i))
        self.assertEqual(len(s.snapshot()['events']),500)

    def test_paper_retry_escalates_without_exposing_injection_label(self):
        calls=[]
        d.truth['a']='thread_pool_exhausted'
        def upstream(method,base,path,*args,**kwargs):
            if path=='/telemetry':
                return {'latest':{'healthy':False,'error_rate':1},'anomaly':{'anomalous':True,'reasons':['HTTP请求失败']}}
            if path=='/sync':return {}
            if path=='/run':
                calls.append(args[0])
                return {'feedback':{'success':False},'observation':{'event_id':args[0]['event_id']}}
            raise AssertionError(path)
        with patch.dict(os.environ,{'PAPER_PROFILE':'1'}),patch.object(d,'request',side_effect=upstream):
            s.tick()
            self.assertEqual(d.truth['a'],'thread_pool_exhausted')
            for n in 'abc':s.nodes[n]['next_retry']=0
            s.tick()
        self.assertEqual(len(calls),6)
        self.assertTrue(all(c['force_mode'] is None for c in calls[:3]))
        self.assertTrue(all(c['force_mode']=='edge' for c in calls[3:]))
        self.assertTrue(all(set(c)=={'force_mode','event_id'} for c in calls))
        d.truth.pop('a',None)

    def tearDown(self):
        s.events.clear()
        s.enabled=True
        for n in 'abc': s.reset(n)
        self.env.stop()
        self.tmp.cleanup()
