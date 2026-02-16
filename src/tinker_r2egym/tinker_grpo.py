"""
Tinker GRPO training loop for SWE agents.

Uses R2E-Gym for environment rollouts (agent loop, sandbox management, reward computation)
and Tinker API for model training (forward_backward, optim_step, sampling).

GRPO (Group Relative Policy Optimization):
- For each batch, sample G rollouts per task (group_size)
- Center advantages within each group (reward - mean_reward)
- Train on trajectories weighted by their advantages

Usage:
    python -m tinker_r2egym.tinker_grpo \
        --config configs/grpo.yaml
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
import tinker
import tinker.types as types
from datasets import load_dataset
from transformers import AutoTokenizer

from r2egym.agenthub.run.edit import runagent
from r2egym.agenthub.trajectory import Trajectory
from tinker_r2egym.s3_sync import S3Sync

logger = logging.getLogger(__name__)


@dataclass
class GRPOConfig:
    """Configuration for GRPO training with Tinker."""

    # Model
    model_name: str = "Qwen/Qwen3-30B-A3B"
    lora_rank: int = 32
    lora_alpha: int = 64

    # Training
    learning_rate: float = 2e-5
    num_steps: int = 1000
    group_size: int = 10
    batch_size: int = 8
    temperature: float = 1.0
    kl_coeff: float = 0.01

    # Rollout
    dataset: str = "R2E-Gym/R2E-Gym-Lite"
    split: str = "train"
    max_steps: int = 40
    max_workers: int = 20
    backend: str = "kubernetes"
    scaffold: str = "r2egym"
    use_fn_calling: bool = True  # Tinker proxy translates OpenAI tool calls to Qwen3 native format

    # Output
    log_dir: str = "/data/training/"
    save_every: int = 50
    eval_every: int = 0

    # Wandb
    wandb_project: str = ""
    wandb_run_name: str = ""

    @classmethod
    def from_yaml(cls, path: str) -> GRPOConfig:
        with open(path) as f:
            raw = yaml.safe_load(f)
        # Flatten nested sections into flat kwargs
        kwargs = {}
        for section in raw.values():
            if isinstance(section, dict):
                kwargs.update(section)
            else:
                kwargs.update(raw)
                break
        return cls(**{k: v for k, v in kwargs.items() if k in cls.__dataclass_fields__})


def collect_rollouts(
    ds_entries: list[dict],
    config: GRPOConfig,
    exp_name: str,
) -> list[dict]:
    """
    Run R2E-Gym agent on a batch of tasks and collect trajectories with rewards.

    Uses R2E-Gym's runagent() which handles:
    - Creating Docker/K8s sandbox containers
    - Running the ReAct agent loop
    - Computing rewards via _calculate_reward()
    - Cleaning up containers

    Returns list of {trajectory_json, reward, task_id} dicts.
    """
    import concurrent.futures

    results = []

    # Use the OpenAI-compatible proxy for rollouts (LLM_BASE_URL must be set)
    llm_name = os.environ.get("LLM_NAME", "openai/gpt-tinker")

    with concurrent.futures.ProcessPoolExecutor(max_workers=config.max_workers) as executor:
        future_to_ds = {
            executor.submit(
                runagent,
                ds=ds_entry,
                exp_name=exp_name,
                max_steps=config.max_steps,
                llm_name=llm_name,
                temperature=config.temperature,
                use_fn_calling=config.use_fn_calling,
                backend=config.backend,
                scaffold=config.scaffold,
            ): ds_entry
            for ds_entry in ds_entries
        }

        for future in concurrent.futures.as_completed(future_to_ds):
            ds_entry = future_to_ds[future]
            try:
                traj_json = future.result()
                if traj_json is not None:
                    traj = Trajectory.load_from_model_dump_json(traj_json)
                    results.append({
                        "trajectory_json": traj_json,
                        "reward": traj.reward,
                        "task_id": ds_entry.get("instance_id", ds_entry.get("docker_image", "unknown")),
                    })
            except Exception as e:
                logger.error(f"Rollout failed for {ds_entry.get('docker_image', '?')}: {e}")

    return results


def trajectories_to_training_data(
    rollout_groups: list[list[dict]],
    tokenizer: Any,
) -> list[tinker.Datum]:
    """
    Convert rollout groups into Tinker Datum objects for forward_backward.

    GRPO advantage computation:
    - For each group of rollouts on the same task, compute advantages
    - advantage_i = reward_i - mean(rewards_in_group)
    - Weight training signal by advantage

    Each trajectory becomes a Datum with:
    - model_input: tokenized conversation (system + user + assistant messages)
    - loss_fn_inputs: weights (0 for prompt, advantage for completion) + target tokens
    """
    data = []

    for group in rollout_groups:
        if not group:
            continue

        # Compute group advantages (GRPO)
        rewards = [r["reward"] for r in group]
        mean_reward = sum(rewards) / len(rewards) if rewards else 0.0
        advantages = [r - mean_reward for r in rewards]

        # Skip groups where all rewards are identical (no learning signal)
        if all(a == 0.0 for a in advantages):
            continue

        for rollout, advantage in zip(group, advantages):
            try:
                traj = json.loads(rollout["trajectory_json"])
            except (json.JSONDecodeError, KeyError):
                continue

            # Build the conversation as the model saw it
            # The agent's full trajectory is stored in traj
            problem_statement = traj.get("problem_statement", "")
            output_patch = traj.get("output_patch", "")

            # Tokenize: prompt = system + problem statement, completion = agent trajectory
            prompt_text = f"Fix the following issue:\n{problem_statement}"
            completion_text = output_patch if output_patch else ""

            if not completion_text:
                continue

            prompt_tokens = tokenizer.encode(prompt_text, add_special_tokens=True)
            completion_tokens = tokenizer.encode(completion_text, add_special_tokens=False)
            full_tokens = prompt_tokens + completion_tokens

            # Build weights: 0 for prompt tokens, advantage for completion tokens
            weights = [0.0] * len(prompt_tokens) + [advantage] * len(completion_tokens)

            # Target tokens are shifted by 1 (next-token prediction)
            target_tokens = full_tokens[1:] + [tokenizer.eos_token_id]

            datum = tinker.Datum(
                model_input=types.ModelInput.from_ints(full_tokens),
                loss_fn_inputs={
                    "target_tokens": types.ModelInput.from_ints(target_tokens),
                    "weights": types.TensorData.from_list(weights, dtype=types.TensorDtype.FLOAT32),
                },
            )
            data.append(datum)

    return data


async def train_step(
    training_client: tinker.TrainingClient,
    data: list[tinker.Datum],
    learning_rate: float,
) -> dict[str, float]:
    """Execute one GRPO training step: forward_backward + optim_step."""
    if not data:
        return {"loss": 0.0, "num_samples": 0}

    fwd_bwd_future = await training_client.forward_backward_async(
        data, loss_fn="importance_sampling"
    )
    fwd_bwd_result = await fwd_bwd_future.result_async()

    adam_params = types.AdamParams(
        learning_rate=learning_rate, beta1=0.9, beta2=0.95, eps=1e-8
    )
    optim_future = await training_client.optim_step_async(adam_params)
    await optim_future.result_async()

    return {
        "loss": float(fwd_bwd_result.metrics.get("loss", 0.0)) if fwd_bwd_result.metrics else 0.0,
        "num_samples": len(data),
    }


async def async_main(config: GRPOConfig):
    """Main GRPO training loop."""
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # S3 sync for persistent storage
    s3 = S3Sync()

    # Save config
    with open(log_dir / "config.json", "w") as f:
        json.dump(config.__dict__, f, indent=2)
    s3.upload_file(log_dir / "config.json", base_dir=log_dir)

    # Initialize Tinker clients
    logger.info(f"Connecting to Tinker API for model: {config.model_name}")
    service_client = tinker.ServiceClient()
    training_client = service_client.create_lora_training_client(
        base_model=config.model_name,
        rank=config.lora_rank,
    )
    logger.info("Tinker training client ready")

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(config.model_name)

    # Load dataset
    logger.info(f"Loading dataset: {config.dataset} ({config.split})")
    ds = load_dataset(config.dataset, split=config.split)
    ds = ds.shuffle(seed=42)
    logger.info(f"Dataset loaded: {len(ds)} tasks")

    # Training loop
    metrics_log = []
    for step in range(config.num_steps):
        t_start = time.time()
        logger.info(f"=== Training step {step}/{config.num_steps} ===")

        # Sample batch of tasks
        batch_indices = [
            (step * config.batch_size + i) % len(ds)
            for i in range(config.batch_size)
        ]

        # For GRPO, run group_size rollouts per task
        rollout_groups = []
        for idx in batch_indices:
            ds_entries = [ds[idx]] * config.group_size
            group_results = collect_rollouts(
                ds_entries,
                config,
                exp_name=f"step_{step}_task_{idx}",
            )
            rollout_groups.append(group_results)

        # Log rollout stats
        all_rewards = [r["reward"] for group in rollout_groups for r in group]
        num_rollouts = len(all_rewards)
        mean_reward = sum(all_rewards) / num_rollouts if num_rollouts > 0 else 0.0
        resolve_rate = sum(1 for r in all_rewards if r > 0) / num_rollouts if num_rollouts > 0 else 0.0
        logger.info(f"Rollouts: {num_rollouts}, mean_reward: {mean_reward:.3f}, resolve_rate: {resolve_rate:.1%}")

        # Convert to training data with GRPO advantages
        training_data = trajectories_to_training_data(rollout_groups, tokenizer)
        logger.info(f"Training data: {len(training_data)} samples")

        # Train
        step_metrics = await train_step(training_client, training_data, config.learning_rate)
        step_metrics.update({
            "step": step,
            "num_rollouts": num_rollouts,
            "mean_reward": mean_reward,
            "resolve_rate": resolve_rate,
            "time_s": time.time() - t_start,
        })
        metrics_log.append(step_metrics)
        logger.info(f"Step {step} done: {step_metrics}")

        # Save metrics incrementally
        with open(log_dir / "metrics.jsonl", "a") as f:
            f.write(json.dumps(step_metrics) + "\n")
        s3.upload_file(log_dir / "metrics.jsonl", base_dir=log_dir)

        # Checkpoint
        if config.save_every > 0 and (step + 1) % config.save_every == 0:
            checkpoint_name = f"checkpoint-{step + 1:06d}"
            logger.info(f"Saving checkpoint: {checkpoint_name}")
            sampling_client = training_client.save_weights_and_get_sampling_client(
                name=checkpoint_name
            )
            logger.info(f"Checkpoint saved: {checkpoint_name}")

    # Final checkpoint
    logger.info("Saving final checkpoint")
    training_client.save_weights_and_get_sampling_client(name="final")

    # Final S3 sync
    s3.sync_dir(log_dir)
    logger.info("Training complete")


def main(config_path: str = "configs/grpo.yaml", dry_run: bool = False):
    """Entry point for GRPO training."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    config = GRPOConfig.from_yaml(config_path)
    logger.info(f"Config: {config}")

    if dry_run:
        logger.info("Dry run — config loaded successfully, exiting")
        return

    asyncio.run(async_main(config))


if __name__ == "__main__":
    import fire
    fire.Fire(main)
