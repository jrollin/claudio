import email.message
import io
import json
import pathlib
import unittest
import urllib.error
import urllib.parse

import roles
import state
from providers import _http, github

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "github"
BASE = "https://api.example.test"
LINKS = "https://code.example.test"
TOKEN_VAR = "CODE_TOKEN"
TOKEN_VALUE = "-".join(["token", "sentinel"])
PROVIDER = {"adapter": "github", "links_base": LINKS, "api": {"base_url": BASE, "credentials": {"token": TOKEN_VAR}}}
WINDOW = {"from_ts": 1788508800, "to_ts": 1788552000}
WINDOW_START = "2026-09-04T08:00:00Z"
STORED_AT = "2026-09-04T09:00:00Z"
STORED = {"updated_at": STORED_AT}
TRANSPORT = {"cloud": "api", "local": "api"}
SOURCE = {
    "name": "code",
    "provider": "code",
    "transport": TRANSPORT,
    "repos": ["acme/app", "acme/infra"],
    "provider_config": PROVIDER,
}
APP_PULLS = "/repos/acme/app/pulls"
APP_ISSUES = "/repos/acme/app/issues"
INFRA_PULLS = "/repos/acme/infra/pulls"
INFRA_ISSUES = "/repos/acme/infra/issues"
SHARED_OVER_API = ("api_app_pulls.json", "api_app_issues.json", "api_infra_pulls.json", "api_infra_issues.json")
EXPECTED_PULLS = [
    {
        "repo": "acme/app",
        "number": 11,
        "title": "Fix the login redirect",
        "author": "bob-dev",
        "state": "closed",
        "draft": False,
        "created_at": "2026-09-02T09:00:00Z",
        "updated_at": "2026-09-04T12:30:00Z",
        "merged_at": "2026-09-04T12:30:00Z",
        "link": LINKS + "/acme/app/pull/11",
    },
    {
        "repo": "acme/app",
        "number": 12,
        "title": "Add retry to the importer",
        "author": "alice-dev",
        "state": "open",
        "draft": True,
        "created_at": "2026-09-03T10:00:00Z",
        "updated_at": "2026-09-04T15:00:00Z",
        "merged_at": None,
        "link": LINKS + "/acme/app/pull/12",
    },
    {
        "repo": "acme/infra",
        "number": 3,
        "title": "Pin the base image",
        "author": "bob-dev",
        "state": "open",
        "draft": False,
        "created_at": "2026-09-04T09:30:00Z",
        "updated_at": "2026-09-04T10:15:00Z",
        "merged_at": None,
        "link": LINKS + "/acme/infra/pull/3",
    },
]
EXPECTED_ISSUES = [
    {
        "repo": "acme/app",
        "number": 9,
        "title": "Typo on the settings page",
        "author": "dana-dev",
        "state": "closed",
        "created_at": "2026-08-28T10:00:00Z",
        "updated_at": "2026-09-04T11:00:00Z",
        "link": LINKS + "/acme/app/issues/9",
    },
    {
        "repo": "acme/app",
        "number": 14,
        "title": "Importer times out",
        "author": "carol-dev",
        "state": "open",
        "created_at": "2026-09-04T13:00:00Z",
        "updated_at": "2026-09-04T14:00:00Z",
        "link": LINKS + "/acme/app/issues/14",
    },
    {
        "repo": "acme/infra",
        "number": 5,
        "title": "Disk alert on the runner",
        "author": "alice-dev",
        "state": "closed",
        "created_at": "2026-09-01T07:00:00Z",
        "updated_at": "2026-09-04T09:45:00Z",
        "link": LINKS + "/acme/infra/issues/5",
    },
]


class FakeResponse:
    def __init__(self, body, link=None):
        self.stream = io.BytesIO(body)
        self.headers = email.message.Message()
        if link is not None:
            self.headers["Link"] = link

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


def ok(name, link=None):
    return FakeResponse(fixture(name), link)


