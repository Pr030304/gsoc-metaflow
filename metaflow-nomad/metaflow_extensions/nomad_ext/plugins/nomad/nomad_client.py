import time
from typing import Any, Dict, List, Optional

import requests

from .nomad_exceptions import NomadException


class NomadClient:
    GENERIC_EVENT_TYPES = {
        "Received",
        "Task Setup",
        "Started",
        "Restarting",
        "Not Restarting",
    }
    FAILURE_EVENT_TYPES = (
        "Driver Failure",
        "Failed Validation",
        "Setup Failure",
        "Killing",
        "Killed",
        "Terminated",
    )

    def __init__(
        self,
        address: Optional[str] = None,
        namespace: Optional[str] = None,
        region: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self.base_url = (address or "http://127.0.0.1:4646").rstrip("/")
        self.namespace = namespace or "default"
        self.region = region
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Nomad-Namespace": self.namespace})
        if token:
            self.session.headers.update({"X-Nomad-Token": token})
        if region:
            self.session.headers.update({"X-Nomad-Region": region})

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(
            method, self._url(path), timeout=self.timeout, **kwargs
        )
        if response.status_code >= 400:
            raise NomadException(
                f"{method} {path} failed with {response.status_code}: {response.text}"
            )
        return response

    def submit_job(self, jobspec: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/jobs", json=jobspec).json()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/job/{job_id}").json()

    def job_exists(self, job_id: str) -> bool:
        try:
            self.get_job(job_id)
            return True
        except NomadException as exc:
            if " 404:" in str(exc):
                return False
            raise

    def get_job_allocations(self, job_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/v1/job/{job_id}/allocations").json()

    def get_latest_allocation(self, job_id: str) -> Optional[Dict[str, Any]]:
        allocations = self.get_job_allocations(job_id)
        if not allocations:
            return None
        return max(
            allocations,
            key=lambda alloc: (
                alloc.get("ModifyIndex", 0),
                alloc.get("CreateIndex", 0),
            ),
        )

    def get_allocation(self, alloc_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/allocation/{alloc_id}").json()

    def stop_job(self, job_id: str, purge: bool = False) -> Dict[str, Any]:
        return self._request(
            "DELETE", f"/v1/job/{job_id}", params={"purge": str(purge).lower()}
        ).json()

    def stop_job_if_present(
        self, job_id: str, purge: bool = False
    ) -> Optional[Dict[str, Any]]:
        if not self.job_exists(job_id):
            return None
        return self.stop_job(job_id, purge=purge)

    def get_logs(
        self,
        alloc_id: str,
        task_name: str,
        log_type: str = "stdout",
        origin: str = "start",
        plain: bool = True,
    ) -> str:
        try:
            return self._request(
                "GET",
                f"/v1/client/fs/logs/{alloc_id}",
                params={
                    "task": task_name,
                    "type": log_type,
                    "origin": origin,
                    "plain": str(plain).lower(),
                },
            ).text
        except NomadException as exc:
            message = str(exc)
            if " 404:" in message and (
                "No logs available" in message or "not started yet" in message
            ):
                return ""
            raise

    def wait_for_allocation(
        self, job_id: str, poll_interval: float = 1.0, timeout: int = 60
    ) -> Dict[str, Any]:
        started = time.time()
        while time.time() - started < timeout:
            allocation = self.get_latest_allocation(job_id)
            if allocation is not None:
                return allocation
            time.sleep(poll_interval)
        raise NomadException(f"Timed out waiting for allocation for job '{job_id}'.")

    @staticmethod
    def extract_task_state(
        allocation: Dict[str, Any], task_name: str
    ) -> Optional[Dict[str, Any]]:
        return (allocation.get("TaskStates") or {}).get(task_name)

    @staticmethod
    def extract_exit_code(task_state: Optional[Dict[str, Any]]) -> Optional[int]:
        if not task_state:
            return None
        events = task_state.get("Events") or []
        for event in reversed(events):
            if event.get("Type") == "Terminated":
                exit_code = event.get("ExitCode")
                if exit_code is not None:
                    exit_code = int(exit_code)
                    if task_state.get("Failed") is True and exit_code == 0:
                        break
                    return exit_code
        for event in reversed(events):
            exit_code = event.get("ExitCode")
            if exit_code is not None:
                exit_code = int(exit_code)
                if task_state.get("Failed") is True and exit_code == 0:
                    continue
                return exit_code
        if task_state.get("Failed") is True:
            return None
        if (
            task_state.get("FinishedAt")
            and task_state.get("State") == "dead"
            and task_state.get("Failed") is False
        ):
            return 0
        return None

    @staticmethod
    def extract_message(
        allocation: Dict[str, Any], task_state: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        if task_state:
            events = task_state.get("Events") or []
            for event_type in NomadClient.FAILURE_EVENT_TYPES:
                for event in reversed(events):
                    if event.get("Type") != event_type:
                        continue
                    for field in ("DisplayMessage", "Message"):
                        value = event.get(field)
                        if value:
                            return value
            for event in reversed(events):
                if event.get("Type") in NomadClient.GENERIC_EVENT_TYPES:
                    continue
                for field in ("DisplayMessage", "Message"):
                    value = event.get(field)
                    if value:
                        return value
        return allocation.get("ClientDescription")
