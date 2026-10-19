import copy
import unittest

import state
import tribe_judgment
import tribe_state
import tribe_support

OLD_LINK = "https://chat.example.test/old/1"
THREAD_LINK = "https://chat.example.test/t/1"
MESSAGE_LINK = "https://chat.example.test/t/1/m/2"
ISSUE_LINK = "https://tracker.example.test/9"
HIDDEN_LINK = "https://tracker.example.test/hidden"
AUTHOR = "usr_8f3k2"
CPU_CITE = {"feature": "cpu", "name": "value", "value": 90}
CPU_STORED_CITE = {"feature": "cpu", "name": "value"}
MESSAGE_CITE = {"source": "chat", "link": MESSAGE_LINK}
OLD_CITE = {"source": "chat", "link": OLD_LINK}


def stored_warning(**fields):
    return tribe_support.make_warning(
        **{
            "title": "Database capacity",
            "topic": "Database",
            "severity": "High",
            "when": "now",
            "runway": "3 weeks",
            "risk": "Disk fills before the next resize",
            "impact": "Writes fail",
            "mitigation": ["Add a replica"],
            "cites": [OLD_CITE, CPU_STORED_CITE],
            "metric": "cpu",
            "since": "2026-05-01",
            **fields,
        }
    )


def make_features():
    return {
        "keys": {
            "thread-1": {"kind": "record", "source": "chat", "link": THREAD_LINK, "title": "Thread", "values": {}, "text": "slow"},
            "message-2": {"kind": "record", "source": "chat", "link": MESSAGE_LINK, "title": "Message", "values": {}, "text": "slow"},
            "issue-9": {"kind": "record", "source": "tracker", "link": ISSUE_LINK, "title": "Issue", "values": {}, "text": f"slow, see {HIDDEN_LINK}"},
            "cpu": {"kind": "metric", "source": "metrics", "link": None, "title": "CPU", "values": {"value": 90, "latest": 85.5, "stale": False}},
        },
        "previous": {
            "warnings": {"db-capacity": stored_warning()},
            "checks": {"review-db": {"text": "Review the database plan", "topic": "Database", "group": "This week", "since": "2026-05-01"}},
            "retired": {"old-queue": "Queue backlog"},
        },
        "deferred": [],
        "authors": [AUTHOR],
        "pack": ["cpu"],
    }


def make_warning(**fields):
    return dict(
        {
            "title": "API latency",
            "topic": "API",
            "severity": "Medium",
            "when": "within months",
            "runway": "2 months",
            "status": "open",
            "confidence": "reported",
            "risk": "Pages load slowly",
            "impact": "Users leave the checkout",
            "mitigation": ["Profile the endpoint", "Add a cache"],
            "metric": None,
            "verdict": "open",
            "evidence": [{"claim": "Users report slow pages", "cites": [MESSAGE_CITE]}],
        },
        **fields,
    )


JUDGMENT = {
    "warnings": {
        "db-capacity": make_warning(
            title="Database capacity",
            topic="Database",
            severity="High",
            when="now",
            confidence="measured",
            metric="cpu",
            evidence=[{"claim": "CPU is at 90", "cites": [CPU_CITE, OLD_CITE]}],
        ),
        "api-latency": make_warning(),
    },
    "checks": {
        "review-db": {"text": "Review the database plan", "topic": "Database", "group": "This week"},
        "check-cache": {"text": "Check the cache hit rate", "topic": "API", "group": "Investigate"},
    },
    "decisions": [{"decision": "Resize the database", "deadline": "Friday", "options": "Resize now or wait", "topic": "Database"}],
    "details": {"Database": [{"text": "CPU rose", "cites": [CPU_CITE]}]},
    "corrections": [{"was": "CPU at 80", "now": "CPU at 90", "cites": [CPU_CITE]}],
    "highlights": [{"text": "Database capacity stays the top risk", "cites": [CPU_CITE, {"source": "tracker", "link": ISSUE_LINK}]}],
    "coverage_notes": [{"source": "Mobile app", "text": "Not read, no connector is configured for it"}],
}


def make_judgment():
    return copy.deepcopy(JUDGMENT)


def changed(*path_and_value):
    *path, value = path_and_value
    document = make_judgment()
    target = document
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return document


def without(*path):
    document = make_judgment()
    target = document
    for step in path[:-1]:
        target = target[step]
    del target[path[-1]]
    return document


class CheckTestCase(unittest.TestCase):
    def rejection(self, document, features_doc=None):
        with self.assertRaises(state.Rejected) as caught:
            tribe_judgment.check(features_doc or make_features(), document)
        return str(caught.exception)


class ValidJudgmentTest(CheckTestCase):
    def test_full_judgment_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), make_judgment()))

    def test_stored_checks_absent_from_the_judgment_pass(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("checks", {})))

    def test_metric_less_warning_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("warnings", "api-latency", "metric", None)))

    def test_inferred_warning_without_evidence_passes(self):
        document = changed("warnings", "api-latency", make_warning(confidence="inferred", evidence=[]))

        self.assertIsNone(tribe_judgment.check(make_features(), document))


