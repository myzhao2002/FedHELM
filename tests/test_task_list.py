import os
import tempfile
import unittest
from unittest.mock import patch
from fedhelm.history import record,task_page


class TaskListTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name});self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_filters_and_pagination_do_not_return_model_payloads(self):
        for i in range(7):
            record('a',str(i),'故障注入','service_down')
            record('a',str(i),'处置结果','恢复成功',{'feedback':{'success':True},'diagnosis':{'root_cause':'service_down'},'parameters':[1]*10000})
        record('edge','training','完成本地训练','训练完成',{'parameters':[1]*10000})
        page=task_page(status='resolved',page=2,size=5)
        self.assertEqual(page['total'],7);self.assertEqual(len(page['items']),2)
        self.assertNotIn('parameters',str(page))
        self.assertEqual(task_page(node='b')['total'],0)
        self.assertEqual(task_page(kind='operation')['total'],1)
        self.assertEqual(task_page(search='service_down')['total'],7)
        self.assertEqual(task_page(search='服务停止')['total'],7)
    def test_retry_and_recovery_status_follow_latest_result(self):
        record('b','incident','故障注入','config_error')
        record('b','incident','处置结果','恢复失败',{'feedback':{'success':False}})
        record('b','incident','恢复失败','等待重试')
        self.assertEqual(task_page()['items'][0]['status'],'failed')
        record('b','incident','检测异常','再次诊断')
        self.assertEqual(task_page()['items'][0]['status'],'waiting')
        record('b','incident','处置结果','恢复成功',{'feedback':{'success':True}})
        record('b','incident','案例入库','成功案例')
        row=task_page()['items'][0]
        self.assertEqual(row['status'],'resolved');self.assertEqual(row['case_stored'],1)
