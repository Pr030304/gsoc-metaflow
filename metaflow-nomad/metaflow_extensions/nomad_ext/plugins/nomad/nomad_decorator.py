import os
import sys

from metaflow import R
from metaflow.decorators import StepDecorator
from metaflow.exception import MetaflowException
from metaflow.metadata_provider import MetaDatum
from metaflow.metadata_provider.util import sync_local_metadata_to_datastore
from metaflow.metaflow_config import DATASTORE_LOCAL_DIR, FEAT_ALWAYS_UPLOAD_CODE_PACKAGE
from metaflow.sidecar import Sidecar

from metaflow_extensions.nomad_ext.config.mfextinit_nomad_ext import (
    NOMAD_ADDRESS,
    NOMAD_DATACENTERS,
    NOMAD_IMAGE,
    NOMAD_NAMESPACE,
    NOMAD_REGION,
    NOMAD_TOKEN,
)

from .nomad_exceptions import NomadException


class NomadDecorator(StepDecorator):
    name = "nomad"

    defaults = {
        "address": None,
        "namespace": None,
        "region": None,
        "token": None,
        "datacenters": None,
        "image": None,
        "cpu": 500,
        "memory": 256,
    }

    package_metadata = None
    package_url = None
    package_sha = None

    def __init__(self, attributes=None, statically_defined=False):
        super(NomadDecorator, self).__init__(attributes, statically_defined)
        if not self.attributes["address"]:
            self.attributes["address"] = NOMAD_ADDRESS
        if not self.attributes["namespace"]:
            self.attributes["namespace"] = NOMAD_NAMESPACE
        if not self.attributes["region"]:
            self.attributes["region"] = NOMAD_REGION
        if not self.attributes["token"]:
            self.attributes["token"] = NOMAD_TOKEN
        if not self.attributes["datacenters"]:
            self.attributes["datacenters"] = NOMAD_DATACENTERS
        if not self.attributes["image"]:
            self.attributes["image"] = NOMAD_IMAGE or "python:3.11-slim"

    def step_init(self, flow, graph, step, decos, environment, flow_datastore, logger):
        self.logger = logger
        self.environment = environment
        self.step = step
        self.flow_datastore = flow_datastore

        if any(deco.name == "parallel" for deco in decos):
            raise MetaflowException(
                "Step *{step}* contains a @parallel decorator with the @nomad "
                "decorator. @parallel is not yet supported with @nomad.".format(
                    step=step
                )
            )

    def package_init(self, flow, step_name, environment):
        try:
            import requests  # noqa: F401
        except (ImportError, ModuleNotFoundError):
            raise NomadException(
                "Could not import module 'requests'.\n\nInstall requests first:\n"
                "%s -m pip install requests" % sys.executable
            )

    def runtime_init(self, flow, graph, package, run_id):
        self.flow = flow
        self.graph = graph
        self.package = package
        self.run_id = run_id

    def runtime_task_created(
        self, task_datastore, task_id, split_index, input_paths, is_cloned, ubf_context
    ):
        if not is_cloned:
            self._save_package_once(self.flow_datastore, self.package)

    def runtime_step_cli(self, cli_args, retry_count, max_user_code_retries, ubf_context):
        if retry_count <= max_user_code_retries:
            cli_args.commands = ["nomad", "step"]
            cli_args.command_args.append(self.package_metadata)
            cli_args.command_args.append(self.package_sha)
            cli_args.command_args.append(self.package_url)

            command_options = dict(self.attributes)
            if "namespace" in command_options:
                command_options["nomad-namespace"] = command_options.pop("namespace")
            cli_args.command_options.update(command_options)

            if not R.use_r():
                cli_args.entrypoint[0] = sys.executable

    def task_pre_step(
        self,
        step_name,
        task_datastore,
        metadata,
        run_id,
        task_id,
        flow,
        graph,
        retry_count,
        max_retries,
        ubf_context,
        inputs,
    ):
        self.metadata = metadata
        self.task_datastore = task_datastore

        meta = {}
        if "METAFLOW_NOMAD_WORKLOAD" in os.environ:
            for field in (
                "NOMAD_JOB_ID",
                "NOMAD_ALLOC_ID",
                "NOMAD_NAMESPACE",
                "NOMAD_DC",
                "NOMAD_REGION",
                "NOMAD_TASK_NAME",
            ):
                value = os.environ.get(field)
                if value:
                    meta[field.lower().replace("_", "-")] = value

            self._save_logs_sidecar = Sidecar("save_logs_periodically")
            self._save_logs_sidecar.start()

        if meta:
            entries = [
                MetaDatum(
                    field=key,
                    value=value,
                    type=key,
                    tags=["attempt_id:{0}".format(retry_count)],
                )
                for key, value in meta.items()
            ]
            metadata.register_metadata(run_id, step_name, task_id, entries)

    def task_finished(self, step_name, flow, graph, is_task_ok, retry_count, max_retries):
        if "METAFLOW_NOMAD_WORKLOAD" in os.environ:
            if hasattr(self, "metadata") and self.metadata.TYPE == "local":
                sync_local_metadata_to_datastore(
                    DATASTORE_LOCAL_DIR, self.task_datastore
                )

        try:
            self._save_logs_sidecar.terminate()
        except Exception:
            pass

    @classmethod
    def _save_package_once(cls, flow_datastore, package):
        if cls.package_url is None:
            if not FEAT_ALWAYS_UPLOAD_CODE_PACKAGE:
                cls.package_url, cls.package_sha = flow_datastore.save_data(
                    [package.blob], len_hint=1
                )[0]
                cls.package_metadata = package.package_metadata
            else:
                cls.package_url = package.package_url()
                cls.package_sha = package.package_sha()
                cls.package_metadata = package.package_metadata
