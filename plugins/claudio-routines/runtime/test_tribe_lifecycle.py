import json
import os
import unittest

import state
import tribe_lifecycle
import tribe_page
import tribe_state
import tribe_support as seam
from support import ts
from tribe_support import (
    CHANNEL_A, NOW, PAGE_ID, PREVIOUS, SLACK_TS, THREAD_TS, WRITTEN, FileCase, make_check, make_state, make_warning, run_cli,
)

HERE = os.path.dirname(os.path.abspath(__file__))
LINK = "https://example.test/c/1"
NEW_LINK = "https://example.test/c/2"
NEW_THREAD = "1791990500.000300"
NEWER_TS = "1791990900.000200"
METRIC_CITE = {"feature": "metric:queue-depth", "name": "value", "value": 120}
RECORD_CITE = {"source": "channels", "link": LINK}
NEW_RECORD_CITE = {"source": "channels", "link": NEW_LINK}
RUN_AT = NOW
SAME_LINK = "https://example.test/c/3"
SAME_THREAD_CITE = {"source": "channels", "link": SAME_LINK}
THREAD_ENTRY = {"channel": CHANNEL_A, "root_ts": THREAD_TS, "links": [LINK]}
NEW_THREAD_ENTRY = {"channel": CHANNEL_A, "root_ts": NEW_THREAD, "links": [NEW_LINK]}
SUMMARY_FIELDS = {
    "digest", "run_at", "window", "baseline", "report_only", "previous_page", "warnings", "moved", "resolved",
    "checks", "done", "decisions", "details", "corrections", "highlights", "blind_spots", "blind_spots_dropped",
    "coverage_notes", "sources", "edits_ignored",
}
NOTES = [
    {"source": "Mobile app", "text": "Not read, no connector is configured for it"},
    {"source": "Issue tracker", "text": "A rule names it and the features hold no record of it"},
]


def message_doc(link, ts_value, thread):
    values = {"channel": CHANNEL_A, "ts": ts_value, "thread": thread, "reply": thread != ts_value}
    return {"kind": "record", "source": "channels", "link": link, "title": "Message", "values": values, "text": "queue is slow"}


def empty_edits(**fields):
    edits = {"page_id": PAGE_ID, "edited_at": WRITTEN, "after_written": False, "statuses": {}, "ticked": [], "unticked": [], "ignored": []}
    return {**edits, **fields}


def make_features(stored, **fields):
    features = {
        "keys": {
            "metric:queue-depth": {"kind": "metric", "source": "metrics", "link": None, "title": "Queue depth", "values": {"value": 120}},
            "record:channels:c1": message_doc(LINK, THREAD_TS, THREAD_TS),
            "record:channels:c2": message_doc(NEW_LINK, NEW_THREAD, NEW_THREAD),
            "record:channels:c3": message_doc(SAME_LINK, "1791990100.000400", THREAD_TS),
        },
        "previous": {"warnings": stored["warnings"], "checks": stored["checks"], "retired": stored["retired"]},
        "edits": empty_edits(),
        "deferred": [],
        "authors": [],
        "pack": ["queue-depth"],
    }
    return {**features, **fields}


def judged(**fields):
    entry = {
        "title": "Queue depth rises",
        "topic": "Capacity",
        "severity": "Medium",
        "when": "watch",
        "runway": "about two weeks",
        "status": "open",
        "confidence": "measured",
        "risk": "jobs start late",
        "impact": "reports arrive late",
        "mitigation": ["add a worker"],
        "metric": "queue-depth",
        "verdict": "open",
        "evidence": [{"claim": "Depth is at 120", "cites": [METRIC_CITE, RECORD_CITE]}],
    }
    return {**entry, **fields}


def judged_new(**fields):
    entry = judged(
        title="Disk fills",
        confidence="reported",
        metric=None,
        evidence=[{"claim": "Users report a full disk", "cites": [NEW_RECORD_CITE]}],
    )
    return {**entry, **fields}


def make_judgment(**sections):
    document = {"warnings": {"queue-depth": judged()}, "checks": {}, "decisions": [], "details": {}, "corrections": [], "highlights": []}
    return {**document, **sections}


def source_row(name, role, read=True):
    window = {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW)} if read else {"from_ts": None, "to_ts": None}
    return {"source": name, "role": role, "read": read, "reason": None if read else "no collection", **window}


def make_base(**fields):
    base = {
        "sources": [source_row("channels", "chat"), source_row("metrics", "observability"), source_row("issues", "issue_tracker", False)],
        "cursors": {
            "observability": {"events_ts_ms": 2_000, "monitors": {"1001": "OK"}, "metrics": {"queue-depth": 120}},
            "channels": {"ts": {CHANNEL_A: NEWER_TS}},
        },
        "blind_spots": [{"key": "channels", "gap": "no history"}],
        "daily_metrics_on": "2026-10-16",
        "models": {"collect": "model-b"},
    }
    return {**base, **fields}


def make_window(**fields):
    window = {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW), "buckets": [], "cut": None, "explicit": False, "retry_known_gaps": False}
    return {**window, **fields}


class LifecycleCase(FileCase):
    def run_apply(self, stored=None, judgment=None, base=None, window=None, **features):
        stored = make_state() if stored is None else stored
        paths = {
            "--state": self.write("state.json", stored),
            "--features": self.write("features.json", make_features(stored, **features)),
            "--base": self.write("base.json", make_base() if base is None else base),
            "--judgment": self.write("judgment.json", make_judgment() if judgment is None else judgment),
            "--window": self.write("window.json", make_window() if window is None else window),
            "--out": self.path("next.json"),
            "--summary": self.path("summary.json"),
            "--record": self.path("record.json"),
        }
        self.code, _, self.err = run_cli("apply", *[item for pair in paths.items() for item in pair])
        return self.code

    def apply(self, **arguments):
        self.assertEqual(self.run_apply(**arguments), 0, self.err)

    def again(self, **arguments):
        self.apply(stored=self.next(), **arguments)

    def next(self):
        return self.read("next.json")

    def summary(self):
        return self.read("summary.json")

    def record(self):
        return self.read("record.json")

    def warning(self):
        return self.next()["warnings"]["queue-depth"]

    def rejected(self, code, **arguments):
        self.assertEqual(self.run_apply(**arguments), code, self.err)
        self.assertFalse(os.path.exists(self.path("next.json")))
        return self.err


