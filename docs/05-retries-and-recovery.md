# Retries and Recovery

The engine retries failed or abandoned work up to a per-job attempt limit. `max_attempts` defaults to 3.

## Handler failure

Each claim increments `attempt`. If the handler fails while the worker still owns a live lease, `fail_job` clears the owner and lease and:

- returns the job to `PENDING` when `attempt < max_attempts`;
- sets the job to `FAILED` when the limit has been reached.

## Worker abandonment

`recover_expired_jobs` finds `RUNNING` jobs whose lease has expired. It applies the same attempt-limit rule, clears ownership, and returns counts of retried and failed jobs. Recovery itself does not increment the attempt; the next claim does.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"primaryColor": "#dbeafe", "primaryTextColor": "#172554", "primaryBorderColor": "#2563eb", "lineColor": "#475569", "secondaryColor": "#dcfce7", "tertiaryColor": "#fee2e2", "fontFamily": "ui-sans-serif, system-ui"}}}%%
flowchart LR
    R["Failure or expired lease"] --> C{"Attempts remain?"}
    C -->|"yes"| P["PENDING<br/>next claim increments attempt"]
    C -->|"no"| F["FAILED<br/>terminal"]
    classDef decision fill:#fef3c7,stroke:#d97706,color:#451a03,stroke-width:2px;
    classDef pending fill:#dbeafe,stroke:#2563eb,color:#172554,stroke-width:2px;
    classDef failed fill:#fee2e2,stroke:#dc2626,color:#450a0a,stroke-width:2px;
    class C decision;
    class P pending;
    class F failed;
```

The behavior is implemented in [`fail_job.py`](../engine/workers/fail_job.py) and [`recover_expired_job.py`](../engine/workers/recover_expired_job.py). Integration tests cover retry limits, valid leases, idempotent recovery, and concurrent recovery: [`test_fail_job.py`](../tests/integration/test_fail_job.py), [`test_recover_expired_jobs.py`](../tests/integration/test_recover_expired_jobs.py).

**Current limits:** retries are immediate; there is no exponential backoff or dead-letter queue. These mechanisms handle state recovery, but external effects still need idempotent handlers. There is also no continuous worker runtime yet to run recovery periodically.

## Retry exhaustion example

```mermaid
flowchart LR
    A[Attempt 1 fails] --> B[PENDING]
    B --> C[Attempt 2 fails]
    C --> D[PENDING]
    D --> E[Attempt 3 fails]
    E --> F[FAILED]
```

## Concurrent recovery

```mermaid
sequenceDiagram
    participant A as Recovery A
    participant PG as PostgreSQL
    participant B as Recovery B
    A->>PG: BEGIN and recover expired row
    PG-->>A: One recovered, uncommitted
    B->>PG: Recover same row
    Note over B,PG: B waits on A
    A->>PG: COMMIT
    Note over PG: Recheck predicate under READ COMMITTED
    PG-->>B: Zero recovered
```

The second update rechecks eligibility after the first commits. The row is no longer RUNNING, so it is not recovered again. No separate distributed recovery lock is required for this tested transition.
