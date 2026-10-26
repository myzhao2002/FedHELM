import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from fedhelm.registry import Cluster, node_ids, validate_node
from fedhelm import model_api, traffic


class ClusterTests(unittest.TestCase):
    def test_invalid_provider_does_not_echo_secret(self):
        from fastapi.testclient import TestClient
        from fedhelm.edge import app
        r = TestClient(app).put('/ui/model-api/edge', json={'mode': 'openai-compatible', 'api_key': 'never-echo-this'})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn('never-echo-this', r.text)

    def test_injection_requires_separate_service(self):
        from fastapi.testclient import TestClient
        from fedhelm.edge import app
        with patch.dict(os.environ, SEPARATE_INJECTOR='1', INTERNAL_TOKEN='unit-test-token'):
            c = TestClient(app)
            self.assertEqual(c.post('/ui/command', json={'node': 'a', 'action': 'inject', 'fault': 'service_down'}).status_code, 403)
            self.assertEqual(c.post('/internal/experiment', json={'node': 'a', 'fault': 'service_down'}).status_code, 403)

    def test_kubernetes_has_16_device_pods_and_private_services(self):
        from scripts.cluster_manifest import generate
        conf = Cluster.model_validate_json(Path('config/cluster.local.json').read_text(encoding='utf-8'))
        manifest = generate(conf)
        deployments = [i for i in manifest['items'] if i['kind'] == 'Deployment']
        self.assertEqual(len(deployments), 18)
        self.assertEqual(sum(i['metadata']['name'].startswith('agent-') for i in deployments), 16)
        for item in deployments:
            pod = item['spec']['template']['spec']
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertTrue(all(c.get('resources', {}).get('limits') for c in pod['containers']))

    def test_inventory_and_validation(self):
        path = Path('config/cluster.local.json').resolve()
        conf = Cluster.model_validate_json(path.read_text(encoding='utf-8'))
        self.assertEqual([sum(n.tier == t for n in conf.nodes) for t in 'ABC'], [5, 6, 5])
        with patch.dict(os.environ, CLUSTER_CONFIG=str(path)):
            self.assertEqual(len(node_ids()), 16)
            self.assertEqual(validate_node('c05'), 'c05')
            with self.assertRaises(ValueError): validate_node('c06')
        body = conf.model_dump(); body['nodes'][1]['agent_url'] = body['nodes'][0]['agent_url']
        with self.assertRaises(ValueError): Cluster.model_validate(body)

    def test_key_masking_preserving_and_clearing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, MODEL_API_CONFIG=str(Path(tmp)/'api.json')):
            result = model_api.save('edge', model_api.Provider(api_key='test-secret'))
            self.assertNotIn('test-secret', json.dumps(result))
            self.assertTrue(result['providers']['edge']['has_key'])
            model_api.save('edge', model_api.Provider())
            self.assertEqual(model_api.read()['edge']['api_key'], 'test-secret')
            model_api.save('edge', model_api.Provider(clear_key=True))
            self.assertFalse(model_api.public()['providers']['edge']['has_key'])

    def test_disabled_provider_has_no_mock_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, MODEL_API_CONFIG=str(Path(tmp)/'api.json')):
            with self.assertRaises(HTTPException) as error: model_api.infer(None, 'edge')
            self.assertEqual(error.exception.status_code, 503)

    def test_traffic_persists_and_releases_file_handles(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, DATA_DIR=tmp):
            traffic.record('a01', 'edge', 'telemetry', bytes_count=123)
            events = traffic.recent()
            self.assertEqual(events[0]['bytes'], 123)
            self.assertEqual(traffic.recent(events[0]['seq']), [])
            Path(tmp, 'traffic.sqlite').rename(Path(tmp, 'closed.sqlite'))
