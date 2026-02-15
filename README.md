# Tinker_r2e-gym

R2E-Gym on EKS with Tinker GRPO training. Runs SWE-bench evaluation and RL training for code agents using [R2E-Gym](https://github.com/R2E-Gym/R2E-Gym) as the environment and [Tinker](https://www.thinkingmachines.ai/) for model training/inference.

## Architecture

```
EKS Cluster
├── System Node Group (m5.xlarge, 1→3)
│   ├── Orchestrator Pod — r2e-gym + tinker training code
│   └── Tinker Proxy Pod — OpenAI-compatible API → Tinker SDK (optional)
│
└── Sandbox Node Group (m5.4xlarge, 0→20)
    └── Ephemeral sandbox pods (created/deleted by orchestrator via K8s API)
```

The orchestrator Docker image layers upstream R2E-Gym with this repo's Tinker training code. R2E-Gym is installed as-is from the upstream repo (pinned via `R2EGYM_REF` build arg), keeping the dependency clean and easy to update.

## Quick Start

### Prerequisites

- AWS CLI, `eksctl`, `kubectl`, `helm`, Docker
- Tinker API key
- AWS account with EKS/ECR permissions

### 1. Create the EKS cluster

```bash
./scripts/setup-cluster.sh
```

### 2. Create secrets

```bash
kubectl create secret generic tinker-credentials \
  --from-literal=TINKER_API_KEY=<key> \
  --from-literal=WANDB_API_KEY=<key> \
  --from-literal=HF_TOKEN=<token>
```

### 3. Build, push, deploy

```bash
# Set your ECR registry
export ECR_REGISTRY=<account-id>.dkr.ecr.us-east-1.amazonaws.com

make build push deploy
```

### 4. Run inference

```bash
make exec
# Inside the pod:
python -m r2egym.agenthub.run.edit runagent_multiple \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split "test" --k 5 --max_workers 5 \
  --backend kubernetes --llm_name "gpt-4o" \
  --traj_dir /data/results
```

### 5. Run GRPO training

```bash
# Deploy with proxy enabled
make deploy-training

make exec
# Inside the pod:
python -m tinker_r2egym.tinker_grpo --config_path configs/grpo.yaml
```

## Modes

### Inference

Uses an external LLM (e.g. GPT-4o) or Tinker proxy for agent inference. Deploy with default values:

```bash
helm install tinker-r2egym helm/tinker-r2egym \
  --set image.repository=$ECR_REGISTRY/tinker-r2egym
```

### Training (GRPO)

Deploys the Tinker proxy alongside the orchestrator. The proxy serves a Tinker model via OpenAI-compatible API, and the GRPO loop collects rollouts and trains the model:

```bash
helm install tinker-r2egym helm/tinker-r2egym \
  -f helm/tinker-r2egym/values-training.yaml \
  --set image.repository=$ECR_REGISTRY/tinker-r2egym \
  --set proxy.image.repository=$ECR_REGISTRY/tinker-r2egym-proxy
```

## Configuration

### Helm values

| Parameter | Default | Description |
|---|---|---|
| `image.repository` | `""` | ECR image URI (required) |
| `image.tag` | `"latest"` | Image tag |
| `proxy.enabled` | `false` | Deploy Tinker proxy |
| `proxy.model.name` | `"Qwen/Qwen3-30B-A3B"` | Model for proxy |
| `sandbox.nodeSelector` | `'{"role": "cpu-sandbox"}'` | Node selector for sandboxes |
| `sandbox.resources.limits.cpu` | `"4"` | CPU limit per sandbox |
| `sandbox.resources.limits.memory` | `"8Gi"` | Memory limit per sandbox |
| `aws.s3.bucket` | `""` | S3 bucket for results |

See `helm/tinker-r2egym/values.yaml` for all options.

### GRPO training config

Edit `configs/grpo.yaml`:

| Parameter | Default | Description |
|---|---|---|
| `model.model_name` | `"Qwen/Qwen3-30B-A3B"` | Base model |
| `training.learning_rate` | `2.0e-5` | Learning rate |
| `training.group_size` | `10` | Rollouts per task (GRPO) |
| `training.num_steps` | `1000` | Training steps |
| `rollout.max_workers` | `20` | Parallel sandboxes |
| `rollout.backend` | `"kubernetes"` | `kubernetes` or `docker` |

## Makefile targets

| Target | Description |
|---|---|
| `make build` | Build Docker images |
| `make push` | Push to ECR |
| `make deploy` | Helm install (inference) |
| `make deploy-training` | Helm install (training with proxy) |
| `make upgrade` | Helm upgrade |
| `make uninstall` | Helm uninstall |
| `make logs` | Tail orchestrator logs |
| `make exec` | Exec into orchestrator pod |
| `make results` | Download results from S3 |
| `make lint` | Lint Helm chart |
| `make template` | Render Helm templates |

## Guides

- [EKS Evaluation Guide](docs/eval-guide.md)
- [Local Evaluation Guide](docs/local-eval-guide.md)

## Upstream R2E-Gym

This repo uses [R2E-Gym](https://github.com/R2E-Gym/R2E-Gym) as a dependency, installed in the Docker image from source. The `R2EGYM_REF` build arg (default: `main`) pins the upstream version:

```bash
# Build with a specific upstream commit
make build R2EGYM_REF=abc1234
```
