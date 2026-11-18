
import logging

from engine.workers.renew_lease import renew_lease

logger = logging.getLogger(__name__)

def heartbeat_loop(
    heartbeat_conn,
    job_id,
    worker_id,
    attempt,
    stop_event,
    ownership_lost
):
    """
    Renew the lease every 10 seconds.
    Signal if ownership is lost.
    """

    while not stop_event.wait(10):
        try:
            renewed = renew_lease(
                heartbeat_conn,
                job_id,
                worker_id,
                attempt
            )
        except Exception:
            # Renewal outcome is uncertain.
            # Conservatively signal that execution
            # must not assume valid ownership.
            logger.exception(
                "Heartbeat failed for job %s",
                job_id,
            )
            ownership_lost.set()
            break

        if not renewed:
            ownership_lost.set()
            break
