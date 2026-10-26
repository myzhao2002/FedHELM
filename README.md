# FedHELM research prototype

FedHELM is a local research simulator for edge–end fault diagnosis, constrained remediation, feedback validation, federated encoder updates, and verified fault memory. It is a prototype, not a production repair system.

![FedHELM edge–end architecture](output/paper-figures/figure-1-fedhelm-architecture-v2.png)

*System architecture overview. The live dashboard is available after deployment.*

## Deploy the 16-node Docker Desktop simulation

This guide is for the setup you previously ran: a local Docker Desktop + kind cluster with **16 logical end nodes** (A: 5, B: 6, C: 5), hosted by **two Kubernetes node containers** (`fedhelm16-control-plane` and `fedhelm16-worker`). It does not emulate 16 physical servers. Each logical node has an Agent and an isolated test workload.

For a cluster already created, start Docker Desktop and run:

```powershell
.\open-k8s16.cmd
```

Open the [system console](http://127.0.0.1:16000/), [node topology](http://127.0.0.1:16000/topology), or [fault lab](http://127.0.0.1:16090/). To build and deploy for the first time, run `start-k8s16.cmd`; to recheck the node and storage counts, run `.\.venv\Scripts\python.exe -m scripts.verify_k8s16`.

The **main operation and deployment manual** is [docs/运行与复现.md](docs/运行与复现.md). It covers first deployment, daily startup, verification, UI workflow, data storage, troubleshooting, and migration to physical nodes. Use the verification steps there to check the cluster's current state before opening the UI.

## Train and evaluate on ALFA

ALFA is the public UAV sensor dataset used in the paper's real-data section. The repository includes the official archive downloader, preprocessing, sequence-level train/test split, centralized baseline, compact federated training, and evaluation report pipeline. On Windows with Python 3.12, create an environment once and download the official processed archive:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.training.txt
.\.venv\Scripts\python.exe -m pip install -r requirements.alfa.txt
.\.venv\Scripts\python.exe -m scripts.download_alfa
```

Run the centralized baseline or compact federated encoder training and evaluation:

```powershell
.\.venv\Scripts\python.exe -m scripts.train_alfa --method extra-trees --repeats 10 --seed 641 --output artifacts/alfa/my-baseline
.\.venv\Scripts\python.exe -m scripts.train_alfa --method fedhelm --rounds 80 --repeats 1 --seed 641 --output artifacts/alfa/my-fedhelm
```

Each output directory is new; completed runs are not overwritten. Reports include evaluation metrics, confusion matrices, sequence splits, predictions, and training-round details. See [ALFA training and evaluation](docs/ALFA实验说明.md) for the data protocol, model scope, and limitations. The ALFA UAV model has a different input schema and label set from the online service model, so it cannot be uploaded to the service nodes.

## Research figures and implementation notes

Editable vector and high-resolution PNG versions of Figures 1 and 2 are in [`output/paper-figures`](output/paper-figures). The generator is [`redraw_publication_figures.py`](output/paper-figures/redraw_publication_figures.py). The figures follow the manuscript's two-tier architecture and separate per-event remediation from round-based federated learning.

Local secrets, runtime records, trained artifacts, and downloaded ALFA files are excluded by `.gitignore`; ALFA remains subject to its own distribution terms. Paper PDFs and local machine configuration are not part of the code release. The code repository license is provided in `LICENSE` when selected by the rights holder.