class KeyTest(CheckTestCase):
    def test_warning_key_that_is_not_kebab_case_is_rejected_with_its_key_path(self):
        document = make_judgment()
        document["warnings"]["Api_Latency"] = document["warnings"].pop("api-latency")

        message = self.rejection(document)

        self.assertIn("warnings.Api_Latency", message)
        self.assertIn("kebab-case", message)

    def test_check_key_that_is_not_kebab_case_is_rejected_with_its_key_path(self):
        document = make_judgment()
        document["checks"]["Check Cache"] = document["checks"].pop("check-cache")

        self.assertIn("checks.Check Cache", self.rejection(document))

    def test_warning_key_with_a_double_hyphen_is_rejected(self):
        document = make_judgment()
        document["warnings"]["api--latency"] = document["warnings"].pop("api-latency")

        self.assertIn("warnings.api--latency", self.rejection(document))

    def test_retired_warning_key_is_rejected_with_its_key_path(self):
        document = make_judgment()
        document["warnings"]["old-queue"] = document["warnings"].pop("api-latency")

        message = self.rejection(document)

        self.assertIn("warnings.old-queue", message)
        self.assertIn("retired", message)

    def test_retired_check_key_is_rejected_with_its_key_path(self):
        document = make_judgment()
        document["checks"]["old-queue"] = document["checks"].pop("check-cache")

        self.assertIn("checks.old-queue", self.rejection(document))

    def test_key_used_by_a_warning_and_a_check_of_the_run_is_rejected_with_its_key_path(self):
        document = changed("checks", "api-latency", {"text": "Check latency", "topic": "API", "group": "Investigate"})

        message = self.rejection(document)

        self.assertIn("warnings.api-latency", message)
        self.assertIn("check key", message)

    def test_new_warning_key_of_a_stored_check_is_rejected_with_its_key_path(self):
        document = make_judgment()
        document["warnings"]["review-db"] = document["warnings"].pop("api-latency")

        message = self.rejection(document)

        self.assertIn("warnings.review-db", message)
        self.assertIn("stored check", message)

    def test_new_check_key_of_a_stored_warning_is_rejected_with_its_key_path(self):
        document = without("warnings", "db-capacity")
        document["warnings"]["api-latency"]["replaces"] = "db-capacity"
        document["checks"]["db-capacity"] = document["checks"].pop("check-cache")

        message = self.rejection(document)

        self.assertIn("checks.db-capacity", message)
        self.assertIn("stored warning", message)

    def test_a_long_key_is_quoted_with_a_short_cap(self):
        document = make_judgment()
        document["warnings"]["A" * 100] = document["warnings"].pop("api-latency")

        message = self.rejection(document)

        self.assertIn("A" * 60, message)
        self.assertNotIn("A" * 61, message)

    def test_warning_key_over_the_cap_is_rejected_with_a_capped_key_path(self):
        document = make_judgment()
        document["warnings"]["a" * 100] = document["warnings"].pop("api-latency")

        message = self.rejection(document)

        self.assertIn("warnings." + "a" * 60 + ": the key must be kebab-case", message)
        self.assertIn("at most 60 characters", message)
        self.assertNotIn("a" * 61, message)

    def test_check_key_over_the_cap_is_rejected_with_a_capped_key_path(self):
        document = make_judgment()
        document["checks"]["a" * 100] = document["checks"].pop("check-cache")

        message = self.rejection(document)

        self.assertIn("checks." + "a" * 60 + ": the key must be kebab-case", message)
        self.assertNotIn("a" * 61, message)

    def test_warning_key_of_the_cap_length_passes(self):
        document = make_judgment()
        document["warnings"]["a" * 60] = document["warnings"].pop("api-latency")

        self.assertIsNone(tribe_judgment.check(make_features(), document))

    def test_a_key_with_markup_is_quoted_without_it(self):
        document = make_judgment()
        document["checks"]["<b>go@host"] = document["checks"].pop("check-cache")

        message = self.rejection(document)

        self.assertIn("checks. b go host", message)


class StoredWarningTest(CheckTestCase):
    def test_stored_warning_absent_from_the_judgment_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.db-capacity", self.rejection(without("warnings", "db-capacity")))

    def test_deferred_stored_warning_may_be_absent(self):
        features_doc = make_features()
        features_doc["deferred"] = ["db-capacity"]

        self.assertIsNone(tribe_judgment.check(features_doc, without("warnings", "db-capacity")))

    def test_replaced_stored_warning_may_be_absent(self):
        document = without("warnings", "db-capacity")
        document["warnings"]["api-latency"]["replaces"] = "db-capacity"

        self.assertIsNone(tribe_judgment.check(make_features(), document))

    def test_replaces_naming_an_unknown_key_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.replaces", self.rejection(changed("warnings", "api-latency", "replaces", "ghost")))

    def test_replaces_naming_a_retired_key_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.replaces", self.rejection(changed("warnings", "api-latency", "replaces", "old-queue")))

    def test_replaces_naming_a_warning_judged_in_the_run_is_rejected(self):
        message = self.rejection(changed("warnings", "api-latency", "replaces", "db-capacity"))

        self.assertIn("warnings.api-latency.replaces", message)
        self.assertIn("also judged", message)

    def test_two_warnings_replacing_the_same_key_are_rejected(self):
        document = without("warnings", "db-capacity")
        document["warnings"]["api-latency"]["replaces"] = "db-capacity"
        document["warnings"]["web-latency"] = make_warning(title="Web latency", replaces="db-capacity")

        message = self.rejection(document)

        self.assertIn("warnings.web-latency.replaces", message)
        self.assertIn("already replaced by warnings.api-latency", message)

    def test_stored_warning_replacing_another_is_rejected(self):
        features_doc = make_features()
        features_doc["previous"]["warnings"]["api-latency"] = stored_warning(title="API latency")
        document = changed("warnings", "api-latency", "replaces", "db-capacity")

        self.assertIn("warnings.api-latency.replaces", self.rejection(document, features_doc))

    def test_replaces_naming_a_deferred_warning_is_rejected_with_its_key_path(self):
        features_doc = make_features()
        features_doc["deferred"] = ["db-capacity"]
        document = without("warnings", "db-capacity")
        document["warnings"]["api-latency"]["replaces"] = "db-capacity"

        message = self.rejection(document, features_doc)

        self.assertIn("warnings.api-latency.replaces", message)
        self.assertIn("deferred", message)

    def test_deferred_warning_present_in_the_judgment_passes(self):
        features_doc = make_features()
        features_doc["deferred"] = ["db-capacity"]

        self.assertIsNone(tribe_judgment.check(features_doc, make_judgment()))

    def test_replaces_key_is_quoted_without_markup(self):
        message = self.rejection(changed("warnings", "api-latency", "replaces", "<ghost>"))

        self.assertIn(" ghost  is not a stored warning", message)

    def test_null_replaces_counts_as_absent(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("warnings", "api-latency", "replaces", None)))