def body(value, link=None):
    return FakeResponse(json.dumps(value).encode("utf-8"), link)


def next_link(page):
    return f'<{BASE}{APP_PULLS}?page={page}>; rel="next", <{BASE}{APP_PULLS}?page=40>; rel="last"'


def status(code):
    return urllib.error.HTTPError(BASE, code, "status", email.message.Message(), io.BytesIO(fixture(f"error_{code}.json")))


def pull(number, updated_at, **changes):
    item = {
        "number": number,
        "title": f"Change {number}",
        "user": {"login": "erin-dev"},
        "state": "open",
        "draft": False,
        "created_at": "2026-09-04T09:00:00Z",
        "updated_at": updated_at,
        "merged_at": None,
        "html_url": f"{LINKS}/acme/app/pull/{number}",
    }
    return {**item, **changes}


def issue(number, updated_at, state="open"):
    return {
        "number": number,
        "title": f"Report {number}",
        "user": {"login": "erin-dev"},
        "state": state,
        "created_at": "2026-09-04T09:00:00Z",
        "updated_at": updated_at,
    }


def full_pulls(first):
    return [pull(number, "2026-09-04T16:00:00Z") for number in range(first, first + github.PER_PAGE)]


def full_issues(first):
    return [issue(number, "2026-09-04T16:00:00Z") for number in range(first, first + github.PER_PAGE)]


def client(opener, environ=None):
    environ = {TOKEN_VAR: TOKEN_VALUE} if environ is None else environ
    return github.api_client(PROVIDER, opener=opener, environ=environ, sleep=lambda seconds: None)


def run(*outcomes, source=SOURCE, cursor=STORED):
    opener = FakeOpener(outcomes)
    return opener, github.fetch(source, WINDOW, cursor, [], client(opener))


def app_only(*outcomes, cursor=STORED):
    return run(*outcomes, source={**SOURCE, "repos": ["acme/app"]}, cursor=cursor)


def read_shared():
    return run(*(ok(name) for name in SHARED_OVER_API))


def endpoint(request):
    return request.get_method(), urllib.parse.urlsplit(request.full_url).path


def query(request):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


