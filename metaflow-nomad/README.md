# Metaflow Nomad Prototype

This repository is a proof-of-work implementation of a `@nomad` compute backend for Metaflow.

It is built to answer one concrete question:

Can a Metaflow step be redirected to HashiCorp Nomad, executed as a Docker batch task, monitored through the Nomad API, and surfaced back to the Metaflow CLI with logs and terminal status?

For a local Nomad dev cluster, the answer is now yes.

## What this prototype does

The current prototype implements the core pieces required for a basic `@nomad` backend:

- `@nomad` step decorator with `cpu`, `memory`, `image`, `namespace`, and `datacenters` settings
- Metaflow runtime integration through a `nomad step` CLI path
- Nomad jobspec generation for Docker batch jobs
- job submission through the Nomad HTTP API
- allocation polling for pending, running, complete, and failed states
- exit-code extraction from Nomad task events
- stdout / stderr retrieval from Nomad allocation logs
- a working end-to-end example flow that runs a Metaflow step remotely on Nomad

## Verified end-to-end behavior

This repo is no longer only a design or HCL experiment. The prototype has been verified locally with:

- Metaflow recognizing and loading the `@nomad` decorator
- a `@nomad` step being rewritten to the Nomad backend path
- Nomad accepting and scheduling the generated Docker job
- Metaflow polling the Nomad allocation state through backend code
- Nomad allocation logs being shown back in the Metaflow CLI
- the remote step completing successfully and the flow continuing to the next local step

In the current successful path:

- `start` runs remotely on Nomad
- `end` runs locally in Metaflow
- the CLI shows remote logs such as `hello from @nomad`
- Metaflow receives terminal success back from the Nomad task

## Architecture

The layout mirrors the structure of `metaflow-slurm`:

- `nomad_decorator.py`: step-decorator lifecycle wiring
- `nomad_cli.py`: `nomad step` command used by Metaflow runtime
- `nomad.py`: backend orchestration, bootstrap, and wait loop
- `nomad_job.py`: jobspec generation and allocation-state model
- `nomad_client.py`: Nomad Jobs / Allocations / Logs API wrapper
- `nomad_exceptions.py`: backend-specific exceptions

## Current scope

This prototype is intentionally narrow. It demonstrates one honest end-to-end execution path on a local Nomad dev agent, but it is not yet a production-ready extension.

Implemented:

- installable Metaflow extension scaffold
- extension registration and module layout mirroring `metaflow-slurm`
- backend-specific decorator, CLI, client, and job modules
- Docker task driver support
- Nomad batch jobs with restart and reschedule disabled by default
- allocation-based terminal state handling
- log retrieval by polling allocation logs
- local proof-of-work flow using `@nomad`

Prototype-grade pieces that still need improvement:

- the example currently installs `requests` inside the Docker task at runtime
- local metadata sync is best-effort rather than fully robust
- local datastore support is intended for WSL/Linux local development only

Not yet implemented:

- full retry integration with Metaflow `@retry`
- exhaustive metadata synchronization
- production-grade image / environment packaging
- `exec` driver support
- GPU support
- production-oriented integration tests

## Local development

1. Start a local Nomad dev agent with Docker bind mounts enabled:

```bash
nomad agent -dev -bind=0.0.0.0 -config dev/nomad-dev-docker-volumes.hcl
```
2. Install the extension in editable mode:

```bash
pip install -e .
```

3. Run the example flow:

```bash
PYTHONPATH=$PWD python examples/hello_nomad_flow.py run
```

Notes:

- Run the full `@nomad` flow path from WSL/Linux, not native Windows.
- The current prototype supports local-datastore development only from WSL/Linux.
- For the Docker driver, local-datastore runs require Nomad to allow Docker bind
  mounts. The included dev config enables this using
  `client.options["docker.volumes.enabled"] = true`.
- For the narrow standalone proof-of-work, use `examples/runnable_nomad_demo.py`.

Expected successful flow shape:

```text
Metaflow ... executing HelloNomadFlow ...
Workflow starting ...
[.../start/1] Task is starting.
[pranjali-HelloNomadFlow-...-start-1-0] Task is starting (pending)...
[pranjali-HelloNomadFlow-...-start-1-0] hello from @nomad
[pranjali-HelloNomadFlow-...-start-1-0] Task finished with exit code 0.
[.../end/2] done
Done!
```

## Runnable demo

For a narrower but fully runnable proof-of-work, this repo also includes a lightweight
Nomad demo that exercises the same core components without requiring full Metaflow
runtime integration:

- `@nomad` decorator for CPU / memory / image config
- jobspec generation
- Nomad API submission
- allocation polling
- stdout / stderr log streaming

Run a successful task:

```bash
python examples/runnable_nomad_demo.py --mode success --print-jobspec
```

Run a failing task:

```bash
python examples/runnable_nomad_demo.py --mode fail --print-jobspec
```

Expected success output includes:

```text
[Nomad] Submitted job: nomad-demo-train
[Nomad][stdout] Epoch 1...
[Nomad][stdout] Epoch 2...
[Nomad][stdout] Training complete
[Nomad] Final status: complete
[Nomad] Exit code: 0
```

Expected failure output includes:

```text
[Nomad] Submitted job: nomad-demo-train-fail
[Nomad][stdout] Epoch 1...
[Nomad][stdout] Worker crashed
[Nomad] Final status: failed
[Nomad] Exit code: 2
```
It is not yet a  fully finished community extension. It is a working prototype that proves the core remote execution path and informs the design of a fuller `@nomad` backend.
