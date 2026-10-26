import copy
import unittest
from unittest.mock import patch
from fedhelm.contracts import Observation,RunRequest,Resources
from fedhelm.telemetry import detect,vector
from fedhelm.compression import encode,decode,Packet
from fedhelm.policy import choose,fuse


class PaperTests(unittest.TestCase):
    def test_final_result_check_uses_returned_confidence_and_confirmed_memory(self):
        from fedhelm.policy import review_reasons
        from types import SimpleNamespace
        result=SimpleNamespace(root_cause='config_error',confidence=.4)
        self.assertIn('最终诊断置信度不足',review_reasons(result,[]))
        result.confidence=.9
        case={'diagnosis':{'root_cause':'pool_exhausted','confidence':.8},'feedback':{'success':True},'root_cause_confirmed':True}
        self.assertIn('最终根因与相似已确认记忆冲突',review_reasons(result,[case]))
        case['root_cause_confirmed']=False
        self.assertEqual(review_reasons(result,[case]),[])
        result.root_cause='healthy'
        self.assertTrue(review_reasons(result,[],healthy=False))

    def test_ideal_language_model_review_uses_observations(self):
        import os
        from fedhelm.contracts import Diagnosis,InferenceRequest
        from fedhelm.llm import infer
        obs=Observation(event_id='x',node_id='a',service_id='service-a',healthy=False,error_rate=1,latency_ms=350,pool_usage=0,logs=['config_error'],metrics={'worker_wait_ms':350})
        d=Diagnosis(event_id='x',root_cause='unknown',confidence=0,embedding=[0.]*4,model_version=1,evidence=[])
        with patch.dict(os.environ,{'PAPER_PROFILE':'1'}):
            result=infer(InferenceRequest(observation=obs,diagnosis=d))
        self.assertEqual(result.root_cause,'thread_pool_exhausted')
        self.assertEqual(result.action,'reset_workers')
        self.assertEqual(d.root_cause,'unknown')

    def test_latency_only_detection(self):
        rows=[{'healthy':True,'error_rate':0,'latency_ms':20} for _ in range(10)]
        rows += [{'healthy':True,'error_rate':0,'latency_ms':650} for _ in range(3)]
        self.assertTrue(detect(rows)['anomalous'])
        self.assertFalse(detect(rows[:10])['anomalous'])

    def test_diagnosis_contract_rejects_injector_label(self):
        with self.assertRaises(ValueError):RunRequest(event_id='x',fault='config_error')

    def test_inference_cannot_read_fault_keywords_or_metric_extras(self):
        from fedhelm.temporal import bootstrap,diagnose
        model=bootstrap();model.training_samples=12
        obs=Observation(event_id='x',node_id='a',service_id='service-a',healthy=False,error_rate=1,latency_ms=100,pool_usage=.2,logs=['config_error'])
        original=diagnose(obs,model,[])
        altered=obs.model_copy(update={'logs':['service_down','worker queue timeout'],'metrics':{'injected_fault':123.}})
        changed=diagnose(altered,model,[])
        self.assertEqual(vector(obs),vector(altered))
        self.assertEqual(original.probabilities,changed.probabilities)

    def test_untrained_model_abstains(self):
        from fedhelm.temporal import bootstrap,diagnose
        obs=Observation(event_id='x',node_id='a',service_id='service-a',healthy=False,error_rate=1,latency_ms=100,pool_usage=.2,logs=[])
        self.assertEqual(diagnose(obs,bootstrap(),[]).root_cause,'unknown')

    def test_sparse_packet_checksums_and_shape(self):
        delta=[(i-256)*.0001 for i in range(512)]
        packet=encode(delta);decoded=decode(packet)
        self.assertEqual(len(packet.indices),256)
        self.assertEqual(len(decoded),512)
        self.assertLess(max(abs(delta[i]-decoded[i]) for i in packet.indices),.0003)
        bad=packet.model_dump();bad['values'][0]+=1
        with self.assertRaises(ValueError):Packet.model_validate(bad)

    def test_memory_conflict_forces_edge_and_exposes_costs(self):
        from fedhelm.contracts import Diagnosis
        d=Diagnosis(event_id='x',root_cause='config_error',confidence=.9,embedding=[1.,0,0,0],embedding_version='v2',model_version=1,evidence=[],probabilities={'config_error':.9,'pool_exhausted':.1})
        case={'diagnosis':{'root_cause':'pool_exhausted','embedding':[1.,0,0,0],'embedding_version':'v2'}}
        result,matches,score=fuse(d,[case])
        self.assertTrue(result.memory_conflict)
        self.assertAlmostEqual(result.probabilities['pool_exhausted'],.415)
        with patch('fedhelm.policy.statistics',return_value={}):
            mode,detail=choose(result,Resources(node_id='b',tier='B'),memory_score=score)
        self.assertEqual(mode,'edge');self.assertIn('costs',detail)
        self.assertNotIn('local',detail['feasible'])
