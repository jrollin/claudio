import base64
import calendar
import email.message
import io
import json
import pathlib
import re
import time
import unittest
import urllib.error

import roles
import state
from providers import _http, jira

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "jira"
BASE = "https://example.atlassian.net"
LINKS = "https://site.example.atlassian.net"
EMAIL_VAR = "TRACKER_EMAIL"
TOKEN_VAR = "TRACKER_TOKEN"
EMAIL_VALUE = "-".join(["analyst", "sentinel"]) + "@" + "example.test"
TOKEN_VALUE = "-".join(["token", "sentinel"])
ACCOUNT = "-".join(["account", "sentinel"])
PROVIDER = {
    "adapter": "jira",
    "links_base": LINKS,
    "api": {"base_url": BASE, "credentials": {"email": EMAIL_VAR, "token": TOKEN_VAR}},
}
SEARCH = "/rest/api/3/search/jql"
FILTER = str(10000 + 42)
QUERY = "labels = digest"
CONNECTOR = "tracker-connector"
TRANSPORT = {"cloud": "api", "local": "api"}
SOURCE = {
    "name": "issues",
    "provider": "tracker",
    "transport": TRANSPORT,
    "filter": FILTER,
    "query": QUERY,
    "open_sprints": True,
    "provider_config": PROVIDER,
}
RELAY_SOURCE = {**SOURCE, "transport": {"cloud": "mcp", "local": "mcp"}}
JQL = "project = PROJ AND type in (Bug, Task)"
JQL_SOURCE = {**{key: value for key, value in SOURCE.items() if key not in ("filter", "open_sprints")}, "jql": JQL}
RELAY_JQL_SOURCE = {**JQL_SOURCE, "transport": RELAY_SOURCE["transport"]}
FIELDS = ["summary", "issuetype", "status", "priority", "created", "updated"]
STORED = {"updated": "2026-10-16T15:00:00Z"}
STORED_UPDATED = "2026-10-16T15:00:00Z"
UPDATED_JQL = f'filter = {FILTER} AND ({QUERY}) AND updated >= "2026-10-15 14:00" ORDER BY key ASC'
JQL_UPDATED_JQL = f'({JQL}) AND ({QUERY}) AND updated >= "2026-10-15 14:00" ORDER BY key ASC'
SPRINT_JQL = f"filter = {FILTER} AND sprint in openSprints() ORDER BY key ASC"
SHARED_OVER_API = ("api_updated_page_1.json", "api_updated_page_2.json", "api_sprint.json")
SHARED_OVER_RELAY = ("relay_updated_page_1.json", "relay_updated_page_2.json", "relay_sprint.json")
UPDATED_ONLY_OVER_API = SHARED_OVER_API[:2]
UPDATED_ONLY_OVER_RELAY = SHARED_OVER_RELAY[:2]


def ts(text):
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))


WINDOW = {
    "from_ts": ts("2026-10-16T15:00:00Z"),
    "to_ts": ts("2026-10-16T18:00:00Z"),
    "first_read_from_ts": ts("2026-10-12T00:00:00Z"),
}


def expected(key, title, kind, status, priority, created, updated, in_open_sprint):
    return {
        "key": key,
        "title": title,
        "type": kind,
        "status": status,
        "priority": priority,
        "created": created,
        "updated": updated,
        "link": f"{LINKS}/browse/{key}",
        "in_open_sprint": in_open_sprint,
    }


EXPECTED = [
    expected("PROJ-12", "Fix the login redirect", "Bug", "In Progress", "High", "2026-10-10T07:15:00Z", "2026-10-16T15:38:23Z", True),
    expected("PROJ-21", "Rotate the staging keys", "Task", "To Do", "Low", "2026-10-15T15:00:00Z", "2026-10-16T14:00:00Z", False),
    expected("PROJ-40", "Plan the sprint review", "Task", "To Do", "Medium", "2026-10-01T07:00:00Z", "2026-10-02T08:00:00Z", True),
    expected("PROJ-7", "Import timeout", "Story", "Done", None, "2026-09-28T09:00:00Z", "2026-10-16T14:30:00Z", False),
]
NEWEST = {"updated": "2026-10-16T15:38:23Z"}
PERSON_NAMES = "Sample (Assignee|Reporter)"


class FakeResponse:
    def __init__(self, body):
        self.stream = io.BytesIO(body)
        self.headers = email.message.Message()

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def fixture(name):
    return (FIXTURES / name).read_bytes()


def ok(name):
    return FakeResponse(fixture(name))


def body(value):
    return FakeResponse(json.dumps(value).encode("utf-8"))


def status(code):
    return urllib.error.HTTPError(BASE, code, "status", email.message.Message(), io.BytesIO(fixture(f"error_{code}.json")))


