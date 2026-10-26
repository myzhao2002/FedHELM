import os
import tempfile
import unittest
from unittest.mock import patch
from fedhelm.datasets import generate,GenerateRequest,DatasetImport,import_dataset,training_rows,listing,select


class DatasetTests(unittest.TestCase):
    def test_temporal_samples_and_splits_are_reproducible(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'DATA_DIR':d}):
            request=GenerateRequest(dataset_id='sample-a',seed=631,per_class=6)
            dataset=generate(request)
            self.assertEqual(dataset,generate(request))
            self.assertEqual(dataset.source,'synthetic')
            failure=next(r for r in dataset.records if r.label=='pool_exhausted')
            self.assertEqual(failure.series[0].error_rate,0)
            self.assertEqual(failure.series[-1].error_rate,1)
            self.assertGreater(failure.series[-1].pool_usage,.9)
            self.assertEqual(len(failure.series),20)
            import_dataset(dataset)
            rows=training_rows()
            self.assertTrue(all(len(r['window'][0])==12 for r in rows))
            self.assertEqual(listing()['active_dataset'],'sample-a')
            select(None);self.assertIsNone(training_rows())
            with self.assertRaises(ValueError):import_dataset(dataset)

    def test_rejects_event_leakage_and_unknown_metrics(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'DATA_DIR':d}):
            dataset=generate(GenerateRequest(dataset_id='x')).model_dump()
            dataset['records'][1]['event_id']=dataset['records'][0]['event_id']
            with self.assertRaises(ValueError):DatasetImport.model_validate(dataset)
            dataset['records'][1]['event_id']='new'
            dataset['records'][0]['series'][0]['injected_fault']='config_error'
            with self.assertRaises(ValueError):DatasetImport.model_validate(dataset)

    def test_profiles_change_class_distribution_and_transition_windows(self):
        from collections import Counter
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'DATA_DIR':d,'NODE_ID':'b'}):
            balanced=generate(GenerateRequest(dataset_id='balanced',profile='balanced',per_class=12))
            skewed=generate(GenerateRequest(dataset_id='skewed',profile='non_iid',per_class=12))
            transitions=generate(GenerateRequest(dataset_id='transitions',profile='transition',per_class=12))
            self.assertEqual(set(Counter(r.label for r in balanced.records).values()),{12})
            counts=Counter(r.label for r in skewed.records)
            self.assertGreater(counts['pool_exhausted'],counts['thread_pool_exhausted'])
            starts=[next(i for i,f in enumerate(r.series) if f.error_rate>0) for r in transitions.records if r.label!='healthy']
            self.assertGreater(max(starts)-min(starts),8)
            self.assertEqual(sum(r.split=='test' for r in balanced.records),12)

    def test_holdout_evaluation_does_not_update_model_or_use_training_rows(self):
        from fedhelm.temporal import bootstrap,evaluate
        model=bootstrap();before=model.model_dump_json()
        rows=[{'event_id':'held-out','split':'test','label':0,'window':[[0.]*12]}]
        rows.append({'event_id':'train','split':'train','label':5,'window':'deliberately not read'})
        result=evaluate(model,rows)
        self.assertEqual(result['test_count'],1)
        self.assertEqual(sum(map(sum,result['confusion_matrix'])),1)
        self.assertEqual(before,model.model_dump_json())
        rows[-1]['event_id']='held-out'
        with self.assertRaises(ValueError):evaluate(model,rows)
