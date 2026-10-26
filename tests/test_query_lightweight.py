import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch
from fedhelm import federation, history


class LightweightQueries(unittest.TestCase):
    def test_health_does_not_load_updates_or_acquire_training_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DATA_DIR': directory}), patch.object(federation, 'lock') as lock, patch.object(federation, 'restore_pending', side_effect=AssertionError('heavy read')):
            self.assertEqual(asyncio.run(federation.health())['status'], 'ok')
            lock.__enter__.assert_not_called()

    def test_log_list_omits_payload_but_detail_remains(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DATA_DIR': directory}):
            history.record('a', 'task', 'upload', 'update', {'delta': [1.0] * 10000})
            self.assertEqual(history.page_records(include_payload=False)['items'][0]['payload'], {})
            self.assertEqual(len(history.query()[0]['payload']['delta']), 10000)
