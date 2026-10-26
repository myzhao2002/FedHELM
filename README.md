# FedHELM

**An edge–end simulation platform for collaborative fault diagnosis and federated learning.**

[Overview](#overview) · [Quick start](#quick-start) · [Interface guide](#interface-guide) · [Simulation manual](SIMULATION.md) · [Physical-node deployment](SIMULATION.md#physical-node-deployment)

## Overview

FedHELM connects heterogeneous end nodes with a shared edge service. End nodes collect telemetry, run a lightweight fault encoder, select an inference mode, execute an allowed remediation action, and validate recovery. The edge service coordinates model APIs, fault memory, resource information, and federated model updates.

The default simulation contains **16 logical end nodes: 5 Tier-A, 6 Tier-B, and 5 Tier-C**. Each end node has its own Agent, test workload, model state, and persistent data. A kind cluster provides one control-plane container and one worker container to host the simulation.

## Components

| Component | Responsibility |
| --- | --- |
| End-node Agent | Telemetry collection, lightweight diagnosis, inference routing, local training, remediation, and recovery checks |
| Edge application | Fleet coordination, incident history, resource summaries, and the management console |
| Model API gateways | Separate `edge` and `local` inference roles with configurable providers, prompts, and usage limits |
| Fault-aware aggregator | Receives compressed updates, computes contribution weights, publishes model versions, and coordinates synchronization |
| Federated fault memory | Stores verified cases and supplies retrieved knowledge for subsequent diagnosis |
| Fault laboratory | Injects faults into isolated test workloads through a separate web endpoint |

The federated training path updates the fault encoder and classifier. Language models are accessed through the configured inference gateways.

## Quick start

Prepare a Docker engine running Linux containers, kind, and kubectl. Clone the repository:

~~~sh
git clone https://github.com/myzhao2002/FedHELM.git
cd FedHELM
docker info --format '{{.OSType}}'
kind version
kubectl version --client
~~~

Follow the command-by-command procedure in [SIMULATION.md](SIMULATION.md#deploy-the-simulation). If using the bundled PowerShell launcher, it performs the cluster creation, image build, Secret setup, and application deployment:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-k8s16.ps1
~~~

After the deployments become available, run these commands in **two separate terminals**:

~~~sh
kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/edge 16000:8000
~~~

~~~sh
kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/injector 16090:8000
~~~

Open the [management console](http://127.0.0.1:16000/) and the [fault laboratory](http://127.0.0.1:16090/). Keep the forwarding terminals active.

## Interface guide

| Page | What to inspect or control |
| --- | --- |
| [Overview](http://127.0.0.1:16000/) | Fleet status, current activity, and recent incidents |
| [Topology](http://127.0.0.1:16000/topology) | Edge–end relationships, observed transfers, and interactive node details |
| [Nodes and resources](http://127.0.0.1:16000/resources) | Agent availability, workload status, resource information, and node workspaces |
| [Telemetry](http://127.0.0.1:16000/telemetry) | Metric sequences, anomaly evidence, and monitoring activity |
| [Fault tasks](http://127.0.0.1:16000/tasks) | Timestamped diagnosis, routing, execution, and recovery timelines |
| [Models and transfers](http://127.0.0.1:16000/models) | Model inventory, versions, uploaded updates, aggregation, and synchronization |
| [Fault memory](http://127.0.0.1:16000/memory) | Verified cases and reusable remediation knowledge |
| [Data storage](http://127.0.0.1:16000/storage) | Persistent storage locations, records, and node artifacts |
| [Datasets](http://127.0.0.1:16000/datasets) | Per-node training data selection, import, preview, and evaluation |
| [Algorithms](http://127.0.0.1:16000/algorithms) | Inference costs, mode statistics, and aggregation contributions |
| [Model API settings](http://127.0.0.1:16000/settings) | Provider endpoints, model names, credential references, and call budgets |
| [Training workbench](http://127.0.0.1:16000/lab) | Manual collection, training, aggregation, synchronization, and diagnosis |
| [Operation logs](http://127.0.0.1:16000/logs) | Searchable, paginated operation records and input/output details |
| [Fault laboratory](http://127.0.0.1:16090/) | Inject or restore faults in a selected test workload |

## Run a fault-management session

1. Check the registered nodes and workload health in the console.
2. Configure the `edge` and `local` model roles in Model API settings.
3. Select a logical node and a fault in the separate fault laboratory.
4. Follow the resulting task: telemetry collection → lightweight diagnosis → memory fusion → mode selection → action plan → execution → recovery validation.
5. Inspect the node workspace, task evidence, and operation logs.
6. Prepare or import per-node training data, then follow the training, upload, aggregation, and synchronization records.
7. Review verified cases in fault memory.

Automatic monitoring and manual controls can be used from the same console. Task records retain the actual outcome of each operation.

## Model API configuration

Both model roles support OpenAI-compatible chat-completion endpoints. Configure the base URL, model identifier, credential file or environment variable, timeout, output-token limit, daily call limit, and minimum call interval.

The same interface accepts a hosted provider or a self-hosted inference service. Role-specific prompts are stored in [fedhelm/prompts](fedhelm/prompts). See [model API setup](SIMULATION.md#configure-model-apis) for the Secret mount and configuration procedure.

## Project structure

~~~text
FedHELM/
├── fedhelm/             # Agents, edge services, learning, memory, and web console
├── config/              # Cluster configuration
├── k8s/                 # Simulation manifests and kind configuration
├── scripts/             # Deployment, verification, and data tooling
├── tests/               # Automated checks
├── README.md            # Project overview and quick start
└── SIMULATION.md        # Deployment, operation, and physical-node migration
~~~

## Deployment and operation

The [simulation manual](SIMULATION.md) covers application counts, persistence, model credentials, fault injection, training controls, routine startup, updates, troubleshooting, and migration to physical nodes. Downloaded data, trained checkpoints, credentials, and runtime records are created locally during use.
