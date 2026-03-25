import time
from typing import Any, Dict, List, Optional

import requests


class NomadClientError(RuntimeError):
    pass


class NomadClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4646",
        namespace: str = "default",
        token: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.namespace = namespace
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Nomad-Namespace": namespace})
        if token:
            self.session.headers.update({"X-Nomad-Token": token})

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(
            method, self._url(path), timeout=self.timeout, **kwargs
        )
        if response.status_code >= 400:
            raise NomadClientError(
                f"{method} {path} failed with {response.status_code}: {response.text}"
            )
        return response

    def submit_job(self, jobspec: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/jobs", json=jobspec).json()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/job/{job_id}").json()

    def get_job_allocations(self, job_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/v1/job/{job_id}/allocations").json()

    def get_allocation(self, alloc_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/allocation/{alloc_id}").json()

    def stop_job(self, job_id: str, purge: bool = False) -> Dict[str, Any]:
        return self._request(
            "DELETE", f"/v1/job/{job_id}", params={"purge": str(purge).lower()}
        ).json()

    def get_logs(
        self,
        alloc_id: str,
        task_name: str,
        log_type: str = "stdout",
        origin: str = "end",
        plain: bool = True,
    ) -> str:
        response = self._request(
            "GET",
            f"/v1/client/fs/logs/{alloc_id}",
            params={
                "task": task_name,
                "type": log_type,
                "origin": origin,
                "plain": str(plain).lower(),
            },
        )
        return response.text

    def wait_for_allocation(
        self, job_id: str, poll_interval: float = 1.0, timeout: int = 60
    ) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < timeout:
            allocations = self.get_job_allocations(job_id)
            if allocations:
                return allocations[0]
            time.sleep(poll_interval)
        raise NomadClientError(
            f"Timed out waiting for allocation for job '{job_id}'."
        )

    def wait_for_terminal_allocation(
        self, alloc_id: str, poll_interval: float = 1.0, timeout: int = 300
    ) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < timeout:
            allocation = self.get_allocation(alloc_id)
            client_status = allocation.get("ClientStatus")
            if client_status in {"complete", "failed", "lost"}:
                return allocation
            time.sleep(poll_interval)
        raise NomadClientError(
            f"Timed out waiting for terminal allocation state for '{alloc_id}'."
        )

    @staticmethod
    def get_task_state(allocation: Dict[str, Any], task_name: str) -> Dict[str, Any]:
        task_states = allocation.get("TaskStates") or {}
        if task_name not in task_states:
            raise NomadClientError(
                f"Task '{task_name}' not found in allocation task states."
            )
        return task_states[task_name]

    @staticmethod
    def get_exit_code(task_state: Dict[str, Any]) -> Optional[int]:
        events = task_state.get("Events") or []

        # Prefer the terminal container/process exit reported by Nomad.
        for event in reversed(events):
            if event.get("Type") == "Terminated":
                exit_code = event.get("ExitCode")
                if exit_code is not None:
                    return exit_code

        # Fall back to any event carrying an exit code if no explicit
        # termination event is present.
        for event in reversed(events):
            exit_code = event.get("ExitCode")
            if exit_code is not None:
                return exit_code

        # Nomad may still mark the task as failed even if no exit code is exposed.
        if task_state.get("Failed") is True:
            return 1

        if task_state.get("FinishedAt") and task_state.get("Failed") is False:
            return 0

        return None
