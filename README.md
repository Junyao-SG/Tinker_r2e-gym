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

## Guides

- [EKS Evaluation Guide](docs/eval-guide.md) — full walkthrough for cluster setup and running evals
- [Local Evaluation Guide](docs/local-eval-guide.md) — run evals on your local machine with Docker

## Makefile targets

| Target | Description |
|---|---|
| `make create-cluster` | Create EKS cluster |
| `make install-autoscaler` | Install cluster autoscaler via Helm |
| `make create-bucket` | Create S3 bucket for results |
| `make create-ecr` | Create ECR repository |
| `make create-secrets` | Create K8s secrets from `.env` |
| `make build` | Build Docker image |
| `make push` | Push to ECR |
| `make deploy` | Helm install (inference) |
| `make deploy-training` | Helm install (training with GRPO overrides) |
| `make upgrade` | Helm upgrade |
| `make uninstall` | Helm uninstall |
| `make logs` | Tail orchestrator logs |
| `make exec` | Exec into orchestrator pod |
| `make results` | Download results from S3 |
| `make teardown` | Uninstall Helm release and delete EKS cluster |
| `make lint` | Lint Helm chart |
| `make template` | Render Helm templates |

## Upstream R2E-Gym

This repo uses [R2E-Gym](https://github.com/R2E-Gym/R2E-Gym) as a dependency, installed in the Docker image from source. The `R2EGYM_REF` build arg (default: `main`) pins the upstream version:

```bash
make build R2EGYM_REF=abc1234
```