class TitleTest(CheckTestCase):
    def test_new_title_matching_a_stored_one_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("warnings", "api-latency", "title", "database CAPACITY"))

        self.assertIn("warnings.api-latency.title", message)
        self.assertIn("db-capacity", message)

    def test_new_title_matching_a_stored_one_passes_when_it_replaces_that_key(self):
        document = without("warnings", "db-capacity")
        document["warnings"]["api-latency"].update(title="Database Capacity", replaces="db-capacity")

        self.assertIsNone(tribe_judgment.check(make_features(), document))

    def test_new_title_matching_a_stored_one_is_rejected_when_it_replaces_another_key(self):
        features_doc = make_features()
        features_doc["previous"]["warnings"]["queue-depth"] = stored_warning(title="Queue depth")
        document = make_judgment()
        document["warnings"]["api-latency"].update(title="Database capacity", replaces="queue-depth")

        self.assertIn("warnings.api-latency.title", self.rejection(document, features_doc))

    def test_new_title_matching_a_retired_one_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("warnings", "api-latency", "title", " queue backlog "))

        self.assertIn("warnings.api-latency.title", message)
        self.assertIn("old-queue", message)

    def test_new_title_matching_a_retired_one_is_rejected_even_when_it_replaces(self):
        document = without("warnings", "db-capacity")
        document["warnings"]["api-latency"].update(title="Queue backlog", replaces="db-capacity")

        self.assertIn("warnings.api-latency.title", self.rejection(document))

    def test_two_new_warnings_with_the_same_title_are_rejected_with_the_key_path_of_the_second(self):
        document = make_judgment()
        document["warnings"]["web-latency"] = make_warning(title="api LATENCY")

        message = self.rejection(document)

        self.assertIn("warnings.web-latency.title", message)
        self.assertIn("warnings.api-latency", message)

    def test_new_title_matching_a_stored_one_after_collapsing_whitespace_is_rejected(self):
        message = self.rejection(changed("warnings", "api-latency", "title", "Database \t  capacity"))

        self.assertIn("warnings.api-latency.title", message)

    def test_stored_warning_retitled_to_the_title_of_a_deferred_stored_warning_is_rejected(self):
        features_doc = make_features()
        features_doc["previous"]["warnings"]["queue-depth"] = stored_warning(title="Queue depth")
        features_doc["deferred"] = ["queue-depth"]
        document = changed("warnings", "db-capacity", "title", "queue DEPTH")

        message = self.rejection(document, features_doc)

        self.assertIn("warnings.db-capacity.title", message)
        self.assertIn("queue-depth", message)

    def test_new_title_equal_to_a_retitled_stored_warning_is_rejected(self):
        document = changed("warnings", "db-capacity", "title", "API latency")

        self.assertIn("warnings.db-capacity.title", self.rejection(document))


class FieldTest(CheckTestCase):
    def test_severity_outside_its_values_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.severity", self.rejection(changed("warnings", "api-latency", "severity", "Critical")))

    def test_when_outside_its_values_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.when", self.rejection(changed("warnings", "api-latency", "when", "soon")))

    def test_confidence_outside_its_values_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.confidence", self.rejection(changed("warnings", "api-latency", "confidence", "High")))

    def test_status_outside_its_values_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.status", self.rejection(changed("warnings", "api-latency", "status", "closed")))

    def test_every_status_of_the_requirement_passes(self):
        for status in ("open", "in progress", "mitigated", "decided", "dropped"):
            with self.subTest(status=status):
                self.assertIsNone(tribe_judgment.check(make_features(), changed("warnings", "api-latency", "status", status)))

    def test_verdict_outside_its_values_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.verdict", self.rejection(changed("warnings", "api-latency", "verdict", "closed")))

    def test_under_verdict_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("warnings", "api-latency", "verdict", "under")))

    def test_missing_warning_field_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.impact", self.rejection(without("warnings", "api-latency", "impact")))

    def test_check_group_outside_the_groups_is_rejected_with_its_key_path(self):
        self.assertIn("checks.check-cache.group", self.rejection(changed("checks", "check-cache", "group", "Someday")))

    def test_metric_outside_the_pack_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.metric", self.rejection(changed("warnings", "api-latency", "metric", "memory")))

    def test_empty_mitigation_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.mitigation", self.rejection(changed("warnings", "api-latency", "mitigation", [])))

    def test_four_mitigation_leads_are_rejected_with_their_key_path(self):
        self.assertIn("warnings.api-latency.mitigation", self.rejection(changed("warnings", "api-latency", "mitigation", ["a", "b", "c", "d"])))

    def test_four_decisions_are_rejected_with_their_key_path(self):
        decisions = make_judgment()["decisions"] * 4

        self.assertEqual(self.rejection(changed("decisions", decisions)), "decisions: expected at most 3 decisions, got 4")

    def test_three_decisions_pass(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("decisions", make_judgment()["decisions"] * 3)))

    def test_decision_without_a_topic_is_rejected_with_its_key_path(self):
        self.assertIn("decisions[0].topic", self.rejection(without("decisions", 0, "topic")))

    def test_missing_section_is_rejected_with_its_key_path(self):
        self.assertIn("highlights", self.rejection(without("highlights")))


