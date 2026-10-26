import os
import tempfile
import unittest
from unittest.mock import patch
from fedhelm import feedback_data as f

class FeedbackTests(unittest.TestCase):
    def test_confirmation_is_idempotent_and_rejects_conflicting_label(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'DATA_DIR':directory}):
            f.retain('event',[[0.]*12],True)
            self.assertEqual(f.rows(),[])
            a=f.confirm('event','config_error');b=f.confirm('event','config_error')
            self.assertEqual(a,b);self.assertEqual(len(f.rows()),1)
            with self.assertRaises(ValueError):f.confirm('event','pool_exhausted')

    def test_failed_or_missing_event_never_enters_training(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'DATA_DIR':directory}):
            f.retain('failed',[[0.]*12],False)
            with self.assertRaises(ValueError):f.confirm('failed','config_error')
            with self.assertRaises(ValueError):f.confirm('missing','config_error')
            self.assertEqual(f.rows(),[])
