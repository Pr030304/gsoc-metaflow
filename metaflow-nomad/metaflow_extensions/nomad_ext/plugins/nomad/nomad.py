import atexit
import json
import os
import time

from metaflow.metaflow_config import (
    DEFAULT_METADATA,
    DATASTORE_LOCAL_DIR,
    DATASTORE_SYSROOT_S3,
    DATATOOLS_S3ROOT,
    DEFAULT_SECRETS_BACKEND_TYPE,
    KUBERNETES_SANDBOX_INIT_SCRIPT,
    OTEL_ENDPOINT,
    S3_ENDPOINT_URL,
    S3_SERVER_SIDE_ENCRYPTION,
    SERVICE_HEADERS,
    SERVICE_INTERNAL_URL,
)
from metaflow.metaflow_config_funcs import config_values
from metaflow.mflog import (
    BASH_FLUSH_LOGS,
    BASH_SAVE_LOGS,
    TASK_LOG_SOURCE,
    bash_capture_logs,
    export_mflog_env_vars,
)
from metaflow.package import MetaflowPackage

from .nomad_client import NomadClient
from .nomad_exceptions import NomadException, NomadKilledException
from .nomad_job import NomadJob


TASK_LOCAL_ROOT = "$NOMAD_TASK_DIR"
TASK_WORKDIR = "$NOMAD_TASK_DIR/metaflow"
LOGS_DIR = "$NOMAD_TASK_DIR/.logs"
STDOUT_PATH = os.path.join(LOGS_DIR, "mflog_stdout")
STDERR_PATH = os.path.join(LOGS_DIR, "mflog_stderr")

NOMAD_SAFE_BASH_MFLOG = (
    "mflog(){ "
    "T=$(date -u -Ins|tr , .); "
    'TS=$(printf "%s" "$T" | cut -c1-26); '
    'echo "[MFLOG|0|$TS' + 'Z|%s|$T]$1" >> "$MFLOG_STDOUT"; '
    'echo "$1"; '
    "}" % TASK_LOG_SOURCE
)


