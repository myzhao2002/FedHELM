# Simulation Deployment Guide

This guide deploys the FedHELM simulation, explains the management workflow, and describes how to move the services to physical nodes.

[Topology](#simulation-topology) · [Deployment](#deploy-the-simulation) · [Verification](#verify-the-deployment) · [Model APIs](#configure-model-apis) · [Operation](#operate-the-platform) · [Physical nodes](#physical-node-deployment)

## Simulation topology

The default cluster is named `fedhelm16`, with context `kind-fedhelm16` and namespace `fedhelm-cluster`.

| Resource | Deployment |
| --- | --- |
| Kubernetes nodes | One control-plane container and one worker container |
| Tier A | `agent-a01` through `agent-a05` |
| Tier B | `agent-b01` through `agent-b06` |
| Tier C | `agent-c01` through `agent-c05` |
| End-node Pod | Agent container and isolated test-workload container |
| Edge Pod | Management application, aggregator, edge-model gateway, and local-model gateway |
| Fault laboratory Pod | Separate injector service |
| Persistent storage | One PVC per logical end node, one for edge services, and one for the fault laboratory |

The application comprises **18 Deployments, 18 Pods, 37 containers, and 18 PVCs** after rollout. These counts exclude Kubernetes system components. Each logical end node owns its model state, observations, local training data, and test workload.

## Prerequisites

| Tool or resource | Purpose |
| --- | --- |
| Docker engine with Linux containers | Runs the kind nodes and builds application images |
| kind | Creates the simulation cluster |
| kubectl | Applies manifests, checks resources, and forwards web endpoints |
| Python 3.12 | Creates an internal token and runs host-side verification or data tools |
| PowerShell, optional | Runs the bundled deployment and forwarding helpers |
| Available memory and disk space | Stores the container images, kind cluster, and persistent volumes |

Check the tools before deployment:

~~~sh
docker info --format '{{.OSType}}'
kind version
kubectl version --client
python --version
~~~

The Docker command should return `linux`. Image builds install the application dependencies and CPU PyTorch inside the image. The configured model-provider endpoint determines where language-model inference runs.

## Deploy the simulation

### 1. Obtain the code

~~~sh
git clone https://github.com/myzhao2002/FedHELM.git
cd FedHELM
~~~

All following commands run from the repository root.

### 2. Choose a deployment method

The bundled PowerShell launcher automates the remaining setup:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-k8s16.ps1
~~~

It creates or reuses the dedicated kind cluster, builds the application image, loads it into kind, creates the internal-auth Secret when needed, applies the manifests, restarts application Deployments, and waits for availability.

For a command-by-command deployment, use the steps below.

### 3. Create the cluster and build the image

Run the cluster-creation command on first deployment. For an existing cluster, check `kind get clusters` and reuse `fedhelm16`.

~~~sh
kind create cluster --name fedhelm16 --config k8s/kind16.yaml --wait 180s
docker build -f Dockerfile.training -t fedhelm-cluster:k8s16 .
kind load docker-image fedhelm-cluster:k8s16 --name fedhelm16
kubectl --context kind-fedhelm16 apply -f k8s/namespace16.json
~~~

The base image is selected by the `PYTHON_IMAGE` build argument in `Dockerfile.training`. To use another accessible registry:

~~~sh
docker build --build-arg PYTHON_IMAGE=python:3.12-slim -f Dockerfile.training -t fedhelm-cluster:k8s16 .
kind load docker-image fedhelm-cluster:k8s16 --name fedhelm16
~~~

### 4. Create the internal service token

On first deployment, create a shared internal token and a Kubernetes Secret. Reuse the existing `internal-auth` Secret on subsequent starts.

~~~sh
python -c "from pathlib import Path; import secrets; p=Path('secrets/k8s-internal.token'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(secrets.token_urlsafe(32), encoding='utf-8')"
kubectl --context kind-fedhelm16 -n fedhelm-cluster create secret generic internal-auth --from-file=token=secrets/k8s-internal.token
~~~

The Secret supplies the same internal authentication token to the communicating services.

### 5. Apply the application manifests

~~~sh
kubectl --context kind-fedhelm16 apply -f k8s/cluster16-local.json
kubectl --context kind-fedhelm16 -n fedhelm-cluster wait --for=condition=Available deployment --all --timeout=600s
kubectl --context kind-fedhelm16 -n fedhelm-cluster get pods,pvc,svc -o wide
~~~

### 6. Open the web endpoints

Run each forwarding command in its own terminal:

~~~sh
kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/edge 16000:8000
~~~

~~~sh
kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/injector 16090:8000
~~~

| Endpoint | Address |
| --- | --- |
| Management console | http://127.0.0.1:16000/ |
| Interactive topology | http://127.0.0.1:16000/topology |
| Fault laboratory | http://127.0.0.1:16090/ |
| Edge API reference | http://127.0.0.1:16000/docs |

Keep both forwarding terminals active. Re-establish forwarding after the corresponding Pod is replaced. The `open-k8s16.ps1` helper also provides background forwarding and writes its output to `runtime/forward-*.log`.

## Verify the deployment

Check the infrastructure and application:

~~~sh
kubectl --context kind-fedhelm16 get nodes -o wide
kubectl --context kind-fedhelm16 -n fedhelm-cluster get deployments,pods,pvc
python -m scripts.verify_k8s16
~~~

The verifier writes `runtime/k8s16-verification.json`. Its checks cover:

- The expected Agent IDs and A5/B6/C5 tier distribution.
- Available Deployments and ready containers.
- Eighteen bound persistent-volume claims.
- Agent connectivity through the management API.

A successful verification report contains `"passed": true`. Workload health is recorded separately so that a previously injected fault remains visible.

## Configure model APIs

Open [Model API settings](http://127.0.0.1:16000/settings). Configure the two inference roles independently:

| Role | Usage |
| --- | --- |
| `edge` | Shared diagnosis review and action planning through the edge gateway |
| `local` | The inference role available to Tier-A nodes |

Both gateways support OpenAI-compatible `/chat/completions` endpoints. They accept hosted providers or a self-hosted inference service.

### Mount a provider credential

Create a local file named `secrets/provider-api.key` containing your own provider credential. Create or update the optional Secret:

~~~sh
kubectl --context kind-fedhelm16 -n fedhelm-cluster create secret generic provider-key --from-file=provider-api.key=secrets/provider-api.key --dry-run=client -o yaml | kubectl --context kind-fedhelm16 apply -f -
~~~

In the settings page, use `/secrets/provider-api.key` as the credential-file path. This is a file reference; the credential value is read from the mounted Secret. The `secrets/` directory is excluded from Git and the image build context.

### Set the role configuration

| Field | Setting |
| --- | --- |
| Mode | `openai-compatible` |
| Base URL | The provider's compatible API base, including its version path when required |
| Model | The model identifier supported by that endpoint |
| Credential file | `/secrets/provider-api.key`, or another mounted credential path |
| Deployment | `cloud-api` or `self-hosted` |
| Maximum output tokens | The response-size budget |
| Daily call limit | The maximum number of requests reserved for the role per day |
| Minimum call interval | The minimum interval between calls |
| Timeout | The allowed response wait time |

The gateways append `/chat/completions` to the base URL. Choose an address reachable from the gateway container. A self-hosted model endpoint can be exposed through a Kubernetes Service or a reachable host address.

Role prompts are in `fedhelm/prompts/edge.txt` and `fedhelm/prompts/local.txt`. The gateway uses structured JSON responses and validates the proposed action against the allowed remediation actions.

## Operate the platform

### Fleet and telemetry

Use Overview and Topology to inspect the edge service and registered end nodes. Click a node to open its workspace, including service status, observations, current model version, storage, and incident history.

The Telemetry page shows metric sequences and anomaly evidence. Model and memory transfers appear in their corresponding histories and in the topology's observed traffic activity.

### Inject a workload fault

Open the separate [fault laboratory](http://127.0.0.1:16090/), select a node, and choose an available fault:

| Fault | Test-workload effect |
| --- | --- |
| Service interruption | Stops the managed test-workload process |
| Configuration error | Applies an invalid test database configuration |
| Database connection-pool exhaustion | Occupies the test SQLite connection pool |
| Worker-pool exhaustion | Occupies the test workload's worker threads |
| Dependency timeout | Delays the test dependency response |

Injection targets the selected isolated workload. Monitoring collects the resulting observations, and the diagnosis path uses that telemetry.

### Follow an incident

Open the task from Fault tasks and inspect its timestamped stages:

1. Observation collection and anomaly detection.
2. Lightweight diagnosis and memory fusion.
3. Inference-mode selection.
4. Action-plan generation.
5. Allowed remediation execution.
6. Recovery sampling and validation.
7. Case review and storage, when applicable.

Task details include the stage inputs, outputs, execution status, and elapsed time. Operation logs provide filters, pagination, and record details. Use the laboratory's restore action when a manual workload reset is needed.

### Run federated training

The Datasets page selects each node's training data and supports import, preview, and evaluation. Prepare active training and validation partitions for every participating node.

The Training workbench provides manual actions and automatic-round controls. The automatic controller supports an enable switch, a round interval, and a cumulative round limit. It runs one node's local training at a time, uploads the update, aggregates the round, and synchronizes model versions.

Observe the round's task records and the Models and transfers page to follow:

~~~text
Global model synchronization
    -> Per-node local training
    -> Compressed update upload
    -> Contribution-weighted aggregation
    -> Global model publication
    -> End-node synchronization and version confirmation
~~~

The controller exposes its status at `GET /ui/training`, configuration at `PUT /ui/training`, and an execute/resume action at `POST /ui/training/run`. Paused or waiting rounds retain their recorded state.

### Inspect persistence

| Storage | Contents |
| --- | --- |
| Each Agent PVC | Local observations, datasets, model checkpoints, and node records |
| Edge PVC | Fault memory, model versions, provider configuration, and coordination history |
| Fault laboratory PVC | Injection and restoration records |
| Provider-key Secret | Mounted model-provider credential |

Use Data storage and node workspaces to inspect stored artifacts. Training state and records remain on the persistent volumes across Pod replacements.

## Routine startup, updates, and shutdown

For an existing simulation, start the two kind containers if they are stopped:

~~~sh
docker start fedhelm16-control-plane fedhelm16-worker
kubectl --context kind-fedhelm16 wait --for=condition=Ready nodes --all --timeout=180s
~~~

Then re-establish the two port-forwarding sessions.

After changing application code, rebuild and reload the image, then restart the Deployments:

~~~sh
docker build -f Dockerfile.training -t fedhelm-cluster:k8s16 .
kind load docker-image fedhelm-cluster:k8s16 --name fedhelm16
kubectl --context kind-fedhelm16 -n fedhelm-cluster rollout restart deployment
kubectl --context kind-fedhelm16 -n fedhelm-cluster wait --for=condition=Available deployment --all --timeout=600s
~~~

To stop the simulation while retaining the kind containers and their local volumes:

~~~sh
docker stop fedhelm16-worker fedhelm16-control-plane
~~~

Cluster deletion and PVC deletion are separate cleanup operations. Back up persistent data before removing a cluster or its volumes.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Docker engine unavailable | Start the container engine and inspect its diagnostics before running kind |
| Image build or pull failure | Check registry access, proxy settings, the base-image argument, and package-download logs |
| Pending Pod | Inspect Pod events, requested resources, and PVC binding |
| ImagePullBackOff | Confirm that the image was loaded into kind or is reachable in the configured registry |
| CrashLoopBackOff | Inspect the affected container's current and previous logs |
| Web endpoint unavailable | Check Pod readiness and restart the relevant port-forwarding session |
| Fault laboratory cannot reach the management service | Check the edge Service and its ready endpoints |
| Plan generation waiting or failed | Check the selected model role, endpoint, credential reference, call budget, and task details |
| Training round waiting | Check Agent availability, active training partitions, current anomalies, and the recorded wait reason |
| Slow interface responses | Inspect resource utilization, Agent timeouts, and concurrent training or deployment activity |

Useful diagnostic commands:

~~~sh
kubectl --context kind-fedhelm16 -n fedhelm-cluster get events --sort-by=.metadata.creationTimestamp
kubectl --context kind-fedhelm16 -n fedhelm-cluster logs deployment/edge -c edge8000 --tail=100
kubectl --context kind-fedhelm16 -n fedhelm-cluster logs deployment/agent-a01 -c agent8000 --tail=100
kubectl --context kind-fedhelm16 -n fedhelm-cluster describe pod <pod-name>
~~~

## Physical-node deployment

The service contracts and Agent workflow can also be deployed on a Kubernetes cluster backed by physical machines.

1. Build and publish the application image to a registry reachable by every node.
2. Generate manifests with the published image and the intended public console URLs.
3. Create the namespace and internal-auth Secret in the target context.
4. Select an appropriate StorageClass for each PVC.
5. Label physical nodes and assign Agent Deployments with node selectors or affinity.
6. Configure reachable model endpoints and mount provider credentials.
7. Connect the workload adapter to the intended telemetry sources, allowed remediation actions, and recovery checks.
8. Verify service connectivity, node placement, persistence, and model synchronization.

Example image publication and manifest generation:

~~~sh
docker build -f Dockerfile.training -t registry.example.org/fedhelm:simulation .
docker push registry.example.org/fedhelm:simulation
python -m scripts.cluster_manifest --config config/cluster.local.json --image registry.example.org/fedhelm:simulation --console-url https://console.example.org --injector-public-url https://faultlab.example.org --output k8s/physical-cluster.json
~~~

Label a physical node and select it for a logical Agent:

~~~sh
kubectl --context <target-context> label node <node-name> fedhelm-node-id=a01
kubectl --context <target-context> -n fedhelm-cluster patch deployment agent-a01 --type merge -p '{"spec":{"template":{"spec":{"nodeSelector":{"fedhelm-node-id":"a01"}}}}}'
~~~

Repeat the placement configuration for the intended node-to-Agent mapping. For a node-local SLM service, deploy the inference endpoint on the relevant Tier-A machine and configure the Agent's local inference address.

A standalone-host deployment can use `config/cluster.local.json` with reachable service addresses and host metadata. Deploy the corresponding Agent and workload adapter on each machine, and run the edge services at their shared address. Keep authentication tokens consistent across the communicating services.
