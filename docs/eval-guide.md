# Running SWE-bench Evaluation on EKS

Step-by-step guide to deploy the cluster and run R2E-Gym evaluation.

## Prerequisites

- AWS CLI configured with appropriate permissions
- `eksctl`, `kubectl`, `helm` installed
- Docker (for building the image)

## 1. Create the EKS Cluster

```bash
eksctl create cluster -f cluster/cluster.yaml
```

This provisions:
- A `tinker-r2egym` cluster in `us-east-1`
- A `system` node group (1x `m5.large`) for the orchestrator and proxy pods
- A `cpu-sandbox` node group (0–20 spot instances, c5/m5 family) for sandbox pods, with autoscaling

Verify:

```bash
kubectl get nodes
```

## 2. Build and Push the Image

```bash
make create-ecr
make build push
```

## 3. Create Secrets

```bash
kubectl create secret generic tinker-credentials --from-env-file=.env
```

## 4. Deploy with Helm

```bash
# Inference mode
make deploy

# Or training mode (higher temperature, more workers)
make deploy-training
```

Or manually:

```bash
helm install tinker-r2egym helm/tinker-r2egym \
  --set image.repository=$ECR_REGISTRY/tinker-r2egym \
  --set image.tag=latest \
  --set aws.s3.bucket=your-s3-bucket \
  --set aws.s3.prefix=r2egym-trajectories
```

> The default `serviceAccount.create=false` assumes the SA was already created by `eksctl` via IRSA in `cluster.yaml`. Set `--set serviceAccount.create=true` if you need Helm to create it.

Verify:

```bash
kubectl get pods                   # Orchestrator + proxy pods running
kubectl get networkpolicy          # Sandbox egress denied
```

## 5. Run Evaluation

Exec into the orchestrator pod:

```bash
make exec

# Smoke test — 5 tasks
python -m tinker_r2egym.run_eval \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split test \
  --k 5 \
  --max_workers 5 \
  --backend kubernetes \
  --traj_dir /data/results

# Full eval (all tasks)
python -m tinker_r2egym.run_eval \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split test \
  --k 2294 \
  --max_workers 20 \
  --backend kubernetes \
  --traj_dir /data/results
```

> `LLM_NAME` and `LLM_BASE_URL` are set automatically via the configmap when `proxy.enabled: true`. No need to set them manually.

### What happens under the hood

1. R2E-Gym loads SWE-bench Verified from HuggingFace
2. For each task, creates a K8s sandbox pod on `cpu-sandbox` nodes
3. EKS autoscaler adds more `m5.4xlarge` nodes if capacity is insufficient
4. Runs the ReAct agent inside each sandbox (up to 40 steps)
5. The agent calls the Tinker proxy (`openai/tinker` via `LLM_BASE_URL`) for LLM inference
6. Computes reward via test execution
7. Destroys sandbox pods
8. Writes trajectory JSONL to `/data/results/` and syncs to S3

### Pre-scaling nodes

```bash
# Scale up before a large run
eksctl scale nodegroup --cluster tinker-r2egym --name cpu-sandbox --nodes 5

# Scale back down after
eksctl scale nodegroup --cluster tinker-r2egym --name cpu-sandbox --nodes 0
```

## 6. Run GRPO Training

```bash
make exec

python -m tinker_r2egym.tinker_grpo --config_path configs/grpo.yaml
```

This runs the full GRPO loop: rollout collection via R2E-Gym -> reward computation -> Tinker `forward_backward` -> `optim_step`.

## 7. Retrieve Results

```bash
make results S3_BUCKET=your-s3-bucket
```

Or via kubectl:

```bash
ORCH_POD=$(kubectl get pod -l app=tinker-r2egym-orchestrator -o jsonpath='{.items[0].metadata.name}')
kubectl cp $ORCH_POD:/data/results/ ./results/
```

## 8. Teardown

```bash
helm uninstall tinker-r2egym
eksctl delete cluster --name tinker-r2egym --region us-east-1
```

## Tuning

Edit `helm/tinker-r2egym/values.yaml` or pass `--set` flags:

| Parameter | Default | What it controls |
|---|---|---|
| `sandbox.resources.limits.cpu` | `"4"` | CPU per sandbox pod |
| `sandbox.resources.limits.memory` | `"8Gi"` | RAM per sandbox pod |
| `sandbox.nodeSelector` | `{"role": "cpu-sandbox"}` | Which nodes run sandboxes |

Edit `cluster/cluster.yaml` for node group sizing:

| Parameter | Default | What it controls |
|---|---|---|
| `cpu-sandbox.instanceTypes` | `c5.2xlarge`, `c5a.2xlarge`, etc. | Spot instance types for sandbox nodes |
| `cpu-sandbox.desiredCapacity` | `0` | Initial node count |
| `cpu-sandbox.maxSize` | `20` | Max nodes the autoscaler can provision |
