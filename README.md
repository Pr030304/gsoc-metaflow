# GSoC Metaflow Nomad Workspace

This repository contains my preparation, experiments, design notes, and proof-of-work implementation for the **Metaflow Nomad Integration** GSoC project.

The workspace is not a single polished package. It is organized as a working project folder with:

- design and architecture notes
- Nomad HCL experiments
- findings from local testing
- small helper scripts
- a working `metaflow-nomad` prototype extension

## Important files and folders

### `design.md`

This is the main technical design note for the project.

It covers:

- proposed `@nomad` backend architecture
- mapping from `metaflow-slurm` concepts to Nomad concepts
- jobspec generation and execution flow
- log handling
- retry design
- risks and scope decisions

If you want to understand the intended project structure first, start here.

### `notes/findings.md`

This file summarizes local Nomad experiments and the behaviors they revealed.

It includes findings from:

- successful Docker job execution
- failing jobs with default Nomad retry behavior
- restart-disabled tests
- restart + reschedule disabled tests

This file is especially relevant for understanding why the current backend design keeps Metaflow `@retry` in charge of visible retry behavior.

### `examples/`

This folder contains the early Nomad and Metaflow experiments used to validate scheduler behavior before building the backend.

Contents:

- `docker-job.nomad.hcl`
  - minimal successful Docker batch job on Nomad
- `fail-job.nomad.hcl`
  - failing Docker job showing default failure / retry behavior
- `fail-test.nomad.hcl`
  - failing job configured to avoid hidden Nomad retries
- `fail-test-once.nomad.hcl`
  - related failure-mode experiment for restart/reschedule behavior
- `helloworld.py`
  - simple local Metaflow flow used during setup and validation

These examples are mainly for scheduler experiments and reproducibility.

### `scripts/`

This folder contains helper prototypes used before the full `metaflow-nomad` extension path was working.

These scripts demonstrate:

- Nomad API submission
- allocation polling
- log retrieval
- jobspec generation

They are useful as backend experiments and intermediate proof-of-work, but the stronger artifact is the `metaflow-nomad/` directory.

### `metaflow-nomad/`

This is the main proof-of-work implementation.

It contains a working prototype of a `@nomad` backend for Metaflow, including:

- installable extension scaffold
- `@nomad` step decorator
- `nomad step` CLI path
- Nomad jobspec generation
- Nomad HTTP API submission
- allocation polling
- exit-code extraction
- log retrieval
- a verified end-to-end example flow where a Metaflow step runs remotely on a local Nomad dev agent

This is the most important folder in the workspace.

Start with:

- [metaflow-nomad/README.md](./metaflow-nomad/README.md)

### `metaflow/`

Local clone of the main Metaflow codebase used for reading core runtime, plugin, decorator, and remote-backend implementations.

### `metaflow-slurm/`

Local clone of the Slurm extension used as the primary architectural reference for the Nomad backend.

### `metaflow-slurm-fork/`

Local fork used for contribution experiments and candidate upstream fixes while studying backend behavior.

## Suggested reading order

If you are reviewing this workspace quickly, this order is best:

1. `design.md`
2. `notes/findings.md`
3. `metaflow-nomad/README.md`
4. `metaflow-nomad/examples/hello_nomad_flow.py`
5. `examples/` HCL files if you want to see the earlier scheduler experiments

## Current status

At this stage, the strongest result in the workspace is that the `metaflow-nomad` prototype can:

- register `@nomad` with Metaflow
- submit a Metaflow step to a local Nomad dev cluster as a Docker batch task
- poll Nomad allocation state
- stream allocation logs back into the Metaflow CLI
- propagate terminal success back to Metaflow

This workspace should be read as a **working prototype plus supporting design and experiments**, not yet as a production-ready extension.