UNKNOWN_FIELDS = (
    ("extra", ("extra",)),
    ("warnings.api-latency.extra", ("warnings", "api-latency", "extra")),
    ("warnings.api-latency.evidence[0].extra", ("warnings", "api-latency", "evidence", 0, "extra")),
    ("warnings.api-latency.evidence[0].cites[0].extra", ("warnings", "api-latency", "evidence", 0, "cites", 0, "extra")),
    ("checks.check-cache.extra", ("checks", "check-cache", "extra")),
    ("decisions[0].extra", ("decisions", 0, "extra")),
    ("details.Database[0].extra", ("details", "Database", 0, "extra")),
    ("corrections[0].extra", ("corrections", 0, "extra")),
    ("highlights[0].extra", ("highlights", 0, "extra")),
    ("coverage_notes[0].extra", ("coverage_notes", 0, "extra")),
)


class UnknownFieldTest(CheckTestCase):
    def test_every_object_rejects_an_unknown_field_with_its_key_path(self):
        for path, steps in UNKNOWN_FIELDS:
            with self.subTest(path=path):
                self.assertIn(f"{path}: unknown field", self.rejection(changed(*steps, "x")))


TEXT_FIELDS = (
    ("warnings.api-latency.title", ("warnings", "api-latency", "title")),
    ("warnings.api-latency.topic", ("warnings", "api-latency", "topic")),
    ("warnings.api-latency.runway", ("warnings", "api-latency", "runway")),
    ("warnings.api-latency.risk", ("warnings", "api-latency", "risk")),
    ("warnings.api-latency.impact", ("warnings", "api-latency", "impact")),
    ("warnings.api-latency.mitigation[1]", ("warnings", "api-latency", "mitigation", 1)),
    ("warnings.api-latency.evidence[0].claim", ("warnings", "api-latency", "evidence", 0, "claim")),
    ("checks.check-cache.text", ("checks", "check-cache", "text")),
    ("checks.check-cache.topic", ("checks", "check-cache", "topic")),
    ("decisions[0].decision", ("decisions", 0, "decision")),
    ("decisions[0].deadline", ("decisions", 0, "deadline")),
    ("decisions[0].options", ("decisions", 0, "options")),
    ("decisions[0].topic", ("decisions", 0, "topic")),
    ("details.Database[0].text", ("details", "Database", 0, "text")),
    ("corrections[0].was", ("corrections", 0, "was")),
    ("corrections[0].now", ("corrections", 0, "now")),
    ("highlights[0].text", ("highlights", 0, "text")),
    ("coverage_notes[0].source", ("coverage_notes", 0, "source")),
    ("coverage_notes[0].text", ("coverage_notes", 0, "text")),
)