class JudgeTest(FileCase):
    def run_judge(self, judgment=None, stored=None, **features):
        stored = make_state() if stored is None else stored
        return run_cli(
            "judge",
            "--features", self.write("features.json", make_features(stored, **features)),
            "--judgment", self.write("judgment.json", make_judgment() if judgment is None else judgment),
        )

    def test_a_valid_judgment_exits_0_and_prints_nothing(self):
        self.assertEqual(self.run_judge(), (0, "", ""))

    def test_a_rejection_exits_3_with_the_key_path(self):
        code, _, err = self.run_judge(make_judgment(warnings={"queue-depth": judged(), "old-warning": judged_new()}))
        self.assertEqual(code, 3)
        self.assertIn("rejected: judgment: warnings.old-warning", err)

    def test_a_rejection_names_the_field_of_a_value_outside_the_allowed_ones(self):
        code, _, err = self.run_judge(make_judgment(warnings={"queue-depth": judged(severity="Huge")}))
        self.assertEqual(code, 3)
        self.assertIn("warnings.queue-depth.severity", err)

    def test_a_judgment_that_is_not_json_exits_3(self):
        features = self.write("features.json", make_features(make_state()))
        with open(self.path("judgment.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, _, err = run_cli("judge", "--features", features, "--judgment", self.path("judgment.json"))
        self.assertEqual(code, 3)
        self.assertIn("judgment: invalid JSON", err)

    def test_a_missing_judgment_file_exits_2(self):
        features = self.write("features.json", make_features(make_state()))
        code, _, err = run_cli("judge", "--features", features, "--judgment", self.path("absent.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_features_without_their_keys_exit_2_with_the_path(self):
        features = make_features(make_state())
        del features["authors"]
        code, _, err = run_cli(
            "judge", "--features", self.write("features.json", features), "--judgment", self.write("judgment.json", make_judgment())
        )
        self.assertEqual(code, 2)
        self.assertIn("features: missing key authors", err)

    def test_the_correction_message_comes_from_the_checker(self):
        code, _, err = self.run_judge(make_judgment(highlights=[{"text": "No cite", "cites": []}]))
        self.assertEqual(code, 3)
        self.assertIn("highlights[0].cites", err)


class WarningResolutionTest(LifecycleCase):
    def test_an_open_verdict_keeps_the_warning_with_the_judged_fields(self):
        stored = make_state(warnings={"queue-depth": make_warning(runs_under=1)})
        self.apply(stored=stored, judgment=make_judgment(warnings={"queue-depth": judged(risk="jobs queue up")}))
        self.assertEqual(self.warning(), make_warning(risk="jobs queue up", runs_under=0, cites=[
            {"feature": "metric:queue-depth", "name": "value"}, {"source": "channels", "link": LINK},
        ]))

    def test_a_stored_warning_has_exactly_the_state_fields(self):
        self.apply()
        self.assertEqual(set(self.warning()), set(tribe_state.WARNING_SPEC))

    def test_the_next_state_passes_the_state_check(self):
        self.apply()
        self.assertIsNone(tribe_state.check_state(self.next()))

    def test_an_under_verdict_adds_one_run(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(verdict="under")}))
        self.assertEqual(self.warning()["runs_under"], 1)

    def test_one_under_run_does_not_resolve_the_warning(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(verdict="under")}))
        self.assertEqual(self.summary()["resolved"], [])

    def test_two_under_runs_in_a_row_resolve_the_warning(self):
        stored = make_state(warnings={"queue-depth": make_warning(runs_under=1)})
        self.apply(stored=stored, judgment=make_judgment(warnings={"queue-depth": judged(verdict="under")}))
        self.assertEqual(self.next()["warnings"], {})
        self.assertEqual(
            self.summary()["resolved"],
            [{"key": "queue-depth", "title": "Queue depth rises", "reason": "under every threshold for 2 runs"}],
        )

    def test_two_under_runs_in_a_row_resolve_across_two_applies(self):
        under = make_judgment(warnings={"queue-depth": judged(verdict="under")})
        self.apply(judgment=under)
        self.again(judgment=under)
        self.assertEqual(self.next()["warnings"], {})

    def test_an_open_verdict_resets_the_count(self):
        self.apply(stored=make_state(warnings={"queue-depth": make_warning(runs_under=1)}))
        self.assertEqual(self.warning()["runs_under"], 0)

    def test_a_warning_without_a_metric_never_resolves_by_verdict(self):
        stored = make_state(warnings={"queue-depth": make_warning(metric=None, runs_under=0)})
        reported = [{"claim": "Reported slow", "cites": [RECORD_CITE]}]
        under = make_judgment(warnings={"queue-depth": judged(metric=None, confidence="reported", verdict="under", evidence=reported)})
        self.apply(stored=stored, judgment=under)
        self.again(judgment=under)
        self.again(judgment=under)
        self.assertEqual(self.warning()["runs_under"], 0)

    def test_a_warning_without_a_metric_resolves_by_its_status(self):
        stored = make_state(warnings={"queue-depth": make_warning(metric=None)})
        decided = judged(metric=None, confidence="reported", status="decided", evidence=[{"claim": "Reported slow", "cites": [RECORD_CITE]}])
        self.apply(stored=stored, judgment=make_judgment(warnings={"queue-depth": decided}))
        self.assertEqual(self.summary()["resolved"][0]["reason"], "status decided")

    def test_a_decided_status_resolves(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(status="decided")}))
        self.assertEqual(self.next()["warnings"], {})
        self.assertEqual(self.summary()["resolved"][0]["reason"], "status decided")

    def test_a_dropped_status_resolves(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(status="dropped")}))
        self.assertEqual(self.summary()["resolved"][0]["reason"], "status dropped")

    def test_the_other_statuses_do_not_resolve(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(status="mitigated")}))
        self.assertEqual(self.warning()["status"], "mitigated")
        self.assertEqual(self.summary()["resolved"], [])

    def test_a_new_warning_starts_at_the_run_time_with_no_runs_under(self):
        warnings = {"queue-depth": judged(), "disk-fills": judged_new()}
        self.apply(judgment=make_judgment(warnings=warnings))
        created = self.next()["warnings"]["disk-fills"]
        self.assertEqual((created["since"], created["runs_under"]), (RUN_AT, 0))
        self.assertEqual(self.summary()["warnings"]["disk-fills"]["change"], "new")

    def test_a_new_warning_judged_under_with_a_metric_counts_one_run(self):
        measured = judged_new(
            confidence="measured", metric="queue-depth", verdict="under", evidence=[{"claim": "Depth is at 120", "cites": [METRIC_CITE]}]
        )
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(), "disk-fills": measured}))
        self.assertEqual(self.next()["warnings"]["disk-fills"]["runs_under"], 1)

    def test_a_replaced_warning_resolves_and_its_replacement_is_new(self):
        replacement = judged(title="Queue depth grows", replaces="queue-depth")
        self.apply(judgment=make_judgment(warnings={"queue-depth-v2": replacement}))
        self.assertEqual(list(self.next()["warnings"]), ["queue-depth-v2"])
        self.assertEqual(self.next()["warnings"]["queue-depth-v2"]["since"], RUN_AT)
        self.assertEqual(
            self.summary()["resolved"],
            [{"key": "queue-depth", "title": "Queue depth rises", "reason": "replaced by Queue depth grows"}],
        )

    def test_a_new_warning_judged_resolved_at_once_never_enters_the_state(self):
        warnings = {"queue-depth": judged(), "disk-fills": judged_new(status="decided")}
        self.apply(judgment=make_judgment(warnings=warnings))
        self.assertEqual(list(self.next()["warnings"]), ["queue-depth"])
        self.assertEqual(self.next()["retired"]["disk-fills"], "Disk fills")


