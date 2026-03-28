import os
import sys
import time
import traceback

from metaflow import R, util
from metaflow._vendor import click
from metaflow.exception import METAFLOW_EXIT_DISALLOW_RETRY
from metaflow.metadata_provider.util import sync_local_metadata_from_datastore
from metaflow.metaflow_config import DATASTORE_LOCAL_DIR

from .nomad import Nomad
from .nomad_exceptions import NomadKilledException


@click.group()
def cli():
    pass


@cli.group(help="Commands related to Nomad.")
def nomad():
    pass


@nomad.command(
    help="Execute a single task using Nomad. This command calls the top-level "
    "step command inside a Nomad batch job with the given options. Typically "
    "you do not call this command directly; it is used internally by Metaflow."
)
@click.argument("step-name")
@click.argument("code-package-metadata")
@click.argument("code-package-sha")
@click.argument("code-package-url")
@click.option("--executable", help="Executable requirement for Nomad.")
@click.option("--address", help="Nomad HTTP API address.")
@click.option("--token", help="Nomad ACL token.")
@click.option("--region", help="Nomad region.")
@click.option("--nomad-namespace", default=None, help="Nomad namespace.")
@click.option("--datacenters", default=None, help="Comma-separated Nomad datacenters.")
@click.option("--image", help="Docker image for the Nomad task.")
@click.option("--cpu", default=500, help="CPU requirement for Nomad task.")
@click.option("--memory", default=256, help="Memory requirement for Nomad task.")
@click.option("--run-id", help="Passed to the top-level 'step'.")
@click.option("--task-id", help="Passed to the top-level 'step'.")
@click.option("--input-paths", help="Passed to the top-level 'step'.")
@click.option("--split-index", help="Passed to the top-level 'step'.")
@click.option("--clone-path", help="Passed to the top-level 'step'.")
@click.option("--clone-run-id", help="Passed to the top-level 'step'.")
@click.option("--tag", multiple=True, default=None, help="Passed to the top-level 'step'.")
@click.option("--namespace", default=None, help="Passed to the top-level 'step'.")
@click.option("--retry-count", default=0, help="Passed to the top-level 'step'.")
@click.option(
    "--max-user-code-retries", default=0, help="Passed to the top-level 'step'."
)
@click.pass_context
def step(
    ctx,
    step_name,
    code_package_metadata,
    code_package_sha,
    code_package_url,
    executable=None,
    address=None,
    token=None,
    region=None,
    nomad_namespace=None,
    datacenters=None,
    image=None,
    cpu=500,
    memory=256,
    **kwargs,
):
    def echo(msg, stream="stderr", job_id=None, **echo_kwargs):
        msg = util.to_unicode(msg)
        if job_id:
            msg = "[%s] %s" % (job_id, msg)
        ctx.obj.echo_always(msg, err=(stream == "stderr"), **echo_kwargs)

    if R.use_r():
        entrypoint = R.entrypoint()
    else:
        executable = ctx.obj.environment.executable(step_name, executable)
        entrypoint = "%s -u %s" % (executable, os.path.basename(sys.argv[0]))

    node = ctx.obj.graph[step_name]
    top_args = " ".join(util.dict_to_cli_options(ctx.parent.parent.params))

    env = {"METAFLOW_FLOW_FILENAME": os.path.basename(sys.argv[0])}
    env_deco = [deco for deco in node.decorators if deco.name == "environment"]
    if env_deco:
        env.update(dict(env_deco[0].attributes["vars"]))

    input_paths = kwargs.get("input_paths")
    split_vars = None
    if input_paths:
        max_size = 30 * 1024
        split_vars = {
            "METAFLOW_INPUT_PATHS_%d" % (i // max_size): input_paths[i : i + max_size]
            for i in range(0, len(input_paths), max_size)
        }
        kwargs["input_paths"] = "".join("$%s" % key for key in split_vars.keys())
        env.update(split_vars)

    step_args = " ".join(util.dict_to_cli_options(kwargs))
    step_cli = "{entrypoint} {top_args} step {step} {step_args}".format(
        entrypoint=entrypoint,
        top_args=top_args,
        step=step_name,
        step_args=step_args,
    )

    retry_count = int(kwargs.get("retry_count", 0))
    retry_deco = [deco for deco in node.decorators if deco.name == "retry"]
    minutes_between_retries = None
    if retry_deco:
        minutes_between_retries = int(
            retry_deco[0].attributes.get("minutes_between_retries", 1)
        )
    if retry_count:
        ctx.obj.echo_always(
            "Sleeping %d minutes before the next retry" % minutes_between_retries
        )
        time.sleep(minutes_between_retries * 60)

    task_spec = {
        "flow_name": ctx.obj.flow.name,
        "step_name": step_name,
        "run_id": kwargs["run_id"],
        "task_id": kwargs["task_id"],
        "retry_count": str(retry_count),
    }
    attrs = {"metaflow.%s" % key: value for key, value in task_spec.items()}
    attrs["metaflow.user"] = util.get_username()
    attrs["metaflow.version"] = ctx.obj.environment.get_environment_info()[
        "metaflow_version"
    ]

    def _sync_metadata():
        if ctx.obj.metadata.TYPE == "local":
            try:
                sync_local_metadata_from_datastore(
                    DATASTORE_LOCAL_DIR,
                    ctx.obj.flow_datastore.get_task_datastore(
                        kwargs["run_id"], step_name, kwargs["task_id"]
                    ),
                )
            except Exception as exc:
                ctx.obj.echo_always(
                    "Skipping local metadata sync for @nomad step: %s" % util.to_unicode(exc),
                    err=True,
                )

    try:
        nomad_backend = Nomad(
            datastore=ctx.obj.flow_datastore,
            metadata=ctx.obj.metadata,
            environment=ctx.obj.environment,
            nomad_access_params={
                "address": address,
                "namespace": nomad_namespace,
                "region": region,
                "token": token,
            },
        )
        with ctx.obj.monitor.measure("metaflow.nomad.launch_job"):
            nomad_backend.launch_job(
                step_name=step_name,
                step_cli=step_cli,
                task_spec=task_spec,
                code_package_metadata=code_package_metadata,
                code_package_sha=code_package_sha,
                code_package_url=code_package_url,
                code_package_ds=ctx.obj.flow_datastore.TYPE,
                image=image or "python:3.11-slim",
                cpu=cpu,
                memory=memory,
                datacenters=datacenters,
                env=env,
                attrs=attrs,
            )
    except Exception:
        traceback.print_exc(chain=False)
        _sync_metadata()
        sys.exit(METAFLOW_EXIT_DISALLOW_RETRY)

    try:
        nomad_backend.wait(echo=echo)
    except NomadKilledException:
        traceback.print_exc()
        sys.exit(METAFLOW_EXIT_DISALLOW_RETRY)
    finally:
        _sync_metadata()
