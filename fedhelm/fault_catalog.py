"""Paper §6.1 fault inventory; availability describes implemented test fixtures."""
FAULTS = [
    ('cpu_saturation','CPU饱和',False,'需要容器CPU配额隔离，当前不对宿主机施压'),
    ('memory_leak','内存泄漏',False,'需要容器内存上限，当前不消耗宿主机内存'),
    ('thread_pool_exhausted','线程池耗尽',True,'占住测试业务的两个实际工作线程，订单任务等待超时'),
    ('disk_full','磁盘写满',False,'需要有容量上限的独立卷，当前不填满电脑磁盘'),
    ('pool_exhausted','数据库连接池耗尽',True,'占住测试SQLite的四个连接，实际数据库请求等待超时'),
    ('network_latency','网络延迟',False,'需要独立网络命名空间与网络故障工具'),
    ('packet_loss','分组丢失',False,'需要独立网络命名空间，当前不修改电脑网络'),
    ('dependency_timeout','依赖超时',True,'本机测试依赖实际延迟响应，订单服务的HTTP依赖调用超时'),
    ('service_down','服务崩溃',True,'停止本项目测试业务子进程；K8s适配器缩容业务至零'),
    ('config_error','配置错误',True,'写入错误数据库配置，使实际订单请求失败'),
]


def catalog():
    import os
    paper=os.getenv('PAPER_PROFILE')=='1'
    return {'source':'FedHELM-cn.pdf · §6.1（PDF第15页）',
            'note':'支持项已在同机独立进程测试床验证；K8s适配器尚未完成集群实测。服务崩溃采用进程停止实验，不模拟任意崩溃根因。',
            'faults':[{'id':i,'name':n,'implemented':ok,'mechanism':m,
                       'diagnosis':'六分类时序Transformer（需真实训练）' if paper and ok else '日志规则扩展（不属于四分类神经模型）' if i in ('thread_pool_exhausted','dependency_timeout') else '四分类轻量模型' if ok else '未实现'}
                      for i,n,ok,m in FAULTS]}


def extension_diagnosis(obs, model):
    """Explicit rules for new fixtures, separate from the trained four-class model."""
    from .contracts import Diagnosis
    signatures = [('thread_pool_exhausted','worker queue timeout'),('dependency_timeout','dependency read timeout')]
    for index,(fault,signature) in enumerate(signatures):
        if not obs.healthy and signature in obs.logs:
            return Diagnosis(event_id=obs.event_id,root_cause=fault,confidence=1.0,
                             embedding=[float(index==0),float(index==1),obs.error_rate,0.0],
                             embedding_version='explicit-fault-rules-v1',model_version=model.version,
                             evidence=['显式日志规则命中；置信值为规则分值，非神经模型概率',signature])
    return None
