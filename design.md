# Metaflow Nomad Integration Design

## Overview

This document proposes a `@nomad` compute backend for Metaflow that executes decorated steps as Nomad batch jobs. The initial target is a practical MVP aligned with the project brief:

- `@nomad` step decorator
- Docker task driver support
- basic CPU and memory configuration
- job submission, polling, and exit-code handling
- stdout/stderr log retrieval in the Metaflow CLI
- compatibility with Metaflow `@retry`

The design follows the extension pattern used by `metaflow-slurm`, but replaces its SSH and `sbatch` control path with Nomad's HTTP API and allocation model. This is the central architectural shift: Slurm launches shell scripts on a remote login node, while Nomad accepts a jobspec, schedules an allocation, and exposes job state and logs through API endpoints.

This document began as a forward-looking design note, but parts of it are now validated by a working local prototype. In particular, the following path has been verified on a local Nomad dev agent:

- Metaflow loads and recognizes `@nomad`
- a `@nomad` step is redirected to `nomad step`
- the backend submits a Docker batch job to Nomad
- Metaflow polls allocation state through backend code
- allocation logs are surfaced in the Metaflow CLI
- the remote step completes and the flow continues locally

The prototype is still intentionally narrow and local-development-oriented, but it now validates the core scheduler integration path rather than only the underlying Nomad experiments.

## Goals

### Primary goals

- Add a `@nomad` decorator that schedules a Metaflow step as a Nomad batch job.
- Support Docker-based execution so remote steps run in containers, similar in spirit to Metaflow's existing cloud/container backends.
- Translate basic resource requests from the decorator into a Nomad jobspec.
- Monitor Nomad jobs until terminal completion and surface success or failure back to Metaflow.
- Retrieve and display task logs from the corresponding Nomad allocation.
- Preserve Metaflow retry semantics instead of delegating retries implicitly to Nomad.

### Non-goals for the MVP

- Full parity with every Nomad driver or scheduling feature.
- Multi-task or service-style jobs.
- Advanced networking, Vault, Consul, CSI volumes, or placement policies.
- GPU support and `exec` driver support. These remain explicit stretch goals.

## Reference Architecture

The strongest local reference is `metaflow-slurm`, especially these modules:

- `slurm_decorator.py`: decorator lifecycle hooks and runtime CLI rewrite
- `slurm_cli.py`: backend-specific `step` command invoked by Metaflow runtime
- `slurm.py`: remote command construction, environment propagation, wait loop, log handling
- `slurm_job.py`: backend job abstraction and terminal-state classification
- `slurm_client.py`: scheduler transport layer

The Nomad backend should preserve the same high-level division of responsibilities while swapping in Nomad-native primitives.

### Proposed module mapping

| Slurm module | Proposed Nomad module | Responsibility |
| --- | --- | --- |
| `slurm_decorator.py` | `nomad_decorator.py` | Step decorator attributes, lifecycle validation, package staging, runtime CLI rewrite, task metadata registration |
| `slurm_cli.py` | `nomad_cli.py` | `nomad step` entrypoint used by Metaflow runtime to submit and monitor one remote step |
| `slurm.py` | `nomad.py` | Command/bootstrap construction, jobspec assembly, launch, polling, log tailing, cleanup |
| `slurm_job.py` | `nomad_job.py` | Job and allocation abstraction, status normalization, terminal state handling, cancellation |
| `slurm_client.py` | `nomad_client.py` | HTTP client for Jobs, Allocations, and Client FS logs endpoints |
| `slurm_exceptions.py` | `nomad_exceptions.py` | Backend-specific exceptions and retry-disallow failures |

## Metaflow Integration Points

Metaflow step decorators influence execution through lifecycle hooks exposed by `StepDecorator`. The Nomad backend should follow the same overall pattern as `metaflow-slurm`:

1. `step_init`
   - validate decorator combinations
   - capture flow datastore, environment, logger, and graph context
   - reject unsupported combinations for the MVP if necessary

2. `package_init`
   - validate soft dependencies such as `python-nomad` or `requests`

3. `runtime_init`
   - cache the package blob, graph, and run metadata

4. `runtime_task_created`
   - save the code package once to the configured Metaflow datastore

5. `runtime_step_cli`
   - rewrite the execution command from local `step` execution to `nomad step`
   - pass the package SHA, package URL, retry count, and decorator attributes

6. `task_pre_step`
   - when running inside Nomad, register Nomad metadata such as job ID, allocation ID, namespace, datacenter, and node ID
   - start Metaflow's log-saving sidecar if needed

7. `task_finished`
   - sync local metadata to the datastore if required
   - terminate the log sidecar