def raw(key, updated, summary="Change", priority="Medium", created="2026-10-01T09:00:00.000+0000"):
    return {
        "id": "id-" + key,
        "key": key,
        "fields": {
            "summary": summary,
            "issuetype": {"name": "Task"},
            "status": {"name": "To Do"},
            "priority": None if priority is None else {"name": priority},
            "created": created,
            "updated": updated,
            "assignee": {"accountId": ACCOUNT, "displayName": "Sample Assignee"},
            "reporter": {"accountId": ACCOUNT, "displayName": "Sample Reporter"},
        },
    }


def page(*items, token=None):
    result = {"issues": list(items), "isLast": token is None}
    return result if token is None else {**result, "nextPageToken": token}


def client(opener, environ=None):
    environ = {EMAIL_VAR: EMAIL_VALUE, TOKEN_VAR: TOKEN_VALUE} if environ is None else environ
    return jira.api_client(PROVIDER, opener=opener, environ=environ, sleep=lambda seconds: None)


def run(*outcomes, source=SOURCE, cursor=STORED):
    opener = FakeOpener(outcomes)
    return opener, jira.fetch(source, WINDOW, cursor, [], client(opener))


def read_shared(source=SOURCE, cursor=STORED):
    return run(*(ok(name) for name in SHARED_OVER_API), source=source, cursor=cursor)


def sent(request):
    return json.loads(request.data)


