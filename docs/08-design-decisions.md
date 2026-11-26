# Design Decisions

This short log records the main decisions and lessons, including alternatives that were considered and rejected.

| Question or alternative | Decision | Reason and lesson |
|---|---|---|
| Use a separate broker or Redis for the initial queue? | Keep durable jobs and claims in PostgreSQL. | A cache-based “already processing?” check can race. PostgreSQL can lock and update a job atomically. Add infrastructure when a measured need appears. |
| Hold a database transaction open for the full job? | Claim in a short transaction, then execute under a lease. | Long jobs should not hold row locks and database transactions for their full duration. |
| How should a client retry after a submission acknowledgment is lost? | Use a unique idempotency key for each logical submission. | The database constraint prevents duplicate rows. The submission API that returns the existing job is not implemented yet. |
| Can we assume an expired worker has stopped? | Use database-time leases and fence updates with worker ID and attempt. | Logs cannot reliably prove a worker is dead. A stale process may resume; fencing protects job state but cannot undo its effects. |
| Promise exactly-once execution? | Permit repeated execution with bounded retries; let handlers make effects idempotent. | A worker can commit an effect and fail before recording job completion. Queue state alone cannot make that external effect happen exactly once. |
| Add Redis, workflow DAGs, ML routing, or benchmarks now? | Defer them. | The current milestone focuses on database coordination and failure behavior. The later layers need demonstrated requirements and their own evidence. |

## Design evolution

- The project began with PostgreSQL job storage, atomic claims, leases, and recovery ([initial implementation](../engine/persistence/schema.sql)).
- Execution, heartbeats, and handler-failure paths were added next ([worker components](../engine/workers/)).
- Stale-worker fencing was then tested; completing a job was updated to clear its lease ([`complete_job.py`](../engine/workers/complete_job.py)).
- Fault-injection tests later demonstrated both duplicate effects and idempotent effect handling ([fault-injection tests](../tests/fault_injection/)).

These component decisions are implemented, but there is no continuous worker runtime yet. The earlier `run_worker.py` loop bypassed `process_job` and called `execute_job` with the wrong signature, so it was removed rather than patched.

See [Architecture](01-architecture.md) for the current system boundary and [Fault-Injection Evidence](07-fault-injection.md) for what has and has not been tested.

## Architecture decision records

The following accepted decisions summarize the current design; validation refers to the reported tests or implementation, not production certification.

| ADR | Context and decision | Trade-off / validation |
|---|---|---|
| 001 | Use PostgreSQL rather than a separate coordination service | Central dependency; claim tests |
| 002 | Use atomic SKIP LOCKED claims rather than unguarded reads | Not strict FIFO; claim tests |
| 003 | Use leases rather than locks held throughout execution | Expiry does not stop execution; recovery tests |
| 004 | Use separate heartbeat connection | Extra connection per active worker; real heartbeat integration remains pending |
| 005 | Use attempt as fencing token rather than worker ID alone | Protects job row only; fencing tests |
| 006 | Bound retries with max_attempts | Jobs may fail permanently; failure tests |
| 007 | Recover through conditional updates | Concurrent recovery may wait; recovery tests |
| 008 | Permit repeated execution with bounded retries | No exactly-once or guaranteed success; duplicate execution tests |
| 009 | Deduplicate effects at handler boundary | Destination must enforce key; idempotency tests |
| 010 | Test real PostgreSQL concurrency | Requires isolated database; integration and fault tests |
| 011 | Remove obsolete worker loop rather than patch it | Continuous runtime deferred; full suite (23 tests) passes after removal |
