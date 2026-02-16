# Tinker_r2e-gym

R2E-Gym on EKS with Tinker GRPO training. Runs SWE-bench evaluation and RL training for code agents using [R2E-Gym](https://github.com/R2E-Gym/R2E-Gym) as the environment and [Tinker](https://www.thinkingmachines.ai/) for model training/inference.

## Architecture

```
EKS Cluster
├── System Node Group (m5.xlarge, 1–3)
│   ├── Orchestrator Pod — R2E-Gym + Tinker training code
│   └── Tinker Proxy Pod — OpenAI-compatible API adapter for Tinker SDK
│
└── Sandbox Node Group (m5.4xlarge, 0–20)
    └── Ephemeral sandbox pods (created/deleted by orchestrator via K8s API)
```

A single Docker image contains both upstream R2E-Gym and this repo's Tinker code. The orchestrator pod runs `sleep infinity` and you exec in to launch jobs. The proxy pod runs the same image with a different entrypoint (`tinker_r2egym.tinker_proxy`), serving Tinker models via an OpenAI-compatible `/v1/chat/completions` endpoint.

## Quick Start

### Prerequisites

- AWS CLI, `eksctl`, `kubectl`, `helm`, Docker
- Tinker API key
- AWS account with EKS/ECR permissions

### 1. Create the EKS cluster

```bash
eksctl create cluster -f cluster/cluster.yaml
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
export ECR_REGISTRY=<account-id>.dkr.ecr.us-east-1.amazonaws.com

make create-ecr
make build push deploy
```

> Use `--set serviceAccount.create=false` (already the default) if the ServiceAccount was created by `eksctl` via IRSA in `cluster.yaml`.

### 4. Run evaluation

```bash
make exec
# Inside the pod:
python -m tinker_r2egym.run_eval \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split test --k 5 --max_workers 5 \
  --backend kubernetes \
  --traj_dir /data/results
```

### 5. Run GRPO training

```bash
make deploy-training   # redeploy with training values

make exec
# Inside the pod:
python -m tinker_r2egym.tinker_grpo --config_path configs/grpo.yaml
```

## Modes

Both modes deploy the Tinker proxy, which serves a Tinker-hosted model via an OpenAI-compatible API. R2E-Gym agents call the proxy using `LLM_BASE_URL` (set automatically by the configmap).

### Inference (evaluation)

```bash
make deploy
```

### Training (GRPO)

Uses `values-training.yaml` overrides (higher temperature, more workers, group_size for GRPO):

```bash
make deploy-training
```

## Configuration

### Helm values

| Parameter | Default | Description |
|---|---|---|
| `image.repository` | `""` | ECR image URI (required) |
| `image.tag` | `"latest"` | Image tag |
| `proxy.enabled` | `true` | Deploy Tinker proxy |
| `proxy.model.name` | `"Qwen/Qwen3-30B-A3B"` | Model for proxy |
| `serviceAccount.create` | `false` | Create SA (set false when using eksctl IRSA) |
| `aws.s3.bucket` | `""` | S3 bucket for results (required) |
| `aws.s3.prefix` | `"r2egym-trajectories"` | S3 key prefix |
| `sandbox.nodeSelector` | `{"role": "cpu-sandbox"}` | Node selector for sandboxes |
| `sandbox.resources.limits.cpu` | `"4"` | CPU limit per sandbox |
| `sandbox.resources.limits.memory` | `"8Gi"` | Memory limit per sandbox |

See [values.yaml](helm/tinker-r2egym/values.yaml) for all options.

### GRPO training config

Edit [configs/grpo.yaml](configs/grpo.yaml):

| Parameter | Default | Description |
|---|---|---|
| `model.model_name` | `"Qwen/Qwen3-30B-A3B"` | Base model |
| `training.learning_rate` | `2.0e-5` | Learning rate |
| `training.group_size` | `10` | Rollouts per task (GRPO) |
| `training.num_steps` | `1000` | Training steps |
| `rollout.max_workers` | `20` | Parallel sandboxes |
| `rollout.backend` | `"kubernetes"` | `kubernetes` or `docker` |
| `rollout.use_fn_calling` | `false` | Use OpenAI function calling (false for open-weight models) |

## Makefile targets

| Target | Description |
|---|---|
| `make build` | Build Docker image |
| `make push` | Push to ECR |
| `make deploy` | Helm install (inference) |
| `make deploy-training` | Helm install (training with GRPO overrides) |
| `make upgrade` | Helm upgrade |
| `make uninstall` | Helm uninstall |
| `make logs` | Tail orchestrator logs |
| `make exec` | Exec into orchestrator pod |
| `make results` | Download results from S3 |
| `make create-ecr` | Create ECR repository |
| `make create-bucket` | Create S3 bucket |
| `make lint` | Lint Helm chart |
| `make template` | Render Helm templates |

## Guides

- [EKS Evaluation Guide](docs/eval-guide.md) — full walkthrough for cluster setup and running evals
- [Local Evaluation Guide](docs/local-eval-guide.md) — run evals on your local machine with Docker

## Upstream R2E-Gym

This repo uses [R2E-Gym](https://github.com/R2E-Gym/R2E-Gym) as a dependency, installed in the Docker image from source. The `R2EGYM_REF` build arg (default: `main`) pins the upstream version:

```bash
make build R2EGYM_REF=abc1234
```
