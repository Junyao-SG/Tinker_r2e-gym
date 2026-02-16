# Running SWE-bench Evaluation Locally

Run R2E-Gym evaluation on your local machine using Docker containers and Tinker for inference.

## Prerequisites

- Python 3.10+
- Docker Desktop running
- Tinker API key (sign up at https://auth.thinkingmachines.ai/sign-up)

## 1. Install R2E-Gym

```bash
git clone https://github.com/R2E-Gym/R2E-Gym.git
cd R2E-Gym
uv venv && source .venv/bin/activate
uv sync && uv pip install -e .
```

Install this repo's code and the Tinker SDK into the same venv:

```bash
uv pip install -e /path/to/Tinker_r2e-gym
uv pip install tinker
```

## 2. Set API Key

```bash
export TINKER_API_KEY=your-tinker-key
```

## 3. Start the Tinker Inference Proxy

R2E-Gym uses LiteLLM internally (OpenAI-compatible). The proxy bridges Tinker's SamplingClient to an OpenAI-compatible `/v1/chat/completions` endpoint.

```bash
# Serve a base model
python -m tinker_r2egym.tinker_proxy --model_name "Qwen/Qwen3-30B-A3B"

# Or serve a fine-tuned checkpoint after GRPO training
python -m tinker_r2egym.tinker_proxy \
  --model_name "Qwen/Qwen3-30B-A3B" \
  --weights_path "tinker://run-id/weights/checkpoint-000050"
```

The proxy starts at `http://localhost:8080`. Keep it running in a separate terminal.

## 4. Run Evaluation

Run from the R2E-Gym directory (where `src/r2egym/` lives):

```bash
cd R2E-Gym

# Smoke test — 2 tasks
OPENAI_API_KEY=sk-placeholder \
LLM_BASE_URL=http://localhost:8080/v1 \
python src/r2egym/agenthub/run/edit.py runagent_multiple \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split "test" \
  --k 2 \
  --max_workers 2 \
  --backend docker \
  --llm_name "openai/tinker" \
  --temperature 0 \
  --max_steps 40 \
  --traj_dir ./results \
  --use_fn_calling False

# Full eval — all 2294 tasks
OPENAI_API_KEY=sk-placeholder \
LLM_BASE_URL=http://localhost:8080/v1 \
python src/r2egym/agenthub/run/edit.py runagent_multiple \
  --dataset "R2E-Gym/SWE-Bench-Verified" \
  --split "test" \
  --k 2294 \
  --max_workers 8 \
  --backend docker \
  --llm_name "openai/tinker" \
  --temperature 0 \
  --max_steps 40 \
  --traj_dir ./results \
  --use_fn_calling False
```

> `--use_fn_calling False` because open-weight models (Qwen, Llama) use R2E-Gym's XML-based tool format instead of OpenAI function calling.

### Key flags

| Flag | What it does |
|---|---|
| `--backend docker` | Use local Docker (vs `kubernetes` for EKS) |
| `--k 5` | Number of tasks to run |
| `--max_workers 2` | Parallel containers (limited by your machine's CPU/RAM) |
| `--llm_name "openai/tinker"` | Route through Tinker proxy via LiteLLM |
| `--temperature 0` | Greedy decoding for eval |
| `--max_steps 40` | Max agent steps per task |
| `--traj_dir ./results` | Where to save trajectory JSONL |
| `--scaffold r2egym` | Agent scaffold (`r2egym`, `openhands`, or `sweagent`) |
| `--use_fn_calling False` | Use XML tool format (for open-weight models) |

## 5. Check Results

Trajectories are saved as JSONL in `--traj_dir`:

```bash
python -c "
import json
with open('results/<exp_name>.jsonl') as f:
    trajs = [json.loads(line) for line in f]
resolved = sum(1 for t in trajs if t['reward'] == 1)
print(f'Resolved: {resolved}/{len(trajs)} ({resolved/len(trajs):.1%})')
"
```

## 6. Resource Requirements

Each sandbox container uses ~300–500MB disk + ~1 CPU + ~1GB RAM. Tinker handles GPU inference remotely — your local machine only needs CPU for the sandbox containers.

| `max_workers` | Recommended machine |
|---|---|
| 2 | 4 CPU, 8GB RAM (laptop) |
| 8 | 16 CPU, 32GB RAM |
| 20+ | Use EKS instead (see [eval-guide.md](eval-guide.md)) |
