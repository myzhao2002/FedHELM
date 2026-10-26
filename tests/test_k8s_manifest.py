import unittest
from scripts.k8s_manifest import generate


class KubernetesManifestTests(unittest.TestCase):
    def test_fault_permissions_are_scoped_to_one_workload(self):
        items=generate()['items']
        roles=[x for x in items if x['kind']=='Role']
        self.assertEqual(len(roles),3)
        for role in roles:
            n=role['metadata']['name'][-1]
            self.assertEqual(role['metadata']['namespace'],'fedhelm')
            self.assertEqual(role['rules'],[{'apiGroups':['apps'],'resources':['deployments/scale'],
                'resourceNames':['business-'+n],'verbs':['get','patch']}])

    def test_tier_placement_and_no_tokens_for_models(self):
        deployments={x['metadata']['name']:x for x in generate()['items'] if x['kind']=='Deployment'}
        self.assertEqual(len(deployments),13)
        for name in ('edge','federation','llm-edge'):
            self.assertEqual(deployments[name]['spec']['template']['spec']['nodeSelector'],{'fedhelm-role':'edge'})
        self.assertEqual(deployments['llm-local']['spec']['template']['spec']['nodeSelector'],{'fedhelm-tier':'A'})
        for n in 'abc':
            for prefix in ('agent-','business-','workload-'):
                pod=deployments[prefix+n]['spec']['template']['spec']
                self.assertEqual(pod['nodeSelector'],{'fedhelm-tier':n.upper()})
                self.assertEqual(pod['automountServiceAccountToken'],prefix=='workload-')
