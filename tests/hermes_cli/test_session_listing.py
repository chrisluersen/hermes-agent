"""Tests for the shared session-listing helpers (hermes_cli/session_listing.py)."""

import pytest

from hermes_cli.session_listing import (
    display_session_title,
    prepare_session_rows,
    parse_session_listing_args,
    query_session_listing,
)


class TestParseSessionListingArgs:
    def test_plain_listing(self):
        assert parse_session_listing_args("") == (False, False, "", None)


class TestSessionDisplayTitles:
    def test_explicit_closeout_prefix_marks_still_running_session_closed(self):
        row = {
            "id": "current",
            "source": "tui",
            "title": "[closed] Closeout title",
            "ended_at": None,
            "end_reason": None,
        }

        assert display_session_title(row) == "[closed] Closeout title"

    def test_new_user_activity_reopens_an_explicitly_closed_session(self, tmp_path):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "reopen-user.db")
        try:
            db.create_session("current", "tui")
            db.set_session_title("current", "[closed] Closeout title")
            db.end_session("current", "completed")

            db.append_message("current", "user", content="Continue")

            row = db.get_session("current")
            assert row["title"] == "Closeout title"
            assert row["ended_at"] is None
            assert row["end_reason"] is None
            assert display_session_title(row) == "[open] Closeout title"
        finally:
            db.close()

    @pytest.mark.parametrize("role", ["assistant", "tool", "system", "background"])
    def test_delayed_non_user_activity_does_not_reopen_closed_session(self, tmp_path, role):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / f"delayed-{role}.db")
        try:
            db.create_session("current", "tui")
            db.set_session_title("current", "[closed] Closeout title")
            db.end_session("current", "completed")

            db.append_message("current", role, content="Delayed event")

            row = db.get_session("current")
            assert row["title"] == "[closed] Closeout title"
            assert row["ended_at"] is not None
            assert row["end_reason"] == "completed"
            assert display_session_title(row) == "[closed] Closeout title"
        finally:
            db.close()

    def test_batched_user_activity_reopens_an_explicitly_closed_session(self, tmp_path):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "batch-user.db")
        try:
            db.create_session("current", "tui")
            db.set_session_title("current", "[closed] Closeout title")
            db.end_session("current", "completed")

            assert db.append_messages_batch(
                "current",
                [
                    {"role": "assistant", "content": "Delayed event"},
                    {"role": "user", "content": "Continue"},
                ],
            ) == 2

            row = db.get_session("current")
            assert row["title"] == "Closeout title"
            assert row["ended_at"] is None
            assert row["end_reason"] is None
            assert display_session_title(row) == "[open] Closeout title"
        finally:
            db.close()

    def test_batched_non_user_activity_does_not_reopen_closed_session(self, tmp_path):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "batch-background.db")
        try:
            db.create_session("current", "tui")
            db.set_session_title("current", "[closed] Closeout title")
            db.end_session("current", "completed")

            assert db.append_messages_batch(
                "current", [{"role": "background", "content": "Delayed event"}]
            ) == 1

            row = db.get_session("current")
            assert row["title"] == "[closed] Closeout title"
            assert row["ended_at"] is not None
            assert row["end_reason"] == "completed"
            assert display_session_title(row) == "[closed] Closeout title"
        finally:
            db.close()

    def test_reopen_title_collision_uses_unique_suffix_without_losing_message(self, tmp_path):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "collision.db")
        try:
            db.create_session("existing", "tui")
            db.set_session_title("existing", "Alpha")
            db.create_session("current_273847", "tui")
            db.set_session_title("current_273847", "[closed] Alpha")
            db.end_session("current_273847", "completed")

            db.append_message("current_273847", "user", content="Continue")

            row = db.get_session("current_273847")
            assert row["title"] == "Alpha (reopened 273847)"
            assert row["ended_at"] is None
            assert row["end_reason"] is None
            assert [m["content"] for m in db.get_messages("current_273847")] == ["Continue"]
        finally:
            db.close()

    def test_exact_closed_prefix_reopens_to_fallback_title(self, tmp_path):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "exact-prefix.db")
        try:
            db.create_session("current", "tui")
            db.set_session_title("current", "[closed]")

            db.append_message("current", "user", content="Continue")

            row = db.get_session("current")
            assert row["title"] == "Untitled session"
            assert display_session_title(row) == "[open] Untitled session"
        finally:
            db.close()

    def test_generated_prefixes_before_closed_are_removed_on_reopen(self, tmp_path):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "generated-prefixes.db")
        try:
            db.create_session("current", "cron")
            db.set_session_title("current", "[automated] [closed] Job")

            db.append_message("current", "user", content="Continue")

            row = db.get_session("current")
            assert row["title"] == "Job"
            assert display_session_title(row) == "[automated] [open] Job"
        finally:
            db.close()

    def test_labels_are_derived_without_mutating_stored_rows(self):
        open_row = {"id": "open", "source": "telegram", "title": "Human chat"}
        closed_auto = {
            "id": "cron-1",
            "source": "cron",
            "title": "[automated] Nightly job",
            "end_reason": "completed",
        }

        assert display_session_title(open_row) == "[open] Human chat"
        assert display_session_title(closed_auto) == "[automated] [closed] Nightly job"
        prepared = prepare_session_rows([closed_auto])
        assert prepared[0]["title"] == "[automated] [closed] Nightly job"
        assert closed_auto["title"] == "[automated] Nightly job"

    def test_repeated_preparation_does_not_duplicate_prefixes(self):
        row = {"id": "kanban-1", "source": "kanban", "title": "Worker", "ended_at": 1}
        once = prepare_session_rows([row])
        twice = prepare_session_rows(once)
        assert twice[0]["title"] == "[automated] [closed] Worker"




