"""
Wrapper around R2E-Gym's runagent_multiple that syncs results to S3.

Usage:
    python -m tinker_r2egym.run_eval \
        --dataset "R2E-Gym/SWE-Bench-Verified" \
        --split test \
        --k 5 \
        --max_workers 5 \
        --llm_name "openai/gpt-tinker" \
        --traj_dir /data/results
"""

from __future__ import annotations

import logging
import sys

from r2egym.agenthub.run.edit import runagent_multiple
from tinker_r2egym.s3_sync import S3Sync

logger = logging.getLogger(__name__)


def main(
    dataset: str = "R2E-Gym/SWE-Bench-Verified",
    split: str = "test",
    k: int = 5,
    max_workers: int = 5,
    max_steps: int = 40,
    llm_name: str = "openai/gpt-tinker",
    temperature: float = 0.0,
    backend: str = "kubernetes",
    scaffold: str = "r2egym",
    use_fn_calling: bool = True,
    traj_dir: str = "/data/results",
    exp_name: str | None = None,
):
    """Run R2E-Gym evaluation then sync results to S3."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if exp_name is None:
        exp_name = f"eval_{dataset.replace('/', '_')}_{split}_k{k}"

    logger.info(f"Starting eval: {dataset} ({split}), k={k}, workers={max_workers}")

    runagent_multiple(
        dataset=dataset,
        split=split,
        k=k,
        max_workers=max_workers,
        max_steps=max_steps,
        llm_name=llm_name,
        temperature=temperature,
        backend=backend,
        scaffold=scaffold,
        use_fn_calling=use_fn_calling,
        traj_dir=traj_dir,
        exp_name=exp_name,
    )

    logger.info(f"Eval complete. Syncing {traj_dir} to S3...")
    s3 = S3Sync()
    s3.sync_dir(traj_dir)
    logger.info("Done.")


if __name__ == "__main__":
    import fire
    fire.Fire(main)
