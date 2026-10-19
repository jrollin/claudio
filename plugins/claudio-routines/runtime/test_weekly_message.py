import copy
import unittest

from test_weekly import (
    DM_ITEM, ISSUE_KEY, OWNER_NAME, PAGE_KEY, PR_KEY, THREAD_ITEM, WeeklyCase,
    make_features_document, make_judgment, make_source_rows, make_summary, make_window,
)

TITLE = "**Weekly status, week of Mon 12 Oct**"
ISSUE_LINK = "[PROJ-12](https://tracker.example.test/browse/PROJ-12)"
PR_LINK = "[service#7](https://code.example.test/example-org/service/pull/7)"
PAGE_LINK = "[Launch plan for the autumn release](https://docs.example.test/page-ab12)"
THREAD_LINK = "[thread](https://chat.example.test/archives/C111111/p1791990000000100)"
DM_LINK = "[DM](https://chat.example.test/archives/D111111/p1791990000000200)"
FULL_MESSAGE = f"""{TITLE}

**Key accomplishments**
- Fixed the checkout failure and the export. ({ISSUE_LINK}, {PR_LINK})

**Decisions**
- Ship the export behind a flag. ({PAGE_LINK})

**Still open / next week**
- Review the rollout plan. (owner: {OWNER_NAME}) ({THREAD_LINK})

_Sources checked: issue tracker, code host, chat, document store._
"""


class MessageCase(WeeklyCase):
    def message(self, judgment=None, features=None, summary=None):
        features = features or make_features_document()
        self.write("features.json", features)
        self.write("summary.json", summary or make_summary(judgment, features))
        return self.run_weekly("message", "--summary", self.path("summary.json"), "--features", self.path("features.json"), "--out", self.path("message.md"))

    def rendered(self, **options):
        code, _, err = self.message(**options)
        self.assertEqual((code, err), (0, ""))
        with open(self.path("message.md"), encoding="utf-8") as handle:
            return handle.read()

    def section(self, heading, **options):
        lines = self.rendered(**options).split("\n\n")
        return next(block for block in lines if block.startswith(f"**{heading}**")).split("\n")[1:]

    def sources_block(self, **options):
        return self.rendered(**options).rstrip("\n").split("\n\n")[-1].split("\n")

    def judged(self, **sections):
        judgment = make_judgment()
        judgment.update(sections)
        return judgment


class LayoutTest(MessageCase):
    def test_renders_the_title_the_three_sections_in_order_and_the_sources_line(self):
        self.assertEqual(self.rendered(), FULL_MESSAGE)

    def test_the_title_names_the_monday_of_the_week(self):
        features = make_features_document()
        features["week_start"] = "2026-10-14"

        self.assertEqual(self.rendered(features=features).split("\n")[0], TITLE)

    def test_the_title_pads_the_day_of_the_month(self):
        features = make_features_document()
        features["week_start"] = "2026-11-02"

        self.assertEqual(self.rendered(features=features).split("\n")[0], "**Weekly status, week of Mon 02 Nov**")

    def test_the_message_ends_with_one_line_break(self):
        self.assertTrue(self.rendered().endswith("._\n"))



class EmptySectionTest(MessageCase):
    def test_no_decision_shows_none_recorded(self):
        self.assertEqual(self.section("Decisions", judgment=self.judged(decisions=[])), ["- None recorded"])

    def test_no_accomplishment_shows_none(self):
        features = make_features_document(items={})

        self.assertEqual(self.section("Key accomplishments", judgment={"schema": 1, "accomplishments": [], "decisions": [], "open": []}, features=features), ["- None"])

    def test_nothing_open_shows_none(self):
        self.assertEqual(self.section("Still open / next week", judgment=self.judged(open=[])), ["- None"])


