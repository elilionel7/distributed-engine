from unittest.mock import patch

from engine.workers.process_job import process_job


def test_failed_job_is_retried():
    job = {
        "id": 101,
        "attempt": 1,
        "max_attempts": 3,
    }

    with (
        patch("engine.workers.process_job.execute_job") as mock_execute,
        patch("engine.workers.process_job.heartbeat_loop"),
        patch("engine.workers.process_job.fail_job") as mock_fail,
        patch("engine.workers.process_job.complete_job") as mock_complete,
    ):
        mock_execute.side_effect = ValueError("Simulated execution failure")
        mock_fail.return_value = True

        result = process_job(
            conn=None,
            heartbeat_conn=None,
            worker_id="worker-1",
            job=job,
        )

        # Your assertions go here.
        mock_fail.assert_called_once_with(None, 101, "worker-1", 1)
        mock_complete.assert_not_called()
        assert result is False

def test_successful_job_is_completed():
    job = {
        "id": 102,
        "attempt": 1,
        "max_attempts": 3,
    }

    with (
        patch("engine.workers.process_job.execute_job") as mock_execute,
        patch("engine.workers.process_job.heartbeat_loop"),
        patch("engine.workers.process_job.fail_job") as mock_fail,
        patch("engine.workers.process_job.complete_job") as mock_complete,
    ):
        # Configure your mocks here.
        mock_complete.return_value = True

        result = process_job(
            conn=None,
            heartbeat_conn=None,
            worker_id="worker-1",
            job=job,
        )

        # Write your assertions here.
        mock_complete.assert_called_once_with(None, 102, "worker-1", 1)
        mock_fail.assert_not_called()
        
        assert result is True
        
def test_ownership_lost_does_not_update_job():
    job = {
            "id": 102,
            "attempt": 1,
            "max_attempts": 3,
        }                        # e.g. id 103, attempt 1

    def simulate_ownership_loss(job, ownership_lost):
        ownership_lost.set()

    with (
        patch("engine.workers.process_job.execute_job") as mock_execute,
        patch("engine.workers.process_job.heartbeat_loop"),
        patch("engine.workers.process_job.fail_job") as mock_fail,
        patch("engine.workers.process_job.complete_job") as mock_complete,
    ):
        mock_execute.side_effect = simulate_ownership_loss   # configure BEFORE the call

        result = process_job(
                    conn=None,
                    heartbeat_conn=None,
                    worker_id="worker-1",
                    job=job,
                )

        # your assertions: neither fail_job nor complete_job called, result is False
        mock_fail.assert_not_called()
        mock_complete.assert_not_called()
        assert result is False