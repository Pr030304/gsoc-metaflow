from typing import Dict, List, Optional

from .nomad_client import NomadClient


def sanitize_name(job_name: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in job_name)


class NomadJob:
    def __init__(
        self,
        client: NomadClient,
        name: str,
        command: str,
        image: str,
        cpu: int,
        memory: int,
        datacenters,
        task_name: str = "step",
        env: Optional[Dict[str, str]] = None,
        attrs: Optional[Dict[str, str]] = None,
        volumes: Optional[List[str]] = None,
        restart_enabled: bool = False,
        reschedule_enabled: bool = False,
    ) -> None:
        self.client = client
        self.name = sanitize_name(name)
        self.command = command
        self.image = image
        self.cpu = int(cpu)
        self.memory = int(memory)
        self.datacenters = datacenters
        self.task_name = task_name
        self.env = env or {}
        self.attrs = attrs or {}
        self.volumes = volumes or []
        self.restart_enabled = restart_enabled
        self.reschedule_enabled = reschedule_enabled
        self.jobspec = None

    def environment_variable(self, name: str, value) -> "NomadJob":
        if value is None:
            return self
        self.env[name] = str(value)
        return self

    def create_jobspec(self) -> "NomadJob":
        group = {
            "Name": "main",
            "Tasks": [
                {
                    "Name": self.task_name,
                    "Driver": "docker",
                    "Config": {
                        "image": self.image,
                        "command": "bash",
                        "args": ["-lc", self.command],
                    },
                    "Env": self.env,
                    "Resources": {
                        "CPU": self.cpu,
                        "MemoryMB": self.memory,
                    },
                    "Meta": dict(self.attrs),
                }
            ],
        }
        if self.volumes:
            group["Tasks"][0]["Config"]["volumes"] = list(self.volumes)
        if not self.restart_enabled:
            group["RestartPolicy"] = {"Attempts": 0, "Mode": "fail"}
        if not self.reschedule_enabled:
            group["ReschedulePolicy"] = {"Attempts": 0, "Unlimited": False}
        self.jobspec = {
            "Job": {
                "ID": self.name,
                "Name": self.name,
                "Type": "batch",
                "Datacenters": self._normalize_datacenters(),
                "TaskGroups": [group],
                "Meta": dict(self.attrs),
            }
        }
        return self

    def _normalize_datacenters(self):
        if not self.datacenters:
            return ["dc1"]
        if isinstance(self.datacenters, str):
            return [dc.strip() for dc in self.datacenters.split(",") if dc.strip()]
        return list(self.datacenters)

    def create(self) -> "NomadJob":
        return self.create_jobspec()

    def execute(self) -> "RunningJob":
        self.client.submit_job(self.jobspec)
        return RunningJob(
            client=self.client,
            job_id=self.name,
            task_name=self.task_name,
        )


class RunningJob:
    def __init__(self, client: NomadClient, job_id: str, task_name: str) -> None:
        self.client = client
        self.job_id = job_id
        self.task_name = task_name

    def __repr__(self) -> str:
        return "{}('{}')".format(self.__class__.__name__, self.job_id)

    @property
    def id(self):
        return self.job_id

    def _allocation_stub(self) -> Optional[Dict]:
        return self.client.get_latest_allocation(self.job_id)

    @property
    def allocation(self) -> Optional[Dict]:
        alloc = self._allocation_stub()
        if alloc is None:
            return None
        alloc_id = alloc.get("ID")
        if not alloc_id:
            return None
        return self.client.get_allocation(alloc_id)

    @property
    def allocation_id(self) -> Optional[str]:
        alloc = self._allocation_stub()
        if alloc is None:
            return None
        return alloc.get("ID")

    @property
    def task_state(self) -> Optional[Dict]:
        alloc = self.allocation
        if alloc is None:
            return None
        return self.client.extract_task_state(alloc, self.task_name)

    @property
    def status(self) -> str:
        alloc = self.allocation
        if alloc is None:
            return "pending"
        return alloc.get("ClientStatus") or "pending"

    @property
    def exit_code(self) -> Optional[int]:
        return self.client.extract_exit_code(self.task_state)

    @property
    def message(self) -> Optional[str]:
        alloc = self.allocation
        if alloc is None:
            return None
        return self.client.extract_message(alloc, self.task_state)

    @property
    def is_waiting(self) -> bool:
        return self.status in {"pending"}

    @property
    def is_running(self) -> bool:
        return self.status in {"pending", "running"}

    @property
    def has_failed(self) -> bool:
        if self.status in {"failed", "lost"}:
            return True
        exit_code = self.exit_code
        return self.status == "complete" and exit_code not in (None, 0)

    @property
    def has_succeeded(self) -> bool:
        return self.status == "complete" and self.exit_code in (None, 0)

    @property
    def has_finished(self) -> bool:
        return self.has_succeeded or self.has_failed

    def logs(self, stream: str = "stdout") -> str:
        alloc_id = self.allocation_id
        if alloc_id is None:
            return ""
        return self.client.get_logs(alloc_id, self.task_name, log_type=stream)

    def kill(self):
        self.client.stop_job(self.job_id, purge=False)
