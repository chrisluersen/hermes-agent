"""A card that already reached a terminal success must never gain a
terminal-failure event.

The kanban worker's iteration-budget path (``agent/turn_finalizer.py``) records
``outcome="timed_out"`` through ``_record_task_failure`` on *every*
budget-exhausted turn exit — including a turn that already called
``kanban_complete``. Only the ``tasks`` UPDATE is guarded
(``WHERE id = ? AND status = 'running'``), so the task row correctly stayed
``done`` with ``consecutive_failures = 0`` and the run stayed ``completed``
while the ``timed_out`` **event** was appended unconditionally.

That event is what the notification layer renders, and the rendered form
contradicts the card's real state ("timed out; dispatcher will retry" on a
``done`` card that holds exactly one ``completed`` run and is never retried).
The sibling path ``enforce_max_runtime`` already guards its event append on
``cur.rowcount == 1``; ``_record_task_failure`` did not.

These tests pin the invariant, not a snapshot:

* a terminal success is not overwritten by a late failure record, and
* a genuinely running task still records its failure (guards against
  over-fixing the guard into "never record anything").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def conn(tmp_path: Path):
    db = kbc.connect(tmp_path / "kanban.db")
    try:
        yield db
    finally:
        db.close()


_BUDGET_ERROR = (
    "Iteration budget exhausted (120/120) — task could not complete "
    "within the allowed iterations"
)


def _budget_exhausted_record(conn, task_id):
    """Exactly the call ``turn_finalizer._record_kanban_budget_exhausted`` makes."""
    return kbd._record_task_failure(
        conn,
        task_id,
        error=_BUDGET_ERROR,
        outcome="timed_out",
        release_claim=True,
        end_run=True,
        event_payload_extra={"budget_used": 120, "budget_max": 120},
    )


def test_completed_task_gains_no_terminal_failure_event(conn) -> None:
    tid = kb.create_task(conn, title="finished before the budget ran out")
    claim = kb.claim_task(conn, tid, claimer="default:1")
    assert claim is not None
    assert kb.complete_task(conn, tid, summary="done", expected_run_id=claim.current_run_id)

    before = kb.get_task(conn, tid)
    assert before.status == "done"

    _budget_exhausted_record(conn, tid)

    after = kb.get_task(conn, tid)
    assert after.status == "done"
    assert after.consecutive_failures == 0
    assert after.last_failure_error is None
    assert after.current_run_id is None

    kinds = [event.kind for event in kb.list_events(conn, task_id=tid)]
    assert "timed_out" not in kinds
    assert "gave_up" not in kinds

    runs = kb.list_runs(conn, tid)
    assert [run.outcome for run in runs] == ["completed"]
    assert runs[0].ended_at is not None


def test_running_task_still_records_the_budget_failure(conn) -> None:
    """The guard must not disable the legitimate path: a task that really is
    still running (claimed, open run) still records the failure."""
    tid = kb.create_task(conn, title="genuinely out of budget")
    claim = kb.claim_task(conn, tid, claimer="default:1")
    assert claim is not None

    _budget_exhausted_record(conn, tid)

    after = kb.get_task(conn, tid)
    assert after.consecutive_failures == 1
    assert after.last_failure_error is not None
    assert after.status == "ready"

    kinds = [event.kind for event in kb.list_events(conn, task_id=tid)]
    assert "timed_out" in kinds

    runs = kb.list_runs(conn, tid)
    assert [run.outcome for run in runs] == ["timed_out"]
