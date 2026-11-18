from engine.workers.process_item import process_item


class OwnershipLost(Exception):
    """Raised when the worker no longer holds the job's lease."""


def execute_job(job, ownership_lost):
    for item in job["payload"]["items"]:
        if ownership_lost.is_set():
            raise OwnershipLost(job["id"])

        process_item(item)