def unreadable(test, *outcomes, source=SOURCE, cursor=STORED, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        run(*outcomes, source=source, cursor=cursor)
    return caught.exception


def updated_only(*pages, cursor=STORED):
    return run(*(body(item) for item in pages), source={**SOURCE, "open_sprints": False}, cursor=cursor)[1]


def with_sprint(updated, sprint):
    return run(body(page(*updated)), body(page(*sprint)))[1]


def dumped(value):
    return state.dump(value).decode("utf-8")


def issue_of(result, key):
    return next(item for item in result["records"]["issues"] if item["key"] == key)


def collection(result, transport="api"):
    return {
        "schema": 1,
        "source": SOURCE["name"],
        "role": jira.ROLE,
        "provider": "tracker",
        "transport": transport,
        "place": "cloud",
        "window": {"from_ts": WINDOW["from_ts"], "to_ts": WINDOW["to_ts"]},
        "read": True,
        "reason": None,
        **result,
    }


class ClientTest(unittest.TestCase):
    def test_role_is_issue_tracker(self):
        self.assertEqual(jira.ROLE, "issue_tracker")

    def test_sends_the_email_and_token_as_a_basic_header(self):
        opener, _ = read_shared()

        pair = base64.b64encode(f"{EMAIL_VALUE}:{TOKEN_VALUE}".encode("utf-8")).decode("ascii")
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Basic " + pair)

    def test_posts_json_to_the_issue_search(self):
        opener, _ = read_shared()

        request = opener.requests[0]
        self.assertEqual((request.get_method(), request.full_url, request.get_header("Content-type")), ("POST", BASE + SEARCH, "application/json"))

    def test_rejects_a_provider_without_the_token(self):
        provider = {"api": {"base_url": BASE, "credentials": {"email": EMAIL_VAR}}}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            jira.api_client(provider, opener=FakeOpener([]))
        self.assertEqual(str(caught.exception), "api.credentials: must name email and token; missing token")

    def test_missing_variables_make_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            jira.fetch(SOURCE, WINDOW, STORED, [], client(FakeOpener([]), environ={}))
        self.assertEqual(str(caught.exception), "credentials missing: TRACKER_EMAIL, TRACKER_TOKEN")


class QueryTest(unittest.TestCase):
    def test_asks_for_the_filter_issues_updated_since_the_bound_minus_24_hours(self):
        opener, _ = read_shared()

        self.assertEqual(sent(opener.requests[0]), {"jql": UPDATED_JQL, "fields": FIELDS, "maxResults": 100})

    def test_follows_the_next_page_token(self):
        opener, _ = read_shared()

        self.assertEqual(sent(opener.requests[1]), {"jql": UPDATED_JQL, "fields": FIELDS, "maxResults": 100, "nextPageToken": "next-page-2"})

    def test_reads_the_open_sprints_with_no_time_bound_after_the_updated_read(self):
        opener, _ = read_shared()

        self.assertEqual(sent(opener.requests[2]), {"jql": SPRINT_JQL, "fields": FIELDS, "maxResults": 100})

    def test_the_open_sprint_read_ignores_the_query(self):
        opener, _ = read_shared()

        self.assertNotIn(QUERY, sent(opener.requests[2])["jql"])

    def test_reads_no_open_sprint_without_the_option(self):
        opener, _ = run(ok("api_updated_page_1.json"), ok("api_updated_page_2.json"), source={**SOURCE, "open_sprints": False})

        self.assertEqual(len(opener.requests), 2)

    def test_omits_the_query_clause_without_a_query(self):
        source = {key: value for key, value in SOURCE.items() if key != "query"}

        opener, _ = read_shared(source=source)

        self.assertEqual(
            [sent(request)["jql"] for request in (opener.requests[0], opener.requests[2])],
            [f'filter = {FILTER} AND updated >= "2026-10-15 14:00" ORDER BY key ASC', f"filter = {FILTER} AND sprint in openSprints() ORDER BY key ASC"],
        )

    def test_omits_a_blank_query_clause(self):
        opener, _ = read_shared(source={**SOURCE, "query": "  "})

        self.assertEqual(sent(opener.requests[0])["jql"], f'filter = {FILTER} AND updated >= "2026-10-15 14:00" ORDER BY key ASC')

    def test_asks_for_the_jql_issues_updated_since_the_bound_minus_24_hours(self):
        opener, _ = run(*(ok(name) for name in UPDATED_ONLY_OVER_API), source=JQL_SOURCE)

        self.assertEqual(sent(opener.requests[0]), {"jql": JQL_UPDATED_JQL, "fields": FIELDS, "maxResults": 100})

    def test_a_jql_source_follows_the_next_page_token(self):
        opener, _ = run(*(ok(name) for name in UPDATED_ONLY_OVER_API), source=JQL_SOURCE)

        self.assertEqual(sent(opener.requests[1])["nextPageToken"], "next-page-2")

    def test_a_jql_source_without_a_query_wraps_only_the_jql(self):
        source = {key: value for key, value in JQL_SOURCE.items() if key != "query"}

        opener, _ = run(*(ok(name) for name in UPDATED_ONLY_OVER_API), source=source)

        self.assertEqual(sent(opener.requests[0])["jql"], f'({JQL}) AND updated >= "2026-10-15 14:00" ORDER BY key ASC')

    def test_a_jql_source_reads_no_open_sprint(self):
        opener, _ = run(*(ok(name) for name in UPDATED_ONLY_OVER_API), source=JQL_SOURCE)

        self.assertEqual(len(opener.requests), 2)

    def test_without_a_stored_cursor_the_read_starts_at_the_first_read_start(self):
        opener, _ = read_shared(cursor=None)

        self.assertIn('updated >= "2026-10-11 00:00"', sent(opener.requests[0])["jql"])

    def test_a_cursor_before_the_first_read_start_reads_from_the_first_read_start(self):
        opener, _ = read_shared(cursor={"updated": "2026-10-11T00:00:00Z"})

        self.assertIn('updated >= "2026-10-11 00:00"', sent(opener.requests[0])["jql"])

    def test_a_cursor_with_seconds_floors_the_query_time_to_the_minute(self):
        opener, _ = read_shared(cursor={"updated": "2026-10-16T15:00:30Z"})

        self.assertIn('updated >= "2026-10-15 14:00"', sent(opener.requests[0])["jql"])

    def test_a_cursor_that_is_not_a_time_reads_from_the_first_read_start(self):
        opener, _ = read_shared(cursor={"updated": "yesterday"})

        self.assertIn('updated >= "2026-10-11 00:00"', sent(opener.requests[0])["jql"])


class ReadTest(unittest.TestCase):
    def test_records_keep_the_fields_with_utc_times_and_sprint_flags(self):
        _, result = read_shared()

        self.assertEqual(result["records"]["issues"], EXPECTED)

    def test_cursor_is_the_newest_update_read(self):
        _, result = read_shared()

        self.assertEqual(result["cursor"], NEWEST)

    def test_has_no_entries(self):
        _, result = read_shared()

        self.assertEqual(result["entries"], {})

    def test_an_issue_without_a_priority_has_a_null_priority(self):
        _, result = read_shared()

        self.assertIsNone(issue_of(result, "PROJ-7")["priority"])

    def test_an_issue_updated_at_the_exact_bound_is_kept(self):
        _, result = read_shared()

        self.assertEqual(issue_of(result, "PROJ-21")["updated"], "2026-10-16T14:00:00Z")

    def test_an_issue_read_by_the_query_margin_before_the_exact_bound_is_dropped(self):
        _, result = read_shared()

        self.assertNotIn("PROJ-3", [item["key"] for item in result["records"]["issues"]])

    def test_the_exact_bound_keeps_the_seconds_of_the_cursor(self):
        before, at = raw("PROJ-1", "2026-10-16T16:00:29.000+0200"), raw("PROJ-2", "2026-10-16T16:00:30.000+0200")

        result = updated_only(page(before, at), cursor={"updated": "2026-10-16T15:00:30Z"})

        self.assertEqual([item["key"] for item in result["records"]["issues"]], ["PROJ-2"])

    def test_without_a_stored_cursor_the_exact_bound_is_the_first_read_start(self):
        before, at = raw("PROJ-1", "2026-10-11T23:59:59.000+0000"), raw("PROJ-2", "2026-10-12T00:00:00.000+0000")

        result = updated_only(page(before, at), cursor=None)

        self.assertEqual([item["key"] for item in result["records"]["issues"]], ["PROJ-2"])

    def test_a_cursor_before_the_first_read_start_keeps_the_first_read_start_as_the_bound(self):
        before, at = raw("PROJ-1", "2026-10-11T23:59:59.000+0000"), raw("PROJ-2", "2026-10-12T00:00:00.000+0000")

        result = updated_only(page(before, at), cursor={"updated": "2026-10-11T00:00:00Z"})

        self.assertEqual([item["key"] for item in result["records"]["issues"]], ["PROJ-2"])

    def test_the_overlap_rereads_the_hour_before_the_cursor(self):
        result = updated_only(page(raw("PROJ-1", "2026-10-16T14:00:00.000+0000")))

        self.assertEqual([item["key"] for item in result["records"]["issues"]], ["PROJ-1"])

    def test_records_sort_by_key(self):
        result = updated_only(page(raw("PROJ-9", "2026-10-16T15:10:00.000+0000"), raw("ALPHA-5", "2026-10-16T15:10:00.000+0000")))

        self.assertEqual([item["key"] for item in result["records"]["issues"]], ["ALPHA-5", "PROJ-9"])

    def test_a_key_read_on_two_pages_is_kept_once_with_its_newest_update(self):
        older = raw("PROJ-5", "2026-10-16T15:10:00.000+0000", summary="Older")
        newer = raw("PROJ-5", "2026-10-16T15:20:00.000+0000", summary="Newer")

        result = updated_only(page(older, token="next-page-2"), page(newer))

        self.assertEqual([(item["title"], item["updated"]) for item in result["records"]["issues"]], [("Newer", "2026-10-16T15:20:00Z")])

    def test_nothing_read_keeps_the_stored_cursor(self):
        self.assertEqual(updated_only(page())["cursor"], STORED)

    def test_nothing_read_without_a_stored_cursor_keeps_it_null(self):
        self.assertEqual(updated_only(page(), cursor=None)["cursor"], {"updated": None})

    def test_every_kept_issue_older_than_the_stored_cursor_keeps_the_stored_cursor(self):
        result = updated_only(page(raw("PROJ-1", "2026-10-16T14:30:00.000+0000")))

        self.assertEqual(result["cursor"], STORED)

    def test_only_issues_dropped_by_the_exact_bound_keep_the_stored_cursor(self):
        result = updated_only(page(raw("PROJ-3", "2026-10-16T13:59:59.000+0000")))

        self.assertEqual(result["cursor"], STORED)

    def test_links_use_the_base_url_without_links_base(self):
        provider = {key: value for key, value in PROVIDER.items() if key != "links_base"}

        _, result = run(body(page(raw("PROJ-8", "2026-10-16T15:10:00.000+0000"))), source={**SOURCE, "open_sprints": False, "provider_config": provider})

        self.assertEqual(result["records"]["issues"][0]["link"], BASE + "/browse/PROJ-8")

    def test_collection_passes_the_role_schema(self):
        _, result = read_shared()

        self.assertIsNone(roles.validate_collection(collection(result)))


class OpenSprintTest(unittest.TestCase):
    def test_flags_the_issues_of_the_open_sprint_read(self):
        _, result = read_shared()

        self.assertEqual([(item["key"], item["in_open_sprint"]) for item in result["records"]["issues"]], [("PROJ-12", True), ("PROJ-21", False), ("PROJ-40", True), ("PROJ-7", False)])

    def test_keeps_a_sprint_issue_updated_before_the_exact_bound(self):
        _, result = read_shared()

        self.assertEqual(issue_of(result, "PROJ-40")["updated"], "2026-10-02T08:00:00Z")

    def test_no_open_sprint_reads_no_extra_issue_and_no_error(self):
        _, result = run(ok("api_updated_page_1.json"), ok("api_updated_page_2.json"), ok("api_empty.json"))

        self.assertEqual([(item["key"], item["in_open_sprint"]) for item in result["records"]["issues"]], [("PROJ-12", False), ("PROJ-21", False), ("PROJ-7", False)])

    def test_several_open_sprints_over_two_pages_flag_every_issue(self):
        first = [raw("PROJ-31", "2026-10-03T09:00:00.000+0000"), raw("PROJ-32", "2026-10-03T09:00:00.000+0000")]
        second = [raw("PROJ-33", "2026-10-04T09:00:00.000+0000")]

        _, result = run(body(page()), body(page(*first, token="sprint-page-2")), body(page(*second)))

        self.assertEqual([(item["key"], item["in_open_sprint"]) for item in result["records"]["issues"]], [("PROJ-31", True), ("PROJ-32", True), ("PROJ-33", True)])

    def test_equal_update_times_keep_the_updated_read_record(self):
        result = with_sprint([raw("PROJ-5", "2026-10-16T15:10:00.000+0000", summary="From updated")], [raw("PROJ-5", "2026-10-16T15:10:00.000+0000", summary="From sprint")])

        self.assertEqual((issue_of(result, "PROJ-5")["title"], issue_of(result, "PROJ-5")["in_open_sprint"]), ("From updated", True))

    def test_the_sprint_read_follows_its_own_next_page_token(self):
        opener, _ = run(body(page()), body(page(raw("PROJ-31", "2026-10-03T09:00:00.000+0000"), token="sprint-page-2")), body(page()))

        self.assertEqual(sent(opener.requests[2]), {"jql": SPRINT_JQL, "fields": FIELDS, "maxResults": 100, "nextPageToken": "sprint-page-2"})

    def test_sprint_issues_alone_leave_the_stored_cursor(self):
        result = with_sprint([], [raw("PROJ-31", "2026-10-03T09:00:00.000+0000")])

        self.assertEqual(result["cursor"], STORED)

    def test_a_newer_update_in_the_sprint_read_wins(self):
        result = with_sprint([raw("PROJ-5", "2026-10-16T15:10:00.000+0000", summary="Older")], [raw("PROJ-5", "2026-10-16T15:20:00.000+0000", summary="Newer")])

        self.assertEqual((issue_of(result, "PROJ-5")["title"], issue_of(result, "PROJ-5")["in_open_sprint"]), ("Newer", True))

    def test_a_newer_update_in_the_updated_read_wins(self):
        result = with_sprint([raw("PROJ-5", "2026-10-16T15:20:00.000+0000", summary="Newer")], [raw("PROJ-5", "2026-10-16T15:10:00.000+0000", summary="Older")])

        self.assertEqual((issue_of(result, "PROJ-5")["title"], issue_of(result, "PROJ-5")["in_open_sprint"]), ("Newer", True))


class PrivacyTest(unittest.TestCase):
    def test_records_carry_exactly_the_issue_fields(self):
        _, result = read_shared()

        self.assertEqual({tuple(item) for item in result["records"]["issues"]}, {tuple(EXPECTED[0])})

    def test_records_hold_no_assignee_or_reporter_name(self):
        _, result = read_shared()

        self.assertNotRegex(dumped(result), PERSON_NAMES)

    def test_records_hold_no_account_id(self):
        result = with_sprint([raw("PROJ-5", "2026-10-16T15:10:00.000+0000")], [raw("PROJ-6", "2026-10-16T15:10:00.000+0000")])

        self.assertNotIn(ACCOUNT, dumped(result))

    def test_the_request_asks_for_no_person_field(self):
        opener, _ = read_shared()

        self.assertEqual(sent(opener.requests[0])["fields"], FIELDS)


class PagingTest(unittest.TestCase):
    def pages(self, count, last):
        return [body(page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), token="next-page")) for _ in range(count - 1)] + [body(last)]

    def test_page_cap_makes_the_read_partial(self):
        error = unreadable(self, *self.pages(_http.PAGE_CAP, page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), token="next-page")), error=_http.PartialRead)

        self.assertEqual(str(error), "partial: page cap")

    def test_stops_requesting_at_the_page_cap(self):
        opener = FakeOpener([*self.pages(_http.PAGE_CAP, page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), token="next-page")), body(page())])

        with self.assertRaises(_http.PartialRead):
            jira.fetch(SOURCE, WINDOW, STORED, [], client(opener))
        self.assertEqual(len(opener.requests), _http.PAGE_CAP)

    def test_a_last_page_at_the_cap_ends_the_read(self):
        opener, _ = run(*self.pages(_http.PAGE_CAP, page()), source={**SOURCE, "open_sprints": False})

        self.assertEqual(len(opener.requests), _http.PAGE_CAP)

    def test_the_cap_applies_to_each_read(self):
        error = unreadable(self, body(page()), *self.pages(_http.PAGE_CAP, page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), token="next-page")), error=_http.PartialRead)

        self.assertEqual(str(error), "partial: page cap")

    def test_a_next_page_without_a_token_makes_the_source_unreadable(self):
        error = unreadable(self, body({"issues": [], "isLast": False}))

        self.assertEqual(str(error), f"POST {SEARCH}: next page without a nextPageToken")


