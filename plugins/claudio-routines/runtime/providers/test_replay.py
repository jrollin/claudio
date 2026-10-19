import os
import unittest
from unittest import mock

import state
from providers import _http, _replay, datadog, datadog_support, github, jira, notion, slack, slack_support, test_github, test_jira, test_notion, test_slack

PATH = "/v1/things"
BASE = "https://api.example.test"
PREFIXED = "/prefix"
PROVIDER = {"adapter": "example", "api": {"base_url": BASE + PREFIXED, "credentials": {"token": "EXAMPLE_TOKEN"}}}
NAME = "things"


def record(method="GET", path=PREFIXED + PATH, query="", body=None, status=200, link=None, response=None, error=None):
    return {"method": method, "path": path, "query": query, "body": body, "status": status, "link": link, "response": response, "error": error}


def error_record(error_class, message, status=None, **fields):
    return record(status=status, error={"class": error_class, "message": message, "status": status}, **fields)


def replay_client(*records):
    return _replay.ReplayClient(PROVIDER, NAME, records)


def outcome(adapter, client, source, window, cursor, entries):
    try:
        return state.dump(adapter.fetch(source, window, cursor, entries, client))
    except _http.SourceUnreadable as error:
        return type(error), str(error), error.status


class ProviderReplayTest(unittest.TestCase):
    def assert_replays(self, adapter, client, provider, source, window, cursor, entries=()):
        records = []
        client.recorder = records.append
        read = outcome(adapter, client, source, window, cursor, list(entries))
        replay = _replay.ReplayClient(provider, source["name"], records)
        self.assertGreater(len(records), 0)
        self.assertEqual(outcome(adapter, replay, source, window, cursor, list(entries)), read)
        return read

    def test_replays_a_chat_fetch(self):
        opener = slack_support.FakeOpener([test_slack.ok(name) for name in test_slack.SHARED_OVER_API])
        client = slack_support.client(opener)
        self.assert_replays(slack, client, slack_support.PROVIDER, slack_support.SOURCE, slack_support.WINDOW, slack_support.STORED)

    def test_replays_a_document_store_fetch(self):
        opener = test_notion.FakeOpener([test_notion.ok(name) for name in test_notion.FULL_PAGE])
        client = test_notion.client(opener)
        self.assert_replays(notion, client, test_notion.PROVIDER, test_notion.SOURCE, test_notion.WINDOW, test_notion.STORED)

    def test_replays_an_issue_tracker_fetch(self):
        opener = test_jira.FakeOpener([test_jira.ok(name) for name in test_jira.SHARED_OVER_API])
        client = test_jira.client(opener)
        self.assert_replays(jira, client, test_jira.PROVIDER, test_jira.SOURCE, test_jira.WINDOW, test_jira.STORED)

    def test_replays_an_observability_fetch(self):
        outcomes = [datadog_support.ok("monitor_alert.json"), datadog_support.ok("monitor_ok.json"), datadog_support.ok("events_empty.json")]
        client = datadog_support.client(datadog_support.FakeOpener(outcomes))
        entries = [datadog_support.QUEUE, datadog_support.CHECKOUT]
        self.assert_replays(
            datadog, client, datadog_support.PROVIDER, datadog_support.MONITORS, datadog_support.WINDOW, datadog_support.FRESH, entries
        )

    def test_replays_an_observability_metric_post(self):
        client = datadog_support.client(datadog_support.FakeOpener([datadog_support.ok("scalar.json")]))
        self.assert_replays(
            datadog, client, datadog_support.PROVIDER, datadog_support.METRICS, datadog_support.WINDOW, datadog_support.NO_METRICS, [datadog_support.P95]
        )

    def test_replays_a_code_host_fetch_with_its_next_links(self):
        pages = [test_github.body(test_github.full_pulls(101), link=test_github.next_link(2)), test_github.body([test_github.pull(49, "2026-09-04T15:00:00Z")])]
        opener = test_github.FakeOpener([*pages, test_github.body([])])
        source = {**test_github.SOURCE, "repos": ["acme/app"]}
        self.assert_replays(github, test_github.client(opener), test_github.PROVIDER, source, test_github.WINDOW, test_github.STORED)

    def test_replays_a_code_host_search_fetch_with_its_pull_request_activity(self):
        outcomes = [
            test_github.search_page(test_github.search_item(7)),
            test_github.body([test_github.comment("erin-dev")]),
            test_github.body([test_github.review("erin-dev")]),
            test_github.body([]),
        ]
        client = test_github.client(test_github.FakeOpener(outcomes))
        read = self.assert_replays(github, client, test_github.PROVIDER, test_github.SEARCH_SOURCE, test_github.WINDOW, test_github.STORED)
        self.assertIn(b'"activity"', read)

    def test_replays_a_document_store_fetch_by_editor(self):
        outcomes = [test_notion.search_page(test_notion.hit(test_notion.ONE)), *test_notion.api_read(test_notion.ONE)]
        client = test_notion.client(test_notion.FakeOpener(outcomes))
        read = self.assert_replays(notion, client, test_notion.PROVIDER, test_notion.EDITED_SOURCE, test_notion.EDITED_WINDOW, None)
        self.assertIn(test_notion.ONE.encode(), read)

    def test_replays_a_recorded_http_error_to_the_same_failure(self):
        client = test_github.client(test_github.FakeOpener([test_github.status(404)]))
        source = {**test_github.SOURCE, "repos": ["acme/app"]}
        read = self.assert_replays(github, client, test_github.PROVIDER, source, test_github.WINDOW, test_github.STORED)
        self.assertEqual(read, (_http.SourceUnreadable, "repo acme/app not found: HTTP 404 GET /repos/acme/app/pulls", 404))

    def test_replays_a_recorded_partial_read_to_the_same_failure(self):
        client = test_github.client(test_github.FakeOpener([test_github.FakeResponse(b"{}" + b" " * _http.BODY_CAP)]))
        source = {**test_github.SOURCE, "repos": ["acme/app"]}
        read = self.assert_replays(github, client, test_github.PROVIDER, source, test_github.WINDOW, test_github.STORED)
        self.assertEqual(read, (_http.PartialRead, "partial: response over 10 MB", None))


