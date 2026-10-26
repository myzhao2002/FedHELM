import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from fedhelm import edge, federation, workload, agent
from fedhelm.contracts import Observation, Model, Case, Feedback, Update, Resources
from fedhelm.mock_model import diagnose, plan


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DATA_DIR': self.tmp.name, 'EXPECTED_NODES': 'a,b,c'})
        self.env.start()
        federation.pending.clear()
        self.fed = TestClient(federation.app)
        self.work = TestClient(workload.app)
        self.edge = TestClient(edge.app)
        self.work.post('/inject', json={'fault': 'healthy'})

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def update(self, n='a', version=0):
        return Update(node_id=n, base_version=version, sample_count=4,
                      delta=[.1, .2, .3, .4], label_histogram=[1,1,1,1], quality=.8).model_dump()

    def case(self):
        obs = Observation(event_id='event', node_id=workload.node, service_id=workload.service,
                          healthy=False, error_rate=1, latency_ms=1500, pool_usage=.99,
                          logs=['connection timeout'])
        diagnosis = diagnose(obs, Model())
        action = plan(obs, diagnosis, 'lightweight', 'unit test')
        healthy = obs.model_copy(update={'healthy': True, 'error_rate': 0, 'latency_ms': 20})
        return Case(case_id='case', source_node=workload.node, diagnosis=diagnosis, plan=action,
                    feedback=Feedback(event_id='event', success=True, samples=[healthy]*3, criterion='test'),
                    root_cause_confirmed=True, label_source='synthetic_injector').model_dump()

    def test_rejects_unknown_fields_and_unsafe_actions(self):
        self.assertEqual(self.work.post('/inject', json={'fault':'healthy','command':'x'}).status_code, 422)
        c = self.case()
        c['plan']['action'] = 'shell'
        self.assertEqual(self.work.post('/execute', json=c['plan']).status_code, 422)

    def test_wrong_action_does_not_recover_workload(self):
        self.work.post('/inject', json={'fault':'config_error'})
        action = self.case()['plan']  # reset_pool cannot fix config_error
        self.assertFalse(self.work.post('/execute', json=action).json()['applied'])
        self.assertFalse(self.work.get('/observe?event_id=event').json()['healthy'])
        action['service_id'] = 'unrelated'
        self.assertEqual(self.work.post('/execute', json=action).status_code, 400)

    def test_memory_rejects_false_success_and_unconfirmed_labels(self):
        c = self.case()
        c['feedback']['samples'][0]['healthy'] = False
        self.assertEqual(self.edge.post('/memory/cases', json=c).status_code, 422)
        c = self.case()
        c['root_cause_confirmed'] = False
        c['label_source'] = 'unconfirmed'
        self.assertEqual(self.edge.post('/memory/cases', json=c).status_code, 422)

    def test_case_correlation_idempotency_and_search(self):
        c = self.case()
        bad = self.case()
        bad['feedback']['event_id'] = 'wrong'
        self.assertEqual(self.edge.post('/memory/cases', json=bad).status_code, 422)
        for _ in range(2):
            self.assertEqual(self.edge.post('/memory/cases', json=c).status_code, 200)
        self.assertEqual(len(self.edge.get('/memory/snapshot').json()['cases']), 1)
        hits = self.edge.post('/memory/search', json={'embedding':[0,0,0,1]}).json()['hits']
        self.assertEqual(hits[0]['case']['case_id'], 'case')
        c['plan']['reason'] = 'different payload'
        self.assertEqual(self.edge.post('/memory/cases', json=c).status_code, 409)

    def test_round_requires_all_nodes_and_rejects_stale_updates(self):
        self.fed.post('/updates', json=self.update())
        self.assertEqual(self.fed.post('/aggregate').status_code, 409)
        for n in 'bc':
            self.fed.post('/updates', json=self.update(n))
        result = self.fed.post('/aggregate').json()
        self.assertAlmostEqual(sum(result['weights'].values()), 1)
        for actual, expected in zip(result['model']['parameters'], [.1,.2,.3,.4]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(self.fed.get('/model').json()['version'], 1)
        self.assertEqual(self.fed.post('/updates', json=self.update()).status_code, 409)

    def test_conflicting_updates_and_invalid_histogram(self):
        u = self.update()
        self.assertEqual(self.fed.post('/updates', json=u).status_code, 200)
        self.assertEqual(self.fed.post('/updates', json=u).status_code, 200)
        u['delta'][0] = .5
        self.assertEqual(self.fed.post('/updates', json=u).status_code, 409)
        u['label_histogram'] = [-1,1,1,3]
        self.assertEqual(self.fed.post('/updates', json=u).status_code, 422)

    def test_low_confidence_unavailable_edge_stops_action(self):
        d = diagnose(Observation(event_id='x',node_id='a',service_id='service-a',healthy=True,
                                 error_rate=0,latency_ms=20,pool_usage=.2,logs=[]), Model())
        d.confidence = .3
        with patch.object(agent, 'state', Resources(node_id='a',tier='A',edge_available=False)):
            with self.assertRaises(Exception) as caught:
                agent.choose_mode(d, None)
            self.assertEqual(caught.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
