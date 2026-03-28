# Metaflow Nomad Prototype

This repository is a proof-of-work implementation for a `@nomad` compute backend for Metaflow.

It is intentionally narrow:

- installable Metaflow extension scaffold
- `@nomad` step decorator wiring
- `nomad step` CLI path
- programmatic Nomad batch job submission over the HTTP API
- Docker task driver support
- CPU / memory / image configuration
- allocation polling
- exit-code extraction
- stdout / stderr retrieval from Nomad allocation logs

## Current scope

This prototype is designed to demonstrate the backend architecture and one honest end-to-end execution path on a local Nomad dev agent. It is not yet a production-ready extension.

Implemented:

- extension registration and module layout mirroring `metaflow-slurm`
- backend-specific decorator, CLI, client, and job modules
- Nomad batch jobs with restart/reschedule disabled by default
- allocation-based terminal state handling
- log streaming by polling allocation logs
- example flow using `@nomad`

Not yet implemented:

- full retry integration with Metaflow `@retry`
- exhaustive metadata synchronization
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
python examples/hello_nomad_flow.py run
```

Notes:

- Run the full `@nomad` flow path from WSL/Linux, not native Windows.
- The current prototype supports local-datastore development only from WSL/Linux.
- For the Docker driver, local-datastore runs require Nomad to allow Docker bind
  mounts. The included dev config enables this using
  `client.options["docker.volumes.enabled"] = true`.
- For the narrow standalone proof-of-work, use `examples/runnable_nomad_demo.py`.

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
