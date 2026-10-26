import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from fedhelm import edge, dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DATA_DIR': self.directory.name})
        self.env.start()
        dashboard.truth.clear()
        dashboard.last.clear()
        self.client = TestClient(edge.app)

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def test_console_and_chinese_openapi(self):
        self.assertIn('故障管理控制台', self.client.get('/').text)
        spec = self.client.get('/openapi.json').json()
        self.assertEqual(spec['paths']['/memory/cases']['post']['summary'], '提交已验证的成功案例')

    def test_resources_browser_page_preserves_json_api(self):
        page = self.client.get('/resources?ui=nav3', headers={'Accept': 'text/html,application/xhtml+xml'})
        self.assertEqual(page.status_code, 200)
        self.assertIn('text/html', page.headers['content-type'])
        self.assertIn('故障管理控制台', page.text)
        data = self.client.get('/resources', headers={'Accept': 'application/json'})
        self.assertEqual(data.status_code, 200)
        self.assertIn('nodes', data.json())

    def test_offline_status_is_not_healthy(self):
        with patch.object(dashboard, 'probe', side_effect=lambda pair: (pair[0], {'online': False})):
            result = self.client.get('/ui/status').json()
        self.assertEqual(len(result['services']), 9)
        self.assertTrue(all(not s['online'] for s in result['services'].values()))
        self.assertEqual(result['observations'], {})
        self.assertIsNone(result['model'])

    def test_rejects_unknown_nodes_and_unconfirmed_case(self):
        self.assertEqual(self.client.post('/ui/command', json={'action':'inject','node':'external'}).status_code, 422)
        self.assertEqual(self.client.post('/ui/command', json={'action':'submit','node':'a'}).status_code, 409)

    def test_new_injection_invalidates_prior_candidate(self):
        dashboard.last['a'] = {'result': {}, 'truth': 'service_down'}
        with patch.object(dashboard, 'request', return_value={'fault':'config_error'}):
            self.assertEqual(self.client.post('/ui/command',json={'action':'inject','node':'a','fault':'config_error'}).status_code, 200)
        self.assertNotIn('a', dashboard.last)
        self.assertEqual(dashboard.truth['a'], 'config_error')

    def test_batch_reports_partial_failure(self):
        def upstream(method, url, path, **kwargs):
            if '8102' in url:
                raise RuntimeError('B离线')
            return {'accepted': True}
        with patch.object(dashboard, 'request', side_effect=upstream):
            result = self.client.post('/ui/command',json={'action':'sync_all'}).json()
        self.assertFalse(result['all_succeeded'])
        self.assertFalse(result['nodes']['b']['ok'])
        self.assertTrue(result['nodes']['c']['ok'])