class ErrorsTest(unittest.TestCase):
    def refused(self, code):
        error = unreadable(self, status(code))
        return str(error), error.status

    def test_a_filter_not_found_makes_the_source_unreadable(self):
        self.assertEqual(self.refused(404), (f"filter {FILTER} not found or forbidden: HTTP 404 POST {SEARCH}", 404))

    def test_a_filter_the_user_cannot_see_makes_the_source_unreadable(self):
        self.assertEqual(self.refused(403), (f"filter {FILTER} not found or forbidden: HTTP 403 POST {SEARCH}", 403))

    def test_a_filter_the_search_rejects_makes_the_source_unreadable(self):
        self.assertEqual(self.refused(400), (f"filter {FILTER} or its query rejected: HTTP 400 POST {SEARCH}", 400))

    def test_a_jql_the_user_cannot_run_makes_the_source_unreadable(self):
        error = unreadable(self, status(403), source=JQL_SOURCE)

        self.assertEqual((str(error), error.status), (f"jql not found or forbidden: HTTP 403 POST {SEARCH}", 403))

    def test_a_jql_the_search_rejects_makes_the_source_unreadable(self):
        error = unreadable(self, status(400), source=JQL_SOURCE)

        self.assertEqual((str(error), error.status), (f"jql or its query rejected: HTTP 400 POST {SEARCH}", 400))

    def test_a_refusal_never_repeats_the_jql(self):
        error = unreadable(self, status(400), source=JQL_SOURCE)

        self.assertNotIn(JQL, str(error))

    def test_the_open_sprint_read_failing_makes_the_source_unreadable(self):
        error = unreadable(self, ok("api_updated_page_2.json"), status(400))

        self.assertEqual(str(error), f"filter {FILTER} or its query rejected: HTTP 400 POST {SEARCH}")

    def test_bad_credentials_make_the_source_unreadable(self):
        self.assertEqual(self.refused(401), (f"HTTP 401 POST {SEARCH}", 401))

    def test_a_network_error_makes_the_source_unreadable(self):
        error = unreadable(self, urllib.error.URLError("unreachable"))

        self.assertEqual(str(error), f"POST {SEARCH}: URLError")

    def test_a_response_without_an_issues_list_makes_the_source_unreadable(self):
        error = unreadable(self, body([]))

        self.assertEqual(str(error), f"POST {SEARCH}: response without an issues list")

    def test_an_issue_without_a_key_makes_the_source_unreadable(self):
        error = unreadable(self, body(page({**raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), "key": None})))

        self.assertEqual(str(error), f"POST {SEARCH}: issue without a valid key")

    def test_an_issue_without_a_valid_update_time_makes_the_source_unreadable(self):
        error = unreadable(self, body(page(raw("PROJ-1", "yesterday"))))

        self.assertEqual(str(error), f"POST {SEARCH}: issue PROJ-1 without a valid updated")

    def test_an_issue_without_a_valid_creation_time_makes_the_source_unreadable(self):
        error = unreadable(self, body(page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000", created="soon"))))

        self.assertEqual(str(error), f"POST {SEARCH}: issue PROJ-1 without a valid created")


def saved(name):
    return fixture(name).decode("utf-8")


def responses(*names):
    return {f"issues-{index}": saved(name) for index, name in enumerate(names, start=1)}


def search_call(call_id, jql, token=None):
    arguments = {"cloudId": LINKS, "jql": jql, "fields": FIELDS, "maxResults": 100, "view": "full"}
    arguments = arguments if token is None else {**arguments, "nextPageToken": token}
    return {"id": call_id, "connector": CONNECTOR, "tool": "searchJiraIssuesUsingJql", "arguments": arguments, "digest": None}


def relay_plan(saved_responses, source=RELAY_SOURCE, cursor=STORED):
    return jira.plan(source, WINDOW, cursor, [], saved_responses, CONNECTOR)


def relay(saved_responses, source=RELAY_SOURCE, cursor=STORED):
    return jira.parse(source, WINDOW, cursor, [], saved_responses, {call_id: None for call_id in saved_responses})


def relay_failure(test, saved_responses, error=_http.SourceUnreadable, source=RELAY_SOURCE):
    with test.assertRaises(error) as caught:
        relay(saved_responses, source=source)
    return caught.exception


def wrapped(value):
    return json.dumps({"data": value})


def capped_responses(count, last):
    middle = wrapped(page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), token="next-page"))
    return {f"issues-{index}": middle for index in range(1, count)} | {f"issues-{count}": last}


