CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,

    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),

    worker_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    lease_expires_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A RUNNING job must have an owner and a lease
    CHECK (
        status <> 'RUNNING'
        OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);

-- claim_job(): oldest PENDING job first
CREATE INDEX jobs_pending_idx
    ON jobs (created_at, id)
    WHERE status = 'PENDING';

-- recover_expired_jobs(): RUNNING jobs by lease deadline
CREATE INDEX jobs_running_lease_idx
    ON jobs (lease_expires_at)
    WHERE status = 'RUNNING';