class EditPrecedenceTest(LifecycleCase):
    def test_an_edited_status_wins_over_the_judged_status(self):
        edits = empty_edits(after_written=True, statuses={"queue-depth": "in progress"})
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(status="decided")}), edits=edits)
        self.assertEqual(self.warning()["status"], "in progress")
        self.assertEqual(self.summary()["resolved"], [])

    def test_an_edited_decided_status_resolves_against_a_judged_open_one(self):
        self.apply(edits=empty_edits(after_written=True, statuses={"queue-depth": "decided"}))
        self.assertEqual(self.next()["warnings"], {})
        self.assertEqual(self.summary()["resolved"][0]["reason"], "status decided")

    def test_a_ticked_check_is_done_and_wins_over_a_judged_check(self):
        again = {"ask-export": {"text": "Ask for the export again", "topic": "Capacity", "group": "Investigate"}}
        self.apply(judgment=make_judgment(checks=again), edits=empty_edits(after_written=True, ticked=["ask-export"]))
        self.assertEqual(self.next()["checks"], {})
        self.assertEqual(self.summary()["done"], [{"key": "ask-export", "text": "Ask for the export"}])

    def test_an_unticked_check_stays_open_when_the_judgment_leaves_it_out(self):
        self.apply(edits=empty_edits(after_written=True, unticked=["ask-export"]))
        self.assertEqual(self.next()["checks"], {"ask-export": make_check()})
        self.assertEqual(self.summary()["done"], [])

    def test_edits_ignored_by_the_parser_reach_the_summary_and_the_record(self):
        ignored = [{"where": "warning row 4", "why": "no key marker"}]
        self.apply(edits=empty_edits(after_written=True, ignored=ignored))
        self.assertEqual(self.summary()["edits_ignored"], ignored)
        self.assertEqual(self.record()["edits_ignored"], ignored)