class PlanTest(unittest.TestCase):
    def test_first_step_searches_the_updated_issues_in_the_full_view(self):
        self.assertEqual(relay_plan({})["calls"], [search_call("issues-1", UPDATED_JQL)])

    def test_a_jql_source_searches_the_built_jql_in_the_full_view(self):
        self.assertEqual(relay_plan({}, source=RELAY_JQL_SOURCE)["calls"], [search_call("issues-1", JQL_UPDATED_JQL)])

    def test_a_jql_source_ends_the_plan_after_the_last_updated_page(self):
        step = relay_plan(responses(*UPDATED_ONLY_OVER_RELAY), source=RELAY_JQL_SOURCE)

        self.assertEqual(step, {"done": True, "partial": None, "calls": []})

    def test_first_step_is_not_done(self):
        self.assertFalse(relay_plan({})["done"])

    def test_a_next_page_token_asks_for_the_next_page(self):
        self.assertEqual(relay_plan(responses("relay_updated_page_1.json"))["calls"], [search_call("issues-2", UPDATED_JQL, token="next-page-2")])

    def test_the_last_updated_page_moves_on_to_the_open_sprints(self):
        self.assertEqual(relay_plan(responses("relay_updated_page_1.json", "relay_updated_page_2.json"))["calls"], [search_call("issues-3", SPRINT_JQL)])

    def test_without_the_option_the_last_updated_page_ends_the_plan(self):
        step = relay_plan(responses(*UPDATED_ONLY_OVER_RELAY), source={**RELAY_SOURCE, "open_sprints": False})

        self.assertEqual(step, {"done": True, "partial": None, "calls": []})

    def test_every_page_saved_ends_the_plan(self):
        self.assertEqual(relay_plan(responses(*SHARED_OVER_RELAY)), {"done": True, "partial": None, "calls": []})

    def test_the_site_argument_falls_back_to_the_base_url(self):
        provider = {key: value for key, value in PROVIDER.items() if key != "links_base"}

        step = relay_plan({}, source={**RELAY_SOURCE, "provider_config": provider})

        self.assertEqual(step["calls"][0]["arguments"]["cloudId"], BASE)

    def test_a_provider_without_links_base_or_api_ends_the_plan(self):
        provider = {"adapter": "jira", "mcp": {"connectors": {"cloud": CONNECTOR, "local": CONNECTOR}}}

        self.assertEqual(relay_plan({}, source={**RELAY_SOURCE, "provider_config": provider}), {"done": True, "partial": None, "calls": []})

    def test_page_cap_ends_the_plan_partial(self):
        saved_responses = capped_responses(_http.PAGE_CAP, wrapped(page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), token="next-page")))

        self.assertEqual(relay_plan(saved_responses), {"done": True, "partial": "page cap", "calls": []})

    def test_unreadable_response_ends_the_plan(self):
        self.assertEqual(relay_plan({"issues-1": "Not Found"}), {"done": True, "partial": None, "calls": []})

    def test_a_connector_error_response_ends_the_plan(self):
        self.assertEqual(relay_plan(responses("relay_error.json")), {"done": True, "partial": None, "calls": []})


