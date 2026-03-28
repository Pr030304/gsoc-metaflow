import json
import time
from typing import Any, Dict, Optional

from metaflow_extensions.nomad_ext.plugins.nomad.nomad_client import NomadClient
from metaflow_extensions.nomad_ext.plugins.nomad.nomad_job import NomadJob


def nomad(
    cpu=500,
    memory=256,
    image="python:3.11-slim",
    datacenters="dc1",
    address="http://127.0.0.1:4646",
    namespace="default",
):
    def decorator(func):
        func._nomad_spec = {
            "cpu": cpu,
            "memory": memory,
            "image": image,
            "datacenters": datacenters,
            "address": address,
            "namespace": namespace,
        }
        return func

    return decorator


def _stream_job_logs(job, poll_interval=1.0):
    seen = {"stdout": "", "stderr": ""}
    while not job.has_finished:
        _emit_new_logs(job, seen)
        time.sleep(poll_interval)
    _emit_new_logs(job, seen)


def _emit_new_logs(job, seen):
    for stream_name in ("stdout", "stderr"):
        stream_value = job.logs(stream=stream_name)
        previous = seen[stream_name]
        delta = (
            stream_value[len(previous) :]
            if stream_value.startswith(previous)
            else stream_value
        )
        if delta:
            for line in delta.splitlines():
                prefix = "[Nomad][%s] " % stream_name
                print(prefix + line)
        seen[stream_name] = stream_value


def _merged_spec(func, **overrides):
    spec = getattr(func, "_nomad_spec", None)
    if spec is None:
        raise ValueError("Function is not decorated with @nomad.")
    merged = dict(spec)
    for key, value in overrides.items():
        if value is not None:
            merged[key] = value
    return merged


def build_nomad_job(
    func,
    *,
    cpu: Optional[int] = None,
    memory: Optional[int] = None,
    image: Optional[str] = None,
    datacenters: Optional[str] = None,
    address: Optional[str] = None,
    namespace: Optional[str] = None,
    attrs: Optional[Dict[str, Any]] = None,
):
    spec = _merged_spec(
        func,
        cpu=cpu,
        memory=memory,
        image=image,
        datacenters=datacenters,
        address=address,
        namespace=namespace,
    )

    command = func()
    if not isinstance(command, str):
        raise TypeError("Decorated function must return a shell command string.")

    client = NomadClient(
        address=spec["address"],
        namespace=spec["namespace"],
    )

    job_name = "nomad-demo-%s" % func.__name__.replace("_", "-")
    job_attrs = {"demo": "true", "function": func.__name__}
    if attrs:
        job_attrs.update({key: str(value) for key, value in attrs.items()})

    return NomadJob(
        client=client,
        name=job_name,
        command=command,
        image=spec["image"],
        cpu=spec["cpu"],
        memory=spec["memory"],
        datacenters=spec["datacenters"],
        task_name=func.__name__,
        attrs=job_attrs,
    ).create()


def run_nomad_step(
    func,
    *,
    cpu: Optional[int] = None,
    memory: Optional[int] = None,
    image: Optional[str] = None,
    datacenters: Optional[str] = None,
    address: Optional[str] = None,
    namespace: Optional[str] = None,
    attrs: Optional[Dict[str, Any]] = None,
    purge_existing: bool = True,
    print_jobspec: bool = False,
    poll_interval: float = 1.0,
):
    job_spec = build_nomad_job(
        func,
        cpu=cpu,
        memory=memory,
        image=image,
        datacenters=datacenters,
        address=address,
        namespace=namespace,
        attrs=attrs,
    )
    if purge_existing:
        job_spec.client.stop_job_if_present(job_spec.name, purge=True)
    if print_jobspec:
        print(json.dumps(job_spec.jobspec, indent=2))

    job = job_spec.execute()

    print("[Nomad] Submitted job:", job.id)
    while job.is_waiting:
        print("[Nomad] Waiting for allocation...")
        time.sleep(poll_interval)

    _stream_job_logs(job, poll_interval=poll_interval)

    print("[Nomad] Final status:", job.status)
    print("[Nomad] Exit code:", job.exit_code)

    if job.has_failed:
        raise RuntimeError(job.message or "Nomad job failed.")

    return job