class TextTest(CheckTestCase):
    def test_every_text_field_rejects_markup_with_its_key_path(self):
        for path, steps in TEXT_FIELDS:
            with self.subTest(path=path):
                self.assertIn(path, self.rejection(changed(*steps, "a <b> tag")))

    def test_every_text_field_rejects_a_text_over_300_characters_with_its_key_path(self):
        for path, steps in TEXT_FIELDS:
            with self.subTest(path=path):
                self.assertIn(path, self.rejection(changed(*steps, "x" * 301)))

    def test_every_text_field_rejects_an_empty_text_with_its_key_path(self):
        for path, steps in TEXT_FIELDS:
            with self.subTest(path=path):
                self.assertIn(f"{path}: must not be empty", self.rejection(changed(*steps, "")))

    def test_blank_text_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.risk: must not be empty", self.rejection(changed("warnings", "api-latency", "risk", "   ")))

    def test_text_with_fullwidth_markup_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.risk", self.rejection(changed("warnings", "api-latency", "risk", "a \uff1cb\uff1e tag")))

    def test_text_with_a_fullwidth_at_sign_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.risk", self.rejection(changed("warnings", "api-latency", "risk", "ping \uff20team")))

    def test_text_with_a_fullwidth_url_scheme_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.risk", self.rejection(changed("warnings", "api-latency", "risk", "see https\uff1a\uff0f\uff0fexample.test")))

    def test_text_with_a_fullwidth_author_id_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("warnings", "api-latency", "risk", "Ask \uff55\uff53\uff52\uff3f\uff18\uff46\uff13\uff4b\uff12"))

        self.assertIn("author id", message)

    def test_text_that_grows_over_300_characters_when_normalized_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.risk", self.rejection(changed("warnings", "api-latency", "risk", "\u337f" * 300)))

    def test_text_of_300_characters_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("warnings", "api-latency", "risk", "x" * 300)))

    def test_text_with_a_control_character_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.risk", self.rejection(changed("warnings", "api-latency", "risk", "line one\nline two")))

    def test_details_topic_with_markup_is_rejected_with_its_key_path(self):
        document = make_judgment()
        document["details"]["<Database>"] = document["details"].pop("Database")

        message = self.rejection(document)

        self.assertIn("details. Database : must not contain", message)

    def test_text_with_a_closing_angle_bracket_is_rejected(self):
        self.assertIn("must not contain", self.rejection(changed("warnings", "api-latency", "risk", "a > b")))

    def test_text_with_an_at_sign_is_rejected(self):
        self.assertIn("must not contain", self.rejection(changed("warnings", "api-latency", "risk", "ping @team")))

    def test_text_with_a_url_scheme_is_rejected(self):
        self.assertIn("must not contain", self.rejection(changed("warnings", "api-latency", "risk", "see https://example.test")))

    def test_text_with_a_chat_author_id_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("decisions", 0, "decision", f"Ask {AUTHOR} to resize"))

        self.assertIn("decisions[0].decision", message)
        self.assertIn("author id", message)

    def test_text_with_an_email_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("highlights", 0, "text", "Mail jane.doe@example.test"))

        self.assertIn("highlights[0].text", message)
        self.assertIn("must not contain", message)

    def test_author_ids_of_another_run_pass(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("warnings", "api-latency", "risk", "usr_other9 is not an author here")))

    def authored(self, authors, text):
        features_doc = make_features()
        features_doc["authors"] = authors
        return features_doc, changed("warnings", "api-latency", "risk", text)

    def assert_author_rejected(self, authors, text):
        message = self.rejection(*reversed(self.authored(authors, text)))

        self.assertIn("warnings.api-latency.risk: must not hold a chat author id", message)

    def assert_author_passes(self, authors, text):
        self.assertIsNone(tribe_judgment.check(*self.authored(authors, text)))

    def test_short_author_id_is_rejected_as_a_whole_token(self):
        self.assert_author_rejected(["ab1"], "Ask ab1 to look")

    def test_short_author_id_inside_a_longer_word_passes(self):
        self.assert_author_passes(["ab1"], "The tab1e and ab12 stay")

    def test_digit_only_author_id_is_rejected_as_a_whole_token(self):
        self.assert_author_rejected(["4821937"], "Ticket 4821937 is open")

    def test_digit_only_author_id_inside_a_longer_number_passes(self):
        self.assert_author_passes(["4821937"], "Build 14821937 and 48219370 pass")

    def test_author_id_next_to_punctuation_is_rejected(self):
        self.assert_author_rejected(["ab1"], "Ask (ab1), then ab1-lead")

    def test_author_id_is_matched_literally(self):
        self.assert_author_passes(["a.b"], "The axb token stays")

    def test_author_id_with_a_dot_is_rejected(self):
        self.assert_author_rejected(["a.b"], "Ask a.b to look")

    def test_author_id_is_matched_case_sensitively(self):
        self.assert_author_passes(["ab1"], "Ask AB1 to look")

    def test_empty_author_id_is_ignored(self):
        self.assert_author_passes([""], "Anything goes")


class RecordCiteTest(CheckTestCase):
    def evidence_citing(self, *cites):
        return changed("warnings", "api-latency", "evidence", [{"claim": "Users report slow pages", "cites": list(cites)}])

    def test_record_cite_naming_a_document_link_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), self.evidence_citing({"source": "tracker", "link": ISSUE_LINK})))

    def test_record_cite_naming_the_link_of_a_second_chat_document_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), self.evidence_citing({"source": "chat", "link": MESSAGE_LINK})))

    def test_record_cite_naming_a_link_stored_with_the_warning_passes(self):
        document = changed("warnings", "db-capacity", "evidence", [{"claim": "Still full", "cites": [CPU_CITE, OLD_CITE]}])

        self.assertIsNone(tribe_judgment.check(make_features(), document))

    def test_record_cite_naming_a_link_of_another_source_is_rejected_with_its_key_path(self):
        message = self.rejection(self.evidence_citing({"source": "tracker", "link": MESSAGE_LINK}))

        self.assertIn("warnings.api-latency.evidence[0].cites[0].source", message)

    def test_record_cite_naming_a_stored_link_under_another_source_is_rejected(self):
        document = changed("warnings", "db-capacity", "evidence", [{"claim": "Still full", "cites": [CPU_CITE, {"source": "tracker", "link": OLD_LINK}]}])

        self.assertIn("warnings.db-capacity.evidence[0].cites[1].source", self.rejection(document))

    def test_record_cite_naming_a_link_found_only_in_a_record_text_is_rejected_with_its_key_path(self):
        message = self.rejection(self.evidence_citing({"source": "tracker", "link": HIDDEN_LINK}))

        self.assertIn("warnings.api-latency.evidence[0].cites[0].link", message)

    def test_evidence_without_cites_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("warnings", "api-latency", "evidence", [{"claim": "Likely", "cites": []}]))

        self.assertIn("warnings.api-latency.evidence[0].cites: expected at least 1 cite", message)

    def test_detail_without_cites_is_rejected_with_its_key_path(self):
        self.assertIn("details.Database[0].cites: expected at least 1 cite", self.rejection(changed("details", "Database", 0, "cites", [])))

    def test_correction_without_cites_is_rejected_with_its_key_path(self):
        self.assertIn("corrections[0].cites: expected at least 1 cite", self.rejection(changed("corrections", 0, "cites", [])))

    def test_highlight_without_cites_is_rejected_with_its_key_path(self):
        self.assertIn("highlights[0].cites: expected at least 1 cite", self.rejection(changed("highlights", 0, "cites", [])))

    def test_record_cite_naming_no_known_link_is_rejected_with_its_key_path(self):
        message = self.rejection(self.evidence_citing({"source": "chat", "link": "https://chat.example.test/t/404"}))

        self.assertIn("warnings.api-latency.evidence[0].cites[0].link", message)

    def test_record_cite_naming_a_link_stored_with_another_warning_is_rejected(self):
        message = self.rejection(self.evidence_citing(OLD_CITE))

        self.assertIn("warnings.api-latency.evidence[0].cites[0].link", message)

    def test_cite_with_neither_a_link_nor_a_feature_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.evidence[0].cites[0]", self.rejection(self.evidence_citing({"source": "chat"})))

    def test_cite_with_both_a_link_and_a_feature_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.api-latency.evidence[0].cites[0]", self.rejection(self.evidence_citing({**MESSAGE_CITE, **CPU_CITE})))

    def test_record_cite_in_details_naming_no_known_link_is_rejected_with_its_key_path(self):
        document = changed("details", "Database", 0, "cites", [{"source": "tracker", "link": "https://tracker.example.test/404"}])

        self.assertIn("details.Database[0].cites[0].link", self.rejection(document))

    def test_record_cite_in_corrections_naming_no_known_link_is_rejected_with_its_key_path(self):
        document = changed("corrections", 0, "cites", [{"source": "tracker", "link": "https://tracker.example.test/404"}])

        self.assertIn("corrections[0].cites[0].link", self.rejection(document))

    def test_record_cite_in_details_naming_a_link_stored_with_any_warning_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("details", "Database", 0, "cites", [OLD_CITE])))

    def test_record_cite_in_corrections_naming_a_link_stored_with_any_warning_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("corrections", 0, "cites", [OLD_CITE])))

    def test_record_cite_in_highlights_naming_a_link_stored_with_any_warning_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("highlights", 0, "cites", [OLD_CITE])))

    def test_record_cite_in_corrections_naming_a_stored_link_under_another_source_is_rejected(self):
        document = changed("corrections", 0, "cites", [{"source": "tracker", "link": OLD_LINK}])

        self.assertIn("corrections[0].cites[0].source", self.rejection(document))

    def test_record_cite_in_highlights_naming_no_known_link_is_rejected_with_its_key_path(self):
        document = changed("highlights", 0, "cites", [{"source": "tracker", "link": "https://tracker.example.test/404"}])

        self.assertIn("highlights[0].cites[0].link", self.rejection(document))