This design keeps the Metaflow-facing behavior close to existing compute backends and limits backend-specific logic to the Nomad transport and job model.

## Decorator API

The MVP decorator should remain intentionally small:

```python
@nomad(
    cpu=500,
    memory=256,
    image="python:3.11-slim",
    datacenters=["dc1"],
    namespace="default",
)
```

### Proposed decorator attributes

- `cpu`: Nomad CPU allocation in MHz or scheduler units, mapped to task resources
- `memory`: memory in MiB
- `image`: Docker image to run the step in
- `namespace`: optional Nomad namespace
- `datacenters`: optional list of Nomad datacenters
- `region`: optional Nomad region
- `job_name_prefix`: optional naming override
- `meta`: optional additional Nomad metadata

Attributes intentionally deferred from the MVP:

- affinities and constraints
- volumes
- network blocks
- service registration
- Vault integration
- devices / GPUs
- `exec` driver support

## Execution Model

### High-level flow

1. User runs a flow locally.
2. A step decorated with `@nomad` enters Metaflow runtime.
3. The Nomad decorator rewrites the step execution to `nomad step`.
4. The backend stages the code package in Metaflow's datastore.
5. The backend builds a Nomad jobspec containing one batch task using the Docker driver.
6. Nomad schedules the job and creates an allocation.
7. The remote task downloads the code package, bootstraps the Metaflow environment, and runs the step command.
8. The backend polls the job/allocation until terminal state.
9. Logs are streamed or fetched from the allocation and surfaced in the CLI.
10. The final Nomad termination state is translated into a Metaflow success, failure, or non-retriable failure.

### Why batch jobs

Nomad batch jobs are the closest fit for a single Metaflow step execution: they run to completion, expose terminal success/failure semantics, and naturally model one-off units of work.

## Job Specification Strategy

Each remote step should be submitted as a distinct Nomad batch job with a single task group and a single task for the MVP.

### Example jobspec shape

```json
{
  "Job": {
    "ID": "user-flow-run-step-task-retry",
    "Name": "user-flow-run-step-task-retry",
    "Type": "batch",
    "Datacenters": ["dc1"],
    "TaskGroups": [
      {
        "Name": "main",
        "RestartPolicy": {
          "Attempts": 0,
          "Mode": "fail"
        },
        "ReschedulePolicy": {
          "Attempts": 0,
          "Unlimited": false
        },
        "Tasks": [
          {
            "Name": "step",
            "Driver": "docker",
            "Config": {
              "image": "python:3.11-slim",
              "command": "bash",
              "args": ["-lc", "<bootstrapped metaflow command>"]
            },
            "Resources": {
              "CPU": 500,
              "MemoryMB": 256
            },
            "Env": {
              "METAFLOW_CODE_URL": "...",
              "METAFLOW_CODE_SHA": "...",
              "METAFLOW_USER": "...",
              "METAFLOW_RUNTIME_ENVIRONMENT": "nomad"
            },
            "Meta": {
              "metaflow.flow_name": "...",
              "metaflow.run_id": "...",
              "metaflow.step_name": "...",
              "metaflow.task_id": "...",
              "metaflow.retry_count": "..."
            }
          }
        ]
      }
    ]
  }
}
```

### Naming

Job IDs should be deterministic and encode enough metadata for debugging:

`{user}-{flow_name}-{run_id}-{step_name}-{task_id}-{retry_count}`

This mirrors the Slurm backend's naming pattern and makes job lookup straightforward.

## Command and Environment Construction

The command construction in `slurm.py` is the most important reusable pattern from the reference implementation. The Nomad backend should keep the same logical sequence:

1. export Metaflow log environment variables
2. initialize the code package from the Metaflow datastore
3. run environment bootstrap commands
4. execute the step command
5. save final logs and propagate the true exit code

For Docker tasks, the command should typically be:

```bash
bash -lc "<metaflow bootstrap + step command + log handling>"
```

### Prototype note: local development bootstrap

The current working prototype supports a local-development path where the code package is staged in Metaflow's local datastore and then copied into the Docker task through a bind-mounted host path. To make that work reliably in a local Nomad dev setup, three details turned out to matter:

- the Nomad client must allow Docker bind mounts
- the task should run from a task-local working directory rather than rely on arbitrary container paths
- the example image may need a small amount of runtime dependency installation before Metaflow starts

These are acceptable for proof-of-work, but a fuller implementation should replace ad hoc runtime setup with a cleaner image and packaging strategy.

### Environment variables to propagate

The Nomad task environment should include the same core Metaflow runtime variables currently propagated by `metaflow-slurm`, including:

