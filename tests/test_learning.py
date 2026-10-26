import unittest
import torch
from fedhelm.learning import network,pack,train,diagnose,features,ADAPTER
from fedhelm.contracts import Model,Observation


class LearningTests(unittest.TestCase):
    def test_real_gradients_and_disjoint_validation(self):
        torch.manual_seed(3)
        initial=Model(adapter=ADAPTER,parameters=pack(network()))
        rows=[]
        for label in range(4):
            for i in range(3):
                obs=Observation(event_id=f'{label}-{i}',node_id='a',service_id='service-a',
                    healthy=label==0,error_rate=float(label!=0),latency_ms=100 if label==3 else 10,
                    pool_usage=float(label==3),logs=[['','process unavailable','invalid configuration','connection timeout'][label]])
                rows.append({'event_id':obs.event_id,'features':features(obs),'label':label,
                             'split':'validation' if i==2 else 'train'})
        result=train(initial,rows)
        self.assertLess(result['loss_after'],result['loss_before'])
        self.assertTrue(any(abs(d)>1e-6 for d in result['delta']))
        self.assertEqual(result['sample_count'],8)
        self.assertEqual(result['validation_count'],4)
        trained=Model(adapter=ADAPTER,parameters=[p+d for p,d in zip(initial.parameters,result['delta'])])
        self.assertEqual(diagnose(obs,trained).root_cause,'pool_exhausted')
        rows[-1]['event_id']=rows[0]['event_id']
        with self.assertRaises(ValueError):
            train(initial,rows)

    def test_parameter_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            Model(adapter=ADAPTER,parameters=[0]*4)
