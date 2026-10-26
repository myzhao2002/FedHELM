"""External test harness owns synthetic ground truth; agents never receive it."""
import json
import os
from pathlib import Path
from fedhelm.common import request


def run_demo(base_port=8000):
    edge = os.getenv('DEMO_EDGE_URL', f'http://127.0.0.1:{base_port}')
    fed = os.getenv('DEMO_FED_URL', f'http://127.0.0.1:{base_port+1}')
    agents = {n: os.getenv(f'DEMO_AGENT_{n.upper()}_URL', f'http://127.0.0.1:{base_port+101+i}') for i,n in enumerate('abc')}
    workloads = {n: os.getenv(f'DEMO_WORKLOAD_{n.upper()}_URL', f'http://127.0.0.1:{base_port+201+i}') for i,n in enumerate('abc')}
    results = []
    for node in 'abc':
        request('POST', agents[node], '/sync')
    for node, fault, mode in [('a','service_down','local'), ('b','config_error','edge'), ('c','pool_exhausted','lightweight')]:
        request('POST', workloads[node], '/inject', {'fault': fault})
        result = request('POST', agents[node], '/run', {'force_mode': mode})
        assert result['feedback']['success'], result
        assert result['plan']['mode'] == mode
        candidate = result['case_candidate']
        assert candidate['diagnosis']['root_cause'] == fault
        candidate['root_cause_confirmed'] = True
        candidate['label_source'] = 'testbed_injector' if result['observation'].get('workload_backend') == 'process' else 'synthetic_injector'
        receipt = request('POST', edge, '/memory/cases', candidate)
        assert receipt['accepted']
        results.append(result)
    hits = request('POST', edge, '/memory/search', {'embedding': [0,0,0,1]})
    assert hits['hits'], hits
    request('POST', agents['c'], '/sync')
    request('POST', workloads['c'], '/inject', {'fault': 'pool_exhausted'})
    reuse = request('POST', agents['c'], '/run', {})
    assert reuse['used_case'] and reuse['feedback']['success'], reuse
    old = request('GET', fed, '/model')
    for n in 'abc':
        request('POST', agents[n], '/train')
    aggregation = request('POST', fed, '/aggregate')
    assert aggregation['model']['version'] == old['version'] + 1
    assert aggregation['model']['parameters'] != old['parameters']
    synced = {n: request('POST', agents[n], '/sync') for n in 'abc'}
    assert all(s['model']['version'] == aggregation['model']['version'] for s in synced.values())
    request('POST', workloads['c'], '/inject', {'fault': 'pool_exhausted'})
    after = request('POST', agents['c'], '/run', {})
    assert after['diagnosis']['model_version'] == aggregation['model']['version']
    report = {'simulated': True, 'status': 'passed', 'events': results,
              'memory_reuse': reuse, 'aggregation': aggregation, 'after_sync': after,
              'limitations': ['No LLM weights loaded', 'No gradient training', 'Resource values are synthetic; workload backend is recorded in each observation',
                              'No paper performance claims; simplified aggregation and routing']}
    output = Path(os.getenv('REPORT_DIR', 'runtime'))
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'demo-report.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'PASS: three modes, feedback, verified memory, reuse, aggregate, synchronize; report={path.resolve()}')
    return report


if __name__ == '__main__':
    run_demo(int(os.getenv('BASE_PORT', '8000')))
