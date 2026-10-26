import tempfile
import unittest
from pathlib import Path
from fedhelm.real_workload import Business


class ProcessWorkloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.business = Business(self.directory.name)
        self.business.start()

    def tearDown(self):
        self.business.stop()
        self.directory.cleanup()

    def observe(self):
        return self.business.observe('test-event','a')

    def test_real_http_and_process_restart(self):
        original = self.business.process
        self.assertEqual(self.observe().response_codes, [200]*3)
        self.business.inject('service_down')
        self.assertIsNotNone(original.poll())
        failed = self.observe()
        self.assertEqual(failed.response_codes, [0]*3)
        self.assertIsNone(failed.business_pid)
        self.business.execute('restart_service')
        self.assertTrue(self.observe().healthy)
        self.assertNotEqual(original.pid, self.business.process.pid)

    def test_wrong_action_does_not_mask_config_failure(self):
        self.business.inject('config_error')
        self.assertIn('false', (Path(self.directory.name)/'config.json').read_text())
        self.business.execute('reset_pool')
        obs = self.observe()
        self.assertFalse(obs.healthy)
        self.assertEqual(obs.response_codes, [503]*3)
        self.assertIn('invalid configuration', obs.logs)
        self.business.execute('restore_config')
        self.assertTrue(self.observe().healthy)

    def test_pool_is_exhausted_until_released(self):
        self.business.inject('pool_exhausted')
        obs = self.observe()
        self.assertEqual(obs.pool_usage, 1)
        self.assertEqual(obs.response_codes, [503]*3)
        self.assertGreater(obs.latency_ms, 50)
        self.business.execute('restore_config')
        self.assertFalse(self.observe().healthy)
        self.business.execute('reset_pool')
        self.assertEqual(self.observe().response_codes, [200]*3)

    def test_child_exits_when_supervisor_pipe_closes(self):
        child = self.business.process
        child.stdin.close()
        child.wait(timeout=5)
        self.assertIsNotNone(child.returncode)

    def test_real_worker_exhaustion_and_dependency_timeout(self):
        import httpx
        from fedhelm.fault_catalog import extension_diagnosis
        from fedhelm.contracts import Model
        from fedhelm.mock_model import plan
        for fault,action,signature in [('thread_pool_exhausted','reset_workers','worker queue timeout'),
                                        ('dependency_timeout','restore_dependency','dependency read timeout')]:
            with self.subTest(fault=fault):
                self.business.inject(fault)
                with httpx.Client(trust_env=False) as client:
                    metrics=client.get(self.business.url+'/metrics').json()
                self.assertNotIn('dependency_delay_ms',metrics)
                self.assertNotIn('held_workers',metrics)
                obs=self.observe()
                self.assertEqual(obs.response_codes,[503]*3)
                self.assertGreater(obs.latency_ms,80)
                self.assertIn(signature,obs.logs)
                diagnosis=extension_diagnosis(obs,Model())
                self.assertEqual(diagnosis.root_cause,fault)
                self.assertEqual(diagnosis.embedding_version,'explicit-fault-rules-v1')
                self.assertEqual(plan(obs,diagnosis,'lightweight','test').action,action)
                self.business.execute('restore_config')
                self.assertFalse(self.observe().healthy)
                self.business.execute(action)
                self.assertTrue(self.observe().healthy)
                self.assertIsNone(extension_diagnosis(self.observe(),Model()))