class DeferredWarningTest(LifecycleCase):
    def setUp(self):
        super().setUp()
        self.stored = make_state(warnings={"queue-depth": make_warning(runs_under=1)})

    def test_a_deferred_warning_is_held_unchanged_with_its_count(self):
        self.apply(stored=self.stored, judgment=make_judgment(warnings={}), deferred=["queue-depth"])
        self.assertEqual(self.warning(), make_warning(runs_under=1))

    def test_a_held_warning_is_open_in_the_summary_with_no_evidence_and_no_change(self):
        self.apply(stored=self.stored, judgment=make_judgment(warnings={}), deferred=["queue-depth"])
        held = self.summary()["warnings"]["queue-depth"]
        self.assertEqual((held["change"], held["evidence"]), ("same", []))
        self.assertEqual(self.summary()["resolved"], [])
        self.assertEqual(self.summary()["moved"], [])

    def test_a_judgment_of_a_deferred_warning_changes_nothing(self):
        under = judged(verdict="under", status="decided", severity="High")
        self.apply(stored=self.stored, judgment=make_judgment(warnings={"queue-depth": under}), deferred=["queue-depth"])
        self.assertEqual(self.warning(), make_warning(runs_under=1))

    def hold(self, status):
        edits = empty_edits(after_written=True, statuses={"queue-depth": status})
        self.apply(stored=self.stored, judgment=make_judgment(warnings={}), deferred=["queue-depth"], edits=edits)

    def test_a_status_edit_of_a_deferred_warning_applies_and_the_rest_is_held(self):
        self.hold("in progress")
        self.assertEqual(self.warning(), make_warning(runs_under=1, status="in progress"))

    def test_a_status_edit_of_a_deferred_warning_is_not_listed_as_ignored(self):
        self.hold("in progress")
        self.assertEqual(self.summary()["edits_ignored"], [])

    def test_a_status_edit_of_a_deferred_warning_is_a_move(self):
        self.hold("in progress")
        self.assertEqual(self.summary()["moved"], [{"key": "queue-depth", "field": "status", "from": "open", "to": "in progress"}])
        self.assertEqual(self.summary()["warnings"]["queue-depth"]["change"], "moved")

    def test_a_decided_edit_of_a_deferred_warning_does_not_resolve_it_in_that_run(self):
        self.hold("decided")
        self.assertEqual(self.warning()["status"], "decided")
        self.assertEqual(self.summary()["resolved"], [])

    def test_a_dropped_edit_of_a_deferred_warning_does_not_resolve_it_in_that_run(self):
        self.hold("dropped")
        self.assertEqual(self.warning()["status"], "dropped")
        self.assertEqual(self.summary()["resolved"], [])

    def test_a_decided_deferred_warning_resolves_on_the_first_run_it_is_not_deferred(self):
        self.hold("decided")
        self.again(judgment=make_judgment(warnings={"queue-depth": judged()}))
        self.assertEqual(self.next()["warnings"], {})
        self.assertEqual(self.summary()["resolved"][0]["reason"], "status decided")


class SummaryMovesTest(LifecycleCase):
    def test_moved_severity_when_and_status_are_listed_in_order(self):
        moved = judged(severity="High", when="now", runway="three days", status="in progress")
        self.apply(judgment=make_judgment(warnings={"queue-depth": moved}))
        self.assertEqual(
            self.summary()["moved"],
            [
                {"key": "queue-depth", "field": "severity", "from": "Medium", "to": "High"},
                {"key": "queue-depth", "field": "when", "from": "watch", "to": "now"},
                {"key": "queue-depth", "field": "status", "from": "open", "to": "in progress"},
            ],
        )
        self.assertEqual(self.summary()["warnings"]["queue-depth"]["change"], "moved")

    def test_a_runway_edit_is_not_a_move(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(runway="three days")}))
        summary = self.summary()
        self.assertEqual((summary["moved"], summary["warnings"]["queue-depth"]["change"]), ([], "same"))

    def test_an_unmoved_warning_is_the_same(self):
        self.apply()
        self.assertEqual(self.summary()["moved"], [])
        self.assertEqual(self.summary()["warnings"]["queue-depth"]["change"], "same")

    def test_an_edited_status_move_is_listed(self):
        self.apply(edits=empty_edits(after_written=True, statuses={"queue-depth": "mitigated"}))
        self.assertEqual(self.summary()["moved"], [{"key": "queue-depth", "field": "status", "from": "open", "to": "mitigated"}])

    def test_a_warning_that_moves_and_resolves_is_listed_only_as_resolved(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(severity="High", status="decided")}))
        self.assertEqual(self.summary()["moved"], [])
        self.assertEqual(len(self.summary()["resolved"]), 1)

    def test_open_warnings_carry_their_evidence_in_stored_cite_form(self):
        self.apply()
        self.assertEqual(
            self.summary()["warnings"]["queue-depth"]["evidence"],
            [{"claim": "Depth is at 120", "cites": [{"feature": "metric:queue-depth", "name": "value"}, RECORD_CITE]}],
        )


class OnceOnlyTest(LifecycleCase):
    def test_a_resolved_warning_appears_in_one_summary_then_stays_retired(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(status="decided")}))
        self.assertEqual(len(self.summary()["resolved"]), 1)
        self.again(judgment=make_judgment(warnings={}))
        self.assertEqual(self.summary()["resolved"], [])
        self.assertEqual(self.next()["retired"]["queue-depth"], "Queue depth rises")

    def test_a_done_check_appears_in_one_summary_then_stays_retired(self):
        self.apply(edits=empty_edits(after_written=True, ticked=["ask-export"]))
        self.assertEqual(len(self.summary()["done"]), 1)
        self.again()
        self.assertEqual(self.summary()["done"], [])
        self.assertEqual(self.next()["retired"]["ask-export"], "Ask for the export")

    def test_resolved_keys_join_the_retired_ones_with_their_titles(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(status="dropped")}))
        self.assertEqual(self.next()["retired"], {"old-warning": "Old title", "queue-depth": "Queue depth rises"})

    def test_retired_keys_are_kept_across_a_run_that_resolves_nothing(self):
        self.apply()
        self.assertEqual(self.next()["retired"], {"old-warning": "Old title"})


class CheckLifecycleTest(LifecycleCase):
    def test_a_stored_check_absent_from_the_judgment_is_kept(self):
        self.apply()
        self.assertEqual(self.next()["checks"], {"ask-export": make_check()})

    def test_a_judged_check_updates_the_stored_one_and_keeps_its_since(self):
        update = {"ask-export": {"text": "Ask for the new export", "topic": "Capacity", "group": "Investigate"}}
        self.apply(judgment=make_judgment(checks=update))
        self.assertEqual(self.next()["checks"]["ask-export"], make_check(text="Ask for the new export", group="Investigate"))

    def test_a_new_check_starts_at_the_run_time(self):
        created = {"review-queue": {"text": "Review the queue", "topic": "Capacity", "group": "This week"}}
        self.apply(judgment=make_judgment(checks=created))
        self.assertEqual(self.next()["checks"]["review-queue"], make_check(text="Review the queue", since=RUN_AT))
        self.assertEqual(set(self.summary()["checks"]), {"ask-export", "review-queue"})

    def test_the_summary_lists_the_open_checks_by_key(self):
        self.apply()
        self.assertEqual(self.summary()["checks"], {"ask-export": make_check()})


