import os
import tempfile
import unittest
from unittest.mock import patch
from fedhelm import history

class HistoryTests(unittest.TestCase):
    def test_summary_preserves_result_without_arrays(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}):
            history.record('a','task','上传模型增量','large',{'delta':[.5]*10000})
            history.record('a','task','处置结果','done',{'feedback':{'success':True},'delta':[.5]*10000})
            steps=history.tasks(include_payload='summary')[0]['steps']
            self.assertEqual(steps[0]['payload'],{})
            self.assertEqual(steps[1]['payload']['feedback']['success'],1)
            self.assertNotIn('delta',steps[1]['payload'])
            self.assertEqual(len(history.query()[0]['payload']['delta']),10000)

    def test_monitor_summary_omits_parameters_without_deleting_detail(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}):
            history.record('a','round','上传模型增量','uploaded',{'delta':[.5]*10000})
            summary=history.query(include_payload=False)
            self.assertEqual(summary[0]['payload'],{})
            self.assertEqual(summary[0]['stage'],'上传模型增量')
            self.assertEqual(len(history.query()[0]['payload']['delta']),10000)

    def test_paged_filters_and_distinct_parameter_snapshots(self):
        from fedhelm.contracts import Model
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}):
            for i in range(12):
                history.record('a' if i%2==0 else 'b',str(i),'上传模型增量','test update',{'delta':[i]})
            history.record('edge','aggregate','完成全局模型聚合与保存','saved',{'model':Model(version=1).model_dump()})
            one=history.page_records('a','upload',page=1,size=5)
            two=history.page_records('a','upload',page=2,size=5)
            self.assertEqual(one['total'],6)
            self.assertEqual(len(two['items']),1)
            self.assertFalse({r['seq'] for r in one['items']} & {r['seq'] for r in two['items']})
            self.assertEqual(history.page_records(kind='download')['total'],0)
            self.assertEqual(history.page_records(search="' OR 1=1")['total'],0)
            history.record('a','sync','完成模型下载与加载','saved',{'model':Model(version=1).model_dump()})
            self.assertEqual(len(history.model_versions()),1)
            history.record('b','other','完成模型下载与加载','saved',{'model':Model(version=1,parameters=[.1]*4).model_dump()})
            self.assertEqual(len(history.model_versions()),2)

    def test_task_correlation_pagination_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}):
            history.record('a','incident','故障注入','service_down')
            history.record('a','incident','轻量诊断','service_down',{'confidence':.9})
            history.record('b','other','操作失败','offline')
            rows=history.query('a',limit=1)
            self.assertEqual(rows[0]['payload']['confidence'],.9)
            self.assertEqual(history.query('a',before=rows[0]['seq'])[0]['stage'],'故障注入')
            chain=history.tasks('a')[0]
            self.assertEqual(len(chain['steps']),2)
            self.assertEqual(chain['task'],'incident')
            self.assertEqual(len(history.tasks(before=chain['latest'])),0)
            history.metric('a',{'error_rate':1,'latency_ms':15,'pool_usage':0})
            self.assertEqual(history.series('a')[0]['payload']['error_rate'],1)
            # Every read opens a new DB connection: no in-memory event cache required.
            self.assertEqual(len(history.query()),3)
