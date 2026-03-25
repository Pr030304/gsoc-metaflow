import argparse
import json
from pathlib import Path

from nomad_client import NomadClient, NomadClientError
from metaflow_nomad_command_builder import (
    build_docker_jobspec,
    build_job_name,
    build_metaflow_env,
    build_step_command,
)


def build_example_jobspec(example: str) -> tuple[dict, str, str]:
    if example == "success":
        job_name = "mf-prototype-success"
        task_name = "echo"
        command = "python -c \"print('nomad docker job ok from python client')\""
        jobspec = build_docker_jobspec(
            job_name=job_name,
            image="python:3.11-slim",
            command=command,
            env={},
            task_name=task_name,
        )
        return jobspec, job_name, task_name

    if example == "fail-default":
        job_name = "mf-prototype-fail-default"
        task_name = "fail"
        jobspec = {
            "Job": {
                "ID": job_name,
                "Name": job_name,
                "Type": "batch",
                "Datacenters": ["dc1"],
                "TaskGroups": [
                    {
                        "Name": "main",
                        "Tasks": [
                            {
                                "Name": task_name,
                                "Driver": "docker",
                                "Config": {
                                    "image": "python:3.11-slim",
                                    "command": "python",
                                    "args": [
                                        "-c",
                                        "import sys; print('failing default'); sys.exit(2)",
                                    ],
                                },
                                "Resources": {"CPU": 500, "MemoryMB": 256},
                            }
                        ],
                    }
                ],
            }
        }
        return jobspec, job_name, task_name

    if example == "fail-once":
        job_name = "mf-prototype-fail-once"
        task_name = "fail"
        command = "python -c \"import sys; print('failing once'); sys.exit(2)\""
        jobspec = build_docker_jobspec(
            job_name=job_name,
            image="python:3.11-slim",
            command=command,
            env={},
            task_name=task_name,
            disable_restart=True,
            disable_reschedule=True,
        )
        return jobspec, job_name, task_name

    if example == "metaflow-demo":
        job_name = build_job_name("user", "DemoFlow", "1", "start", "1", 0)
        task_name = "step"
        env = build_metaflow_env(
            code_package_url="s3://example/code-package",
            code_package_sha="dummy-sha",
            user="user",
        )
        command = build_step_command(
            "python -c \"print('placeholder for metaflow step execution')\""
        )
        jobspec = build_docker_jobspec(
            job_name=job_name,
            image="python:3.11-slim",
            command=command,
            env=env,
            task_name=task_name,
        )
        return jobspec, job_name, task_name

    raise ValueError(f"Unknown example '{example}'.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit and monitor a prototype Nomad batch job."
    )
    parser.add_argument(
        "--example",
        choices=["success", "fail-default", "fail-once", "metaflow-demo"],
        default="success",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:4646")
    parser.add_argument("--namespace", default="default")
    parser.add_argument(
        "--print-jobspec",
        action="store_true",
        help="Print the generated jobspec before submitting.",
    )
    parser.add_argument(
        "--save-jobspec",
        type=Path,
        help="Optional path to save the generated JSON jobspec.",
    )
    parser.add_argument(
        "--purge-existing",
        action="store_true",
        help="Purge any existing job with the same ID before submitting.",
    )
    args = parser.parse_args()

    jobspec, job_id, task_name = build_example_jobspec(args.example)
    client = NomadClient(base_url=args.base_url, namespace=args.namespace)

    if args.print_jobspec:
        print(json.dumps(jobspec, indent=2))

    if args.save_jobspec:
        args.save_jobspec.write_text(json.dumps(jobspec, indent=2), encoding="utf-8")
        print(f"Saved jobspec to {args.save_jobspec}")

    if args.purge_existing:
        try:
            client.stop_job(job_id, purge=True)
            print(f"Purged existing job '{job_id}'.")
        except NomadClientError:
            pass

    response = client.submit_job(jobspec)
    print("Submitted job.")
    print(json.dumps(response, indent=2))

    allocation_stub = client.wait_for_allocation(job_id)
    alloc_id = allocation_stub["ID"]
    print(f"Allocation created: {alloc_id}")

    allocation = client.wait_for_terminal_allocation(alloc_id)
    task_state = client.get_task_state(allocation, task_name)
    exit_code = client.get_exit_code(task_state)

    print(f"Final allocation status: {allocation.get('ClientStatus')}")
    print(f"Task state: {task_state.get('State')}")
    print(f"Exit code: {exit_code}")

    try:
        stdout_logs = client.get_logs(alloc_id, task_name, log_type="stdout").strip()
    except NomadClientError as exc:
        stdout_logs = f"<failed to fetch stdout logs: {exc}>"
    print("stdout logs:")
    print(stdout_logs or "<empty>")


if __name__ == "__main__":
    main()