class BlindSpotTest(LifecycleCase):
    def test_a_repeated_gap_counts_one_more_run_and_a_new_gap_starts_at_one(self):
        base = make_base(blind_spots=[{"key": "channels", "gap": "still no history"}, {"key": "issues", "gap": "no collection"}])
        self.apply(base=base)
        self.assertEqual(
            self.next()["blind_spots"],
            [{"key": "channels", "gap": "still no history", "runs": 2}, {"key": "issues", "gap": "no collection", "runs": 1}],
        )

    def test_an_unseen_gap_is_dropped_unless_it_is_known(self):
        spots = [{"key": "alerts", "gap": "no data", "runs": 3}, {"key": "channels", "gap": "no history", "runs": 1}]
        self.apply(stored=make_state(blind_spots=spots), base=make_base(blind_spots=[]))
        self.assertEqual(self.next()["blind_spots"], [spots[0]])

    def test_a_retried_known_gap_that_is_not_seen_again_is_removed(self):
        spots = [{"key": "alerts", "gap": "no data", "runs": 3}]
        self.apply(stored=make_state(blind_spots=spots), base=make_base(blind_spots=[], blind_spots_retried=["alerts"]))
        self.assertEqual(self.next()["blind_spots"], [])

    def test_the_cap_drops_the_extra_gaps_and_counts_them(self):
        gaps = [{"key": f"gap-{index}", "gap": "no data"} for index in range(state.BLIND_SPOT_CAP + 2)]
        self.apply(base=make_base(blind_spots=gaps))
        self.assertEqual(len(self.next()["blind_spots"]), state.BLIND_SPOT_CAP)
        self.assertEqual(self.summary()["blind_spots_dropped"], 2)
        self.assertEqual(self.summary()["blind_spots"], self.next()["blind_spots"])
        self.assertEqual(self.record()["blind_spots_dropped"], 2)


class CursorTest(LifecycleCase):
    def test_a_read_source_takes_its_fresh_cursor(self):
        self.apply()
        self.assertEqual(self.next()["cursors"]["channels"], {"ts": {CHANNEL_A: NEWER_TS}})

    def test_a_source_not_read_keeps_its_stored_cursor(self):
        base = make_base(cursors={"observability": {"events_ts_ms": 2_000, "monitors": {}, "metrics": {}}})
        self.apply(base=base)
        self.assertEqual(self.next()["cursors"]["channels"], {"ts": {CHANNEL_A: SLACK_TS}})

    def test_the_observability_cursor_takes_its_fresh_parts(self):
        self.apply()
        fresh = {"events_ts_ms": 2_000, "monitors": {"1001": "OK"}, "metrics": {"queue-depth": 120}}
        self.assertEqual(self.next()["cursors"]["observability"], fresh)

    def test_a_null_events_cursor_keeps_the_stored_one(self):
        base = make_base(cursors={"observability": {"events_ts_ms": None, "monitors": {"1001": "Alert"}, "metrics": {}}})
        self.apply(base=base)
        self.assertEqual(self.next()["cursors"]["observability"], {"events_ts_ms": 1_000, "monitors": {"1001": "Alert"}, "metrics": {}})

    def test_an_unchanged_cursor_is_accepted(self):
        self.apply(base=make_base(cursors={"channels": {"ts": {CHANNEL_A: SLACK_TS}}}))
        self.assertEqual(self.next()["cursors"]["channels"], {"ts": {CHANNEL_A: SLACK_TS}})

    def test_an_older_chat_cursor_is_rejected_with_its_path(self):
        err = self.rejected(3, base=make_base(cursors={"channels": {"ts": {CHANNEL_A: "1791990000.000001"}}}))
        self.assertIn(f"cursors.channels.ts.{CHANNEL_A}", err)

    def test_an_older_events_cursor_is_rejected(self):
        err = self.rejected(3, base=make_base(cursors={"observability": {"events_ts_ms": 999, "monitors": {}, "metrics": {}}}))
        self.assertIn("cursors.observability.events_ts_ms", err)

    def test_an_older_issue_tracker_cursor_is_rejected(self):
        stored = make_state()
        stored["cursors"]["issues"] = {"updated": "2026-10-15T07:23:59Z"}
        base = make_base(cursors={"issues": {"updated": "2026-10-14T07:23:59Z"}})
        base["sources"][2] = source_row("issues", "issue_tracker")
        self.assertIn("cursors.issues.updated", self.rejected(3, stored=stored, base=base))

    def test_an_older_page_cursor_is_rejected(self):
        stored = make_state()
        stored["cursors"]["pages"] = {"pages": {"page-a": "2026-10-12T14:20:59Z"}}
        base = make_base(cursors={"pages": {"pages": {"page-a": "2026-10-11T14:20:59Z"}}})
        base["sources"][2] = source_row("pages", "document_store")
        self.assertIn("cursors.pages.pages.page-a", self.rejected(3, stored=stored, base=base))

    def test_a_cursor_of_a_source_not_read_is_an_input_error(self):
        err = self.rejected(2, base=make_base(cursors={"issues": {"updated": "2026-10-14T07:23:59Z"}}))
        self.assertIn("cursors.issues", err)

    def test_a_null_chat_cursor_point_over_a_stored_one_is_rejected(self):
        err = self.rejected(3, base=make_base(cursors={"channels": {"ts": {CHANNEL_A: None}}}))
        self.assertIn(f"cursors.channels.ts.{CHANNEL_A}", err)

    def test_an_object_chat_cursor_point_over_a_stored_one_is_rejected(self):
        err = self.rejected(3, base=make_base(cursors={"channels": {"ts": {CHANNEL_A: {}}}}))
        self.assertIn(f"cursors.channels.ts.{CHANNEL_A}", err)

    def test_a_null_issue_tracker_cursor_over_a_stored_one_is_rejected(self):
        stored = make_state()
        stored["cursors"]["issues"] = {"updated": "2026-10-15T07:23:59Z"}
        base = make_base(cursors={"issues": {"updated": None}})
        base["sources"][2] = source_row("issues", "issue_tracker")
        self.assertIn("cursors.issues.updated", self.rejected(3, stored=stored, base=base))

    def test_an_older_code_host_cursor_is_rejected(self):
        stored = make_state()
        stored["cursors"]["code"] = {"updated_at": "2026-10-15T07:23:59Z"}
        base = make_base(cursors={"code": {"updated_at": "2026-10-14T07:23:59Z"}})
        base["sources"][2] = source_row("code", "code_host")
        self.assertIn("cursors.code.updated_at", self.rejected(3, stored=stored, base=base))

    def test_an_explicit_window_skips_the_forward_check(self):
        self.apply(base=make_base(cursors={"channels": {"ts": {CHANNEL_A: "1791990000.000001"}}}), window=make_window(explicit=True))
        self.assertEqual(self.code, 0)


