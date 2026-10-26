"""Explicit, dedicated-context Kubernetes deployment helper. Never deletes clusters."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import webbrowser


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['up','status','open'],default='up',nargs='?')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    os.chdir(root)
    config=root/'runtime/kubeconfig-fedhelm'
    config.parent.mkdir(exist_ok=True)
    kind=str(root/'tools/kind.exe') if os.name=='nt' else shutil.which('kind')
    if not kind or not Path(kind).exists():
        raise SystemExit('kind is missing. Install the official kind binary; see docs/kubernetes.md.')
    def run(command):
        print(' '.join(map(str,command)),flush=True)
        subprocess.run(list(map(str,command)),check=True)
    kube=['kubectl','--kubeconfig',str(config),'--context','kind-fedhelm']
    if args.action=='open':
        run(kube+['get','deployments','-n','fedhelm'])
        webbrowser.open('http://127.0.0.1:13000/')
        return
    if args.action=='status':
        run(kube+['get','nodes','-o','wide'])
        run(kube+['get','pods','-n','fedhelm','-o','wide'])
        return
    run(['docker','info','--format','{{.ServerVersion}}'])
    clusters=subprocess.check_output([kind,'get','clusters'],text=True).splitlines()
    if 'fedhelm' not in clusters:
        run([kind,'create','cluster','--name','fedhelm','--config','k8s/kind.yaml','--kubeconfig',config,'--wait','120s'])
    elif not config.exists():
        run([kind,'export','kubeconfig','--name','fedhelm','--kubeconfig',config])
    run(['docker','build','-f','Dockerfile.training','-t','fedhelm-training:v1','.'])
    run([kind,'load','docker-image','fedhelm-training:v1','--name','fedhelm'])
    from scripts.k8s_manifest import generate
    import json
    Path('k8s/workloads.json').write_text(json.dumps(generate(),ensure_ascii=False,indent=2),encoding='utf-8')
    run(kube+['apply','-f','k8s/workloads.json'])
    run(kube+['rollout','restart','deployment','-n','fedhelm'])
    run(kube+['rollout','status','deployment','-n','fedhelm','--timeout=240s'])
    run(kube+['get','pods','-n','fedhelm','-o','wide'])
    webbrowser.open('http://127.0.0.1:13000/')


if __name__=='__main__':
    main()
