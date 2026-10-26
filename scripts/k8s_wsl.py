"""Use the existing independent Ubuntu Docker Engine, not Docker Desktop."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import webbrowser


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['up','status','open'],nargs='?',default='open')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    os.chdir(root)
    config=root/'runtime/kubeconfig-fedhelm-wsl'
    kube=['kubectl','--kubeconfig',str(config),'--context','kind-fedhelm-wsl']
    def run(cmd):
        print(' '.join(map(str,cmd)),flush=True)
        subprocess.run(list(map(str,cmd)),check=True)
    linux_root=subprocess.check_output(['wsl','-d','Ubuntu','-u','root','--','wslpath','-u',str(root)],text=True).strip()
    def linux(cmd):
        run(['wsl','-d','Ubuntu','-u','root','--','sh','-lc','cd '+shlex.quote(linux_root)+' && '+shlex.join(cmd)])
    if args.action=='up':
        linux(['docker','info','--format','{{.ServerVersion}}'])
        clusters=subprocess.check_output(['wsl','-d','Ubuntu','-u','root','--',linux_root+'/tools/kind-linux','get','clusters'],text=True).splitlines()
        if 'fedhelm-wsl' not in clusters:
            linux(['tools/kind-linux','create','cluster','--name','fedhelm-wsl','--config','k8s/kind.yaml','--kubeconfig','runtime/kubeconfig-fedhelm-wsl','--wait','120s'])
        linux(['docker','build','-f','Dockerfile.training','-t','fedhelm-training:v1','.'])
        linux(['tools/kind-linux','load','docker-image','fedhelm-training:v1','--name','fedhelm-wsl'])
        from scripts.k8s_manifest import generate
        Path('k8s/workloads.json').write_text(json.dumps(generate(),ensure_ascii=False,indent=2),encoding='utf-8')
        run(kube+['apply','-f','k8s/workloads.json'])
        run(kube+['rollout','restart','deployment','-n','fedhelm'])
        run(kube+['rollout','status','deployment','-n','fedhelm','--timeout=240s'])
    run(kube+['get','nodes','-o','wide'])
    run(kube+['get','pods','-n','fedhelm','-o','wide'])
    if args.action!='status':
        webbrowser.open('http://127.0.0.1:13000/')


if __name__=='__main__':
    main()