class ThreadTest(LifecycleCase):
    def without_first_record(self):
        keys = make_features(make_state())["keys"]
        return {name: doc for name, doc in keys.items() if name != "record:channels:c1"}

    def test_threads_are_rebuilt_from_the_cited_message_records(self):
        self.apply(stored=make_state(threads={}))
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY]})

    def test_threads_hold_each_cited_thread_once_in_order(self):
        warnings = {"queue-depth": judged(evidence=[{"claim": "Depth", "cites": [METRIC_CITE, NEW_RECORD_CITE, RECORD_CITE]}])}
        self.apply(judgment=make_judgment(warnings=warnings), stored=make_state(threads={}))
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY, NEW_THREAD_ENTRY]})

    def test_the_links_of_one_thread_merge_into_one_entry(self):
        warnings = {"queue-depth": judged(evidence=[{"claim": "Depth", "cites": [METRIC_CITE, RECORD_CITE, SAME_THREAD_CITE]}])}
        self.apply(judgment=make_judgment(warnings=warnings))
        self.assertEqual(self.next()["threads"], {"channels": [{**THREAD_ENTRY, "links": [LINK, SAME_LINK]}]})

    def test_a_stored_thread_stays_while_an_open_warning_cites_its_link(self):
        self.apply(keys=self.without_first_record())
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY]})

    def test_a_stored_thread_no_open_warning_cites_is_dropped(self):
        other = {"channel": CHANNEL_A, "root_ts": "1791990100.000100", "links": ["https://example.test/c/9"]}
        self.apply(stored=make_state(threads={"channels": [THREAD_ENTRY, other]}))
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY]})

    def test_a_kept_thread_keeps_only_the_links_still_cited(self):
        stale = {**THREAD_ENTRY, "links": [LINK, "https://example.test/c/9"]}
        self.apply(stored=make_state(threads={"channels": [stale]}))
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY]})

    def test_a_resolved_warning_keeps_no_thread(self):
        self.apply(judgment=make_judgment(warnings={"queue-depth": judged(status="decided")}))
        self.assertEqual(self.next()["threads"], {})

    def test_a_held_warning_keeps_its_stored_thread(self):
        self.apply(judgment=make_judgment(warnings={}), deferred=["queue-depth"], keys=self.without_first_record())
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY]})

    def test_a_held_warning_cites_the_threads_of_this_run(self):
        self.apply(stored=make_state(threads={}), judgment=make_judgment(warnings={}), deferred=["queue-depth"])
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY]})

    def test_a_source_not_read_keeps_its_stored_threads(self):
        base = make_base(sources=[source_row("channels", "chat", False), source_row("metrics", "observability")], cursors={})
        features = make_features(make_state())
        self.apply(base=base, keys={name: doc for name, doc in features["keys"].items() if doc["source"] != "channels"})
        self.assertEqual(self.next()["threads"], {"channels": [THREAD_ENTRY]})


class CoverageNoteTest(LifecycleCase):
    def test_the_checked_notes_reach_the_summary(self):
        self.apply(judgment=make_judgment(coverage_notes=NOTES))
        self.assertEqual(self.summary()["coverage_notes"], NOTES)

    def test_a_judgment_without_notes_gives_an_empty_summary_list(self):
        self.apply()
        self.assertEqual(self.summary()["coverage_notes"], [])

    def test_the_notes_change_nothing_in_the_next_state(self):
        self.apply()
        without_notes = self.next()
        self.apply(judgment=make_judgment(coverage_notes=NOTES))
        self.assertEqual(self.next(), without_notes)

    def test_the_notes_change_nothing_in_the_run_record(self):
        self.apply()
        without_notes = self.record()
        self.apply(judgment=make_judgment(coverage_notes=NOTES))
        self.assertEqual(self.record(), without_notes)

    def test_the_notes_change_no_other_field_of_the_summary(self):
        self.apply()
        without_notes = {name: value for name, value in self.summary().items() if name != "coverage_notes"}
        self.apply(judgment=make_judgment(coverage_notes=NOTES))
        self.assertEqual({name: value for name, value in self.summary().items() if name != "coverage_notes"}, without_notes)

    def test_a_report_only_run_with_notes_leaves_the_state_byte_identical(self):
        self.apply(window=make_window(explicit=True), judgment=make_judgment(coverage_notes=NOTES))
        with open(self.path("state.json"), "rb") as before, open(self.path("next.json"), "rb") as after:
            self.assertEqual(after.read(), before.read())

    def test_a_report_only_run_keeps_the_notes_in_the_summary(self):
        self.apply(window=make_window(explicit=True), judgment=make_judgment(coverage_notes=NOTES))
        self.assertEqual(self.summary()["coverage_notes"], NOTES)

    def test_a_repeated_source_is_rejected_by_apply_and_writes_no_file(self):
        code = self.run_apply(judgment=make_judgment(coverage_notes=[NOTES[0], NOTES[0]]))
        self.assertEqual(code, 3)
        self.assertIn("judgment: coverage_notes[1].source: same source as coverage_notes[0]", self.err)
        self.assertFalse(os.path.exists(self.path("summary.json")))

    def test_the_judge_command_rejects_eleven_notes_with_the_key_path(self):
        notes = [{"source": f"Source {number}", "text": "Not read"} for number in range(11)]
        stored = make_state()
        code, _, err = run_cli(
            "judge",
            "--features", self.write("features.json", make_features(stored)),
            "--judgment", self.write("judgment.json", make_judgment(coverage_notes=notes)),
        )
        self.assertEqual(code, 3)
        self.assertIn("rejected: judgment: coverage_notes: expected at most 10 notes, got 11", err)