- `METAFLOW_CODE_SHA`
- `METAFLOW_CODE_URL`
- `METAFLOW_CODE_DS`
- `METAFLOW_USER`
- `METAFLOW_SERVICE_URL`
- `METAFLOW_SERVICE_HEADERS`
- `METAFLOW_DEFAULT_DATASTORE`
- `METAFLOW_DEFAULT_METADATA`
- `METAFLOW_RUNTIME_ENVIRONMENT=nomad`

Plus Nomad-specific markers such as:

- `METAFLOW_NOMAD_WORKLOAD=1`
- `METAFLOW_NOMAD_JOB_ID`
- `METAFLOW_NOMAD_NAMESPACE`

This enables consistent runtime behavior and metadata collection.

For the current local prototype, an additional implementation detail is important:

- when the datastore is `local`, the remote task should use `METAFLOW_DEFAULT_METADATA=local`

This keeps the local-dev execution path aligned with datastore-backed metadata sync instead of assuming a separately configured Metaflow metadata service inside the Docker task.

## Nomad Client Layer

The Nomad client layer replaces the SSH transport in `slurm_client.py` with HTTP API calls.

### Required API interactions

- submit jobspec
- query job status
- enumerate allocations for a job
- inspect allocation status
- fetch allocation logs
- stop or deregister a job

### Proposed client interface

```python
class NomadClient:
    def submit(self, jobspec) -> str: ...
    def job(self, job_id) -> dict: ...
    def allocations(self, job_id) -> list[dict]: ...
    def allocation(self, alloc_id) -> dict: ...
    def logs(self, alloc_id, task_name, log_type, offset=None) -> bytes: ...
    def stop(self, job_id, purge=False) -> None: ...
```

`python-nomad` can accelerate this implementation, but the design should not depend on library-specific behavior. A thin abstraction over the HTTP endpoints keeps the backend easier to test and less coupled to any client library.

## Monitoring and Terminal State Handling

Nomad exposes status at both job and allocation scope. For Metaflow, allocation state is the decisive signal because the actual step executes inside the allocation task.

### Monitoring strategy

1. submit the job
2. poll until at least one allocation exists
3. identify the active allocation for the task group
4. periodically inspect allocation task states
5. determine terminal outcome from task events and exit code
6. fetch any remaining stdout/stderr logs before returning

### Terminal outcome mapping

- task exit code `0` -> Metaflow success
- non-zero exit code -> Metaflow failure
- explicit kill / stop by user -> non-retriable failure
- allocation lost / node failure -> retriable or non-retriable depending on existing Metaflow retry policy and failure classification

The backend should normalize Nomad-specific states into a small internal model:

- `PENDING`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `LOST`
- `KILLED`

## Logs

Log retrieval is a first-class requirement because users expect to see remote step output in the Metaflow CLI.

### Strategy

- Prefer allocation stdout/stderr retrieval through Nomad's client filesystem log APIs.
- Tail logs incrementally while the allocation is running if feasible.
- Always perform a final log fetch after terminal completion to avoid truncation.

### Important edge case

OOMs and hard crashes can terminate the container before the final log-save path executes inside the task command. The backend should therefore not rely only on in-task log persistence. It must retrieve logs from Nomad allocation APIs as the source of truth for CLI display.

This matches the local experiments already performed:

- successful Docker tasks expose logs through `nomad alloc logs`
- failing tasks expose the non-zero exit code and logs
- retry behavior can create multiple allocations, so the backend must decide which allocation's logs to surface for the active attempt

The current prototype also validates a stronger claim than the earlier HCL-only tests: allocation logs can be shown back through the Metaflow CLI during a real `@nomad` step execution, not just by manual `nomad alloc logs` inspection.

## Retry Semantics

This is the most important design constraint beyond basic job submission.

Metaflow already has a `@retry` abstraction, and the Nomad backend should integrate with it rather than allow Nomad to retry tasks invisibly underneath Metaflow.

### Key observation from local validation

Nomad task restart policy and allocation reschedule policy are separate controls. Disabling task restart alone does not guarantee single-attempt execution; Nomad may still reschedule failed allocations unless rescheduling is also constrained.

### MVP policy

For the MVP, Nomad jobs launched by Metaflow should default to:

- no task restarts
- no allocation rescheduling

This keeps each Metaflow task attempt mapped to exactly one Nomad submission path, so retries remain visible and owned by Metaflow.

### Metaflow retry integration