class FeatureCiteTest(CheckTestCase):
    def evidence_citing(self, *cites):
        return changed("warnings", "db-capacity", "evidence", [{"claim": "CPU is at 90", "cites": list(cites)}])

    def test_feature_cite_with_an_equal_value_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), self.evidence_citing(CPU_CITE)))

    def test_feature_cite_with_a_float_value_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), self.evidence_citing({"feature": "cpu", "name": "latest", "value": 85.5})))

    def test_feature_cite_with_a_value_that_differs_is_rejected_with_its_key_path(self):
        message = self.rejection(self.evidence_citing({"feature": "cpu", "name": "value", "value": 91}))

        self.assertIn("warnings.db-capacity.evidence[0].cites[0].value", message)
        self.assertIn("cited 91, the features hold 90", message)

    def test_feature_cite_with_a_value_of_another_type_is_rejected(self):
        self.assertIn("cites[0].value", self.rejection(self.evidence_citing({"feature": "cpu", "name": "stale", "value": 0})))

    def test_feature_cite_with_a_missing_value_is_rejected_with_its_key_path(self):
        self.assertIn("warnings.db-capacity.evidence[0].cites[0].value", self.rejection(self.evidence_citing(CPU_STORED_CITE)))

    def test_feature_cite_of_a_document_absent_from_the_features_is_rejected_with_its_key_path(self):
        message = self.rejection(self.evidence_citing({"feature": "memory", "name": "value", "value": 90}))

        self.assertIn("warnings.db-capacity.evidence[0].cites[0].feature", message)

    def test_feature_cite_naming_markup_is_quoted_without_it(self):
        message = self.rejection(self.evidence_citing({"feature": "cpu", "name": "<script>", "value": 90}))

        self.assertIn("cites[0].name: cpu has no value  script ", message)

    def test_feature_cite_of_a_name_absent_from_the_document_is_rejected_with_its_key_path(self):
        message = self.rejection(self.evidence_citing({"feature": "cpu", "name": "peak", "value": 90}))

        self.assertIn("warnings.db-capacity.evidence[0].cites[0].name", message)

    def test_feature_cite_in_details_with_a_value_that_differs_is_rejected_with_its_key_path(self):
        document = changed("details", "Database", 0, "cites", [{"feature": "cpu", "name": "value", "value": 12}])

        self.assertIn("details.Database[0].cites[0].value", self.rejection(document))

    def test_feature_cite_in_highlights_with_a_value_that_differs_is_rejected_with_its_key_path(self):
        document = changed("highlights", 0, "cites", [{"feature": "cpu", "name": "value", "value": 12}])

        self.assertIn("highlights[0].cites[0].value", self.rejection(document))


