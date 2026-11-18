
import logging
import threading

from engine.workers.complete_job import complete_job
from engine.workers.execute_job import OwnershipLost, execute_job
from engine.workers.fail_job import fail_job
from engine.workers.heartbeat_loop import heartbeat_loop

logger = logging.getLogger(__name__)


def process_job(conn, heartbeat_conn, worker_id, job):
    stop_event = threading.Event()
    ownership_lost = threading.Event()

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(
            heartbeat_conn,
            job["id"],
            worker_id,
            job["attempt"],
            stop_event,
            ownership_lost,
        ),
    )

    heartbeat_thread.start()

    failed = False

    try:
        execute_job(job, ownership_lost)

    except OwnershipLost:
        # Ensure the job is not marked as completed.
        ownership_lost.set()

    except Exception:
        logger.exception(
            "Execution failed for job %s",
            job["id"],
        )
        failed = True

    finally:
        # Stop renewing the lease and wait for the
        # heartbeat thread to finish.
        stop_event.set()
        heartbeat_thread.join()

    if ownership_lost.is_set():
        # Ownership is lost or uncertain.
        # Do not update the job's state.
        logger.warning(
            "Lease lost or uncertain for job %s",
            job["id"],
        )
        return False

    if failed:
        recorded = fail_job(
            conn,
            job["id"],
            worker_id,
            job["attempt"],
        )

        if not recorded:
            logger.warning(
                "Failure update rejected for job %s",
                job["id"],
            )

        return False

    completed = complete_job(
        conn,
        job["id"],
        worker_id,
        job["attempt"],
    )

    if not completed:
        logger.warning(
            "Completion rejected for job %s",
            job["id"],
        )

    return completed