class TestQuerySessionListingSearch:
    @pytest.fixture
    def db(self, tmp_path):
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("sess_an94", "telegram", user_id="1", chat_id="2")
        db.set_session_title("sess_an94", "AN-94 Prestige Barrel Build #2")
        db.create_session("sess_winton", "whatsapp", user_id="1", chat_id="2")
        db.set_session_title("sess_winton", "Winton Email Sheet Update #3")
        db.create_session("sess_untitled", "telegram", user_id="1", chat_id="2")
        yield db
        db.close()

    def _ids(self, db, **kw):
        return [r["id"] for r in query_session_listing(db, **kw)]

    def test_default_listing_excludes_automated_sources(self, db):
        db.create_session("cron_hidden", "cron")
        db.set_session_title("cron_hidden", "Nightly job")
        db.create_session("subagent_hidden", "subagent")
        db.set_session_title("subagent_hidden", "Delegated worker")
        db.create_session("human_visible", "telegram")
        db.set_session_title("human_visible", "Human chat")

        rows = query_session_listing(db, source=None, include_unnamed=True)
        by_id = {row["id"]: row for row in rows}
        assert "cron_hidden" not in by_id
        assert "subagent_hidden" not in by_id
        assert by_id["human_visible"]["title"] == "[open] Human chat"

    def test_explicit_automated_source_is_visible_and_labeled(self, db):
        db.create_session("cron_visible", "cron")
        db.set_session_title("cron_visible", "Nightly job")
        db.end_session("cron_visible", end_reason="completed")

        rows = query_session_listing(db, source="cron", include_unnamed=True)
        assert [row["id"] for row in rows] == ["cron_visible"]
        assert rows[0]["title"] == "[automated] [closed] Nightly job"

    def test_explicit_subagent_source_is_visible_and_labeled(self, db):
        db.create_session("subagent_visible", "subagent")
        db.set_session_title("subagent_visible", "Delegated worker")

        rows = query_session_listing(db, source="subagent", include_unnamed=True)

        assert [row["id"] for row in rows] == ["subagent_visible"]
        assert rows[0]["title"] == "[automated] [open] Delegated worker"



    def test_source_scoping(self, db):
        assert self._ids(db, source="telegram", search_query="winton") == []
        assert self._ids(db, source="whatsapp", search_query="winton") == ["sess_winton"]


    def test_search_matches_compression_root_title(self, tmp_path):
        """Searching an old (compressed-away) title surfaces the live tip."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "chain.db")
        db.create_session("root_1", "telegram", user_id="1", chat_id="2")
        db.set_session_title("root_1", "Old Chat")
        db.end_session("root_1", end_reason="compression")
        db.create_session(
            "tip_1", "telegram", user_id="1", chat_id="2", parent_session_id="root_1"
        )
        db.set_session_title("tip_1", "AN-94 Build")
        try:
            for query in ("old chat", "root_1", "an94"):
                rows = query_session_listing(db, source="telegram", search_query=query)
                assert [r["id"] for r in rows] == ["tip_1"], query
        finally:
            db.close()


class TestQuerySessionListingLaneScope:
    @pytest.fixture
    def db(self, tmp_path):
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "state.db")
        lane_key = "agent:main:telegram:dm:lane"
        db.create_session(
            "lane_current", "telegram", session_key=lane_key,
            user_id="lane-user", chat_id="lane",
        )
        db.set_session_title("lane_current", "Current lane")
        db.create_session(
            "lane_named", "telegram", session_key=lane_key,
            user_id="lane-user", chat_id="lane",
        )
        db.set_session_title("lane_named", "Needle lane")
        db.create_session(
            "lane_unnamed", "telegram", session_key=lane_key,
            user_id="lane-user", chat_id="lane",
        )
        for i in range(60):
            db.create_session(
                f"foreign_{i}", "telegram",
                session_key=f"agent:main:telegram:dm:foreign-{i}",
                user_id=f"foreign-user-{i}", chat_id=f"foreign-{i}",
            )
            db.set_session_title(f"foreign_{i}", f"Needle foreign {i}")
        yield db, lane_key
        db.close()

    def test_exact_lane_precedes_limit_and_current_session_exclusion(self, db):
        session_db, lane_key = db

        rows = query_session_listing(
            session_db,
            source="telegram",
            session_key=lane_key,
            current_session_id="lane_current",
            limit=1,
        )

        assert [row["id"] for row in rows] == ["lane_named"]

    def test_exact_lane_preserves_full_and_search_modes(self, db):
        session_db, lane_key = db

        full_rows = query_session_listing(
            session_db,
            source="telegram",
            session_key=lane_key,
            include_unnamed=True,
            limit=10,
        )
        search_rows = query_session_listing(
            session_db,
            source="telegram",
            session_key=lane_key,
            search_query="needle",
            limit=10,
        )

        assert {row["id"] for row in full_rows} == {
            "lane_current", "lane_named", "lane_unnamed",
        }
        assert [row["id"] for row in search_rows] == ["lane_named"]

    def test_omitted_session_key_keeps_source_scope(self, db):
        session_db, _lane_key = db

        rows = query_session_listing(
            session_db,
            source="telegram",
            search_query="needle foreign 59",
            limit=10,
        )

        assert [row["id"] for row in rows] == ["foreign_59"]
