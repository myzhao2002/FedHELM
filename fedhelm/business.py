"""Small real HTTP business process with SQLite connections and a bounded pool."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import httpx
import psutil
from collections import deque
import statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--standalone',action='store_true')
    parser.add_argument('--port',type=int,default=8000)
    args = parser.parse_args()
    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory/'config.json').exists():
        (directory/'config.json').write_text(json.dumps({'database_enabled':True}))
    pool = [sqlite3.connect(directory/'orders.sqlite', check_same_thread=False) for _ in range(4)]
    pool[0].execute('CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, item TEXT)')
    pool[0].execute("INSERT OR IGNORE INTO orders VALUES (1, 'demo-order')")
    pool[0].commit()
    condition = threading.Condition()
    held = []
    workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='orders-worker')
    release_workers = threading.Event()
    release_workers.set()
    blockers = []
    worker_jobs=deque(maxlen=64)
    worker_slots = threading.BoundedSemaphore(2)
    dependency_delay = threading.Event()
    process_stats=psutil.Process()
    process_stats.cpu_percent()
    recent=deque(maxlen=60)
    metrics_lock=threading.Lock()

    class Dependency(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            # A separate, single-threaded loopback HTTP dependency. No host network changes.
            if dependency_delay.is_set():
                time.sleep(.25)
            try:
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'OK')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    from http.server import HTTPServer
    dependency = HTTPServer(('127.0.0.1', 0), Dependency)
    threading.Thread(target=dependency.serve_forever, daemon=True).start()

    def order():
        spans=[]
        started=time.perf_counter()
        try:
            config=json.loads((directory/'config.json').read_text())
            if config.get('database_enabled') is not True:
                raise ValueError('configuration validation failed')
        except (ValueError,OSError):
            spans.append({'operation':'config.validate','duration_ms':(time.perf_counter()-started)*1000,'ok':False})
            return 503,{'error':'invalid configuration','spans':spans}
        spans.append({'operation':'config.validate','duration_ms':(time.perf_counter()-started)*1000,'ok':True})
        started=time.perf_counter()
        try:
            with httpx.Client(timeout=.10,trust_env=False) as client:
                client.get(f'http://127.0.0.1:{dependency.server_port}/stock').raise_for_status()
        except httpx.HTTPError:
            spans.append({'operation':'stock.http','duration_ms':(time.perf_counter()-started)*1000,'ok':False})
            return 503,{'error':'dependency read timeout','spans':spans}
        spans.append({'operation':'stock.http','duration_ms':(time.perf_counter()-started)*1000,'ok':True})
        started=time.perf_counter()
        with condition:
            if not condition.wait_for(lambda:bool(pool),timeout=.08):
                spans.append({'operation':'db.acquire','duration_ms':(time.perf_counter()-started)*1000,'ok':False})
                return 503,{'error':'connection timeout','spans':spans}
            connection=pool.pop()
        spans.append({'operation':'db.acquire','duration_ms':(time.perf_counter()-started)*1000,'ok':True})
        try:
            return 200,{'orders':connection.execute('SELECT id,item FROM orders').fetchall(),'spans':spans}
        finally:
            with condition:
                pool.append(connection)
                condition.notify_all()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *values):
            pass

        def reply(self, status, body):
            if self.path=='/orders':
                with metrics_lock:
                    recent.append({'status':status,'spans':body.get('spans',[])})
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health':
                return self.reply(200, {'pid': os.getpid(),'pod_name':os.getenv('HOSTNAME')})
            if self.path == '/metrics':
                with metrics_lock:
                    items=list(recent)[-3:]
                spans=[span for item in items for span in item['spans']]
                def durations(op):
                    values=[s['duration_ms'] for s in spans if s['operation']==op]
                    return statistics.mean(values) if values else 0.
                def errors(op):
                    values=[not s['ok'] for s in spans if s['operation']==op]
                    return statistics.mean(values) if values else 0.
                with condition:
                    return self.reply(200,{'pool_usage':(4-len(pool))/4,
                        'worker_usage':min(1,sum(f.running() for f in worker_jobs)/2),
                        'worker_wait_ms':durations('worker.acquire'),'db_wait_ms':durations('db.acquire'),
                        'dependency_ms':durations('stock.http'),'dependency_error_rate':errors('stock.http'),
                        'config_error_rate':errors('config.validate'),
                        'cpu_usage':min(1,process_stats.cpu_percent()/100/max(1,psutil.cpu_count())),
                        'rss_mb':process_stats.memory_info().rss/1024/1024})
            if self.path != '/orders':
                return self.reply(404, {'error': 'not found'})
            waiting=time.perf_counter()
            if not worker_slots.acquire(timeout=.35):
                return self.reply(503, {'error':'worker queue timeout','spans':[{'operation':'worker.acquire','duration_ms':(time.perf_counter()-waiting)*1000,'ok':False}]})
            waited=(time.perf_counter()-waiting)*1000
            future = workers.submit(order)
            worker_jobs.append(future)
            future.add_done_callback(lambda _: worker_slots.release())
            try:
                status, body = future.result(timeout=.35)
                body.setdefault('spans',[]).insert(0,{'operation':'worker.acquire','duration_ms':waited,'ok':True})
                self.reply(status, body)
            except FutureTimeout:
                future.cancel()  # Remove pending work; repeated probes do not accumulate jobs.
                self.reply(503, {'error':'worker queue timeout'})

        def do_POST(self):
            if self.path == '/admin/hold-workers':
                if release_workers.is_set():
                    for _ in range(2):
                        worker_slots.acquire()
                    release_workers.clear()
                    blockers[:] = [workers.submit(release_workers.wait) for _ in range(2)]
                    worker_jobs.extend(blockers)
                return self.reply(200, {'held_workers':len(blockers)})
            with condition:
                if self.path == '/admin/hold-pool':
                    held.extend(pool)
                    pool.clear()
                elif self.path == '/admin/reset-pool':
                    pool.extend(held)
                    held.clear()
                    condition.notify_all()
                elif self.path == '/admin/reset-workers':
                    release_workers.set()
                    for future in blockers:
                        future.result(timeout=1)
                        worker_slots.release()
                    blockers.clear()
                elif self.path == '/admin/delay-dependency':
                    dependency_delay.set()
                elif self.path == '/admin/restore-dependency':
                    dependency_delay.clear()
                    # Drain the bounded dependency backlog before acknowledging recovery.
                    with httpx.Client(timeout=2,trust_env=False) as client:
                        client.get(f'http://127.0.0.1:{dependency.server_port}/stock').raise_for_status()
                elif self.path in ('/admin/break-config','/admin/restore-config'):
                    temporary=directory/'config.tmp'
                    temporary.write_text(json.dumps({'database_enabled':self.path.endswith('restore-config')}))
                    temporary.replace(directory/'config.json')
                else:
                    return self.reply(404, {'error':'unknown operation'})
                self.reply(200, {'held_connections': len(held)})

    # The supervisor owns this stdin pipe. Exit even when the parent is force-terminated.
    def parent_watch():
        sys.stdin.buffer.read()
        os._exit(0)
    if not args.standalone:
        threading.Thread(target=parent_watch, daemon=True).start()
    server = ThreadingHTTPServer(('0.0.0.0' if args.standalone else '127.0.0.1', args.port if args.standalone else 0), Handler)
    print(json.dumps({'port': server.server_port, 'pid': os.getpid()}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