class ConfidenceTest(CheckTestCase):
    def test_measured_warning_without_a_feature_cite_is_rejected_with_its_key_path(self):
        document = changed("warnings", "db-capacity", "evidence", [{"claim": "Reported", "cites": [OLD_CITE]}])

        message = self.rejection(document)

        self.assertIn("warnings.db-capacity.evidence", message)
        self.assertIn("measured", message)

    def test_measured_warning_with_a_feature_cite_in_a_later_evidence_passes(self):
        evidence = [{"claim": "Reported", "cites": [OLD_CITE]}, {"claim": "Measured", "cites": [CPU_CITE]}]

        self.assertIsNone(tribe_judgment.check(make_features(), changed("warnings", "db-capacity", "evidence", evidence)))

    def test_reported_warning_without_a_record_cite_is_rejected_with_its_key_path(self):
        document = changed("warnings", "api-latency", "evidence", [{"claim": "Measured", "cites": [CPU_CITE]}])

        message = self.rejection(document)

        self.assertIn("warnings.api-latency.evidence", message)
        self.assertIn("reported", message)

    def test_measured_warning_without_any_evidence_is_rejected(self):
        self.assertIn("warnings.db-capacity.evidence", self.rejection(changed("warnings", "db-capacity", "evidence", [])))


class CheckedJudgmentTest(unittest.TestCase):
    def test_stored_cites_derive_from_the_evidence_cites_in_order_without_duplicates(self):
        evidence = [
            {"claim": "CPU is at 90", "cites": [CPU_CITE, OLD_CITE]},
            {"claim": "Still", "cites": [OLD_CITE, CPU_CITE, MESSAGE_CITE]},
        ]
        document = make_judgment()
        document["warnings"]["db-capacity"]["evidence"] = evidence

        checked = tribe_judgment.checked_judgment(make_features(), document)

        self.assertEqual(checked["warnings"]["db-capacity"]["cites"], [CPU_STORED_CITE, OLD_CITE, MESSAGE_CITE])

    def test_feature_cites_lose_their_value_everywhere(self):
        checked = tribe_judgment.checked_judgment(make_features(), make_judgment())

        self.assertEqual(checked["warnings"]["db-capacity"]["evidence"][0]["cites"], [CPU_STORED_CITE, OLD_CITE])
        self.assertEqual(checked["details"]["Database"][0]["cites"], [CPU_STORED_CITE])
        self.assertEqual(checked["corrections"][0]["cites"], [CPU_STORED_CITE])
        self.assertEqual(checked["highlights"][0]["cites"], [CPU_STORED_CITE, {"source": "tracker", "link": ISSUE_LINK}])

    def test_record_cites_keep_their_source_and_link_only(self):
        document = make_judgment()
        document["warnings"]["api-latency"]["evidence"][0]["cites"] = [{**MESSAGE_CITE}]

        checked = tribe_judgment.checked_judgment(make_features(), document)

        self.assertEqual(checked["warnings"]["api-latency"]["cites"], [MESSAGE_CITE])

    def test_warning_without_evidence_stores_an_empty_cite_list(self):
        document = make_judgment()
        document["warnings"]["api-latency"].update(confidence="inferred", evidence=[])

        checked = tribe_judgment.checked_judgment(make_features(), document)

        self.assertEqual(checked["warnings"]["api-latency"]["cites"], [])

    def test_other_fields_pass_through_unchanged(self):
        document = make_judgment()

        checked = tribe_judgment.checked_judgment(make_features(), document)

        self.assertEqual(checked["checks"], document["checks"])
        self.assertEqual(checked["decisions"], document["decisions"])
        self.assertEqual(checked["warnings"]["api-latency"]["title"], "API latency")
        self.assertEqual(checked["warnings"]["api-latency"]["mitigation"], ["Profile the endpoint", "Add a cache"])

    def test_warning_keeps_the_spec_fields_and_its_stored_cites_only(self):
        checked = tribe_judgment.checked_judgment(make_features(), make_judgment())

        self.assertEqual(
            set(checked["warnings"]["api-latency"]),
            {*tribe_judgment.WARNING_FIELDS, "evidence", "cites"},
        )

    def test_replaces_is_kept_when_set(self):
        document = without("warnings", "db-capacity")
        document["warnings"]["api-latency"]["replaces"] = "db-capacity"

        checked = tribe_judgment.checked_judgment(make_features(), document)

        self.assertEqual(checked["warnings"]["api-latency"]["replaces"], "db-capacity")

    def test_null_replaces_is_dropped(self):
        checked = tribe_judgment.checked_judgment(make_features(), changed("warnings", "api-latency", "replaces", None))

        self.assertNotIn("replaces", checked["warnings"]["api-latency"])

    def test_the_judgment_holds_the_seven_sections_only(self):
        checked = tribe_judgment.checked_judgment(make_features(), make_judgment())

        self.assertEqual(set(checked), {"warnings", "checks", "decisions", "details", "corrections", "highlights", "coverage_notes"})

    def test_a_judgment_with_an_unknown_field_is_rejected(self):
        with self.assertRaises(state.Rejected) as caught:
            tribe_judgment.checked_judgment(make_features(), changed("warnings", "api-latency", "extra", "x"))

        self.assertIn("warnings.api-latency.extra: unknown field", str(caught.exception))

    def test_the_input_judgment_is_left_unchanged(self):
        document = make_judgment()
        before = copy.deepcopy(document)

        tribe_judgment.checked_judgment(make_features(), document)

        self.assertEqual(document, before)

    def test_a_rejected_judgment_raises_before_any_output(self):
        with self.assertRaises(state.Rejected) as caught:
            tribe_judgment.checked_judgment(make_features(), without("warnings", "db-capacity"))

        self.assertIn("warnings.db-capacity", str(caught.exception))


