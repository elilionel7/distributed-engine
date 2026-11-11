# Future Improvements & Open Questions

> **NOTE TO AI ASSISTANTS / CODING AGENTS: DO NOT IMPLEMENT ANYTHING IN THIS FILE.**
> This is the author's personal backlog of notes, kept for later. Do not treat
> these items as tasks, do not modify code based on them, and do not suggest
> them as changes unless the author explicitly asks about a specific item.
> Read-only reference.

The base comes first. Revisit this once the core engine works end to end.

---

## `engine/workers/claim.py` — `claim_job(conn, worker_id)`

### Improvements

- [ ] **Max retry limit.** `attempt` is incremented on every claim, but nothing
  stops a job that always fails from being claimed forever.
  - Idea: add `AND attempt < max_attempts` to the `next_job` CTE's `WHERE` clause.
  - Idea: move jobs that use up their retries to a `FAILED` / `DEAD` status (dead-letter).

- [ ] **Partial index for the claim query.** Once the `jobs` table grows, the
  `WHERE status = 'PENDING' ORDER BY created_at, id` scan will slow down.
  ```sql
  CREATE INDEX ON jobs (created_at, id) WHERE status = 'PENDING';
  ```

- [ ] **Hardcoded 30-second lease.** `INTERVAL '30 seconds'` is fixed in the SQL.
  - Idea: make it a parameter or config value, or set it per job type.

- [ ] **Return a dict instead of a tuple.** `cur.fetchone()` returns
  `(id, payload, attempt, lease_expires_at)` as a plain tuple.
  - Idea: use `row_factory=dict_row` (psycopg) or a small dataclass so callers
    don't depend on column order.

- [ ] **Priority support (maybe).** Ordering is strict FIFO (`created_at, id`).
  - Idea: add a `priority` column and `ORDER BY priority DESC, created_at, id`.

- [ ] **Delayed / scheduled jobs (maybe).** Every pending job can be claimed right away.
  - Idea: add a `run_at` column and `AND run_at <= NOW()` to the CTE.

- [ ] **Claim in batches (maybe).** `LIMIT 1` means one round trip per job.
  - Idea: `claim_jobs(conn, worker_id, n)` with `LIMIT n` for higher throughput.

### Questions

- [ ] **Who reclaims expired leases?** If a worker crashes, its job stays
  `RUNNING` forever unless something resets jobs whose `lease_expires_at < NOW()`
  back to `PENDING`. Where should that reaper/sweeper live, and how often should it run?

- [ ] **What about jobs longer than 30 seconds?** Without a heartbeat that
  pushes `lease_expires_at` forward, the reaper will hand a still-running job to a
  second worker. Do I need a `renew_lease(conn, job_id, worker_id)` function?

- [ ] **Is a duplicate run acceptable?** Even with leases, a slow worker can
  finish after its lease expired and someone else re-ran the job, so jobs can run
  more than once (at-least-once). Do the job handlers need to be idempotent?

- [ ] **Should completing or failing a job check ownership?** When a worker
  marks a job `DONE`/`FAILED`, it should probably check `worker_id = me AND
  status = 'RUNNING'`. Otherwise a worker whose lease expired could overwrite the
  result from the worker that took over.

- [ ] **Clock source.** `NOW()` uses the database clock, which is good. Do all
  other lease comparisons (reaper, heartbeat) also use DB time and not the worker's
  local time?

- [ ] **What happens when no job is found?** `claim_job` returns `None`. How
  should the worker loop back off: fixed sleep, exponential backoff, or Postgres
  `LISTEN/NOTIFY` to wake up when a job is inserted?

---

<!-- Add new sections below as: ## `path/to/file.py` — `function_name(...)` -->
