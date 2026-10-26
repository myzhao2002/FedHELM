"""Cross-platform local process launcher; owns and terminates only its children."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
from scripts.demo import run_demo


def existing_console(base_port, workload_backend=None, training_backend=None):
    """Only reuse a known FedHELM console with all expected local services alive."""
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            base = f'http://127.0.0.1:{base_port}'
            spec = client.get(base+'/openapi.json').json()
            if not spec.get('info', {}).get('title', '').startswith('FedHELM'):
                return False
            if '/ui/command' not in spec.get('paths', {}):
                return False
            status = client.get(base+'/ui/status').json()
            if os.getenv('PAPER_PROFILE')=='1' and not all(status.get('services',{}).get(f'agent-{n}',{}).get('paper_profile') for n in 'abc'):
                return False
            if workload_backend and any(status.get('services', {}).get(f'workload-{n}', {}).get('workload_backend', 'synthetic') != workload_backend for n in 'abc'):
                return False
            if training_backend and any(status.get('services',{}).get(f'agent-{n}',{}).get('training_backend','mock') != training_backend for n in 'abc'):
                return False
            return len(status.get('services', {})) == 9 and all(
                service.get('online') for service in status['services'].values())
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return False


def ports_free(base_port):
    for offset in (0,1,2,3,101,102,103,201,202,203):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', base_port+offset))
            except OSError:
                return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='run end-to-end checks and stop all children')
    parser.add_argument('--open-browser', action='store_true', help='open the Chinese console after startup')
    parser.add_argument('--reuse-existing', action='store_true', help='reuse a verified console or select free ports')
    parser.add_argument('--workload-backend', choices=['synthetic','process'], default='synthetic')
    parser.add_argument('--training-backend', choices=['mock','torch'], default='mock')
    parser.add_argument('--base-port', type=int, default=8000)
    parser.add_argument('--data-dir', default='runtime/local')
    args = parser.parse_args()
    if args.reuse_existing and not args.demo:
        candidates = list(dict.fromkeys([args.base_port, 9000, 10000, 11000, 12000]))
        for candidate in candidates:
            if existing_console(candidate, args.workload_backend,args.training_backend):
                url = f'http://127.0.0.1:{candidate}/'
                print(f'FedHELM is already running. Opening existing console: {url}', flush=True)
                if args.open_browser:
                    import webbrowser
                    webbrowser.open(url)
                return
        free = next((p for p in candidates if ports_free(p)), None)
        if free is None:
            raise SystemExit('Configured port groups are occupied. Stop the old platform or use --base-port.')
        if free != args.base_port:
            print(f'Existing services occupy port {args.base_port}; using port {free}.', flush=True)
        args.base_port = free
    root = Path(__file__).resolve().parents[1]
    directory = Path(args.data_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    b = args.base_port
    console_env = {'AUTO_MONITOR':'0' if args.demo else os.getenv('AUTO_MONITOR','1'), 'LLM_URL': f'http://127.0.0.1:{b+2}', 'LOCAL_LLM_URL': f'http://127.0.0.1:{b+3}',
                   'FEDERATION_URL': f'http://127.0.0.1:{b+1}'}
    for i,n in enumerate('abc'):
        console_env[f'AGENT_{n.upper()}_URL'] = f'http://127.0.0.1:{b+101+i}'
        console_env[f'WORKLOAD_{n.upper()}_URL'] = f'http://127.0.0.1:{b+201+i}'
    services = [('edge', 'edge', b, console_env),
                ('federation', 'federation', b+1, {'TRAINING_BACKEND':args.training_backend,'EDGE_URL':f'http://127.0.0.1:{b}'}),
                ('llm-edge', 'llm', b+2, {'MODEL_MODE': 'edge'}),
                ('llm-local', 'llm', b+3, {'MODEL_MODE': 'local'})]
    for i,n in enumerate('abc'):
        services.append((f'workload-{n}', 'real_workload' if args.workload_backend == 'process' else 'workload', b+201+i, {'NODE_ID': n}))
        services.append((f'agent-{n}', 'agent', b+101+i, {
            'NODE_ID': n, 'TIER': n.upper(), 'TRAINING_BACKEND':args.training_backend,'EDGE_URL': f'http://127.0.0.1:{b}',
            'FEDERATION_URL': f'http://127.0.0.1:{b+1}', 'LOCAL_LLM_URL': f'http://127.0.0.1:{b+3}',
            'WORKLOAD_URL': f'http://127.0.0.1:{b+201+i}'}))
    # Refuse to attach to unrelated processes on occupied ports.
    for name, _, port, _ in services:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError as exc:
                raise SystemExit(f'{name}: port {port} occupied; use --base-port') from exc
    children, streams = [], []
    (directory/'launcher.json').write_text(json.dumps({'pid':os.getpid(),'recorded_at':time.time(),
        'workspace':str(root),'base_port':b}),encoding='utf-8')
    try:
        for name, module, port, extra in services:
            env = {**os.environ, **extra, 'DATA_DIR': str(directory/name), 'PYTHONUNBUFFERED': '1'}
            stream = (directory/f'{name}.log').open('w', encoding='utf-8')
            streams.append(stream)
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', f'fedhelm.{module}:app',
                '--host', '127.0.0.1', '--port', str(port)], cwd=root, env=env,
                stdout=stream, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            children.append(process)
        deadline = time.monotonic()+45
        with httpx.Client(timeout=1, trust_env=False) as client:
            for name, _, port, _ in services:
                while True:
                    if any(p.poll() is not None for p in children):
                        raise RuntimeError(f'service exited; inspect {directory}')
                    try:
                        if client.get(f'http://127.0.0.1:{port}/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'{name} did not become ready; inspect logs')
                    time.sleep(.2)
        print(f'10 services ready. UI: http://127.0.0.1:{b}/  API: http://127.0.0.1:{b}/docs', flush=True)
        if args.open_browser:
            import webbrowser
            webbrowser.open(f'http://127.0.0.1:{b}/')
        if args.demo:
            run_demo(b)
        else:
            print('Ctrl+C stops all child services.', flush=True)
            while all(p.poll() is None for p in children):
                time.sleep(.5)
            raise RuntimeError('a service stopped; inspect logs')
    except KeyboardInterrupt:
        pass
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in streams:
            stream.close()


if __name__ == '__main__':
    main()
