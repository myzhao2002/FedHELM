"""Generate reviewable Kubernetes JSON (kubectl accepts JSON manifests)."""
import json
from pathlib import Path


def generate():
    ns='fedhelm'
    items=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns}}]
    image='fedhelm-training:v1'
    def add(name,module,role='edge',env=None,training=False,service_account=None,command=None):
        selector={'app':name}
        environment={'DATA_DIR':'/data',**(env or {})}
        if training:
            environment['TRAINING_BACKEND']='torch'
        container={'name':name,'image':image,'imagePullPolicy':'IfNotPresent',
            'command':command or ['python','-m','uvicorn',f'fedhelm.{module}:app','--host','0.0.0.0','--port','8000'],
            'ports':[{'containerPort':8000}],
            'env':[{'name':k,'value':str(v)} for k,v in environment.items()]+[
                {'name':'K8S_NODE_NAME','valueFrom':{'fieldRef':{'fieldPath':'spec.nodeName'}}}],
            'resources':{'requests':{'cpu':'20m','memory':'80Mi'},'limits':{'cpu':'750m','memory':'768Mi' if training else '256Mi'}},
            'volumeMounts':[{'name':'data','mountPath':'/data'}],
            'readinessProbe':{'httpGet':{'path':'/health','port':8000},'initialDelaySeconds':2,'periodSeconds':2},
            'livenessProbe':{'httpGet':{'path':'/health','port':8000},'initialDelaySeconds':30,'periodSeconds':10,'failureThreshold':6}}
        pod={'containers':[container], 'nodeSelector':{'fedhelm-role':'edge'} if role=='edge' else {'fedhelm-tier':role},
            'automountServiceAccountToken':bool(service_account),
            'volumes':[{'name':'data','hostPath':{'path':'/var/local/fedhelm/'+name,'type':'DirectoryOrCreate'}}]}
        if role=='edge':
            pod['tolerations']=[{'key':'node-role.kubernetes.io/control-plane','operator':'Exists','effect':'NoSchedule'}]
        if service_account:
            pod['serviceAccountName']=service_account
        items.append({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name,'namespace':ns},
            'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':selector},
                    'template':{'metadata':{'labels':selector},'spec':pod}}})
        service={'apiVersion':'v1','kind':'Service','metadata':{'name':name,'namespace':ns},
                 'spec':{'selector':selector,'ports':[{'port':8000,'targetPort':8000}]}}
        if name=='edge':
            service['spec']['type']='NodePort'
            service['spec']['ports'][0]['nodePort']=30080
        items.append(service)
    edge_env={'LLM_URL':'http://llm-edge:8000','LOCAL_LLM_URL':'http://llm-local:8000','FEDERATION_URL':'http://federation:8000'}
    for n in 'abc':
        edge_env[f'AGENT_{n.upper()}_URL']=f'http://agent-{n}:8000'
        edge_env[f'WORKLOAD_{n.upper()}_URL']=f'http://workload-{n}:8000'
    add('edge','edge',env=edge_env)
    add('federation','federation',training=True,env={'EDGE_URL':'http://edge:8000'})
    add('llm-edge','llm',env={'MODEL_MODE':'edge'})
    add('llm-local','llm',role='A',env={'MODEL_MODE':'local'})
    for n in 'abc':
        account='fault-controller-'+n
        items.extend([
            {'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':account,'namespace':ns}},
            {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':{'name':account,'namespace':ns},
             'rules':[{'apiGroups':['apps'],'resources':['deployments/scale'],'resourceNames':['business-'+n],'verbs':['get','patch']}]},
            {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':account,'namespace':ns},
             'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':account},
             'subjects':[{'kind':'ServiceAccount','name':account,'namespace':ns}]}])
        add('agent-'+n,'agent',role=n.upper(),training=True,env={
            'NODE_ID':n,'TIER':n.upper(),'EDGE_URL':'http://edge:8000','FEDERATION_URL':'http://federation:8000',
            'WORKLOAD_URL':f'http://workload-{n}:8000','LOCAL_LLM_URL':'http://llm-local:8000'})
        add('workload-'+n,'k8s_workload',role=n.upper(),env={'NODE_ID':n,'POD_NAMESPACE':ns},service_account=account)
        add('business-'+n,'business',role=n.upper(),command=['python','-m','fedhelm.business','--standalone','--port','8000','--directory','/data'])
    return {'apiVersion':'v1','kind':'List','items':items}


if __name__=='__main__':
    path=Path('k8s/workloads.json')
    path.write_text(json.dumps(generate(),ensure_ascii=False,indent=2),encoding='utf-8')
    print(path)
