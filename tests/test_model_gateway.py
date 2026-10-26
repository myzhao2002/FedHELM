import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx
from fastapi import HTTPException
from fedhelm import model_api as gateway
from fedhelm.contracts import Observation, Diagnosis, InferenceRequest


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,MODEL_API_CONFIG=str(Path(self.tmp.name)/'providers.json'))
        self.env.start()

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def body(self):
        return InferenceRequest(observation=Observation(event_id='incident-1',node_id='a01',service_id='orders',healthy=False,
            error_rate=1,latency_ms=200,pool_usage=.99,logs=['token=private-secret','sk-private-value'],metrics={'db_wait_ms':180}),
            diagnosis=Diagnosis(event_id='incident-1',root_cause='pool_exhausted',confidence=.5,embedding=[0]*4,model_version=6,evidence=[]))

    def config(self,**kwargs):
        return gateway.Provider(mode='openai-compatible',base_url='http://localhost:8888/v1',model='served-model',min_interval_seconds=0,**kwargs)

    def test_deleted_key_does_not_fall_back(self):
        key=Path(self.tmp.name)/'only.key';key.write_text('private-value')
        config=self.config(api_key_file=str(key),api_key='other-key')
        gateway.save('edge',config)
        self.assertTrue(gateway.public()['providers']['edge']['has_key'])
        key.unlink()
        self.assertFalse(gateway.public()['providers']['edge']['has_key'])
        with patch.object(gateway.httpx,'Client') as client:
            with self.assertRaises(HTTPException):gateway.infer(self.body(),'edge')
            client.assert_not_called()

    def test_atomic_call_budget(self):
        config=self.config(daily_call_limit=3)
        def reserve(_):
            try:gateway.reserve('edge',config);return True
            except HTTPException as e:self.assertEqual(e.status_code,429);return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(8)))
        self.assertEqual(sum(results),3)
        self.assertEqual(gateway.usage()['roles']['edge']['calls'],3)

    def test_prompt_input_is_bounded_and_redacted(self):
        body=self.body();body.observation.logs*=100
        compact=gateway.compact_input(body)
        self.assertLess(len(compact),4000)
        self.assertNotIn('private-secret',compact)
        self.assertNotIn('sk-private-value',compact)
        self.assertNotIn('embedding',compact)
        self.assertNotIn('incident-1',compact)

    def test_self_hosted_adapter_and_usage(self):
        gateway.save('local',self.config(deployment='self-hosted',max_output_tokens=256))
        answer={'root_cause':'pool_exhausted','action':'reset_pool','confidence':.91,'parameters':{},'reason':'连接池占用与等待升高'}
        response=httpx.Response(200,request=httpx.Request('POST','http://localhost:8888/v1/chat/completions'),json={
            'choices':[{'message':{'content':json.dumps(answer)}}],'usage':{'prompt_tokens':100,'completion_tokens':40}})
        with patch.object(gateway.httpx,'Client') as client:
            post=client.return_value.__enter__.return_value.post;post.return_value=response
            plan=gateway.infer(self.body(),'local')
            payload=post.call_args.kwargs['json']
            self.assertEqual(payload['max_tokens'],256)
            self.assertNotIn('enable_thinking',payload)
            self.assertEqual(plan.node_id,'a01')
        self.assertEqual(gateway.usage()['roles']['local']['completion_tokens'],40)

    def test_conflicting_plan_is_not_executed_or_retried(self):
        gateway.save('edge',self.config())
        with patch.object(gateway.httpx,'Client') as client:
            post=client.return_value.__enter__.return_value.post
            post.return_value=httpx.Response(200,request=httpx.Request('POST','http://localhost/'),json={'choices':[{'message':{'content':json.dumps(
                {'root_cause':'healthy','action':'restart_service','confidence':1,'parameters':{},'reason':'wrong'})}}]})
            with self.assertRaises(HTTPException):gateway.infer(self.body(),'edge')
            self.assertEqual(post.call_count,1)
        self.assertEqual(gateway.usage()['roles']['edge']['successes'],0)
