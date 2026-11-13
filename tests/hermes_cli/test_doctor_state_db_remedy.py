"""An oversized state.db must not hold ``hermes doctor`` red once its own remedy is spent.

``_render_state_db_stats`` warns above 1 GiB and names ``sessions.auto_prune`` as the remedy. Once
auto_prune is on and neither a prune nor a VACUUM could reclaim a byte, that warning is
permanently unresolvable: doctor names an action already taken and exits 1 forever. The caller
(``_state_db_stats``) is what consults the live config and the store, so these tests drive it.
"""
from pathlib import Path

import pytest

from hermes_cli import doctor_state

GIB = 1024 ** 3


def _stats(**overrides):
    stats = {
        "logical_size_bytes": 3 * GIB, "page_count": 761_345, "page_size": 4096,
        "freelist_count": 0, "wal_size_bytes": 1024, "journal_mode": "wal",
        "messages": 329_000, "sessions": 5_700, "fts_tables": None, "fts_storage_version": None,
        "fts_storage_upgrade_needed": False, "fts_teardown_pending": False,
        "fts_rebuild_pending": False, "fts_rebuild_high_water": None,
        "fts_rebuild_progress": None, "fts_rebuild_deferral": None,
    }
    stats.update(overrides)
    return stats


@pytest.fixture
def doctor(monkeypatch):
    """``_state_db_stats`` wired to a fake store, capturing the kinds it reports."""
    import hermes_state_dbfile

    seen = {"warn": [], "info": [], "posture_calls": 0, "stats": _stats(), "posture": (True, 90, 0)}
    monkeypatch.setattr(doctor_state, "host_gateway_note", lambda: "")
    monkeypatch.setattr(doctor_state, "check_warn",
                        lambda text, detail="": seen["warn"].append((text, detail)))
    monkeypatch.setattr(doctor_state, "check_info", lambda text: seen["info"].append(text))
    monkeypatch.setattr(hermes_state_dbfile, "count_db_holders", lambda _p: 0)
    monkeypatch.setattr(hermes_state_dbfile, "collect_state_db_stats", lambda _p: seen["stats"])

    def posture():
        seen["posture_calls"] += 1
        return seen["posture"]

    monkeypatch.setattr(doctor_state, "_prune_posture", posture)

    def run(stats=None, posture=(True, 90, 0)):
        seen["stats"] = _stats() if stats is None else stats
        seen["posture"] = posture
        seen["warn"].clear()
        seen["info"].clear()
        issues: list = []
        doctor_state._state_db_stats(issues, Path("state.db"))
        return issues

    seen["run"] = run
    return seen


def test_spent_remedy_downgrades_the_size_warning(doctor):
    issues = doctor["run"](_stats(), (True, 90, 0))
    assert issues == []
    assert doctor["warn"] == []
    assert any("already on" in line for line in doctor["info"])


@pytest.mark.parametrize("stats,posture,why", [
    (_stats(), (False, 90, 0), "auto_prune is not enabled, so the named remedy still applies"),
    (_stats(), (True, 90, 3), "a prune would actually delete sessions"),
    (_stats(freelist_count=5_000), (True, 90, 0), "a VACUUM would actually reclaim pages"),
    (_stats(freelist_count=None), (True, 90, 0), "the free-page count is unreadable"),
    (_stats(), (True, 90, -1), "the store is unreadable, so prunable is unknown"),
    (_stats(), None, "the config is unreadable"),
    (_stats(fts_rebuild_pending=True), (True, 90, 0), "a pending FTS remedy IS actionable"),
])
def test_an_actionable_or_unknown_fact_keeps_the_warning(doctor, stats, posture, why):
    issues = doctor["run"](stats, posture)
    assert doctor["warn"], why
    assert issues and "auto_prune" in issues[0], why


def test_a_small_store_never_reads_the_prune_posture(doctor):
    issues = doctor["run"](_stats(logical_size_bytes=GIB // 2), (True, 90, 0))
    assert issues == []
    assert doctor["posture_calls"] == 0