class RequestCheckTest(unittest.TestCase):
    def test_serves_the_response_of_a_matching_get(self):
        client = replay_client(record(query="page=1&q=a+b", response={"n": 1}))
        self.assertEqual(client.get(PATH, {"page": 1, "q": "a b"}), {"n": 1})

    def test_serves_the_response_of_a_matching_post(self):
        client = replay_client(record("POST", body={"q": ["x"]}, response={"n": 2}))
        self.assertEqual(client.post(PATH, {"q": ("x",)}), {"n": 2})

    def test_serves_the_response_of_a_matching_get_url(self):
        client = replay_client(record(query="page=2", response={"n": 3}))
        self.assertEqual(client.get_url(BASE + PREFIXED + PATH + "?page=2"), {"n": 3})

    def test_serves_the_records_in_call_order(self):
        client = replay_client(record(response=1), record(response=2))
        self.assertEqual([client.get(PATH), client.get(PATH)], [1, 2])

    def test_a_different_query_fails_naming_the_source_the_call_and_the_request(self):
        client = replay_client(record(response=1), record(query="page=1"))
        client.get(PATH)
        with self.assertRaises(_replay.ReplayMismatch) as caught:
            client.get(PATH, {"page": 2})
        self.assertEqual(str(caught.exception), f"source {NAME} call 2 GET {PREFIXED + PATH}: request differs from its record in query")

    def test_a_different_body_fails(self):
        client = replay_client(record("POST", body={"q": "x"}))
        with self.assertRaises(_replay.ReplayMismatch) as caught:
            client.post(PATH, {"q": "y"})
        self.assertTrue(str(caught.exception).endswith("request differs from its record in body"))

    def test_a_different_method_and_path_fail_naming_both(self):
        client = replay_client(record("POST", path="/other"))
        with self.assertRaises(_replay.ReplayMismatch) as caught:
            client.get(PATH)
        self.assertTrue(str(caught.exception).endswith("request differs from its record in method, path"))

    def test_a_different_base_url_path_fails(self):
        client = _replay.ReplayClient({"api": {"base_url": BASE}}, NAME, [record()])
        with self.assertRaises(_replay.ReplayMismatch):
            client.get(PATH)

    def test_a_call_past_the_last_record_fails_naming_the_source_the_call_and_the_request(self):
        client = replay_client(record(response=1))
        client.get(PATH)
        with self.assertRaises(_replay.ReplayMismatch) as caught:
            client.get(PATH)
        self.assertEqual(str(caught.exception), f"source {NAME} call 2 GET {PREFIXED + PATH}: no record, 1 recorded")

    def test_a_call_with_no_record_at_all_fails(self):
        with self.assertRaises(_replay.ReplayMismatch) as caught:
            replay_client().get(PATH)
        self.assertEqual(str(caught.exception), f"source {NAME} call 1 GET {PREFIXED + PATH}: no record, 0 recorded")

    def test_a_mismatch_leaves_the_query_values_out_of_the_message(self):
        client = replay_client(record(query="q=secret-text"))
        with self.assertRaises(_replay.ReplayMismatch) as caught:
            client.get(PATH, {"q": "other-text"})
        self.assertNotIn("text", str(caught.exception))