def notes(count):
    return [{"source": f"Source {number}", "text": "Not read this run"} for number in range(count)]


class CoverageNoteTest(CheckTestCase):
    def test_a_judgment_without_coverage_notes_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), without("coverage_notes")))

    def test_an_empty_list_of_notes_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("coverage_notes", [])))

    def test_ten_notes_pass(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("coverage_notes", notes(10))))

    def test_eleven_notes_are_rejected_with_their_key_path(self):
        self.assertEqual(self.rejection(changed("coverage_notes", notes(11))), "coverage_notes: expected at most 10 notes, got 11")

    def test_the_cap_is_a_named_constant_of_the_state(self):
        self.assertEqual(tribe_state.COVERAGE_NOTE_CAP, 10)

    def test_notes_that_are_not_a_list_are_rejected_with_their_key_path(self):
        self.assertIn("coverage_notes", self.rejection(changed("coverage_notes", {"source": "Mobile app", "text": "Not read"})))

    def test_a_repeated_source_is_rejected_with_both_key_paths(self):
        document = changed("coverage_notes", [{"source": "Mobile app", "text": "one"}, {"source": "Mobile app", "text": "two"}])

        self.assertEqual(self.rejection(document), "coverage_notes[1].source: same source as coverage_notes[0]")

    def test_a_source_repeated_in_another_case_is_rejected(self):
        document = changed("coverage_notes", [{"source": "Mobile app", "text": "one"}, {"source": "MOBILE APP", "text": "two"}])

        self.assertIn("coverage_notes[1].source: same source", self.rejection(document))

    def test_a_source_repeated_with_other_spacing_is_rejected(self):
        document = changed("coverage_notes", [{"source": "Mobile app", "text": "one"}, {"source": " Mobile   app ", "text": "two"}])

        self.assertIn("coverage_notes[1].source: same source", self.rejection(document))

    def test_a_source_repeated_in_its_normalized_form_is_rejected(self):
        document = changed("coverage_notes", [{"source": "Mobile app", "text": "one"}, {"source": "\uff2dobile app", "text": "two"}])

        self.assertIn("coverage_notes[1].source: same source", self.rejection(document))

    def test_two_different_sources_pass(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("coverage_notes", notes(2))))

    def test_a_source_of_60_characters_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("coverage_notes", 0, "source", "s" * 60)))

    def test_a_source_over_60_characters_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("coverage_notes", 0, "source", "s" * 61))

        self.assertEqual(message, "coverage_notes[0].source: must be at most 60 characters")

    def test_the_source_cap_is_a_named_constant_of_the_state(self):
        self.assertEqual(tribe_state.COVERAGE_SOURCE_CAP, 60)

    def test_a_source_that_grows_over_60_characters_when_normalized_is_rejected(self):
        self.assertIn("coverage_notes[0].source", self.rejection(changed("coverage_notes", 0, "source", "\u337f" * 20)))

    def test_a_source_with_a_chat_author_id_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("coverage_notes", 0, "source", f"Mail of {AUTHOR}"))

        self.assertEqual(message, "coverage_notes[0].source: must not hold a chat author id")

    def test_a_note_text_with_a_chat_author_id_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("coverage_notes", 0, "text", f"Ask {AUTHOR}"))

        self.assertEqual(message, "coverage_notes[0].text: must not hold a chat author id")

    def test_a_note_text_of_300_characters_passes(self):
        self.assertIsNone(tribe_judgment.check(make_features(), changed("coverage_notes", 0, "text", "x" * 300)))

    def test_a_note_with_a_cite_is_rejected_as_an_unknown_field(self):
        message = self.rejection(changed("coverage_notes", 0, "cites", [CPU_CITE]))

        self.assertEqual(message, "coverage_notes[0].cites: unknown field")

    def test_a_note_without_a_text_is_rejected_with_its_key_path(self):
        self.assertIn("coverage_notes[0].text", self.rejection(without("coverage_notes", 0, "text")))

    def test_a_rejection_never_echoes_an_uncapped_source(self):
        message = self.rejection(changed("coverage_notes", 0, "source", "s" * 5000))

        self.assertLess(len(message), 300)
        self.assertNotIn("s" * 20, message)

    def test_the_checked_judgment_keeps_the_notes(self):
        checked = tribe_judgment.checked_judgment(make_features(), make_judgment())

        self.assertEqual(checked["coverage_notes"], [{"source": "Mobile app", "text": "Not read, no connector is configured for it"}])

    def test_the_checked_judgment_holds_an_empty_list_when_the_notes_are_absent(self):
        checked = tribe_judgment.checked_judgment(make_features(), without("coverage_notes"))

        self.assertEqual(checked["coverage_notes"], [])

    def test_the_checked_judgment_copies_the_notes(self):
        document = make_judgment()

        tribe_judgment.checked_judgment(make_features(), document)["coverage_notes"][0]["text"] = "changed"

        self.assertEqual(document["coverage_notes"][0]["text"], "Not read, no connector is configured for it")


class RecordLinkLengthTest(CheckTestCase):
    def test_rejects_a_record_link_the_state_would_reject(self):
        link = "https://chat.example.test/" + "x" * 400
        features_doc = make_features()
        features_doc["keys"]["message-2"]["link"] = link
        evidence = [{"claim": "Users report slow pages", "cites": [{"source": "chat", "link": link}]}]
        document = changed("warnings", "api-latency", "evidence", evidence)
        self.assertRegex(self.rejection(document, features_doc), r"cites\[0\]\.link$")


if __name__ == "__main__":
    unittest.main()