class BulletTest(MessageCase):
    def test_a_bullet_lists_its_links_in_cite_order(self):
        judgment = self.judged(decisions=[{"text": "Order check.", "cites": [PR_KEY, ISSUE_KEY]}])

        self.assertEqual(self.section("Decisions", judgment=judgment), [f"- Order check. ({PR_LINK}, {ISSUE_LINK})"])

    def test_an_open_bullet_shows_its_owner_before_the_links(self):
        self.assertEqual(self.section("Still open / next week"), [f"- Review the rollout plan. (owner: {OWNER_NAME}) ({THREAD_LINK})"])

    def test_an_open_bullet_without_owner_shows_no_owner(self):
        judgment = self.judged(open=[{"text": "Review the plan.", "owner": None, "cites": [THREAD_ITEM]}])

        self.assertEqual(self.section("Still open / next week", judgment=judgment), [f"- Review the plan. ({THREAD_LINK})"])

    def test_a_thread_with_its_channel_name_is_labelled_with_the_channel(self):
        features = make_features_document()
        features["items"][THREAD_ITEM]["channel_name"] = "#export"

        self.assertEqual(self.section("Still open / next week", features=features), [f"- Review the rollout plan. (owner: {OWNER_NAME}) ({THREAD_LINK.replace('[thread]', '[thread in #export]')})"])

    def test_a_direct_message_is_labelled_dm(self):
        judgment = self.judged(decisions=[{"text": "Answered.", "cites": [DM_ITEM]}])

        self.assertEqual(self.section("Decisions", judgment=judgment), [f"- Answered. ({DM_LINK})"])

    def test_a_page_is_labelled_with_the_first_six_words_of_its_title(self):
        self.assertIn(PAGE_LINK, self.section("Decisions")[0])

    def test_a_pull_request_is_labelled_with_its_repository_name_and_number(self):
        self.assertIn(PR_LINK, self.section("Key accomplishments")[0])

    def test_text_markup_is_escaped(self):
        judgment = self.judged(decisions=[{"text": "Use **bold** and [a](b) here.", "cites": [ISSUE_KEY]}])

        self.assertEqual(self.section("Decisions", judgment=judgment), [f"- Use * *bold* * and [a] (b) here. ({ISSUE_LINK})"])

    def test_a_label_with_a_closing_bracket_cannot_end_the_link_text(self):
        features = make_features_document()
        features["items"][PAGE_KEY]["title"] = "Plan](https://evil.example.test) now"

        line = self.section("Decisions", features=features)[0]

        self.assertNotIn("](https://evil", line)

    def test_a_link_without_a_web_scheme_shows_its_label_only(self):
        features = make_features_document()
        features["items"][ISSUE_KEY]["link"] = "javascript:alert(1)"

        line = self.section("Key accomplishments", features=features)[0]

        self.assertEqual(line, f"- Fixed the checkout failure and the export. (PROJ-12, {PR_LINK})")

    def test_a_link_with_parentheses_is_escaped(self):
        features = make_features_document()
        features["items"][ISSUE_KEY]["link"] = "https://tracker.example.test/browse/PROJ-12?q=(a b)"

        line = self.section("Key accomplishments", features=features)[0]

        self.assertIn("[PROJ-12](https://tracker.example.test/browse/PROJ-12?q=%28a%20b%29)", line)

    def test_a_cite_missing_from_the_features_is_an_input_error_naming_the_key_path(self):
        features = make_features_document()
        del features["items"][PR_KEY]

        code, _, err = self.message(features=features, summary=make_summary())

        self.assertEqual(code, 2)
        self.assertIn(f"accomplishments[0].cites[1]: {PR_KEY} is not an item of the features", err)


class SourcesTest(MessageCase):
    def test_a_role_with_no_source_read_is_left_out(self):
        features = make_features_document(items={}, sources=make_source_rows(code={"read": False, "reason": "http 503"}, docs={"read": False, "reason": "no collection"}))
        judgment = {"schema": 1, "accomplishments": [], "decisions": [], "open": []}

        last = self.sources_block(judgment=judgment, features=features)

        self.assertEqual(last[0], "_Sources checked: issue tracker, chat._")

    def test_each_source_not_read_has_a_line_with_its_reason(self):
        features = make_features_document(items={}, sources=make_source_rows(code={"read": False, "reason": "http 503"}, docs={"read": False, "reason": "no collection"}))
        judgment = {"schema": 1, "accomplishments": [], "decisions": [], "open": []}

        last = self.sources_block(judgment=judgment, features=features)

        self.assertEqual(last[1:], ["Not read: code (http 503)", "Not read: docs (no collection)"])

    def test_the_recap_counts_as_chat_when_it_fed_items(self):
        features = make_features_document(sources=make_source_rows(chat={"read": False, "reason": "no collection"}))

        last = self.sources_block(features=features)

        self.assertEqual(last, ["_Sources checked: issue tracker, code host, chat, document store._", "Not read: chat (no collection)"])

    def test_no_source_read_says_none(self):
        features = make_features_document(items={}, sources=[])
        judgment = {"schema": 1, "accomplishments": [], "decisions": [], "open": []}

        self.assertTrue(self.rendered(judgment=judgment, features=features).endswith("_Sources checked: none._\n"))

    def test_a_source_not_read_without_reason_shows_its_name_only(self):
        features = make_features_document(sources=make_source_rows(code={"read": False, "reason": None}))

        self.assertTrue(self.rendered(features=features).endswith("Not read: code\n"))

    def test_a_reason_is_escaped(self):
        features = make_features_document(sources=make_source_rows(code={"read": False, "reason": "see **x** [a](b)"}))

        self.assertTrue(self.rendered(features=features).endswith("Not read: code (see * *x* * [a] (b))\n"))


class InputTest(MessageCase):
    def test_a_summary_missing_a_key_is_an_input_error_naming_the_key_path(self):
        summary = make_summary()
        del summary["decisions"]

        code, _, err = self.message(summary=summary)

        self.assertEqual(code, 2)
        self.assertIn("decisions", err)

    def test_features_missing_a_key_are_an_input_error_naming_the_key_path(self):
        features = copy.deepcopy(make_features_document())
        del features["items"][ISSUE_KEY]["kind"]

        code, _, err = self.message(features=features, summary=make_summary())

        self.assertEqual(code, 2)
        self.assertIn(f"items.{ISSUE_KEY}.kind", err)

    def test_a_cite_without_an_item_key_shape_is_an_input_error(self):
        judgment = self.judged(decisions=[{"text": "Odd.", "cites": ["other:1"]}])

        code, _, err = self.message(summary=make_summary(judgment))

        self.assertEqual(code, 2)
        self.assertIn("decisions[0].cites[0]", err)


if __name__ == "__main__":
    unittest.main()
