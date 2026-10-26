import unittest
from unittest.mock import patch
from contextlib import ExitStack
from fastapi import HTTPException
from fedhelm import agent
from fedhelm.contracts import Observation,Diagnosis,Plan,RunRequest


class FinalReviewTests(unittest.TestCase):
    def exercise(self,edge_confidence):
        calls=[];executed=False
        observation=Observation(event_id='review',node_id=agent.node,service_id='fixture',healthy=False,
                                error_rate=1,latency_ms=10,pool_usage=0,logs=[])
        diagnosis=Diagnosis(event_id='review',root_cause='config_error',confidence=.9,
                            embedding=[0.]*4,model_version=1,evidence=[],source='temporal-transformer-v2')
        def request(method,base,path,body=None,**kwargs):
            nonlocal executed
            calls.append(path)
            if path=='/health':return {'intervention_revision':0}
            if path.startswith('/observe'):
                return observation.model_copy(update={'healthy':executed,'error_rate':0 if executed else 1}).model_dump()
            if path in ('/infer','/diagnose'):
                return Plan(event_id='review',node_id=agent.node,service_id='fixture',mode='local' if path=='/infer' else 'edge',
                            root_cause='config_error',confidence=.3 if path=='/infer' else edge_confidence,
                            action='restore_config',reason='test response').model_dump()
            if path=='/execute':executed=True;return {'applied':True}
            if path=='/ui/events':return {}
            raise AssertionError(path)
        with ExitStack() as stack:
            for name,value in [('paper_profile',True),('cache',[]),('validation_seconds_setting',30)]:
                stack.enter_context(patch.object(agent,name,value))
            stack.enter_context(patch.object(agent,'request',side_effect=request))
            stack.enter_context(patch.object(agent,'audit'))
            stack.enter_context(patch('fedhelm.temporal.diagnose',return_value=diagnosis))
            stack.enter_context(patch('fedhelm.telemetry.window',return_value=[]))
            stack.enter_context(patch('fedhelm.policy.choose',return_value=('local',{})))
            stack.enter_context(patch('fedhelm.policy.update'))
            stack.enter_context(patch('fedhelm.feedback_data.retain'))
            stack.enter_context(patch('fedhelm.agent.time.sleep'))
            from itertools import count
            stack.enter_context(patch('fedhelm.agent.time.monotonic',side_effect=lambda:next(clock)))
            clock=count(0,.25)
            if edge_confidence<.55:
                with self.assertRaises(HTTPException):agent.run(RunRequest(event_id='review'))
                self.assertFalse(executed)
            else:
                result=agent.run(RunRequest(event_id='review'))
                self.assertTrue(result['feedback']['success'])
                self.assertTrue(result['policy']['post_inference_escalation'])
                self.assertEqual(result['initial_diagnosis']['confidence'],.9)
                self.assertLess(calls.index('/diagnose'),calls.index('/execute'))
            self.assertIn('/infer',calls);self.assertIn('/diagnose',calls)

    def test_low_confidence_local_result_is_reviewed_before_execution(self):self.exercise(.9)

    def test_insufficient_edge_review_never_executes(self):self.exercise(.4)
