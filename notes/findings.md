# Nomad Local Validation Findings

This document summarizes the local Nomad experiments used to validate the proposed `@nomad` backend design for Metaflow. All tests were run against a local Nomad dev agent with the Docker task driver enabled.

## Test Environment

- Nomad dev agent running locally
- Docker driver enabled through Docker Desktop + WSL
- Test image: `python:3.11-slim`
- Resource shape used in all jobs:
  - `cpu = 500`
  - `memory = 256`

## 1. Successful Docker Batch Job

Jobspec: [docker-job.nomad.hcl](/c:/Users/Pranjali/OneDrive/Desktop/gsoc/examples/docker-job.nomad.hcl)

### Purpose

Validate the base execution path for a Nomad-backed Metaflow step:

- batch job submission
- allocation creation
- task completion
- exit code propagation
- stdout log retrieval

### Result

- Nomad accepted the batch job and created one allocation.
- The task completed successfully with `Exit Code: 0`.
- `nomad alloc logs` returned the expected stdout output: `nomad docker job ok`.

### Implication for `@nomad`

This confirms the basic Docker-driver path is viable for the MVP. A Metaflow step can be represented as a single Nomad batch task and monitored through allocation state until successful completion.

## 2. Failing Docker Job with Default Retry Behavior

Jobspec: [fail-job.nomad.hcl](/c:/Users/Pranjali/OneDrive/Desktop/gsoc/examples/fail-job.nomad.hcl)

### Purpose

Observe Nomad's default behavior for a task that exits non-zero without any explicit restart or reschedule controls.

### Result

- The task exited with `Exit Code: 2`.
- Nomad retried the task automatically inside the same allocation lifecycle.
- Task events showed repeated `Restarting` and `Terminated` transitions.
- `nomad alloc logs` showed repeated output:
  - `failing`
  - `failing`
  - `failing`

### Key Finding

Nomad's default behavior can hide retries from higher-level workflow logic. If this behavior is left unchanged, Metaflow `@retry` would not be the only retry mechanism affecting task execution.

### Implication for `@nomad`

The backend should not rely on Nomad defaults for retry behavior. Retry ownership must remain explicit, predictable, and aligned with Metaflow semantics.

## 3. Failing Job with Restart Disabled but Reschedule Still Active

Jobspec: [fail-test-once.nomad.hcl](/c:/Users/Pranjali/OneDrive/Desktop/gsoc/examples/fail-test-once.nomad.hcl)

### Purpose

Test whether disabling task restart alone is sufficient to guarantee single-attempt execution.

### Result

- Task events showed `Not Restarting`, confirming the restart policy was honored.
- Despite that, the job still produced a replacement allocation.
- Allocation metadata showed:
  - `Replacement Alloc ID`
  - `Reschedule Attempts = 1/1`
- Both allocations failed with `Exit Code: 2`.
- Logs were available from both failed allocations.

### Key Finding

Disabling Nomad task restart is not enough to prevent hidden retries. Nomad restart policy and allocation reschedule policy are separate controls.

### Implication for `@nomad`

This is the most important scheduler-level finding from local testing. A Metaflow backend that wants retries to remain controlled by `@retry` must explicitly consider both:

- task restart policy
- allocation reschedule policy

## 4. Failing Job with Restart and Reschedule Disabled

Jobspec: [fail-test.nomad.hcl](/c:/Users/Pranjali/OneDrive/Desktop/gsoc/examples/fail-test.nomad.hcl)

### Purpose

Validate a clean single-attempt failure path that better matches Metaflow retry expectations.

### Result

- A single allocation was created for the job.
- The task failed once with `Exit Code: 2`.
- Task events included `Not Restarting`.
- The final job status transitioned to `dead`.
- Job status showed one failed allocation and no replacement allocation after settling.
- `nomad alloc logs` returned the expected output: `failing once`.

### Key Finding

Setting both:

- `restart.attempts = 0`
- `reschedule.attempts = 0`

produces a much cleaner one-attempt execution model for failed tasks.

### Implication for `@nomad`

This is the preferred MVP failure behavior because it keeps the mapping simple:

- one Metaflow attempt
- one Nomad job submission path
- one allocation lifecycle
- one terminal success or failure outcome

That makes retry handling much easier to integrate cleanly with Metaflow `@retry`.

## Cross-Test Conclusions

### Submission and monitoring

Nomad batch jobs are a workable execution model for Metaflow steps. A job can be submitted, tracked through allocations, and resolved into a terminal state using job and allocation APIs.

### Exit code handling

Nomad surfaces non-zero container exits clearly in task events. This is sufficient to translate Nomad task failure into Metaflow task failure.

### Log retrieval

`nomad alloc logs` provides useful stdout for both success and failure cases. Allocation logs are a viable source for CLI log streaming or final log retrieval in an MVP backend.

### Retry semantics

The most important design constraint is that Nomad has more than one retry-related mechanism. A backend that wants Metaflow to own retries must explicitly disable hidden scheduler retries when appropriate.

### Test hygiene

Reusing the same Nomad job ID can retain prior allocation history and make debugging noisy. For repeatable backend tests, previous jobs should be purged before rerunning:

```bash
nomad job stop -purge <job_id>
```

## Resulting MVP Recommendation

For the initial `@nomad` implementation:

- use Nomad batch jobs
- use the Docker driver first
- monitor allocation state for terminal success or failure
- retrieve logs from allocation APIs
- disable scheduler-level retry behavior by default for Metaflow-managed attempts
- let Metaflow `@retry` own visible retry behavior