class TransportEqualityTest(unittest.TestCase):
    def test_both_transports_give_the_same_records(self):
        _, over_api = read_shared()

        self.assertEqual(state.dump(relay(responses(*SHARED_OVER_RELAY))["records"]), state.dump(over_api["records"]))

    def test_both_transports_give_the_same_cursor(self):
        _, over_api = read_shared()

        self.assertEqual(state.dump(relay(responses(*SHARED_OVER_RELAY))["cursor"]), state.dump(over_api["cursor"]))

    def test_both_transports_agree_without_a_stored_cursor(self):
        _, over_api = read_shared(cursor=None)

        self.assertEqual(state.dump(relay(responses(*SHARED_OVER_RELAY), cursor=None)), state.dump(over_api))

    def test_both_transports_agree_without_open_sprints(self):
        _, over_api = run(*(ok(name) for name in UPDATED_ONLY_OVER_API), source={**SOURCE, "open_sprints": False})

        over_relay = relay(responses(*UPDATED_ONLY_OVER_RELAY), source={**RELAY_SOURCE, "open_sprints": False})

        self.assertEqual(state.dump(over_relay), state.dump(over_api))

    def test_both_transports_give_the_same_records_for_a_jql_source(self):
        _, over_api = run(*(ok(name) for name in UPDATED_ONLY_OVER_API), source=JQL_SOURCE)

        over_relay = relay(responses(*UPDATED_ONLY_OVER_RELAY), source=RELAY_JQL_SOURCE)

        self.assertEqual(state.dump(over_relay), state.dump(over_api))

    def test_relayed_records_match_the_expected_records(self):
        self.assertEqual(relay(responses(*SHARED_OVER_RELAY))["records"], {"issues": EXPECTED})


