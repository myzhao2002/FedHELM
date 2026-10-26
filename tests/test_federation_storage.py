import os
import tempfile
import unittest
from unittest.mock import patch
from fedhelm import federation as f
from fedhelm.contracts import Update

class FederationStorageTests(unittest.TestCase):
    def test_restart_retains_updates_and_consumed_round(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'DATA_DIR':directory,'TRAINING_BACKEND':'mock'}):
            f.pending.clear()
            for node in 'abc':
                ack=f.update(Update(node_id=node,base_version=0,sample_count=4,delta=[.1]*4,
                                    label_histogram=[1]*4,quality=.8))
                self.assertTrue(ack['persisted'])
            f.pending.clear() # model process restart: all volatile state gone
            self.assertEqual(len(f.round_status()['updates']),3)
            f.aggregate()
            f.pending.clear()
            self.assertEqual(f.round_status()['version'],1)
            self.assertEqual(f.round_status()['updates'],[])
            self.assertEqual(f.model().parameters,[.1]*4)
