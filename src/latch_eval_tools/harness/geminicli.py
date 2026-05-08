import os
import subprocess
from pathlib import Path

from latch_eval_tools.harness._cli_runner import _run_cli_agent, EVAL_TIMEOUT
from latch_eval_tools.harness.utils import DEFAULT_DOCKER_IMAGE

MODEL_MAP = {
    "gemini/gemini-3.1-pro-preview": "gemini-3.1-pro-preview",
    "gemini/gemini-3.1-pro-preview-customtools": "gemini-3.1-pro-preview-customtools",
    "gemini/gemini-3-flash-preview": "gemini-3-flash-preview",
    "gemini/gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
    "gemini/gemini-3.1-flash-lite-preview": "gemini-3.1-flash-lite-preview",
    "gemini/gemini-2.5-pro": "gemini-2.5-pro",
    "gemini/gemini-2.5-flash": "gemini-2.5-flash",
    "gemini/gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
}


def _image_has_gemini_cli(docker_image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", docker_image, "gemini", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return False

    return result.returncode == 0


def run_geminicli_task(
    task_prompt: str,
    work_dir: Path,
    model_name: str | None = None,
    eval_timeout: int = EVAL_TIMEOUT,
    docker_image: str = DEFAULT_DOCKER_IMAGE,
    memory_limit_bytes: int | None = None,
) -> dict:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        raise ValueError(
            "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is required for Gemini CLI"
        )

    if not _image_has_gemini_cli(docker_image):
        raise ValueError(
            f"Docker image {docker_image!r} does not have the Gemini CLI installed. "
            "Build ../latch-eval-tools/agent_env as benchmark_agent:local and pass "
            "docker_image='benchmark_agent:local' or --docker-image benchmark_agent:local."
        )

    return _run_cli_agent(
        agent_type="geminicli",
        cli_command=["gemini"],
        task_prompt=task_prompt,
        work_dir=work_dir,
        model_name=model_name,
        eval_timeout=eval_timeout,
        model_map=MODEL_MAP,
        docker_image=docker_image,
        memory_limit_bytes=memory_limit_bytes,
    )
