"""Generate a 16-device Kubernetes deployment. No cluster is modified."""
import argparse
import json
from pathlib import Path
from fedhelm.registry import Cluster


def generate(conf, image='fedhelm-cluster:local'):
    conf = conf.model_copy(deep=True)
    conf.console_url = conf.console_url or conf.edge_url
    conf.injector_public_url = conf.injector_public_url or conf.injector_url
    conf.edge_url = 'http://edge:8000'
    conf.federation_url = 'http://edge:8001'
    conf.llm_edge_url = 'http://edge:8002'
    conf.llm_local_url = 'http://edge:8003'
    conf.injector_url = 'http://injector:8000'
    for n in conf.nodes:
        n.agent_url = f'http://agent-{n.id}:8000'
        n.workload_url = f'http://agent-{n.id}:8001'
        n.placement = 'kubernetes'; n.host = 'assigned-by-kubernetes'
    ns = 'fedhelm-cluster'
    def item(kind, name, **rest):
        return {'apiVersion': 'apps/v1' if kind == 'Deployment' else 'v1', 'kind': kind,
                'metadata': {'name': name, 'namespace': ns}, **rest}
    items = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns}},
             item('ConfigMap', 'cluster-config', data={'cluster.json': conf.model_dump_json(indent=2)})]
    common = {'CLUSTER_CONFIG': '/config/cluster.json', 'PAPER_PROFILE': '1', 'TRAINING_BACKEND': 'torch',
              'EXPECTED_NODES': ','.join(n.id for n in conf.nodes), 'EDGE_URL': conf.edge_url,
              'FEDERATION_URL': conf.federation_url, 'LLM_URL': conf.llm_edge_url,
              'LOCAL_LLM_URL': conf.llm_local_url, 'COLLECT_INTERVAL': '8', 'SEPARATE_INJECTOR': '1',
              'AUTO_MONITOR': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}

    def deploy(name, modules, ports):
        # Each logical device owns one PVC; edge gateways share its provider file.
        items.append(item('PersistentVolumeClaim', name+'-data', spec={'accessModes': ['ReadWriteOnce'],
                     'resources': {'requests': {'storage': '1Gi'}}}))
        containers = []
        for module, port, extra, memory in modules:
            env = {**common, 'DATA_DIR': '/data/'+module, **extra}
            entries = [{'name': k, 'value': str(v)} for k, v in env.items()]
            entries += [{'name': 'INTERNAL_TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'internal-auth', 'key': 'token'}}},
                        {'name': 'K8S_NODE_NAME', 'valueFrom': {'fieldRef': {'fieldPath': 'spec.nodeName'}}},
                        {'name': 'POD_NAME', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.name'}}},
                        {'name': 'NODE_IP', 'valueFrom': {'fieldRef': {'fieldPath': 'status.hostIP'}}}]
            containers.append({'name': module.replace('_', '-')+str(port), 'image': image, 'imagePullPolicy': 'IfNotPresent',
                'command': ['python', '-m', 'uvicorn', 'fedhelm.'+module+':app', '--host', '0.0.0.0', '--port', str(port)],
                'env': entries, 'ports': [{'containerPort': port}],
                'resources': {'requests': {'cpu': '20m', 'memory': '64Mi'}, 'limits': {'cpu': '750m', 'memory': memory}},
                'readinessProbe': {'httpGet': {'path': '/health', 'port': port}, 'initialDelaySeconds': 5, 'periodSeconds': 10, 'timeoutSeconds': 5},
                'volumeMounts': [{'name': 'config', 'mountPath': '/config', 'readOnly': True}, {'name': 'data', 'mountPath': '/data'}]})
        if name == 'edge':
            for container in containers:
                if container['name'].startswith(('edge', 'llm')):
                    container['volumeMounts'].append({'name': 'provider-key', 'mountPath': '/secrets', 'readOnly': True})
        items.append(item('Deployment', name, spec={'replicas': 1, 'strategy': {'type': 'Recreate'},
            'selector': {'matchLabels': {'app': name}}, 'template': {'metadata': {'labels': {'app': name}},
            'spec': {'automountServiceAccountToken': False, 'containers': containers,
                     'volumes': [{'name': 'config', 'configMap': {'name': 'cluster-config'}},
                                 {'name': 'data', 'persistentVolumeClaim': {'claimName': name+'-data'}}]}}}))
        if name == 'edge':
            items[-1]['spec']['template']['spec']['volumes'].append({'name': 'provider-key', 'secret': {
                'secretName': 'provider-key', 'optional': True, 'defaultMode': 256}})
        items.append(item('Service', name, spec={'selector': {'app': name},
            'ports': [{'name': 'http-'+str(p), 'port': p, 'targetPort': p} for p in ports]}))

    api = {'MODEL_API_CONFIG': '/data/providers.json'}
    deploy('edge', [('edge', 8000, api, '768Mi'), ('federation', 8001, {}, '1Gi'),
                   ('llm', 8002, {**api, 'MODEL_MODE': 'edge'}, '192Mi'),
                   ('llm', 8003, {**api, 'MODEL_MODE': 'local'}, '192Mi')], [8000, 8001, 8002, 8003])
    deploy('injector', [('injector', 8000, {}, '192Mi')], [8000])
    for n in conf.nodes:
        deploy('agent-'+n.id, [('agent', 8000, {'NODE_ID': n.id, 'TIER': n.tier, 'WORKLOAD_URL': n.workload_url,
                                               'MODEL_API_CONFIG': '/data/api-adapter-enabled'}, '768Mi'),
                                ('real_workload', 8001, {'NODE_ID': n.id}, '192Mi')], [8000, 8001])
    return {'apiVersion': 'v1', 'kind': 'List', 'items': items}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--config', default='config/cluster.local.json')
    p.add_argument('--output', default='k8s/cluster16.json'); p.add_argument('--image', default='fedhelm-cluster:local')
    p.add_argument('--console-url'); p.add_argument('--injector-public-url')
    args = p.parse_args(); conf = Cluster.model_validate_json(Path(args.config).read_text(encoding='utf-8'))
    if args.console_url:
        conf.console_url = args.console_url
    if args.injector_public_url:
        conf.injector_public_url = args.injector_public_url
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(generate(conf, args.image), ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(output)+' generated; deployment has NOT been applied.')
