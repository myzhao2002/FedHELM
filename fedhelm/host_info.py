"""Report actual hosting information; distinguish host totals from container limits."""
import os
import platform
import socket
from pathlib import Path
import psutil


def snapshot():
    memory=psutil.virtual_memory();process=psutil.Process()
    try:disk=psutil.disk_usage(Path(os.getenv('DATA_DIR','.')).resolve().anchor)
    except OSError:disk=None
    def read(name):
        try:return Path('/sys/fs/cgroup',name).read_text().strip()
        except OSError:return None
    cpu=read('cpu.max');limit=read('memory.max');current=read('memory.current')
    cpu_limit=None
    if cpu and cpu.split()[0]!='max':
        try:quota,period=map(int,cpu.split());cpu_limit=quota/period
        except (ValueError,ZeroDivisionError):pass
    addresses=sorted({v.address for items in psutil.net_if_addrs().values() for v in items
                      if v.family==socket.AF_INET and not v.address.startswith('127.')})[:8]
    return {'os':platform.system(),'release':platform.release(),'architecture':platform.machine(),
            'hostname':socket.gethostname(),'pod_name':os.getenv('POD_NAME'), 'node_ip':os.getenv('NODE_IP'),
            'reported_ipv4':addresses,'cpu_logical':psutil.cpu_count(),'cpu_physical':psutil.cpu_count(logical=False),
            'memory_total_mb':round(memory.total/1024**2),'memory_available_mb':round(memory.available/1024**2),
            'disk_total_gb':round(disk.total/1024**3,1) if disk else None,
            'disk_free_gb':round(disk.free/1024**3,1) if disk else None,
            'agent_rss_mb':round(process.memory_info().rss/1024**2,1),
            'agent_cpu_seconds':round(sum(process.cpu_times()[:2]),2),'uptime_seconds':round(__import__('time').time()-psutil.boot_time()),
            'container_cpu_limit':cpu_limit,'container_memory_limit_mb':round(int(limit)/1024**2) if limit and limit.isdigit() else None,
            'container_memory_available_mb':max(0,int((int(limit)-int(current))/1024**2)) if limit and limit.isdigit() and current and current.isdigit() else None,
            'scope':'进程可见的主机/网络命名空间；容器限制单列，地址不保证可从浏览器直连',
            'sampled_at':__import__('time').time()}