class ReportOnlyTest(LifecycleCase):
    def test_an_explicit_window_leaves_the_state_byte_identical(self):
        self.apply(window=make_window(explicit=True), judgment=make_judgment(warnings={"queue-depth": judged(status="decided")}))
        with open(self.path("state.json"), "rb") as before, open(self.path("next.json"), "rb") as after:
            self.assertEqual(after.read(), before.read())

    def test_an_explicit_window_still_writes_the_summary_and_the_record(self):
        self.apply(window=make_window(explicit=True), judgment=make_judgment(warnings={"queue-depth": judged(status="decided")}))
        self.assertTrue(self.summary()["report_only"])
        self.assertEqual(len(self.summary()["resolved"]), 1)
        self.assertTrue(self.record()["window"]["explicit"])

    def test_a_normal_window_writes_the_state_as_canonical_json(self):
        self.apply()
        for name in ("next.json", "summary.json", "record.json"):
            self.assert_canonical(name)
        self.assertFalse(self.summary()["report_only"])


class OutputShapeTest(LifecycleCase):
    def test_the_summary_holds_the_fields_of_the_data_model(self):
        self.apply()
        self.assertEqual(set(self.summary()), SUMMARY_FIELDS)

    def test_the_summary_header_comes_from_the_state_and_the_window(self):
        self.apply()
        summary = self.summary()
        self.assertEqual(
            (summary["digest"], summary["run_at"], summary["baseline"]), ("example", RUN_AT, False)
        )
        self.assertEqual(summary["window"], {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW)})
        self.assertEqual(summary["previous_page"], {"id": PAGE_ID, "written_at": WRITTEN})

    def test_the_first_run_is_a_baseline(self):
        self.apply(stored=tribe_state.initial_state("example"), judgment=make_judgment(warnings={"queue-depth": judged(), }))
        self.assertTrue(self.summary()["baseline"])
        self.assertEqual(self.summary()["warnings"]["queue-depth"]["change"], "new")

    def test_the_summary_sources_come_from_the_base_with_spaced_roles(self):
        self.apply()
        self.assertEqual(
            [(row["source"], row["role"], row["read"]) for row in self.summary()["sources"]],
            [("channels", "chat", True), ("metrics", "observability", True), ("issues", "issue tracker", False)],
        )

    def test_the_judged_sections_reach_the_summary_with_stored_cites(self):
        decision = {"decision": "Add a worker", "deadline": "Friday", "options": "add now or wait", "topic": "Capacity"}
        judgment = make_judgment(
            decisions=[decision],
            details={"Capacity": [{"text": "Depth rose", "cites": [METRIC_CITE]}]},
            corrections=[{"was": "Depth 100", "now": "Depth 120", "cites": [METRIC_CITE]}],
            highlights=[{"text": "Queue depth is the top risk", "cites": [METRIC_CITE, RECORD_CITE]}],
        )
        self.apply(judgment=judgment)
        stored_cite = {"feature": "metric:queue-depth", "name": "value"}
        summary = self.summary()
        self.assertEqual(summary["decisions"], [decision])
        self.assertEqual(summary["details"], {"Capacity": [{"text": "Depth rose", "cites": [stored_cite]}]})
        self.assertEqual(summary["corrections"], [{"was": "Depth 100", "now": "Depth 120", "cites": [stored_cite]}])
        self.assertEqual(summary["highlights"], [{"text": "Queue depth is the top risk", "cites": [stored_cite, RECORD_CITE]}])

    def test_the_summary_renders_into_a_page_that_passes_the_structure_check(self):
        self.apply()
        with open(os.path.join(HERE, "fixtures", "tribe", "page_values.json"), encoding="utf-8") as handle:
            values = json.load(handle)
        self.assertEqual(tribe_page.check(tribe_page.render(self.summary(), values)), [])

    def test_the_next_state_run_block_follows_the_run(self):
        self.apply()
        run = self.next()["run"]
        self.assertEqual(
            run,
            {
                "at": RUN_AT,
                "window": {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW)},
                "daily_metrics_on": "2026-10-16",
                "previous_page": {"id": PAGE_ID, "written_at": WRITTEN},
                "weekly_heading_week": "2026-W42",
                "layout_version": 1,
                "models": {"collect": "model-b"},
                "posted": False,
            },
        )

    def test_the_record_lists_the_keys_the_counts_and_the_sources_read(self):
        stored = make_state(warnings={"queue-depth": make_warning(), "disk-fills": make_warning(title="Disk fills")})
        warnings = {
            "queue-depth": judged(severity="High"),
            "disk-fills": judged(title="Disk fills", status="decided"),
            "net-drops": judged_new(title="Net drops"),
        }
        self.apply(stored=stored, judgment=make_judgment(warnings=warnings), edits=empty_edits(after_written=True, ticked=["ask-export"]))
        self.assertEqual(
            self.record(),
            {
                "schema": 1,
                "digest": "example",
                "run_at": RUN_AT,
                "window": {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW), "explicit": False, "cut": None},
                "counts": {"new": 1, "moved": 1, "resolved": 1, "done": 1, "held": 0, "open": 2, "checks": 0},
                "new": ["net-drops"],
                "moved": ["queue-depth"],
                "resolved": ["disk-fills"],
                "done": ["ask-export"],
                "held": [],
                "blind_spots": [{"key": "channels", "runs": 2}],
                "blind_spots_dropped": 0,
                "sources_read": ["channels", "metrics"],
                "edits_ignored": [],
            },
        )

    def test_the_record_holds_no_run_context_of_the_base(self):
        context = {"place": "cloud", "runtime": None, "config": None, "config_dirty": None, "collected": {}}
        self.apply(base=make_base(run_context=context))
        self.assertEqual(set(context) & set(self.record()), set())


