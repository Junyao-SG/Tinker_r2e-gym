# Running SWE-bench Evaluation on EKS

Step-by-step guide to deploy the cluster and run R2E-Gym evaluation.

## Prerequisites

- AWS CLI configured with appropriate permissions
- `eksctl`, `kubectl`, `helm` installed
- Docker (for building the orchestrator image)

## 1. Create the EKS Cluster

```bash
eksctl create cluster -f cluster/cluster.yaml
```

This provisions:
- A `tinker-r2egym` cluster in `us-east-1`
- A `system` node group (1x `m5.xlarge`) for cluster services
- A `cpu-sandbox` node group (0-20x `m5.4xlarge`) for sandbox pods, autoscaling

Verify:

```bash
kubectl get nodes
```

## 2. Build and Push Orchestrator Image

```bash
# Use the Makefile
make build push

# Or manually:
export ECR_REGISTRY=<your-account-id>.dkr.ecr.us-east-1.amazonaws.com

aws ecr create-repository --repository-name tinker-r2egym --region us-east-1
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_REGISTRY

docker build -f docker/Dockerfile.orchestrator -t $ECR_REGISTRY/tinker-r2egym:latest .
docker push $ECR_REGISTRY/tinker-r2egym:latest
```

## 3. Create Namespace and Secrets

```bash
kubectl create namespace default

kubectl create secret generic tinker-credentials \
  --from-literal=TINKER_API_KEY=your-tinker-key \
  --from-literal=WANDB_API_KEY=your-wandb-key \
  --from-literal=HF_TOKEN=your-huggingface-token
```

Or create from your `.env` file:

```bash
kubectl create secret generic tinker-credentials --from-env-file=.env
```

## 4. Deploy with Helm

```bash
helm install tinker-r2egym helm/tinker-r2egym \
  --set image.repository=$ECR_REGISTRY/tinker-r2egym \
  --set image.tag=latest \
  --set aws.s3.bucket=your-s3-bucket
```

Verify:

```bash
kubectl get pods                   # Orchestrator pod running
kubectl get networkpolicy          # Sandbox egress denied
```

## 5. Run Evaluation

Exec into the orchestrator pod:

```bash
ORCH_POD=$(kubectl get pod -l app=tinker-r2egym-orchestrator -o jsonpath='{.items[0].metadata.name}')

# Run R2E-Gym evaluation on SWE-bench Verified (5 tasks for smoke test)
kubectl exec $ORCH_POD -- python -m r2egym.agenthub.run.edit runagent_multiple \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split "test" \
  --k 5 \
  --max_workers 5 \
  --backend kubernetes \
  --llm_name "gpt-4o" \
  --traj_dir /data/results

# Full eval (all tasks)
kubectl exec $ORCH_POD -- python -m r2egym.agenthub.run.edit runagent_multiple \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split "test" \
  --k 2294 \
  --max_workers 20 \
  --backend kubernetes \
  --llm_name "gpt-4o" \
  --traj_dir /data/results
```

### What happens under the hood

1. R2E-Gym loads SWE-bench Verified from HuggingFace
2. For each task, creates a K8s sandbox pod on `cpu-sandbox` nodes
3. EKS Cluster Autoscaler adds more `m5.4xlarge` nodes if capacity is insufficient
4. Runs the ReAct agent inside each sandbox (up to 40 steps)
5. Computes reward via test execution
6. Destroys sandbox pods
7. Writes trajectory JSONL to `/data/results/`

### Pre-scaling nodes

```bash
# Scale up before a large run
eksctl scale nodegroup --cluster tinker-r2egym --name cpu-sandbox --nodes 5

# Scale back down after
eksctl scale nodegroup --cluster tinker-r2egym --name cpu-sandbox --nodes 0
```

## 6. Run Tinker GRPO Training

```bash
kubectl exec $ORCH_POD -- python -m tinker_r2egym.tinker_grpo \
  --config_path configs/grpo.yaml
```

This runs the full GRPO loop: rollout collection via R2E-Gym -> reward computation -> Tinker `forward_backward` -> `optim_step`.

## 7. Retrieve Results

```bash
aws s3 ls s3://your-s3-bucket/r2egym-trajectories/
aws s3 sync s3://your-s3-bucket/r2egym-trajectories/ ./results/
```

Or via kubectl:

```bash
kubectl cp $ORCH_POD:/data/results/ ./results/
```

## 8. Teardown

```bash
helm uninstall tinker-r2egym
eksctl delete cluster -f cluster/cluster.yaml --disable-nodegroup-eviction
```

## Tuning

Edit `helm/tinker-r2egym/values.yaml` or pass `--set` flags:

| Parameter | Default | What it controls |
|---|---|---|
| `sandbox.resources.limits.cpu` | `"4"` | CPU per sandbox pod |
| `sandbox.resources.limits.memory` | `8Gi` | RAM per sandbox pod |
| `sandbox.nodeSelector` | `{"role": "cpu-sandbox"}` | Which nodes run sandboxes |

Edit `cluster/cluster.yaml` for node group sizing:

| Parameter | Default | What it controls |
|---|---|---|
| `cpu-sandbox.instanceType` | `m5.4xlarge` | Instance type for sandbox nodes |
| `cpu-sandbox.desiredCapacity` | `0` | Initial node count |
| `cpu-sandbox.maxSize` | `20` | Max nodes the autoscaler can provision |
