import time
import logging

logger = logging.getLogger(__name__)

from engine.workers.execute_job import execute_job
from engine.workers.claim_job import claim_job
from engine.workers.complete_job import complete_job
from engine.workers.fail_job import fail_job


def run_worker(conn, worker_id):
    while True:
        job = claim_job(conn, worker_id)

        if job is None:
            time.sleep(1)
            continue

        

        try:
            execute_job(job)

            completed = complete_job(
                conn,
                job["id"],
                worker_id,
                job["attempt"]
            )

            if not completed:
                logger.warning(
                    "Completion rejected for job %s",
                    job["id"]
                )

        except Exception:
            logger.exception(
                "Execution failed for job %s",
                job["id"]
            )

            recorded = fail_job(
                conn,
                job["id"],
                worker_id,
                job["attempt"]
            )

            if not recorded:
                logger.warning(
                    "Failure update rejected for job %s",
                    job["id"]
                )