class RelayRecordsTest(unittest.TestCase):
    def test_has_no_entries(self):
        self.assertEqual(relay(responses(*SHARED_OVER_RELAY))["entries"], {})

    def test_links_use_links_base(self):
        result = relay(responses(*SHARED_OVER_RELAY))

        self.assertEqual(issue_of(result, "PROJ-12")["link"], LINKS + "/browse/PROJ-12")

    def test_records_hold_no_person(self):
        self.assertNotRegex(dumped(relay(responses(*SHARED_OVER_RELAY))), PERSON_NAMES)

    def test_a_full_view_with_account_ids_never_reaches_a_record(self):
        saved_responses = {"issues-1": wrapped(page(raw("PROJ-5", "2026-10-16T15:10:00.000+0000")))}

        result = relay(saved_responses, source={**RELAY_SOURCE, "open_sprints": False})

        self.assertEqual((ACCOUNT in dumped(result), re.search(PERSON_NAMES, dumped(result))), (False, None))

    def test_a_full_view_record_carries_exactly_the_issue_fields(self):
        saved_responses = {"issues-1": wrapped(page(raw("PROJ-5", "2026-10-16T15:10:00.000+0000")))}

        result = relay(saved_responses, source={**RELAY_SOURCE, "open_sprints": False})

        self.assertEqual(tuple(result["records"]["issues"][0]), tuple(EXPECTED[0]))

    def test_no_open_sprint_reads_no_extra_issue(self):
        result = relay(responses("relay_updated_page_1.json", "relay_updated_page_2.json", "relay_empty.json"))

        self.assertEqual([item["in_open_sprint"] for item in result["records"]["issues"]], [False, False, False])

    def test_collection_passes_the_role_schema(self):
        result = relay(responses(*SHARED_OVER_RELAY))

        self.assertIsNone(roles.validate_collection(collection(result, transport="mcp")))