def unreadable(test, *outcomes, source=SOURCE, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        run(*outcomes, source=source)
    return caught.exception


def collection(result, transport="api"):
    return {
        "schema": 1,
        "source": SOURCE["name"],
        "role": github.ROLE,
        "provider": "code",
        "transport": transport,
        "place": "cloud",
        "window": WINDOW,
        "read": True,
        "reason": None,
        **result,
    }


class ClientTest(unittest.TestCase):
    def test_role_is_code_host(self):
        self.assertEqual(github.ROLE, "code_host")

    def test_sends_the_token_as_a_bearer_header(self):
        opener, _ = read_shared()

        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer " + TOKEN_VALUE)

    def test_asks_for_the_vendor_media_type(self):
        opener, _ = read_shared()

        self.assertEqual(opener.requests[0].get_header("Accept"), "application/vnd.github+json")

    def test_sends_the_pinned_api_version(self):
        opener, _ = read_shared()

        self.assertEqual(opener.requests[0].get_header("X-github-api-version"), "2022-11-28")

    def test_rejects_a_provider_without_the_token(self):
        provider = {"api": {"base_url": BASE, "credentials": {"key": TOKEN_VAR}}}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            github.api_client(provider, opener=FakeOpener([]))
        self.assertEqual(str(caught.exception), "api.credentials: must name token")

    def test_missing_token_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            github.fetch(SOURCE, WINDOW, STORED, [], client(FakeOpener([]), environ={}))
        self.assertEqual(str(caught.exception), "credentials missing: CODE_TOKEN")


class ReadTest(unittest.TestCase):
    def test_reads_pull_requests_then_issues_per_repo_in_config_order(self):
        opener, _ = read_shared()

        self.assertEqual(
            [endpoint(request) for request in opener.requests],
            [("GET", APP_PULLS), ("GET", APP_ISSUES), ("GET", INFRA_PULLS), ("GET", INFRA_ISSUES)],
        )

    def test_asks_for_every_pull_request_newest_update_first(self):
        opener, _ = read_shared()

        self.assertEqual(
            query(opener.requests[0]),
            {"state": ["all"], "sort": ["updated"], "direction": ["desc"], "per_page": ["100"], "page": ["1"]},
        )

    def test_asks_for_issues_updated_since_the_stored_cursor(self):
        opener, _ = read_shared()

        self.assertEqual(
            query(opener.requests[1]),
            {
                "state": ["all"],
                "since": [STORED_AT],
                "sort": ["updated"],
                "direction": ["desc"],
                "per_page": ["100"],
                "page": ["1"],
            },
        )

    def test_without_a_stored_cursor_issues_start_at_the_window_start(self):
        opener, _ = app_only(ok("api_app_pulls.json"), ok("api_app_issues.json"), cursor=None)

        self.assertEqual(query(opener.requests[1])["since"], [WINDOW_START])

    def test_cursor_before_the_window_starts_at_the_window_start(self):
        opener, _ = app_only(ok("api_app_pulls.json"), ok("api_app_issues.json"), cursor={"updated_at": "2026-09-01T00:00:00Z"})

        self.assertEqual(query(opener.requests[1])["since"], [WINDOW_START])

    def test_pull_requests_keep_draft_and_merge_time(self):
        _, result = read_shared()

        self.assertEqual(result["records"]["pull_requests"], EXPECTED_PULLS)

    def test_issues_skip_pull_requests_and_link_to_the_issue_page(self):
        _, result = read_shared()

        self.assertEqual(result["records"]["issues"], EXPECTED_ISSUES)

    def test_records_sort_by_repo_then_number(self):
        _, result = run(ok("api_infra_pulls.json"), ok("api_infra_issues.json"), ok("api_app_pulls.json"), ok("api_app_issues.json"), source={**SOURCE, "repos": ["acme/infra", "acme/app"]})

        self.assertEqual([(item["repo"], item["number"]) for item in result["records"]["pull_requests"]], [("acme/app", 11), ("acme/app", 12), ("acme/infra", 3)])

    def test_items_updated_after_the_window_are_skipped(self):
        _, result = app_only(body([pull(30, "2026-09-04T20:00:01Z"), pull(31, "2026-09-04T20:00:00Z")]), body([]))

        self.assertEqual([item["number"] for item in result["records"]["pull_requests"]], [31])

    def test_items_updated_at_the_start_are_kept(self):
        _, result = app_only(body([pull(32, STORED_AT)]), body([]))

        self.assertEqual([item["number"] for item in result["records"]["pull_requests"]], [32])

    def test_times_are_utc_without_fraction(self):
        _, result = app_only(body([pull(33, "2026-09-04T12:00:00.250+02:00")]), body([]))

        self.assertEqual(result["records"]["pull_requests"][0]["updated_at"], "2026-09-04T10:00:00Z")

    def test_cursor_is_the_newest_update_read(self):
        _, result = read_shared()

        self.assertEqual(result["cursor"], {"updated_at": "2026-09-04T15:00:00Z"})

    def test_nothing_read_keeps_the_stored_cursor(self):
        _, result = app_only(body([]), body([]))

        self.assertEqual(result["cursor"], STORED)

    def test_nothing_read_without_a_stored_cursor_keeps_it_null(self):
        _, result = app_only(body([]), body([]), cursor=None)

        self.assertEqual(result["cursor"], {"updated_at": None})

    def test_has_no_entries(self):
        _, result = read_shared()

        self.assertEqual(result["entries"], {})

    def test_empty_query_reads_the_source(self):
        _, result = run(*(ok(name) for name in SHARED_OVER_API), source={**SOURCE, "query": ""})

        self.assertEqual(result["records"]["issues"], EXPECTED_ISSUES)

    def test_issue_links_derive_from_the_base_url_without_links_base(self):
        provider = {key: value for key, value in PROVIDER.items() if key != "links_base"}
        source = {**SOURCE, "repos": ["acme/app"], "provider_config": provider}

        _, result = run(body([]), body([issue(40, "2026-09-04T10:00:00Z")]), source=source)

        self.assertEqual(result["records"]["issues"][0]["link"], "https://example.test/acme/app/issues/40")

    def test_collection_passes_the_role_schema(self):
        _, result = read_shared()

        self.assertIsNone(roles.validate_collection(collection(result)))


class PagingTest(unittest.TestCase):
    def test_follows_the_next_link(self):
        opener, _ = app_only(body(full_pulls(101), link=next_link(2)), body([pull(49, "2026-09-04T15:00:00Z")]), body([]))

        self.assertEqual(opener.requests[1].full_url, f"{BASE}{APP_PULLS}?page=2")

    def test_reads_every_linked_page(self):
        _, result = app_only(body(full_pulls(101), link=next_link(2)), body([pull(49, "2026-09-04T15:00:00Z")]), body([]))

        self.assertEqual([item["number"] for item in result["records"]["pull_requests"]], [49, *range(101, 201)])

    def test_an_item_older_than_the_start_ends_the_paging(self):
        page = [*full_pulls(101)[:-1], pull(8, "2026-09-04T08:59:59Z")]

        opener, _ = app_only(body(page, link=next_link(2)), body([]))

        self.assertEqual([endpoint(request) for request in opener.requests], [("GET", APP_PULLS), ("GET", APP_ISSUES)])

    def test_a_short_pull_request_page_ends_the_paging(self):
        opener, _ = app_only(body(full_pulls(101)[:-1], link=next_link(2)), body([]))

        self.assertEqual([endpoint(request) for request in opener.requests], [("GET", APP_PULLS), ("GET", APP_ISSUES)])

    def test_a_short_issue_page_ends_the_paging(self):
        issues_link = f'<{BASE}{APP_ISSUES}?page=2>; rel="next"'

        opener, _ = app_only(body([]), body(full_issues(101)[:-1], link=issues_link))

        self.assertEqual(len(opener.requests), 2)

    def test_pull_requests_listed_as_issues_count_toward_a_full_issue_page(self):
        issues_link = f'<{BASE}{APP_ISSUES}?page=2>; rel="next"'
        page = [*full_issues(101)[:-1], {**issue(12, "2026-09-04T15:00:00Z"), "pull_request": {}}]

        opener, _ = app_only(body([]), body(page, link=issues_link), body([]))

        self.assertEqual(opener.requests[2].full_url, f"{BASE}{APP_ISSUES}?page=2")

    def test_an_item_seen_on_two_pages_is_kept_once(self):
        _, result = app_only(body(full_pulls(101), link=next_link(2)), body([pull(200, "2026-09-04T16:00:00Z")]), body([]))

        self.assertEqual(len(result["records"]["pull_requests"]), github.PER_PAGE)

    def test_page_cap_makes_the_read_partial(self):
        pages = [body(full_pulls(101), link=next_link(page + 2)) for page in range(_http.PAGE_CAP)]

        error = unreadable(self, *pages, source={**SOURCE, "repos": ["acme/app"]}, error=_http.PartialRead)

        self.assertEqual(str(error), "partial: page cap")

    def test_stops_requesting_at_the_page_cap(self):
        pages = [body(full_pulls(101), link=next_link(page + 2)) for page in range(_http.PAGE_CAP)]
        opener = FakeOpener([*pages, body([])])

        with self.assertRaises(_http.PartialRead):
            github.fetch({**SOURCE, "repos": ["acme/app"]}, WINDOW, STORED, [], client(opener))
        self.assertEqual(len(opener.requests), _http.PAGE_CAP)

    def test_issue_pages_follow_their_own_next_link(self):
        issues_link = f'<{BASE}{APP_ISSUES}?page=2>; rel="next"'

        opener, _ = app_only(body([]), body(full_issues(101), link=issues_link), body([]))

        self.assertEqual(opener.requests[2].full_url, f"{BASE}{APP_ISSUES}?page=2")

    def test_next_link_to_another_host_makes_the_source_unreadable(self):
        link = f'<https://elsewhere.example.test{APP_PULLS}?page=2>; rel="next"'

        error = unreadable(self, body(full_pulls(101), link=link), source={**SOURCE, "repos": ["acme/app"]})

        self.assertEqual(str(error), f"link refused GET {APP_PULLS}: not on the base_url host")


class ErrorsTest(unittest.TestCase):
    def test_unknown_repo_names_the_repo(self):
        error = unreadable(self, ok("api_app_pulls.json"), ok("api_app_issues.json"), status(404))

        self.assertEqual(str(error), f"repo acme/infra not found: HTTP 404 GET {INFRA_PULLS}")

    def test_issues_disabled_read_as_no_issues(self):
        _, result = app_only(ok("api_app_pulls.json"), status(410))

        self.assertEqual(result["records"]["issues"], [])

    def test_issues_disabled_still_read_the_pull_requests(self):
        _, result = app_only(ok("api_app_pulls.json"), status(410))

        self.assertEqual([item["number"] for item in result["records"]["pull_requests"]], [11, 12])

    def test_gone_pull_requests_make_the_source_unreadable(self):
        error = unreadable(self, status(410))

        self.assertEqual(str(error), f"HTTP 410 GET {APP_PULLS}")

    def test_bad_credentials_make_the_source_unreadable(self):
        error = unreadable(self, status(401))

        self.assertEqual(str(error), f"HTTP 401 GET {APP_PULLS}")

    def test_query_is_not_supported(self):
        error = unreadable(self, source={**SOURCE, "query": "label:bug"})

        self.assertEqual(str(error), "query not supported by the api transport")

    def test_query_sends_no_request(self):
        opener = FakeOpener([])

        with self.assertRaises(_http.SourceUnreadable):
            github.fetch({**SOURCE, "query": "label:bug"}, WINDOW, STORED, [], client(opener))
        self.assertEqual(opener.requests, [])

    def test_response_that_is_not_a_list_makes_the_source_unreadable(self):
        error = unreadable(self, body({"message": "moved"}))

        self.assertEqual(str(error), f"GET {APP_PULLS}: response is not a list")

    def test_item_without_a_valid_update_time_makes_the_source_unreadable(self):
        error = unreadable(self, body([pull(80, "yesterday")]))

        self.assertEqual(str(error), f"GET {APP_PULLS}: item without a valid updated_at")

    def test_item_without_a_valid_creation_time_makes_the_source_unreadable(self):
        error = unreadable(self, body([pull(81, "2026-09-04T16:00:00Z", created_at="soon")]))

        self.assertEqual(str(error), f"GET {APP_PULLS}: item without a valid created_at")

    def test_unreadable_merge_time_makes_the_source_unreadable(self):
        error = unreadable(self, body([pull(82, "2026-09-04T16:00:00Z", state="closed", merged_at="merged")]))

        self.assertEqual(str(error), f"GET {APP_PULLS}: item without a valid merged_at")

    def test_item_without_a_number_makes_the_source_unreadable(self):
        error = unreadable(self, body([pull(None, "2026-09-04T16:00:00Z")]))

        self.assertEqual(str(error), f"GET {APP_PULLS}: item without a valid number")


RELAY_SOURCE = {**SOURCE, "transport": {"cloud": "mcp", "local": "mcp"}}
CONNECTOR = "code-connector"
PULL_FIELDS = ["number", "title", "state", "draft", "html_url", "user", "created_at", "updated_at", "merged_at"]
ISSUE_FIELDS = ["number", "title", "state", "user", "created_at", "updated_at"]
SHARED_OVER_RELAY = ("relay_app_pulls.json", "relay_app_issues.json", "relay_infra_pulls.json", "relay_infra_issues.json")


def saved(name):
    return fixture(name).decode("utf-8")


def responses(*names):
    return {f"code-{index}": saved(name) for index, name in enumerate(names, start=1)}


def text(value):
    return json.dumps(value)


def issue_page(items, has_next=False, end_cursor=None):
    info = {"hasNextPage": has_next, **({"endCursor": end_cursor} if end_cursor is not None else {})}
    return text({"issues": items, "pageInfo": info, "totalCount": len(items)})


def pulls_call(call_id, owner_repo, page):
    owner, repo = owner_repo.split("/")
    arguments = {
        "owner": owner,
        "repo": repo,
        "state": "all",
        "sort": "updated",
        "direction": "desc",
        "perPage": 100,
        "page": page,
        "fields": PULL_FIELDS,
    }
    return {"id": call_id, "connector": CONNECTOR, "tool": "list_pull_requests", "arguments": arguments, "digest": None}


def issues_call(call_id, owner_repo, since, after=None):
    owner, repo = owner_repo.split("/")
    arguments = {
        "owner": owner,
        "repo": repo,
        "since": since,
        "orderBy": "UPDATED_AT",
        "direction": "DESC",
        "perPage": 100,
        "fields": ISSUE_FIELDS,
        **({"after": after} if after is not None else {}),
    }
    return {"id": call_id, "connector": CONNECTOR, "tool": "list_issues", "arguments": arguments, "digest": None}


def relay_plan(saved_responses, source=RELAY_SOURCE, cursor=STORED):
    return github.plan(source, WINDOW, cursor, [], saved_responses, CONNECTOR)


def relay(saved_responses, source=RELAY_SOURCE, cursor=STORED):
    return github.parse(source, WINDOW, cursor, [], saved_responses, {call_id: None for call_id in saved_responses})


def relay_failure(test, saved_responses, error=_http.SourceUnreadable, source=RELAY_SOURCE):
    with test.assertRaises(error) as caught:
        relay(saved_responses, source=source)
    return caught.exception


def app_relay(*texts):
    return {f"code-{index}": value for index, value in enumerate(texts, start=1)}


APP_SOURCE = {**RELAY_SOURCE, "repos": ["acme/app"]}
FULL_PULL_PAGE = text(full_pulls(101))


class PlanTest(unittest.TestCase):
    def test_first_step_lists_the_first_repo_pull_requests(self):
        self.assertEqual(relay_plan({})["calls"], [pulls_call("code-1", "acme/app", 1)])

    def test_first_step_is_not_done(self):
        self.assertFalse(relay_plan({})["done"])

    def test_a_page_without_an_older_item_asks_for_the_next_page(self):
        self.assertEqual(relay_plan({"code-1": FULL_PULL_PAGE})["calls"], [pulls_call("code-2", "acme/app", 2)])

    def test_an_older_item_moves_on_to_the_issues_since_the_start(self):
        self.assertEqual(
            relay_plan(responses("relay_app_pulls.json"))["calls"], [issues_call("code-2", "acme/app", STORED_AT)]
        )

    def test_a_short_page_moves_on_to_the_issues(self):
        short = text(full_pulls(101)[:-1])

        self.assertEqual(relay_plan({"code-1": short})["calls"], [issues_call("code-2", "acme/app", STORED_AT)])

    def test_an_empty_page_moves_on_to_the_issues(self):
        self.assertEqual(
            relay_plan({"code-1": FULL_PULL_PAGE, "code-2": "[]"})["calls"], [issues_call("code-3", "acme/app", STORED_AT)]
        )

    def test_issues_start_at_the_window_start_without_a_stored_cursor(self):
        self.assertEqual(
            relay_plan(responses("relay_app_pulls.json"), cursor=None)["calls"], [issues_call("code-2", "acme/app", WINDOW_START)]
        )

    def test_a_next_issue_page_follows_the_end_cursor(self):
        page = issue_page([issue(91, "2026-09-04T16:00:00Z")], has_next=True, end_cursor="cursor-a")

        self.assertEqual(
            relay_plan({"code-1": "[]", "code-2": page})["calls"], [issues_call("code-3", "acme/app", STORED_AT, after="cursor-a")]
        )

    def test_last_issue_page_moves_on_to_the_next_repo(self):
        self.assertEqual(
            relay_plan(responses("relay_app_pulls.json", "relay_app_issues.json"))["calls"], [pulls_call("code-3", "acme/infra", 1)]
        )

    def test_every_page_saved_ends_the_plan(self):
        self.assertEqual(relay_plan(responses(*SHARED_OVER_RELAY)), {"done": True, "partial": None, "calls": []})

    def test_repeated_issue_cursor_ends_the_plan_partial(self):
        first = issue_page([issue(92, "2026-09-04T16:00:00Z")], has_next=True, end_cursor="cursor-a")
        second = issue_page([issue(93, "2026-09-04T15:00:00Z")], has_next=True, end_cursor="cursor-a")

        self.assertEqual(
            relay_plan(app_relay("[]", first, second), source=APP_SOURCE), {"done": True, "partial": "cursor repeated", "calls": []}
        )

    def test_page_cap_ends_the_plan_partial(self):
        pages = app_relay(*[FULL_PULL_PAGE] * _http.PAGE_CAP)

        self.assertEqual(relay_plan(pages, source=APP_SOURCE), {"done": True, "partial": "page cap", "calls": []})

    def test_unreadable_response_ends_the_plan(self):
        self.assertEqual(relay_plan({"code-1": "Not Found"}), {"done": True, "partial": None, "calls": []})

    def test_query_ends_the_plan_without_a_call(self):
        self.assertEqual(relay_plan({}, source={**RELAY_SOURCE, "query": "label:bug"}), {"done": True, "partial": None, "calls": []})


class TransportEqualityTest(unittest.TestCase):
    def test_both_transports_give_the_same_records(self):
        _, over_api = read_shared()

        self.assertEqual(state.dump(relay(responses(*SHARED_OVER_RELAY))["records"]), state.dump(over_api["records"]))

    def test_both_transports_give_the_same_cursor(self):
        _, over_api = read_shared()

        self.assertEqual(relay(responses(*SHARED_OVER_RELAY))["cursor"], over_api["cursor"])

    def test_issues_disabled_over_the_api_match_an_empty_relayed_issue_list(self):
        _, over_api = app_only(ok("api_app_pulls.json"), status(410))

        relayed = relay(app_relay(saved("relay_app_pulls.json"), issue_page([])), source=APP_SOURCE)

        self.assertEqual(state.dump(relayed), state.dump(over_api))

    def test_relayed_records_match_the_expected_records(self):
        self.assertEqual(
            relay(responses(*SHARED_OVER_RELAY))["records"], {"pull_requests": EXPECTED_PULLS, "issues": EXPECTED_ISSUES}
        )


class RelayRecordsTest(unittest.TestCase):
    def test_merge_time_wins_over_the_merged_flag(self):
        page = text([pull(94, "2026-09-04T16:00:00Z", state="closed", merged=False, merged_at="2026-09-04T16:00:00Z")])

        result = relay(app_relay(page, issue_page([])), source=APP_SOURCE)

        self.assertEqual(result["records"]["pull_requests"][0]["merged_at"], "2026-09-04T16:00:00Z")

    def test_issue_state_is_lowercase(self):
        result = relay(app_relay("[]", issue_page([issue(95, "2026-09-04T16:00:00Z", state="CLOSED")])), source=APP_SOURCE)

        self.assertEqual(result["records"]["issues"][0]["state"], "closed")

    def test_reads_every_issue_page(self):
        first = issue_page([issue(96, "2026-09-04T16:00:00Z")], has_next=True, end_cursor="cursor-a")
        second = issue_page([issue(97, "2026-09-04T15:00:00Z")])

        result = relay(app_relay("[]", first, second), source=APP_SOURCE)

        self.assertEqual([item["number"] for item in result["records"]["issues"]], [96, 97])

    def test_has_no_entries(self):
        self.assertEqual(relay(responses(*SHARED_OVER_RELAY))["entries"], {})

    def test_issue_links_use_the_public_host_without_links_base_or_api(self):
        source = {**APP_SOURCE, "provider_config": {"adapter": "github"}}

        result = relay(app_relay("[]", issue_page([issue(99, "2026-09-04T16:00:00Z")])), source=source)

        self.assertEqual(result["records"]["issues"][0]["link"], "https://github.com/acme/app/issues/99")

    def test_collection_passes_the_role_schema(self):
        result = relay(responses(*SHARED_OVER_RELAY))

        self.assertIsNone(roles.validate_collection(collection(result, transport="mcp")))


class RelayFailureTest(unittest.TestCase):
    def test_response_that_is_not_json_names_the_tool(self):
        error = relay_failure(self, {"code-1": "failed to list pull requests: 404 Not Found"})

        self.assertEqual(str(error), "list_pull_requests acme/app code-1: response is not JSON")

    def test_pull_requests_that_are_not_a_list_name_the_tool(self):
        error = relay_failure(self, {"code-1": text({"items": []})})

        self.assertEqual(str(error), "list_pull_requests acme/app code-1: response is not a JSON array")

    def test_issues_without_an_issue_list_name_the_tool(self):
        error = relay_failure(self, {"code-1": "[]", "code-2": text([])})

        self.assertEqual(str(error), "list_issues acme/app code-2: response without an issues list")

    def test_next_issue_page_without_a_cursor_names_the_tool(self):
        error = relay_failure(self, {"code-1": "[]", "code-2": issue_page([issue(98, "2026-09-04T16:00:00Z")], has_next=True)})

        self.assertEqual(str(error), "list_issues acme/app code-2: next page without an endCursor")

    def test_missing_response_names_the_call(self):
        error = relay_failure(self, responses("relay_app_pulls.json"))

        self.assertEqual(str(error), "list_issues acme/app code-2: no saved response")

    def test_repeated_issue_cursor_makes_the_read_partial(self):
        first = issue_page([issue(92, "2026-09-04T16:00:00Z")], has_next=True, end_cursor="cursor-a")
        second = issue_page([issue(93, "2026-09-04T15:00:00Z")], has_next=True, end_cursor="cursor-a")

        error = relay_failure(self, app_relay("[]", first, second), _http.PartialRead, source=APP_SOURCE)

        self.assertEqual(str(error), "partial: cursor repeated")

    def test_page_cap_makes_the_read_partial(self):
        error = relay_failure(self, app_relay(*[FULL_PULL_PAGE] * _http.PAGE_CAP), _http.PartialRead, source=APP_SOURCE)

        self.assertEqual(str(error), "partial: page cap")

    def test_query_is_not_supported(self):
        error = relay_failure(self, {}, source={**RELAY_SOURCE, "query": "label:bug"})

        self.assertEqual(str(error), "query not supported by the mcp transport")


class LinkHeaderTest(unittest.TestCase):
    def test_follows_the_next_link_after_a_64_kb_run_of_angle_brackets(self):
        crafted = "<" * 65536 + next_link(2)

        opener, _ = app_only(body(full_pulls(101), link=crafted), body([pull(49, "2026-09-04T15:00:00Z")]), body([]))

        self.assertEqual(query(opener.requests[1])["page"], ["2"])


if __name__ == "__main__":
    unittest.main()
