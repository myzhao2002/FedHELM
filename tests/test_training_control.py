import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from types import SimpleNamespace
from fedhelm import training_control as c
from fedhelm.recovery import recovered

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        folder=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ,{'DATA_DIR':folder}))
        self.stack.enter_context(patch.object(c,'node_ids',return_value=['a01','b01']))
        self.stack.enter_context(patch.object(c,'event'))
        self.stack.enter_context(patch.object(c.stop_event,'wait',return_value=False))
        c.stop_event.clear(); c.running=False
        self.version=0; self.pending=set(); self.trained=[]; self.fail_download=False
        self.stack.enter_context(patch.object(c,'federation',side_effect=self.federation))
        self.stack.enter_context(patch.object(c,'remote',side_effect=self.remote))

    def federation(self,route,method='GET'):
        if route=='/aggregate':
            self.assertEqual(self.pending,{'a01','b01'})
            self.version+=1;self.pending.clear()
            return {'model':{'version':self.version}}
        return {'version':self.version,'updates':[{'node_id':n} for n in self.pending]}

    def remote(self,node,method,route,body=None):
        if route=='/health':return {}
        if route=='/datasets':return {'active_dataset':'d','datasets':[{'dataset_id':'d','splits':{'train':4,'validation':2}}]}
        if route=='/telemetry':return {'latest':{'healthy':True},'anomaly':{'anomalous':False}}
        if route=='/train':self.pending.add(node);self.trained.append(node);return {'metrics':{'epochs':2}}
        if route=='/sync':
            if self.version and self.fail_download:raise RuntimeError('interrupted download')
            return {'model':{'version':self.version}}
        raise AssertionError(route)

    def test_round_confirms_all_versions(self):
        c.run_round(manual=True)
        self.assertEqual(self.trained,['a01','b01'])
        self.assertEqual(c.read()['completed'],1)
        self.assertTrue(all(n['version']==1 for n in c.read()['nodes'].values()))

    def test_resume_after_aggregation_does_not_train_or_aggregate_twice(self):
        self.fail_download=True;c.run_round(manual=True)
        self.assertIsNotNone(c.read()['active'])
        self.fail_download=False;c.run_round(manual=True)
        self.assertEqual(self.version,1)
        self.assertEqual(self.trained,['a01','b01'])
        self.assertEqual(c.read()['completed'],1)

    def test_missing_data_never_starts_training(self):
        original=self.remote
        with patch.object(c,'remote',side_effect=lambda n,m,r,b=None: {'active_dataset':None,'datasets':[]} if r=='/datasets' else original(n,m,r,b)):
            c.run_round(manual=True)
        self.assertEqual(self.trained,[])
        self.assertEqual(c.read()['phase'],'等待训练数据')

    def test_resume_uploaded_endpoint_is_not_retrained(self):
        self.pending={'a01'};c.run_round(manual=True)
        self.assertEqual(self.trained,['b01'])

class RecoveryTests(unittest.TestCase):
    def test_bad_initial_sample_can_recover_before_deadline(self):
        good=SimpleNamespace(healthy=True,error_rate=0,latency_ms=10)
        bad=SimpleNamespace(healthy=False,error_rate=1,latency_ms=10)
        samples=[bad,good,good,good]
        self.assertTrue(recovered(samples,10,7,300))
        self.assertFalse(recovered(samples,301,7,300))
        self.assertFalse(recovered(samples,10,7,300,changed=True))
        self.assertFalse(recovered([good,bad,good],10,7,300))
