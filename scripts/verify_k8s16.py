"""Read-only verification of the 16 logical endpoints and their Kubernetes workloads."""
import argparse
import collections
import datetime
import json
import subprocess
import urllib.request
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context', default='kind-fedhelm16')
    p.add_argument('--url', default='http://127.0.0.1:16000')
    p.add_argument('--output', type=Path, default=Path('runtime/k8s16-verification.json'))
    args = p.parse_args()
    def kube(resource):
        command = ['kubectl', '--context', args.context, '-n', 'fedhelm-cluster',
                   'get', resource, '-o', 'json', '--request-timeout=15s']
        return json.loads(subprocess.check_output(command, timeout=30))['items']
    expected = [f'{tier}{i:02d}' for tier, count in [('a', 5), ('b', 6), ('c', 5)] for i in range(1, count+1)]
    report = {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'context': args.context,
              'expected_logical_end_nodes': expected, 'checks': {}}
    try:
        nodes = kube('nodes'); pods = kube('pods'); deployments = kube('deployments'); claims = kube('pvc')
        report['physical_kubernetes_nodes'] = [n['metadata']['name'] for n in nodes]
        report['pods'] = [{'name': x['metadata']['name'], 'app': x['metadata']['labels'].get('app'),
            'node': x['spec'].get('nodeName'), 'phase': x['status'].get('phase'),
            'containers': [{'name': c['name'], 'ready': c['ready'], 'restarts': c['restartCount']}
                for c in x['status'].get('containerStatuses', [])]} for x in pods]
        wanted = {'edge', 'injector'} | {'agent-'+n for n in expected}
        found = {d['metadata']['name'] for d in deployments}
        report['checks']['deployment_names'] = found == wanted
        report['checks']['deployments_available'] = all(d['status'].get('availableReplicas', 0) == 1 for d in deployments)
        report['checks']['all_pods_ready'] = all(x['status'].get('phase') == 'Running' and
            len(x['status'].get('containerStatuses', [])) == len(x['spec']['containers']) and
            all(c['ready'] for c in x['status'].get('containerStatuses', [])) for x in pods) and bool(pods)
        report['checks']['persistent_storage'] = len(claims) == 18 and all(x['status'].get('phase') == 'Bound' for x in claims)
        with urllib.request.urlopen(args.url+'/ui/cluster', timeout=90) as response:
            snapshot = json.load(response)
        ends = snapshot['nodes']
        report['logical_nodes'] = [{k: n.get(k) for k in ['id','tier','online','business_healthy','k8s_node','model_version']} for n in ends]
        report['checks']['api_node_ids'] = {n['id'] for n in ends} == set(expected)
        report['checks']['tier_counts'] = dict(collections.Counter(n['tier'] for n in ends)) == {'A':5,'B':6,'C':5}
        report['checks']['agents_online'] = all(n['online'] for n in ends)
    except Exception as exc:
        report['error'] = str(exc)
    report['passed'] = not report.get('error') and bool(report['checks']) and all(report['checks'].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