class RelayFailureTest(unittest.TestCase):
    def test_response_that_is_not_json_names_the_tool(self):
        error = relay_failure(self, {"issues-1": "Error: filter not found"})

        self.assertEqual(str(error), "searchJiraIssuesUsingJql issues-1: response is not JSON")

    def test_error_response_names_the_tool_and_the_filter(self):
        error = relay_failure(self, responses("relay_error.json"))

        self.assertEqual(str(error), f"searchJiraIssuesUsingJql: filter {FILTER} not read: connector error")

    def test_error_response_names_the_tool_and_the_jql_source(self):
        error = relay_failure(self, responses("relay_error.json"), source=RELAY_JQL_SOURCE)

        self.assertEqual(str(error), "searchJiraIssuesUsingJql: jql not read: connector error")

    def test_error_text_never_reaches_the_reason(self):
        error = relay_failure(self, {"issues-1": json.dumps({"error": "filter = 10 AND (secret query)"})})

        self.assertNotIn("secret query", str(error))

    def test_response_without_data_or_error_text_names_the_tool(self):
        error = relay_failure(self, {"issues-1": json.dumps({"error": {"code": 500}})})

        self.assertEqual(str(error), "searchJiraIssuesUsingJql issues-1: response without data")

    def test_data_without_an_issues_list_names_the_tool(self):
        error = relay_failure(self, {"issues-1": wrapped({"total": 0})})

        self.assertEqual(str(error), "searchJiraIssuesUsingJql issues-1: response without an issues list")

    def test_next_page_without_a_token_names_the_tool(self):
        error = relay_failure(self, {"issues-1": wrapped({"issues": [], "isLast": False})})

        self.assertEqual(str(error), "searchJiraIssuesUsingJql issues-1: next page without a nextPageToken")

    def test_missing_response_names_the_call(self):
        error = relay_failure(self, responses("relay_updated_page_1.json"))

        self.assertEqual(str(error), "searchJiraIssuesUsingJql issues-2: no saved response")

    def test_page_cap_makes_the_read_partial(self):
        saved_responses = capped_responses(_http.PAGE_CAP, wrapped(page(raw("PROJ-1", "2026-10-16T15:10:00.000+0000"), token="next-page")))

        error = relay_failure(self, saved_responses, _http.PartialRead)

        self.assertEqual(str(error), "partial: page cap")

    def test_a_last_page_at_the_cap_ends_the_read(self):
        saved_responses = capped_responses(_http.PAGE_CAP, wrapped(page())) | {f"issues-{_http.PAGE_CAP + 1}": wrapped(page())}

        result = relay(saved_responses)

        self.assertEqual(result["records"]["issues"][0]["key"], "PROJ-1")

    def test_a_provider_without_links_base_or_api_is_not_read(self):
        provider = {"adapter": "jira", "mcp": {"connectors": {"cloud": CONNECTOR, "local": CONNECTOR}}}

        error = relay_failure(self, {}, source={**RELAY_SOURCE, "provider_config": provider})

        self.assertEqual(str(error), "links_base missing in providers.tracker")


if __name__ == "__main__":
    unittest.main()
