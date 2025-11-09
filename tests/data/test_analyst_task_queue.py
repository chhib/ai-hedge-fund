from pathlib import Path

from src.data.analyst_task_queue import AnalystTaskQueue, TaskKey


def test_task_queue_lifecycle(tmp_path: Path):
    queue = AnalystTaskQueue(db_path=tmp_path / "queue.db")
    key = TaskKey(
        analysis_date="2025-11-09",
        ticker="AAPL",
        analyst_name="jim_simons",
        model_name="gpt-5-nano",
        model_provider="OpenAI",
    )

    assert queue.get_status(key) is None

    queue.ensure_task(key)
    assert queue.get_status(key) == "pending"

    queue.mark_completed(key)
    assert queue.get_status(key) == "completed"

    queue.mark_failed(key)
    assert queue.get_status(key) == "failed"
