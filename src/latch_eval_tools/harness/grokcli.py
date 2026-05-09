import os
from pathlib import Path

from latch_eval_tools.harness._cli_runner import _run_cli_agent, EVAL_TIMEOUT
from latch_eval_tools.harness.utils import DEFAULT_DOCKER_IMAGE

MODEL_MAP = {
    "xai/grok-4": "grok-4",
    "xai/grok-4-fast": "grok-4-fast",
    "xai/grok-4-fast-reasoning": "grok-4-fast-reasoning",
    "xai/grok-code-fast-1": "grok-code-fast-1",
    "xai/grok-3": "grok-3",
    "xai/grok-3-mini": "grok-3-mini",
}


def run_grokcli_task(
    task_prompt: str,
    work_dir: Path,
    model_name: str | None = None,
    eval_timeout: int = EVAL_TIMEOUT,
    docker_image: str = DEFAULT_DOCKER_IMAGE,
    memory_limit_bytes: int | None = None,
) -> dict:
    if not (os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")):
        raise ValueError(
            "GROK_API_KEY or XAI_API_KEY environment variable is required for Grok CLI"
        )

    return _run_cli_agent(
        agent_type="grokcli",
        cli_command=["grok"],
        task_prompt=task_prompt,
        work_dir=work_dir,
        model_name=model_name,
        eval_timeout=eval_timeout,
        model_map=MODEL_MAP,
        docker_image=docker_image,
        memory_limit_bytes=memory_limit_bytes,
    )
