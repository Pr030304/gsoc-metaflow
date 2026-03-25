import argparse
import json
from typing import Dict, List, Optional


def build_job_name(
    user: str,
    flow_name: str,
    run_id: str,
    step_name: str,
    task_id: str,
    retry_count: int,
) -> str:
    parts = [user, flow_name, run_id, step_name, task_id, str(retry_count)]
    return "-".join(part.replace("/", "-") for part in parts if part)


def build_metaflow_env(
    code_package_url: str,
    code_package_sha: str,
    datastore_type: str = "s3",
    user: str = "",
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    env = {
        "METAFLOW_CODE_URL": code_package_url,
        "METAFLOW_CODE_SHA": code_package_sha,
        "METAFLOW_CODE_DS": datastore_type,
        "METAFLOW_USER": user,
        "METAFLOW_RUNTIME_ENVIRONMENT": "nomad",
        "METAFLOW_NOMAD_WORKLOAD": "1",
    }
    if extra_env:
        env.update(extra_env)
    return env


def build_step_command(step_cli: str, bootstrap_commands: Optional[List[str]] = None) -> str:
    bootstrap_commands = bootstrap_commands or []
    parts = bootstrap_commands + [step_cli]
    return " && ".join(parts)


def build_docker_jobspec(
    job_name: str,
    image: str,
    command: str,
    env: Dict[str, str],
    cpu: int = 500,
    memory: int = 256,
    datacenters: Optional[List[str]] = None,
    task_name: str = "step",
    disable_restart: bool = True,
    disable_reschedule: bool = True,
) -> Dict:
    group: Dict = {
        "Name": "main",
        "Tasks": [
            {
                "Name": task_name,
                "Driver": "docker",
                "Config": {
                    "image": image,
                    "command": "bash",
                    "args": ["-lc", command],
                },
                "Env": env,
                "Resources": {
                    "CPU": cpu,
                    "MemoryMB": memory,
                },
                "Meta": {
                    "metaflow.backend": "nomad",
                },
            }
        ],
    }

    if disable_restart:
        group["RestartPolicy"] = {"Attempts": 0, "Mode": "fail"}
    if disable_reschedule:
        group["ReschedulePolicy"] = {"Attempts": 0, "Unlimited": False}

    return {
        "Job": {
            "ID": job_name,
            "Name": job_name,
            "Type": "batch",
            "Datacenters": datacenters or ["dc1"],
            "TaskGroups": [group],
            "Meta": {
                "metaflow.job_name": job_name,
            },
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a prototype Nomad jobspec for a Metaflow step."
    )
    parser.add_argument("--user", default="user")
    parser.add_argument("--flow-name", default="ExampleFlow")
    parser.add_argument("--run-id", default="1")
    parser.add_argument("--step-name", default="start")
    parser.add_argument("--task-id", default="1")
    parser.add_argument("--retry-count", type=int, default=0)
    parser.add_argument("--image", default="python:3.11-slim")
    parser.add_argument("--step-cli", required=True)
    parser.add_argument("--code-package-url", default="s3://example/package")
    parser.add_argument("--code-package-sha", default="dummy-sha")
    parser.add_argument("--cpu", type=int, default=500)
    parser.add_argument("--memory", type=int, default=256)
    args = parser.parse_args()

    job_name = build_job_name(
        args.user,
        args.flow_name,
        args.run_id,
        args.step_name,
        args.task_id,
        args.retry_count,
    )
    env = build_metaflow_env(
        code_package_url=args.code_package_url,
        code_package_sha=args.code_package_sha,
        user=args.user,
    )
    command = build_step_command(args.step_cli)
    jobspec = build_docker_jobspec(
        job_name=job_name,
        image=args.image,
        command=command,
        env=env,
        cpu=args.cpu,
        memory=args.memory,
    )
    print(json.dumps(jobspec, indent=2))


if __name__ == "__main__":
    main()