class Nomad:
    def __init__(self, datastore, metadata, environment, nomad_access_params):
        self.datastore = datastore
        self.metadata = metadata
        self.environment = environment
        self.nomad_client = NomadClient(**nomad_access_params)
        atexit.register(lambda: self.job.kill() if hasattr(self, "job") else None)

    def _job_name(self, user, flow_name, run_id, step_name, task_id, retry_count):
        return "{user}-{flow_name}-{run_id}-{step_name}-{task_id}-{retry_count}".format(
            user=user,
            flow_name=flow_name,
            run_id=str(run_id) if run_id is not None else "",
            step_name=step_name,
            task_id=str(task_id) if task_id is not None else "",
            retry_count=str(retry_count) if retry_count is not None else "",
        )

    def _package_commands(self, environment, code_package_url, code_package_metadata):
        if self.datastore.TYPE != "local":
            return environment.get_package_commands(
                code_package_url, self.datastore.TYPE, code_package_metadata
            )

        extra_exports = []
        for key, value in MetaflowPackage.get_post_extract_env_vars(
            code_package_metadata, dest_dir="$(pwd)"
        ).items():
            if key.endswith(":"):
                extra_exports.append("export %s=%s" % (key[:-1], value))
            else:
                extra_exports.append(
                    "export %s=%s:$(printenv %s)"
                    % (key, value.replace('"', '\\"'), key)
                )

        return (
            [
                NOMAD_SAFE_BASH_MFLOG,
                BASH_FLUSH_LOGS,
                "mflog 'Setting up task environment.'",
                "mkdir -p .metaflow",
                "mflog 'Installing runtime dependencies...'",
                "python -m pip install -q requests",
                "mflog 'Copying local code package...'",
                "cp %s job.tar" % json.dumps(code_package_url),
            ]
            + MetaflowPackage.get_extract_commands(
                code_package_metadata, "job.tar", dest_dir="."
            )
            + extra_exports
            + [
                "mflog 'Task is starting.'",
                "flush_mflogs",
            ]
        )

    def _command(
        self,
        environment,
        code_package_url,
        code_package_metadata,
        step_name,
        step_cmds,
        task_spec,
    ):
        mflog_expr = export_mflog_env_vars(
            datastore_type=self.datastore.TYPE,
            stdout_path=STDOUT_PATH,
            stderr_path=STDERR_PATH,
            **task_spec,
        )
        init_cmds = self._package_commands(
            environment, code_package_url, code_package_metadata
        )
        init_expr = " && ".join(init_cmds)
        workspace_expr = 'mkdir -p "%s" && cd "%s"' % (TASK_WORKDIR, TASK_WORKDIR)
        step_expr = bash_capture_logs(
            " && ".join(
                environment.bootstrap_commands(step_name, self.datastore.TYPE) + step_cmds
            )
        )
        cmd_str = "true && mkdir -p %s && %s && %s && %s; " % (
            LOGS_DIR,
            mflog_expr,
            workspace_expr + " && " + init_expr,
            step_expr,
        )
        cmd_str += "c=$?; %s; exit $c" % BASH_SAVE_LOGS
        init_guard = 'if [ -n "$METAFLOW_INIT_SCRIPT" ]; then eval "$METAFLOW_INIT_SCRIPT"; fi'
        cmd_str = "%s && %s" % (init_guard, cmd_str)
        return cmd_str

    def _local_dev_mount_root(self):
        if self.datastore.TYPE != "local":
            return None
        datastore_root = getattr(self.datastore, "datastore_root", None)
        if not datastore_root:
            raise NomadException("Could not determine local datastore root.")
        mount_root = os.path.dirname(datastore_root.rstrip("/\\"))
        if os.name == "nt":
            raise NomadException(
                "@nomad local datastore support is only available from WSL/Linux. "
                "Run the flow from WSL or use a remote datastore."
            )
        return mount_root

    def create_job(
        self,
        step_name,
        step_cli,
        task_spec,
        code_package_metadata,
        code_package_sha,
        code_package_url,
        code_package_ds,
        image,
        cpu,
        memory,
        datacenters=None,
        env=None,
        attrs=None,
    ):
        env = dict(env or {})
        attrs = dict(attrs or {})

        job_name = self._job_name(
            attrs.get("metaflow.user"),
            attrs.get("metaflow.flow_name"),
            attrs.get("metaflow.run_id"),
            attrs.get("metaflow.step_name"),
            attrs.get("metaflow.task_id"),
            attrs.get("metaflow.retry_count"),
        )

        volumes = []
        nomad_job = (
            NomadJob(
                client=self.nomad_client,
                name=job_name,
                command=self._command(
                    self.environment,
                    code_package_url,
                    code_package_metadata,
                    step_name,
                    [step_cli],
                    task_spec,
                ),
                image=image,
                cpu=cpu,
                memory=memory,
                datacenters=datacenters,
                task_name="step",
                env=env,
                attrs=attrs,
                volumes=volumes,
            )
            .environment_variable("METAFLOW_CODE_METADATA", code_package_metadata)
            .environment_variable("METAFLOW_CODE_SHA", code_package_sha)
            .environment_variable("METAFLOW_CODE_URL", code_package_url)
            .environment_variable("METAFLOW_CODE_DS", code_package_ds)
            .environment_variable("METAFLOW_USER", attrs.get("metaflow.user"))
            .environment_variable("METAFLOW_SERVICE_URL", SERVICE_INTERNAL_URL)
            .environment_variable("METAFLOW_SERVICE_HEADERS", json.dumps(SERVICE_HEADERS))
            .environment_variable("METAFLOW_DATASTORE_SYSROOT_S3", DATASTORE_SYSROOT_S3)
            .environment_variable("METAFLOW_DATATOOLS_S3ROOT", DATATOOLS_S3ROOT)
            .environment_variable("METAFLOW_DEFAULT_DATASTORE", self.datastore.TYPE)
            .environment_variable("METAFLOW_NOMAD_WORKLOAD", 1)
            .environment_variable("METAFLOW_RUNTIME_ENVIRONMENT", "nomad")
            .environment_variable("METAFLOW_INIT_SCRIPT", KUBERNETES_SANDBOX_INIT_SCRIPT)
            .environment_variable("METAFLOW_OTEL_ENDPOINT", OTEL_ENDPOINT)
        )

        if self.datastore.TYPE == "local":
            local_root = self._local_dev_mount_root()
            nomad_job.volumes.append("%s:%s" % (local_root, local_root))
            nomad_job.environment_variable(
                "METAFLOW_DATASTORE_SYSROOT_LOCAL", local_root
            )
            nomad_job.environment_variable("METAFLOW_DEFAULT_METADATA", "local")
        else:
            nomad_job.environment_variable("METAFLOW_DEFAULT_METADATA", DEFAULT_METADATA)

        for key, value in config_values():
            if key.startswith("METAFLOW_CONDA_") or key.startswith("METAFLOW_DEBUG_"):
                nomad_job.environment_variable(key, value)

        if DEFAULT_SECRETS_BACKEND_TYPE is not None:
            nomad_job.environment_variable(
                "METAFLOW_DEFAULT_SECRETS_BACKEND_TYPE", DEFAULT_SECRETS_BACKEND_TYPE
            )
        if S3_SERVER_SIDE_ENCRYPTION is not None:
            nomad_job.environment_variable(
                "METAFLOW_S3_SERVER_SIDE_ENCRYPTION", S3_SERVER_SIDE_ENCRYPTION
            )
        if S3_ENDPOINT_URL is not None:
            nomad_job.environment_variable("METAFLOW_S3_ENDPOINT_URL", S3_ENDPOINT_URL)

        for name, value in env.items():
            nomad_job.environment_variable(name, value)

        return nomad_job

    def launch_job(self, **kwargs):
        self.job = self.create_job(**kwargs).create().execute()

    def wait(self, echo=None, poll_interval=1.0):
        def emit_new_logs(job, seen):
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
                        echo(line, stream_name, job_id=job.id)
                seen[stream_name] = stream_value

        status = self.job.status
        echo("Task is starting (%s)..." % status, "stderr", job_id=self.job.id)
        started = time.time()
        while self.job.is_waiting:
            new_status = self.job.status
            if new_status != status or (time.time() - started) > 10:
                status = new_status
                echo("Task is starting (%s)..." % status, "stderr", job_id=self.job.id)
                started = time.time()
            time.sleep(poll_interval)

        seen = {"stdout": "", "stderr": ""}
        while not self.job.has_finished:
            emit_new_logs(self.job, seen)
            time.sleep(poll_interval)
        emit_new_logs(self.job, seen)

        if self.job.has_failed:
            msg = next(
                msg for msg in [self.job.message, "Task crashed."] if msg is not None
            )
            exit_code = self.job.exit_code
            if exit_code is not None:
                msg = "%s (exit code %s)" % (msg, exit_code)
            lower_msg = msg.lower()
            if self.datastore.TYPE == "local" and (
                "volume" in lower_msg
                or "mount" in lower_msg
                or "bind" in lower_msg
                or "driver" in lower_msg
            ):
                msg = (
                    "%s For local-datastore Docker runs, start the Nomad dev agent "
                    "with dev/nomad-dev-docker-volumes.hcl so Docker bind mounts are enabled."
                ) % msg
            raise NomadException(
                "%s This could be a transient error. Use @retry to retry." % msg
            )

        if self.job.is_running:
            raise NomadKilledException("Task failed!")

        echo(
            "Task finished with exit code %s." % self.job.exit_code,
            "stderr",
            job_id=self.job.id,
        )