class InputGuardTest(LifecycleCase):
    def test_features_built_from_another_state_are_an_input_error(self):
        other = make_state(warnings={})
        err = self.rejected(2, previous=make_features(other)["previous"])
        self.assertIn("features: previous", err)

    def test_a_deferred_key_that_is_not_stored_is_an_input_error(self):
        self.assertIn("deferred[0]", self.rejected(2, deferred=["unknown-key"]))

    def test_an_edit_for_a_key_that_is_not_stored_is_an_input_error(self):
        err = self.rejected(2, edits=empty_edits(after_written=True, ticked=["unknown-check"]))
        self.assertIn("edits.ticked[0]", err)

    def test_a_window_ending_before_the_stored_run_is_rejected(self):
        err = self.rejected(3, stored=make_state(at=NOW), window=make_window(to_ts=ts(PREVIOUS)))
        self.assertIn("window: to_ts", err)

    def test_a_rejected_judgment_writes_nothing(self):
        err = self.rejected(3, judgment=make_judgment(warnings={"queue-depth": judged(), "old-warning": judged_new()}))
        self.assertIn("judgment: warnings.old-warning", err)
        self.assertFalse(os.path.exists(self.path("summary.json")))
        self.assertFalse(os.path.exists(self.path("record.json")))

    def test_a_base_without_its_sources_is_an_input_error(self):
        base = make_base()
        del base["sources"]
        self.assertIn("base: missing key sources", self.rejected(2, base=base))

    def test_a_window_file_failing_its_schema_is_rejected(self):
        window = make_window()
        del window["cut"]
        self.assertIn("window: missing key cut", self.rejected(3, window=window))

    def test_a_missing_window_file_is_an_input_error(self):
        self.run_apply()
        code, _, err = run_cli(
            "apply", "--state", self.path("state.json"), "--features", self.path("features.json"), "--base", self.path("base.json"),
            "--judgment", self.path("judgment.json"), "--window", self.path("absent.json"), "--out", self.path("other.json"),
            "--summary", self.path("other-summary.json"), "--record", self.path("other-record.json"),
        )
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)


class ApplyResultTest(LifecycleCase):
    def applied(self, **arguments):
        self.apply(**arguments)
        names = ("state.json", "features.json", "base.json", "judgment.json", "window.json")
        return tribe_lifecycle.apply(*[self.path(name) for name in names])

    def test_apply_returns_the_next_state_the_summary_and_the_record_as_documents(self):
        applied = self.applied()
        self.assertEqual((applied.state, applied.summary, applied.record), (self.next(), self.summary(), self.record()))

    def test_apply_keeps_no_raw_state_for_a_run_that_advances_the_state(self):
        self.assertIsNone(self.applied().raw)

    def test_apply_returns_the_input_bytes_for_a_report_only_run(self):
        applied = self.applied(window=make_window(explicit=True))
        with open(self.path("state.json"), "rb") as handle:
            self.assertEqual(applied.raw, handle.read())


class FeaturesSeamTest(LifecycleCase):
    def feed(self):
        stored = make_state(threads={})
        features_doc, base, _ = seam.compute(stored=stored)
        cites = [{"feature": "metric:queue-depth", "name": "value", "value": 12}, RECORD_CITE]
        warnings = {"queue-depth": judged(evidence=[{"claim": "Depth is at 12", "cites": cites}])}
        window = make_window(from_ts=seam.FROM_TS, to_ts=seam.TO_TS)
        self.apply(stored=stored, judgment=make_judgment(warnings=warnings), base=base, window=window, **features_doc)

    def test_threads_come_from_the_records_of_tribe_features(self):
        self.feed()
        thread = {"channel": CHANNEL_A, "root_ts": "1791990730.002679", "links": [LINK]}
        self.assertEqual(self.next()["threads"], {"channels": [thread]})

    def test_blind_spots_come_from_the_base_of_tribe_features(self):
        self.feed()
        self.assertEqual(self.next()["blind_spots"], [{"key": "previous-digest", "gap": "previous digest unreadable", "runs": 1}])

    def test_cursors_come_from_the_base_of_tribe_features(self):
        self.feed()
        self.assertEqual(self.next()["cursors"]["channels"], {"ts": {CHANNEL_A: "1791990731.000100"}})


class CursorMessageTest(unittest.TestCase):
    def test_the_stored_point_of_a_backward_cursor_is_capped_in_the_message(self):
        with self.assertRaises(state.Rejected) as caught:
            tribe_lifecycle.check_forward("channels", "chat", {"ts": {CHANNEL_A: "9" * 400}}, {"ts": {CHANNEL_A: "1"}})
        self.assertNotIn("9" * 61, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