class ResponseHeadersTest(unittest.TestCase):
    LINK = "<" + BASE + PATH + "?page=2>; rel=next"

    def test_holds_the_link_header_of_the_record(self):
        client = replay_client(record(link=self.LINK))
        client.get(PATH)
        self.assertEqual(client.response_headers.get("Link"), self.LINK)

    def test_holds_nothing_for_a_record_without_a_link(self):
        client = replay_client(record(link=self.LINK), record())
        client.get(PATH)
        client.get(PATH)
        self.assertIsNone(client.response_headers)

    def test_holds_nothing_before_the_first_call(self):
        self.assertIsNone(replay_client().response_headers)


class RecordedErrorTest(unittest.TestCase):
    def raised(self, *records):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            replay_client(*records).get(PATH)
        return caught.exception

    def test_raises_a_recorded_http_error_with_its_message_and_status(self):
        error = self.raised(error_record("SourceUnreadable", "HTTP 404 GET " + PATH, 404))
        self.assertEqual((type(error), str(error), error.status), (_http.SourceUnreadable, "HTTP 404 GET " + PATH, 404))

    def test_raises_a_recorded_error_without_a_status(self):
        error = self.raised(error_record("SourceUnreadable", "GET " + PATH + ": TimeoutError"))
        self.assertEqual((type(error), str(error), error.status), (_http.SourceUnreadable, "GET " + PATH + ": TimeoutError", None))

    def test_raises_a_recorded_partial_read_with_its_message(self):
        error = self.raised(error_record("PartialRead", "partial: response over 10 MB"))
        self.assertEqual((type(error), str(error), error.why), (_http.PartialRead, "partial: response over 10 MB", "response over 10 MB"))

    def test_raises_recorded_missing_credentials(self):
        error = self.raised(error_record("CredentialsMissing", "credentials missing: EXAMPLE_TOKEN"))
        self.assertEqual((type(error), str(error)), (_http.CredentialsMissing, "credentials missing: EXAMPLE_TOKEN"))

    def test_checks_the_request_before_raising_the_recorded_error(self):
        with self.assertRaises(_replay.ReplayMismatch):
            replay_client(error_record("SourceUnreadable", "HTTP 404", 404, path="/other")).get(PATH)

    def test_an_error_class_outside_the_three_fails_naming_it(self):
        with self.assertRaises(_replay.ReplayMismatch) as caught:
            replay_client(error_record("RuntimeError", "boom")).get(PATH)
        self.assertEqual(str(caught.exception), f"source {NAME} call 1 GET {PREFIXED + PATH}: recorded error class RuntimeError is not replayable")


class ForbiddenEnvironment(dict):
    def __getitem__(self, key):
        raise AssertionError(f"environment read: {key}")

    def get(self, key, default=None):
        raise AssertionError(f"environment read: {key}")

    def __iter__(self):
        raise AssertionError("environment listed")

    def items(self):
        raise AssertionError("environment listed")


class EnvironmentTest(unittest.TestCase):
    def test_builds_and_replays_without_reading_the_environment(self):
        with mock.patch.object(os, "environ", ForbiddenEnvironment()):
            value = replay_client(record(response=1)).get(PATH)
        self.assertEqual(value, 1)

    def test_a_link_to_another_host_is_refused_as_in_a_run(self):
        with self.assertRaises(_http.SourceUnreadable):
            replay_client(record(response=1)).get_url("https://other.example.test" + PATH)


if __name__ == "__main__":
    unittest.main()
