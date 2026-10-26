import unittest
from fedhelm.task_progress import progress


def records(stages):
    return [{'seq':i,'stage':s,'time':f'2026-09-09T00:00:{i:02d}+00:00','detail':'',
             'payload':{'feedback':{'success':True}} if s=='处置结果' else {}} for i,s in enumerate(stages)]


class ProgressTests(unittest.TestCase):
    def test_injection_ack_does_not_mean_recovered(self):
        p=progress(records(['操作开始','故障注入','操作完成']))
        self.assertEqual(p['completed'],1)
        self.assertIsNone(p['finished_at'])

    def test_failed_verification_is_not_complete(self):
        data=records(['故障注入','采集观测','轻量诊断','模型选择','生成方案','修复动作返回','恢复验证','处置结果','恢复失败'])
        data[-2]['payload']['feedback']['success']=False
        p=progress(data)
        self.assertEqual(p['completed'],6)
        self.assertEqual(p['phases'][-1]['state'],'failed')

    def test_success_and_case_record_are_separate(self):
        data=records(['故障注入','采集观测','轻量诊断','模型选择','生成方案','修复动作返回','恢复验证','处置结果'])
        p=progress(data)
        self.assertEqual(p['completed'],7)
        self.assertEqual(p['duration_seconds'],7)
        self.assertFalse(p['case_stored'])

    def test_training_does_not_get_fault_milestones(self):
        self.assertIsNone(progress(records(['开始本地训练','上传模型增量'])))

    def test_missing_initial_stage_is_not_mislabeled_as_failure(self):
        data=records(['采集观测','轻量诊断','模型选择','生成方案','修复动作返回','恢复验证','处置结果'])
        data[-1]['payload']['feedback']['success']=False
        result=progress(data)
        self.assertEqual(result['phases'][0]['state'],'unrecorded')
        self.assertEqual(result['phases'][-1]['state'],'failed')

    def test_successful_retry_overrides_prior_failure(self):
        data=records(['故障注入','处置结果','恢复失败','检测异常','采集观测','轻量诊断','模型选择','生成方案','修复动作返回','恢复验证','处置结果','案例入库'])
        data[1]['payload']['feedback']['success']=False
        p=progress(data)
        self.assertEqual(p['status'],'恢复验证通过')
        self.assertEqual(p['completed'],7)
        self.assertTrue(p['case_stored'])

    def test_manual_restore_is_not_automatic_success(self):
        p=progress(records(['故障注入','人工终止']))
        self.assertEqual(p['status'],'人工终止')
        self.assertEqual(p['completed'],1)
        self.assertEqual(p['duration_seconds'],1)

    def test_injection_time_precedes_detection(self):
        data=records(['故障注入','检测异常','采集观测'])
        self.assertEqual(progress(data)['phases'][0]['time'],data[0]['time'])