- If a task fails and Metaflow permits another retry, Metaflow should submit a fresh Nomad job attempt.
- Retry metadata should be recorded both in Metaflow metadata and in the Nomad job metadata.
- User-visible logs should correspond to the current Metaflow attempt, not a hidden Nomad reschedule attempt.

## Metadata

When executing inside Nomad, the backend should attach useful scheduler metadata to the Metaflow task:

- Nomad job ID
- evaluation ID
- allocation ID
- node ID / node name
- namespace
- datacenter
- task driver

This mirrors what `metaflow-slurm` already does for debugging and makes remote failures much easier to diagnose.

## Testing Strategy

The testing plan should combine unit and integration coverage.

### Unit tests

- jobspec generation from decorator attributes
- job naming and metadata encoding
- terminal state normalization
- retry policy configuration
- parsing allocation task state and exit codes

### Integration tests

- submit a successful Docker batch job and verify Metaflow step completion
- submit a failing job and verify non-zero exit propagation
- verify stdout/stderr retrieval
- verify no hidden retries when Nomad restart and reschedule are disabled
- verify Metaflow `@retry` resubmits a fresh Nomad-backed attempt

The integration environment can initially target a local Nomad dev agent with the Docker driver enabled.

### Validation already completed locally

The following has already been validated manually in the current proof-of-work implementation:

- Nomad Docker batch job submission through backend code
- allocation polling and terminal-state handling
- log retrieval for successful and failing tasks
- a full Metaflow flow where the `start` step runs remotely under `@nomad` and the `end` step continues locally after successful completion

This means the next testing work is less about proving basic feasibility and more about making the behavior cleaner, more portable, and better covered by automated tests.

## MVP Deliverables

1. `@nomad` step decorator
2. `nomad step` CLI path
3. Nomad job submission backend
4. Docker driver support
5. CPU and memory configuration
6. job polling and exit-code handling
7. stdout/stderr retrieval in CLI
8. basic retry integration with Metaflow `@retry`
9. example flow and setup documentation
10. automated tests covering success and failure paths

## Stretch Goals

### Exec driver support

Add support for Nomad's `exec` driver to run binaries directly on clients without containers. This likely requires additional bootstrap assumptions about the remote environment and is better deferred until the Docker path is stable.

### GPU support

Add GPU resource requests through Nomad device plugins and corresponding decorator attributes. This should only be attempted after the core scheduling and retry behavior is stable.

## Risks and Mitigations

### Retry ambiguity between Metaflow and Nomad

Risk:
Nomad restarts or reschedules allocations behind Metaflow's back, making attempts hard to reason about.

Mitigation:
Explicitly disable restart and reschedule in the MVP jobspec and let Metaflow own retries.

### Log truncation on crashes

Risk:
Container termination can prevent in-task cleanup logic from persisting final logs.

Mitigation:
Use Nomad allocation logs APIs as the authoritative log source for CLI output.

### Status ambiguity across multiple allocations

Risk:
A batch job may create replacement allocations after failure or reschedule.

Mitigation:
Track the active allocation for the current attempt and normalize task events carefully.

### Environment drift between local and remote execution

Risk:
The Docker image may not contain the tools needed to bootstrap and run the Metaflow step.

Mitigation:
Start with a documented reference image and keep the bootstrap logic close to existing Metaflow remote backends. The current prototype solved this narrowly by installing a small runtime dependency set inside the task, but the full project should move toward cleaner image-based dependency management.

## Why This Scope Is Correct

The proposed MVP is deliberately smaller than the full Nomad feature surface but large enough to be genuinely useful:

- users can run real Metaflow steps on existing Nomad clusters
- the design respects Metaflow's current execution model
- the implementation reuses proven extension patterns from `metaflow-slurm`
- the hardest lifecycle pieces for a first version, namely submission, monitoring, logs, and retries, are addressed explicitly

This avoids the common proposal failure mode of overscoping the first milestone while still delivering a backend that the community can extend later.

## Sources

- Metaflow step decorators: https://docs.metaflow.org/api/step-decorators
- Metaflow API docs: https://docs.metaflow.org/api
- Metaflow failure and retry behavior: https://docs.metaflow.org/scaling/failures
- Metaflow docs root: https://docs.metaflow.org/
- Nomad jobs and job lifecycle concepts: https://developer.hashicorp.com/nomad/docs/concepts/job
- Nomad Jobs API: https://developer.hashicorp.com/nomad/api-docs/jobs
- Nomad job specification docs: https://developer.hashicorp.com/nomad/docs/job-specification
- `metaflow-slurm` reference implementation: https://github.com/outerbounds/metaflow-slurm
- Metaflow extensions template: https://github.com/Netflix/metaflow-extensions-template
