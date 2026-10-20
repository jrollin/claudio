import email.message
import io
import json
import pathlib
import unittest
import urllib.error
import urllib.parse

import evaluate
import roles
import state
from providers import _http, notion

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "notion"
BASE = "https://api.example.test"
TOKEN_VAR = "DOC_TOKEN"
TOKEN_VALUE = "-".join(["token", "sentinel"])
PROVIDER = {"adapter": "notion", "api": {"base_url": BASE, "credentials": {"token": TOKEN_VAR}}}
WINDOW = {"from_ts": 1760000000, "to_ts": 1760010800}
TRANSPORT = {"cloud": "api", "local": "api"}
PAGE_ID = "sources-page"
SOURCE = {"name": "sources", "provider": "docs", "transport": TRANSPORT, "page_id": PAGE_ID}
STORED = {"pages": {"sources-page": "2026-08-01T09:00:00Z"}}
PAGE_PATH = "/v1/pages/sources-page"
BLOCKS_PATH = "/v1/blocks/sources-page/children"
TABLE_PATH = "/v1/blocks/mutes-table/children"
FULL_PAGE = ("page.json", "blocks_page_1.json", "blocks_page_2.json", "table_rows_page_1.json", "table_rows_page_2.json")
MARKUP_PAGE_OVER_API = ("relay_page.json", "markup_blocks.json", "markup_table_rows.json")


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


def page_edited(value):
    page = json.loads(fixture("page.json"))
    return FakeResponse(json.dumps({**page, "last_edited_time": value}).encode("utf-8"))


def last_edited(value):
    _, result = run(page_edited(value), ok("blocks_empty.json"))
    return result["records"]["pages"][0]["last_edited"]


def status(code):
    return urllib.error.HTTPError(BASE, code, "status", email.message.Message(), io.BytesIO(fixture(f"error_{code}.json")))


def client(opener, environ=None):
    environ = {TOKEN_VAR: TOKEN_VALUE} if environ is None else environ
    return notion.api_client(PROVIDER, opener=opener, environ=environ, sleep=lambda seconds: None)


def run(*outcomes, source=SOURCE):
    opener = FakeOpener(outcomes)
    return opener, notion.fetch(source, WINDOW, STORED, [], client(opener))


def read_full_page():
    return run(*(ok(name) for name in FULL_PAGE))


def endpoint(request):
    return request.get_method(), urllib.parse.urlsplit(request.full_url).path


def query(request):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


def unreadable(test, *outcomes):
    with test.assertRaises(_http.SourceUnreadable) as caught:
        run(*outcomes)
    return caught.exception


def collection(result):
    return {
        "schema": 1,
        "source": SOURCE["name"],
        "role": notion.ROLE,
        "provider": "docs",
        "transport": "api",
        "place": "cloud",
        "window": WINDOW,
        "read": True,
        "reason": None,
        **result,
    }


class ClientTest(unittest.TestCase):
    def test_role_is_document_store(self):
        self.assertEqual(notion.ROLE, "document_store")

    def test_sends_the_token_as_a_bearer_header(self):
        opener, _ = run(ok("page.json"), ok("blocks_empty.json"))

        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer " + TOKEN_VALUE)

    def test_sends_the_pinned_api_version(self):
        opener, _ = run(ok("page.json"), ok("blocks_empty.json"))

        self.assertEqual(opener.requests[0].get_header("Notion-version"), "2026-03-11")

    def test_rejects_a_provider_without_the_token(self):
        provider = {"api": {"base_url": BASE, "credentials": {"key": TOKEN_VAR}}}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            notion.api_client(provider, opener=FakeOpener([]))
        self.assertEqual(str(caught.exception), "api.credentials: must name token")

    def test_missing_token_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            notion.fetch(SOURCE, WINDOW, STORED, [], client(FakeOpener([]), environ={}))
        self.assertEqual(str(caught.exception), f"credentials missing: {TOKEN_VAR}")


class PageTest(unittest.TestCase):
    def test_reads_the_page_its_blocks_then_the_table_rows(self):
        opener, _ = read_full_page()

        self.assertEqual(
            [endpoint(request) for request in opener.requests],
            [("GET", PAGE_PATH), ("GET", BLOCKS_PATH), ("GET", BLOCKS_PATH), ("GET", TABLE_PATH), ("GET", TABLE_PATH)],
        )

    def test_title_joins_the_title_typed_property(self):
        _, result = read_full_page()

        self.assertEqual(result["records"]["pages"][0]["title"], "Prod watch sources")

    def test_last_edited_is_utc_without_milliseconds(self):
        _, result = read_full_page()

        self.assertEqual(result["records"]["pages"][0]["last_edited"], "2026-09-04T14:30:00Z")

    def test_page_id_is_the_configured_page_id_not_the_response_id(self):
        _, result = read_full_page()

        self.assertEqual(result["records"]["pages"][0]["id"], PAGE_ID)

    def test_page_without_an_id_has_the_configured_page_id(self):
        _, result = run(ok("page_without_id.json"), ok("blocks_empty.json"))

        self.assertEqual(result["records"]["pages"][0]["id"], PAGE_ID)

    def test_page_without_a_title_property_has_an_empty_title(self):
        _, result = run(ok("page_without_title.json"), ok("blocks_empty.json"))

        self.assertEqual(result["records"]["pages"][0]["title"], "")

    def test_cursor_is_the_page_last_edited(self):
        _, result = read_full_page()

        self.assertEqual(result["cursor"], {"pages": {"sources-page": "2026-09-04T14:30:00Z"}})

    def test_page_link_uses_the_default_host_and_the_id_without_dashes(self):
        _, result = read_full_page()

        self.assertEqual(result["records"]["pages"][0]["link"], "https://www.notion.so/sourcespage")

    def test_page_link_uses_the_links_base_of_the_provider(self):
        source = {**SOURCE, "provider_config": {"links_base": "https://docs.example.test/"}}

        _, result = run(*(ok(name) for name in FULL_PAGE), source=source)

        self.assertEqual(result["records"]["pages"][0]["link"], "https://docs.example.test/sourcespage")

    def test_has_no_entries(self):
        _, result = read_full_page()

        self.assertEqual(result["entries"], {})

    def test_escapes_the_page_id_in_the_path(self):
        source = {**SOURCE, "page_id": "team/sources"}

        opener, _ = run(ok("page.json"), ok("blocks_empty.json"), source=source)

        self.assertEqual(endpoint(opener.requests[0]), ("GET", "/v1/pages/team%2Fsources"))

    def test_page_without_last_edited_makes_the_source_unreadable(self):
        error = unreadable(self, ok("page_without_last_edited.json"))

        self.assertEqual(str(error), f"GET {PAGE_PATH}: response without a valid last_edited_time")

    def test_junk_last_edited_makes_the_source_unreadable(self):
        error = unreadable(self, page_edited("yesterday"))

        self.assertEqual(str(error), f"GET {PAGE_PATH}: response without a valid last_edited_time")

    def test_last_edited_before_year_one_in_utc_makes_the_source_unreadable(self):
        error = unreadable(self, page_edited("0001-01-01T00:30:00+01:00"))

        self.assertEqual(str(error), f"GET {PAGE_PATH}: response without a valid last_edited_time")

    def test_collection_passes_the_role_schema(self):
        _, result = read_full_page()

        self.assertIsNone(roles.validate_collection(collection(result)))


class LastEditedTest(unittest.TestCase):
    def test_drops_a_two_digit_fraction(self):
        self.assertEqual(last_edited("2026-09-04T14:30:00.12Z"), "2026-09-04T14:30:00Z")

    def test_converts_an_offset_to_utc(self):
        self.assertEqual(last_edited("2026-09-04T16:30:00.000+02:00"), "2026-09-04T14:30:00Z")

    def test_reads_a_naive_time_as_utc(self):
        self.assertEqual(last_edited("2026-09-04T14:30:00"), "2026-09-04T14:30:00Z")


class BlocksTest(unittest.TestCase):
    def test_maps_each_block_type_in_page_order(self):
        _, result = read_full_page()

        self.assertEqual(
            [(block["type"], block["text"]) for block in result["records"]["pages"][0]["blocks"]],
            [
                ("heading", "Watch list"),
                ("paragraph", "Sources read on each run."),
                ("list", "Checkout"),
                ("heading", "Mutes"),
                ("table", ""),
                ("list", "Read the monitors"),
                ("list", "Review the mutes"),
                ("paragraph", "Quiet weeks count too."),
                ("paragraph", "Owner: platform"),
                ("paragraph", "Details"),
                ("code", "avg:queue.depth{*}"),
                ("heading", "Notes"),
                ("heading", "Minor"),
                ("paragraph", ""),
                ("other", ""),
                ("other", ""),
            ],
        )

    def test_block_with_a_non_string_type_is_other(self):
        _, result = run(ok("page.json"), ok("blocks_odd_type.json"))

        self.assertEqual(result["records"]["pages"][0]["blocks"], [{"type": "other", "text": "", "rows": None, "checked": None}])

    def test_only_tables_carry_rows(self):
        _, result = read_full_page()

        self.assertEqual(
            [block["type"] for block in result["records"]["pages"][0]["blocks"] if block["rows"] is not None], ["table"]
        )

    def test_table_rows_start_with_the_header_row_across_pages(self):
        _, result = read_full_page()

        self.assertEqual(
            result["records"]["pages"][0]["blocks"][4]["rows"],
            [["key", "until"], ["checkout-p95", "2026-10-30"], ["", "2026-11-01"]],
        )

    def test_first_children_page_asks_for_a_full_page_without_cursor(self):
        opener, _ = read_full_page()

        self.assertEqual(query(opener.requests[1]), {"page_size": ["100"]})

    def test_next_children_page_follows_the_cursor(self):
        opener, _ = read_full_page()

        self.assertEqual(query(opener.requests[2]), {"page_size": ["100"], "start_cursor": ["cursor-2"]})

    def test_table_rows_follow_their_own_cursor(self):
        opener, _ = read_full_page()

        self.assertEqual(query(opener.requests[4]), {"page_size": ["100"], "start_cursor": ["rows-2"]})

    def test_page_cap_makes_the_read_partial(self):
        with self.assertRaises(_http.PartialRead) as caught:
            run(ok("page.json"), *(ok("blocks_more.json") for _ in range(_http.PAGE_CAP)))
        self.assertEqual(str(caught.exception), "partial: page cap")

    def test_stops_requesting_at_the_page_cap(self):
        opener = FakeOpener([ok("page.json"), *(ok("blocks_more.json") for _ in range(_http.PAGE_CAP + 1))])

        with self.assertRaises(_http.PartialRead):
            notion.fetch(SOURCE, WINDOW, STORED, [], client(opener))
        self.assertEqual(len(opener.requests), 1 + _http.PAGE_CAP)

    def test_page_cap_on_table_rows_makes_the_read_partial(self):
        with self.assertRaises(_http.PartialRead) as caught:
            run(ok("page.json"), ok("blocks_table.json"), *(ok("table_rows_more.json") for _ in range(_http.PAGE_CAP)))
        self.assertEqual(str(caught.exception), "partial: page cap")

    def test_table_cells_are_trimmed(self):
        _, result = run(*(ok(name) for name in MARKUP_PAGE_OVER_API))

        self.assertEqual(
            result["records"]["pages"][0]["blocks"][1]["rows"], [["key", "until"], ["checkout-p95", "2026-10-30"]]
        )

    def test_more_pages_without_a_cursor_make_the_read_partial(self):
        with self.assertRaises(_http.PartialRead) as caught:
            run(ok("page.json"), ok("blocks_more_without_cursor.json"))
        self.assertEqual(str(caught.exception), f"partial: GET {BLOCKS_PATH}: has_more without next_cursor")


class ErrorsTest(unittest.TestCase):
    def test_unauthorized_page_makes_the_source_unreadable(self):
        error = unreadable(self, status(401))

        self.assertEqual(str(error), f"HTTP 401 GET {PAGE_PATH}")

    def test_page_not_shared_makes_the_source_unreadable(self):
        error = unreadable(self, status(404))

        self.assertEqual(str(error), f"HTTP 404 GET {PAGE_PATH}")

    def test_children_error_makes_the_source_unreadable(self):
        error = unreadable(self, ok("page.json"), status(403))

        self.assertEqual(str(error), f"HTTP 403 GET {BLOCKS_PATH}")

    def test_table_rows_error_makes_the_source_unreadable(self):
        error = unreadable(self, ok("page.json"), ok("blocks_page_1.json"), ok("blocks_page_2.json"), status(404))

        self.assertEqual(str(error), f"HTTP 404 GET {TABLE_PATH}")

    def test_children_without_results_make_the_source_unreadable(self):
        error = unreadable(self, ok("page.json"), ok("children_without_results.json"))

        self.assertEqual(str(error), f"GET {BLOCKS_PATH}: response without results")

    def test_table_rows_without_results_make_the_source_unreadable(self):
        error = unreadable(self, ok("page.json"), ok("blocks_table.json"), ok("children_without_results.json"))

        self.assertEqual(str(error), f"GET {TABLE_PATH}: response without results")

    def test_table_without_an_id_makes_the_source_unreadable(self):
        error = unreadable(self, ok("page.json"), ok("blocks_table_without_id.json"))

        self.assertEqual(str(error), f"GET {BLOCKS_PATH}: table block 1 without an id")

    def test_server_error_after_the_retry_makes_the_source_unreadable(self):
        error = unreadable(self, status(503), status(503))

        self.assertEqual(str(error), f"HTTP 503 GET {PAGE_PATH}")


RELAY_SOURCE = {**SOURCE, "transport": {"cloud": "mcp", "local": "mcp"}}
CONNECTOR = "docs-connector"
CALL_ID = "sources-1"
SHARED_PAGE_OVER_API = ("relay_page.json", "relay_blocks.json", "relay_table_rows.json")


def saved(name):
    return fixture(name).decode("utf-8")


def fetched(**changes):
    body = json.loads(saved("fetch_page.json"))
    return json.dumps({**body, **changes})


def without(key):
    body = json.loads(saved("fetch_page.json"))
    del body[key]
    return json.dumps(body)


def with_content(markdown):
    text = json.loads(saved("fetch_page.json"))["text"]
    head, rest = text.split("<content>\n", 1)
    _, tail = rest.split("</content>", 1)
    return fetched(text=f"{head}<content>\n{markdown}\n</content>{tail}")


def relay_plan(responses):
    return notion.plan(RELAY_SOURCE, WINDOW, STORED, [], responses, CONNECTOR)


def relay(text):
    return notion.parse(RELAY_SOURCE, WINDOW, STORED, [], {CALL_ID: text}, {CALL_ID: None})


def relay_blocks(markdown):
    return relay(with_content(markdown))["records"]["pages"][0]["blocks"]


def markup_blocks():
    return relay_blocks(saved("markup_content.md"))


def relay_failure(test, text, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        relay(text)
    return caught.exception


def children(*items):
    return FakeResponse(json.dumps({"results": list(items), "has_more": False, "next_cursor": None}).encode("utf-8"))


def paragraph(text):
    return {"type": "paragraph", "text": text, "rows": None, "checked": None}


def table(*rows):
    return {"type": "table", "text": "", "rows": [list(row) for row in rows], "checked": None}


def block(kind, text, checked=None):
    return {"type": kind, "text": text, "rows": None, "checked": checked}


OTHER = {"type": "other", "text": "", "rows": None, "checked": None}
LONG = 60_000
MUTES = [{"key": "checkout-p95", "until": "2026-10-30"}]


class PlanTest(unittest.TestCase):
    def test_first_step_fetches_the_configured_page(self):
        self.assertEqual(
            relay_plan({})["calls"],
            [{"id": CALL_ID, "connector": CONNECTOR, "tool": "notion-fetch", "arguments": {"id": PAGE_ID}, "digest": None}],
        )

    def test_first_step_is_not_done(self):
        self.assertFalse(relay_plan({})["done"])

    def test_saved_page_ends_the_plan(self):
        self.assertEqual(relay_plan({CALL_ID: saved("fetch_page.json")}), {"done": True, "partial": None, "calls": []})


class TransportEqualityTest(unittest.TestCase):
    def test_both_transports_give_the_same_records(self):
        _, over_api = run(*(ok(name) for name in SHARED_PAGE_OVER_API))

        self.assertEqual(state.dump(relay(saved("fetch_page.json"))["records"]), state.dump(over_api["records"]))

    def test_both_transports_give_the_same_cursor(self):
        _, over_api = run(*(ok(name) for name in SHARED_PAGE_OVER_API))

        self.assertEqual(state.dump(relay(saved("fetch_page.json"))["cursor"]), state.dump(over_api["cursor"]))

    def test_shared_page_maps_every_block_in_page_order(self):
        self.assertEqual(
            relay(saved("fetch_page.json"))["records"]["pages"][0]["blocks"],
            [
                {"type": "heading", "text": "Watch list", "rows": None, "checked": None},
                paragraph("Read every run, see the runbook for queue.depth."),
                {"type": "list", "text": "Checkout", "rows": None, "checked": None},
                {"type": "list", "text": "Read the monitors", "rows": None, "checked": None},
                {"type": "list", "text": "Review the mutes", "rows": None, "checked": False},
                {"type": "code", "text": "avg:queue.depth{*}\nby {service}", "rows": None, "checked": None},
                {"type": "heading", "text": "Mutes", "rows": None, "checked": None},
                table(
                    ("key", "until"),
                    ("checkout-p95", "2026-10-30"),
                    ("search & index", "2026-11-01"),
                    ("", "2026-11-02"),
                ),
                OTHER,
                OTHER,
                paragraph("Quiet weeks count too."),
                paragraph(""),
            ],
        )


    def test_formatted_markup_gives_the_same_records_over_both_transports(self):
        _, over_api = run(*(ok(name) for name in MARKUP_PAGE_OVER_API))

        self.assertEqual(relay(with_content(saved("markup_content.md")))["records"], over_api["records"])

    def test_formatted_markup_maps_every_block_in_page_order(self):
        self.assertEqual(
            markup_blocks(),
            [
                block("heading", "Mutes"),
                table(("key", "until"), ("checkout-p95", "2026-10-30")),
                paragraph("\nafter a break"),
                paragraph("Careful with this"),
                OTHER,
                OTHER,
                block("code", "```\ninner\n```"),
                paragraph("R&D and x&ampy, &copy kept"),
                block("list", "Blue item"),
            ],
        )


class CheckedToDoTest(unittest.TestCase):
    TO_DO_BLOCKS = [("Ship the fix", True), ("Review the mutes", False), ("Plain bullet", None), ("Numbered item", None), ("A paragraph", None)]

    def over_api(self, *items):
        _, result = run(ok("page.json"), children(*items))
        return result["records"]["pages"][0]["blocks"]

    def test_both_transports_give_the_same_checked_to_dos(self):
        _, over_api = run(ok("relay_page.json"), ok("todo_blocks.json"))

        self.assertEqual(state.dump(relay(with_content(saved("todo_content.md")))["records"]), state.dump(over_api["records"]))

    def test_api_blocks_carry_true_false_or_null(self):
        _, over_api = run(ok("relay_page.json"), ok("todo_blocks.json"))

        self.assertEqual([(item["text"], item["checked"]) for item in over_api["records"]["pages"][0]["blocks"]], self.TO_DO_BLOCKS)

    def test_connector_blocks_carry_true_false_or_null(self):
        blocks = relay_blocks(saved("todo_content.md"))

        self.assertEqual([(item["text"], item["checked"]) for item in blocks], self.TO_DO_BLOCKS)

    def test_api_to_do_without_a_checked_flag_is_not_checked(self):
        self.assertEqual(self.over_api({"type": "to_do", "to_do": {"rich_text": [{"plain_text": "Open"}]}}), [block("list", "Open", False)])

    def test_api_to_do_with_a_flag_that_is_not_a_boolean_is_not_checked(self):
        item = {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "Open"}], "checked": "true"}}

        self.assertEqual(self.over_api(item), [block("list", "Open", False)])

    def test_connector_upper_case_mark_is_checked(self):
        self.assertEqual(relay_blocks("- [X] Done"), [block("list", "Done", True)])

    def test_connector_star_marker_to_do_is_read(self):
        self.assertEqual(relay_blocks("* [x] Done\n* [ ] Open"), [block("list", "Done", True), block("list", "Open", False)])

    def test_connector_to_do_loses_its_trailing_attributes(self):
        self.assertEqual(relay_blocks('- [x] Done {color="blue"}'), [block("list", "Done", True)])

    def test_connector_bullet_that_looks_like_a_mark_without_a_space_is_a_plain_item(self):
        self.assertEqual(relay_blocks("- [x]Done"), [block("list", "[x]Done", None)])

    def test_connector_empty_to_do_is_read(self):
        self.assertEqual(relay_blocks("- [ ] "), [block("list", "", False)])


class RelayMutesTest(unittest.TestCase):
    def test_mutes_table_under_a_toggle_heading_is_found(self):
        self.assertEqual(evaluate.mutes_table(markup_blocks()), MUTES)

    def test_mutes_table_under_a_colored_heading_is_found(self):
        markdown = (
            '## Mutes {color="red"}\n<table>\n<tr>\n<td>key</td>\n<td>until</td>\n</tr>\n'
            "<tr>\n<td>checkout-p95</td>\n<td>2026-10-30</td>\n</tr>\n</table>"
        )

        self.assertEqual(evaluate.mutes_table(relay_blocks(markdown)), MUTES)


class RelayPageTest(unittest.TestCase):
    def test_page_id_is_the_configured_page_id(self):
        self.assertEqual(relay(saved("fetch_page.json"))["records"]["pages"][0]["id"], PAGE_ID)

    def test_title_comes_from_the_response(self):
        self.assertEqual(relay(saved("fetch_page.json"))["records"]["pages"][0]["title"], "Prod watch sources")

    def test_response_without_a_title_has_an_empty_title(self):
        self.assertEqual(relay(without("title"))["records"]["pages"][0]["title"], "")

    def test_last_edited_is_utc_without_milliseconds(self):
        self.assertEqual(relay(saved("fetch_page.json"))["records"]["pages"][0]["last_edited"], "2026-09-04T14:30:00Z")

    def test_has_no_entries(self):
        self.assertEqual(relay(saved("fetch_page.json"))["entries"], {})

    def test_title_holding_the_content_tag_does_not_start_the_content(self):
        text = json.loads(saved("fetch_page.json"))["text"]
        titled = text.replace('{"title":"Prod watch sources"}', '{"title":"<content> drafts"}')

        self.assertEqual(
            relay(fetched(text=titled))["records"]["pages"][0]["blocks"],
            relay(saved("fetch_page.json"))["records"]["pages"][0]["blocks"],
        )

    def test_content_tag_line_inside_the_properties_does_not_start_the_content(self):
        result = relay(fetched(text="<properties>\n<content>\n</properties>\n<content>\nBody\n</content>"))

        self.assertEqual(result["records"]["pages"][0]["blocks"], [paragraph("Body")])

    def test_zero_unknown_blocks_read_the_page(self):
        self.assertEqual(relay(fetched(unknown_block_count=0))["cursor"], {"pages": {"sources-page": "2026-09-04T14:30:00Z"}})

    def test_page_link_uses_the_links_base_of_the_provider(self):
        source = {**RELAY_SOURCE, "provider_config": {"links_base": "https://docs.example.test"}}

        result = notion.parse(source, WINDOW, STORED, [], {CALL_ID: saved("fetch_page.json")}, {CALL_ID: None})

        self.assertEqual(result["records"]["pages"][0]["link"], "https://docs.example.test/sourcespage")

    def test_collection_passes_the_role_schema(self):
        result = relay(saved("fetch_page.json"))

        self.assertIsNone(roles.validate_collection({**collection(result), "transport": "mcp"}))


class RelayFailureTest(unittest.TestCase):
    def test_truncated_page_makes_the_read_partial(self):
        error = relay_failure(self, fetched(truncated=True), _http.PartialRead)

        self.assertEqual(str(error), "partial: page truncated")

    def test_unknown_blocks_make_the_read_partial(self):
        error = relay_failure(self, fetched(unknown_block_count=2, unknown_block_ids=["b-1", "b-2"]), _http.PartialRead)

        self.assertEqual(str(error), "partial: page truncated")

    def test_response_without_text_names_the_tool(self):
        error = relay_failure(self, without("text"))

        self.assertEqual(str(error), "notion-fetch: response without text")

    def test_response_without_last_edited_names_the_tool(self):
        error = relay_failure(self, without("page_last_edited_at"))

        self.assertEqual(str(error), "notion-fetch: response without a valid page_last_edited_at")

    def test_junk_last_edited_names_the_tool(self):
        error = relay_failure(self, fetched(page_last_edited_at="yesterday"))

        self.assertEqual(str(error), "notion-fetch: response without a valid page_last_edited_at")

    def test_text_without_content_names_the_tool(self):
        error = relay_failure(self, fetched(text="<page>\n</page>"))

        self.assertEqual(str(error), "notion-fetch: response text without a <content> part")

    def test_response_that_is_not_json_names_the_tool(self):
        error = relay_failure(self, "Page not found")

        self.assertEqual(str(error), f"notion-fetch: response {CALL_ID} is not JSON")

    def test_response_that_is_not_an_object_names_the_tool(self):
        error = relay_failure(self, "[]")

        self.assertEqual(str(error), f"notion-fetch: response {CALL_ID} is not a JSON object")

    def test_missing_response_names_the_tool(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            notion.parse(RELAY_SOURCE, WINDOW, STORED, [], {}, {})
        self.assertEqual(str(caught.exception), f"notion-fetch: no response {CALL_ID}")

    def test_unclosed_table_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("## Mutes\n<table>\n<tr>\n<td>key</td>\n</tr>"))

        self.assertEqual(str(error), "notion-fetch: <table> without </table> at content line 2")

    def test_row_without_its_end_tag_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("<table>\n<tr>\n<td>key</td>\n<tr>\n<td>a</td>\n</tr>\n</table>"))

        self.assertEqual(str(error), "notion-fetch: malformed table at content line 1")

    def test_cell_without_its_end_tag_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("<table>\n<tr>\n<td>key\n<td>until</td>\n</tr>\n</table>"))

        self.assertEqual(str(error), "notion-fetch: malformed table at content line 1")

    def test_extra_cell_end_tag_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("<table>\n<tr>\n<td>key</td></td>\n</tr>\n</table>"))

        self.assertEqual(str(error), "notion-fetch: malformed table at content line 1")

    def test_extra_row_end_tag_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("<table>\n<tr>\n<td>key</td>\n</tr>\n</tr>\n</table>"))

        self.assertEqual(str(error), "notion-fetch: malformed table at content line 1")

    def test_unclosed_equation_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("$$\nE = mc^2"))

        self.assertEqual(str(error), "notion-fetch: equation without its end at content line 1")

    def test_unclosed_code_fence_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("Intro\n```\navg:queue.depth{*}"))

        self.assertEqual(str(error), "notion-fetch: code fence without its end at content line 2")

    def test_unclosed_block_tag_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content('<callout icon="x">\n\tNote'))

        self.assertEqual(str(error), "notion-fetch: <callout> without </callout> at content line 1")


class RelayMarkupTest(unittest.TestCase):
    def test_heading_levels_one_to_four_are_headings(self):
        self.assertEqual(
            [block["type"] for block in relay_blocks("# One\n## Two\n### Three\n#### Four")], ["heading"] * 4
        )

    def test_list_markers_are_stripped(self):
        self.assertEqual(
            [block["text"] for block in relay_blocks("- dash\n* star\n12. number\n- [ ] open\n- [x] done")],
            ["dash", "star", "number", "open", "done"],
        )

    def test_crlf_lines_give_the_same_blocks_as_lf_lines(self):
        markdown = "## Mutes\n<table>\n<tr>\n<td>key</td>\n</tr>\n</table>\n```\nline one\nline two\n```\nDone."

        self.assertEqual(relay_blocks(markdown.replace("\n", "\r\n")), relay_blocks(markdown))

    def test_crlf_lines_inside_code_join_with_lf(self):
        self.assertEqual(relay_blocks("```\r\nline one\r\nline two\r\n```")[0]["text"], "line one\nline two")

    def test_html_entities_in_text_are_unescaped(self):
        self.assertEqual(relay_blocks("Fish &amp; chips &lt;3 &quot;daily&quot;"), [paragraph('Fish & chips <3 "daily"')])

    def test_html_entities_in_cells_are_unescaped(self):
        self.assertEqual(relay_blocks("<table>\n<tr>\n<td>a &amp; b</td>\n</tr>\n</table>"), [table(("a & b",))])

    def test_line_break_in_a_cell_becomes_a_newline(self):
        self.assertEqual(
            relay_blocks("<table>\n<tr>\n<td>owner<br>platform<br/>team</td>\n</tr>\n</table>"),
            [table(("owner\nplatform\nteam",))],
        )

    def test_tags_inside_a_cell_are_stripped(self):
        self.assertEqual(
            relay_blocks('<table>\n<tr>\n<td><span color="red">**checkout**</span></td>\n</tr>\n</table>'),
            [table(("checkout",))],
        )

    def test_cell_text_is_trimmed(self):
        self.assertEqual(relay_blocks("<table>\n<tr>\n<td>\n key \n</td>\n</tr>\n</table>"), [table(("key",))])

    def test_table_on_one_line_keeps_its_rows(self):
        self.assertEqual(
            relay_blocks("<table><tr><td>key</td><td>until</td></tr><tr><td>a</td><td>b</td></tr></table>"),
            [table(("key", "until"), ("a", "b"))],
        )

    def test_column_settings_do_not_add_rows(self):
        markdown = '<table header-row="true">\n<colgroup>\n<col color="gray"/>\n</colgroup>\n<tr>\n<td>key</td>\n</tr>\n</table>'

        self.assertEqual(relay_blocks(markdown), [table(("key",))])

    def test_self_closing_tag_is_other(self):
        self.assertEqual(relay_blocks("<table_of_contents/>"), [OTHER])

    def test_block_tag_with_children_is_one_other_block(self):
        self.assertEqual(relay_blocks('<callout icon="x">\n\tNote\n</callout>\nAfter'), [OTHER, paragraph("After")])

    def test_block_tag_closed_on_its_line_is_other(self):
        self.assertEqual(relay_blocks('<page url="https://docs.example.test/child">Child</page>'), [OTHER])

    def test_indented_children_are_not_read(self):
        self.assertEqual(relay_blocks("Parent\n\tChild\n\t\tGrandchild\nNext"), [paragraph("Parent"), paragraph("Next")])

    def test_content_on_the_content_tag_line_is_read(self):
        result = relay(fetched(text="<content>Inline</content>"))

        self.assertEqual(result["records"]["pages"][0]["blocks"], [paragraph("Inline")])

    def test_blank_lines_are_not_blocks(self):
        self.assertEqual(relay_blocks("One\n\n\nTwo"), [paragraph("One"), paragraph("Two")])

    def test_inline_formatting_reduces_to_plain_text(self):
        self.assertEqual(
            relay_blocks(r"**bold** *italic* ~~gone~~ `code` [link](https://docs.example.test/x) \*star\*"),
            [paragraph("bold italic gone code link *star*")],
        )

    def test_code_span_content_stays_literal(self):
        self.assertEqual(relay_blocks("`a*b*c`"), [paragraph("a*b*c")])

    def test_lone_asterisks_stay_in_text(self):
        self.assertEqual(relay_blocks("avg:queue.depth{*} and 2 * 3 * 4"), [paragraph("avg:queue.depth{*} and 2 * 3 * 4")])

    def test_code_block_content_stays_literal(self):
        self.assertEqual(relay_blocks("```python\n**x** &amp; <b>\n```")[0]["text"], "**x** &amp; <b>")

    def test_four_backtick_fence_keeps_inner_fences(self):
        self.assertEqual(relay_blocks("````markdown\n```\ninner\n```\n````"), [block("code", "```\ninner\n```")])

    def test_line_starting_with_a_line_break_is_a_paragraph(self):
        self.assertEqual(relay_blocks("<br>text"), [paragraph("\ntext")])

    def test_line_starting_with_a_date_mention_is_a_paragraph(self):
        blocks = relay_blocks('<mention-date start="2026-01-01"/> freeze starts')

        self.assertEqual(blocks, [paragraph(" freeze starts")])

    def test_line_starting_with_a_colored_span_is_a_paragraph(self):
        self.assertEqual(relay_blocks('<span color="red">Careful</span> with this'), [paragraph("Careful with this")])

    def test_line_starting_with_a_user_mention_is_a_paragraph(self):
        self.assertEqual(relay_blocks('<mention-user url="u">Ann</mention-user> owns it'), [paragraph("Ann owns it")])

    def test_heading_attributes_are_not_heading_text(self):
        blocks = relay_blocks('## Mutes {toggle="true"}\n## Mutes {color="red"}')

        self.assertEqual([item["text"] for item in blocks], ["Mutes", "Mutes"])

    def test_list_quote_and_paragraph_attributes_are_not_text(self):
        markdown = '- item {color="blue"}\n> quoted {color="gray_bg"}\nPlain {color="red" toggle="false"}'

        self.assertEqual([item["text"] for item in relay_blocks(markdown)], ["item", "quoted", "Plain"])

    def test_braces_that_are_not_attributes_stay_in_text(self):
        self.assertEqual(relay_blocks("Group by {service}"), [paragraph("Group by {service}")])

    def test_bare_ampersands_stay_in_text(self):
        self.assertEqual(relay_blocks("R&D x&ampy &copy"), [paragraph("R&D x&ampy &copy")])

    def test_unknown_entity_name_stays_in_text(self):
        self.assertEqual(relay_blocks("&notit;"), [paragraph("&notit;")])

    def test_numeric_entities_are_unescaped(self):
        self.assertEqual(relay_blocks("&#38; &#x26;"), [paragraph("& &")])

    def test_equation_block_is_other(self):
        self.assertEqual(relay_blocks("$$\nE = mc^2\n$$\nAfter"), [OTHER, paragraph("After")])

    def test_one_line_equation_is_other(self):
        self.assertEqual(relay_blocks("$$E = mc^2$$"), [OTHER])

    def test_image_line_is_other(self):
        self.assertEqual(relay_blocks("![diagram](https://docs.example.test/diagram.png)"), [OTHER])


class RelayLongLineTest(unittest.TestCase):
    def test_long_line_of_unclosed_italics_stays_literal(self):
        line = " ".join(["*a"] * (LONG // 3))

        self.assertEqual(relay_blocks(line), [paragraph(line)])

    def test_long_line_of_open_brackets_stays_literal(self):
        line = "[" * LONG

        self.assertEqual(relay_blocks(line), [paragraph(line)])

    def test_long_line_of_unclosed_links_stays_literal(self):
        line = "[a](" * (LONG // 4)

        self.assertEqual(relay_blocks(line), [paragraph(line)])

    def test_long_line_of_unclosed_attribute_groups_stays_literal(self):
        line = " ".join(['{a="b"'] * (LONG // 7))

        self.assertEqual(relay_blocks(line), [paragraph(line)])

    def test_long_table_line_of_unclosed_rows_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("<table>" + "<tr>" * (LONG // 4) + "</table>"))

        self.assertEqual(str(error), "notion-fetch: malformed table at content line 1")

    def test_long_table_line_of_unclosed_cells_makes_the_source_unreadable(self):
        error = relay_failure(self, with_content("<table><tr>" + "<td>" * (LONG // 4) + "</tr></table>"))

        self.assertEqual(str(error), "notion-fetch: malformed table at content line 1")


def served_json(document):
    return FakeResponse(json.dumps(document).encode("utf-8"))


def page_with_tables(count):
    blocks = {"results": [{"type": "table", "id": f"table-{index}"} for index in range(count)], "has_more": False}
    return [ok("page.json"), served_json(blocks), *(served_json({"results": [], "has_more": False}) for _ in range(count))]


class RequestCapTest(unittest.TestCase):
    def test_reads_a_page_that_takes_exactly_50_requests(self):
        _, result = run(*page_with_tables(48))

        self.assertEqual(len(result["records"]["pages"][0]["blocks"]), 48)

    def test_page_that_needs_more_than_50_requests_is_a_partial_read(self):
        with self.assertRaises(_http.PartialRead) as caught:
            run(*page_with_tables(49))
        self.assertEqual(str(caught.exception), "partial: request cap")


def node(block_type, block_id=None, children=False, **body):
    return {"object": "block", "id": block_id, "type": block_type, "has_children": children, block_type: body}


def text_node(block_type, text, block_id=None, children=False, **body):
    return node(block_type, block_id, children, rich_text=[{"plain_text": text}], **body)


def row(*cells):
    return node("table_row", cells=[[{"plain_text": cell}] for cell in cells])


def listing(items, next_cursor=None):
    return {"results": items, "has_more": next_cursor is not None, "next_cursor": next_cursor}


class TreeOpener:
    def __init__(self, listings):
        self.listings = listings
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        _, path = endpoint(request)
        if path == PAGE_PATH:
            return ok("page.json")
        parent_id = path.split("/")[3]
        cursor = query(request).get("start_cursor", [None])[0]
        found = self.listings[parent_id if cursor is None else (parent_id, cursor)]
        return served_json(found if isinstance(found, dict) else listing(found))

    def parents(self):
        return [endpoint(request)[1].split("/")[3] for request in self.requests[1:]]


def read_tree(listings):
    opener = TreeOpener(listings)
    result = notion.fetch(SOURCE, WINDOW, STORED, [], client(opener))
    return opener, result["records"]["pages"][0]["blocks"]


def shapes(blocks):
    return [(record["type"], record["text"]) for record in blocks]


def toggles(count, children=None):
    listings = {PAGE_ID: [text_node("toggle", f"Toggle {number}", f"tg-{number}", True) for number in range(count)]}
    listings.update({f"tg-{number}": [text_node("paragraph", f"Inside {number}")] for number in range(count)})
    return {**listings, **(children or {})}


class NestedBlocksTest(unittest.TestCase):
    def test_toggle_heading_is_followed_by_the_paragraphs_under_it(self):
        opener, blocks = read_tree(
            {
                PAGE_ID: [text_node("heading_1", "Summary", "h-one", True), text_node("paragraph", "After")],
                "h-one": [text_node("paragraph", "First"), text_node("paragraph", "Second")],
            }
        )

        self.assertEqual(
            shapes(blocks), [("heading", "Summary"), ("paragraph", "First"), ("paragraph", "Second"), ("paragraph", "After")]
        )
        self.assertEqual(opener.parents(), [PAGE_ID, "h-one"])

    def test_toggle_reads_as_a_paragraph_followed_by_its_children(self):
        _, blocks = read_tree(
            {PAGE_ID: [text_node("toggle", "Details", "tg", True)], "tg": [text_node("paragraph", "Inside")]}
        )

        self.assertEqual(shapes(blocks), [("paragraph", "Details"), ("paragraph", "Inside")])

    def test_callout_reads_as_a_paragraph_followed_by_its_children(self):
        opener, blocks = read_tree(
            {
                PAGE_ID: [text_node("callout", "Owner", "co", True), text_node("callout", "Alone")],
                "co": [text_node("bulleted_list_item", "Detail")],
            }
        )

        self.assertEqual(shapes(blocks), [("paragraph", "Owner"), ("list", "Detail"), ("paragraph", "Alone")])
        self.assertEqual(opener.parents(), [PAGE_ID, "co"])

    def test_original_synced_block_adds_only_its_children(self):
        opener, blocks = read_tree(
            {
                PAGE_ID: [node("synced_block", "sy", True, synced_from=None)],
                "sy": [text_node("heading_1", "Shared", "sy-h", True)],
                "sy-h": [text_node("paragraph", "Under shared")],
            }
        )

        self.assertEqual(shapes(blocks), [("heading", "Shared"), ("paragraph", "Under shared")])
        self.assertEqual(opener.parents(), [PAGE_ID, "sy", "sy-h"])

    def test_reference_synced_block_reads_the_children_of_its_original(self):
        reference = node("synced_block", "ref", True, synced_from={"type": "block_id", "block_id": "sy"})
        opener, blocks = read_tree({PAGE_ID: [reference], "sy": [text_node("paragraph", "Shared text")]})

        self.assertEqual(shapes(blocks), [("paragraph", "Shared text")])
        self.assertEqual(opener.parents(), [PAGE_ID, "sy"])

    def test_column_list_adds_the_children_of_each_column(self):
        opener, blocks = read_tree(
            {
                PAGE_ID: [node("column_list", "cl", True)],
                "cl": [node("column", "c-one", True), node("column", "c-two", True)],
                "c-one": [text_node("paragraph", "Left")],
                "c-two": [text_node("paragraph", "Right")],
            }
        )

        self.assertEqual(shapes(blocks), [("paragraph", "Left"), ("paragraph", "Right")])
        self.assertEqual(opener.parents(), [PAGE_ID, "cl", "c-one", "c-two"])

    def test_list_item_is_followed_by_its_nested_items_depth_first(self):
        opener, blocks = read_tree(
            {
                PAGE_ID: [text_node("bulleted_list_item", "Parent", "li", True), text_node("bulleted_list_item", "Sibling")],
                "li": [text_node("numbered_list_item", "Child", "li-c", True)],
                "li-c": [text_node("to_do", "Grandchild", checked=True)],
            }
        )

        self.assertEqual(
            blocks,
            [block("list", "Parent"), block("list", "Child"), block("list", "Grandchild", True), block("list", "Sibling")],
        )
        self.assertEqual(opener.parents(), [PAGE_ID, "li", "li-c"])

    def test_nesting_stops_at_four_levels_without_an_error(self):
        listings = {PAGE_ID: [text_node("toggle", "Level 1", "t1", True)]}
        for level in range(1, 6):
            listings[f"t{level}"] = [text_node("toggle", f"Level {level + 1}", f"t{level + 1}", True)]

        opener, blocks = read_tree(listings)

        self.assertEqual([record["text"] for record in blocks], ["Level 1", "Level 2", "Level 3", "Level 4"])
        self.assertEqual(opener.parents(), [PAGE_ID, "t1", "t2", "t3"])

    def test_child_pages_and_databases_stay_other_without_a_children_read(self):
        opener, blocks = read_tree(
            {
                PAGE_ID: [
                    node("child_page", "cp", True, title="Archive"),
                    node("child_database", "cd", True, title="Tasks"),
                    node("link_to_page", "lp", True, type="page_id", page_id="linked"),
                    node("unsupported", "un", True),
                ]
            }
        )

        self.assertEqual(blocks, [OTHER] * 4)
        self.assertEqual(opener.parents(), [PAGE_ID])

    def test_nested_children_follow_their_next_cursor(self):
        opener, blocks = read_tree(
            {
                PAGE_ID: [text_node("toggle", "Details", "tg", True)],
                "tg": listing([text_node("paragraph", "One")], "more-1"),
                ("tg", "more-1"): [text_node("paragraph", "Two")],
            }
        )

        self.assertEqual(shapes(blocks), [("paragraph", "Details"), ("paragraph", "One"), ("paragraph", "Two")])
        self.assertEqual(query(opener.requests[3]), {"page_size": ["100"], "start_cursor": ["more-1"]})

    def test_table_under_a_toggle_keeps_its_rows(self):
        _, blocks = read_tree(
            {
                PAGE_ID: [text_node("toggle", "Details", "tg", True)],
                "tg": [node("table", "tb", True)],
                "tb": [row("key", "until"), row("checkout-p95", "2026-10-30")],
            }
        )

        self.assertEqual(blocks[1], table(("key", "until"), ("checkout-p95", "2026-10-30")))

    def test_children_reads_up_to_the_request_cap_are_read(self):
        _, blocks = read_tree(toggles(48))

        self.assertEqual(len(blocks), 96)

    def test_children_reads_beyond_the_request_cap_are_a_partial_read(self):
        opener = TreeOpener(toggles(49))

        with self.assertRaises(_http.PartialRead) as caught:
            notion.fetch(SOURCE, WINDOW, STORED, [], client(opener))
        self.assertEqual(str(caught.exception), "partial: request cap")
        self.assertEqual(len(opener.requests), 50)

    def test_pages_of_nested_children_count_against_the_request_cap(self):
        paged = {"tg-0": listing([text_node("paragraph", "One")], "more-1"), ("tg-0", "more-1"): []}

        with self.assertRaises(_http.PartialRead) as caught:
            read_tree(toggles(48, paged))
        self.assertEqual(str(caught.exception), "partial: request cap")

    def test_block_with_children_but_no_id_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            read_tree({PAGE_ID: [text_node("toggle", "Details", None, True)]})
        self.assertEqual(str(caught.exception), f"GET {BLOCKS_PATH}: toggle block 0 without an id")

    def test_reference_synced_block_without_its_original_id_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            read_tree({PAGE_ID: [node("synced_block", "ref", True, synced_from={"type": "block_id"})]})
        self.assertEqual(str(caught.exception), f"GET {BLOCKS_PATH}: synced_block block 0 without an id")


ONE, TWO, THREE = "page-one", "page-two", "page-three"
LIST_SOURCE = {"name": "docs", "provider": "docs", "transport": TRANSPORT, "pages": [ONE, TWO, THREE]}
LIST_RELAY_SOURCE = {**LIST_SOURCE, "transport": {"cloud": "mcp", "local": "mcp"}}
TWO_PAGES = {**LIST_SOURCE, "pages": [ONE, TWO]}
DOCUMENTS = {
    ONE: {
        "title": "First page",
        "edited": "2026-09-04T14:30:41.123Z",
        "blocks": [("heading", "Overview"), ("paragraph", "Alpha"), ("list", "Beta")],
    },
    TWO: {"title": "Second page", "edited": "2026-09-05T08:15:59.000Z", "blocks": [("paragraph", "Gamma")]},
    THREE: {"title": "Third page", "edited": "2026-09-06T21:00:00.000Z", "blocks": [("heading", "Notes"), ("paragraph", "Delta")]},
}
API_TYPES = {"heading": "heading_1", "paragraph": "paragraph", "list": "bulleted_list_item"}
MARKDOWN = {"heading": "# ", "paragraph": "", "list": "- "}
SAME_MINUTE_AS_ONE = "2026-09-04T14:30:07Z"
SAME_MINUTE_AS_TWO = "2026-09-05T08:15:02Z"
SAME_MINUTE_AS_THREE = "2026-09-06T21:00:30Z"
MINUTE_BEFORE_ONE = "2026-09-04T14:29:59Z"
MINUTE_AFTER_ONE = "2026-09-04T14:31:00Z"
READ = {"status": "ok", "reason": None}
TRUNCATED = {"status": "failed", "reason": "partial: page truncated"}
NOT_A_PAGE = {"status": "failed", "reason": "not a page"}
UNCHANGED = {"status": "deferred", "reason": "unchanged"}
NOT_SHARED = {"status": "failed", "reason": "not found or not shared"}


def stored_pages(**by_page):
    return {"pages": {page_id.replace("_", "-"): edited for page_id, edited in by_page.items()}}


def api_meta(page_id):
    document = DOCUMENTS[page_id]
    title = [{"type": "text", "plain_text": document["title"]}]
    properties = {"Name": {"id": "title", "type": "title", "title": title}}
    page = json.loads(fixture("page.json"))
    return served_json({**page, "last_edited_time": document["edited"], "properties": properties})


def api_blocks(page_id):
    items = [
        {"object": "block", "id": f"{page_id}-{index}", "type": API_TYPES[kind], API_TYPES[kind]: {"rich_text": [{"plain_text": text}]}}
        for index, (kind, text) in enumerate(DOCUMENTS[page_id]["blocks"])
    ]
    return served_json({"results": items, "has_more": False})


def api_read(page_id):
    return [api_meta(page_id), api_blocks(page_id)]


def connector_page(page_id):
    document = DOCUMENTS[page_id]
    content = "\n".join(MARKDOWN[kind] + text for kind, text in document["blocks"])
    body = json.loads(with_content(content))
    return json.dumps({**body, "title": document["title"], "page_last_edited_at": document["edited"]})


def blocks_of(page_id):
    return [block(kind, text) for kind, text in DOCUMENTS[page_id]["blocks"]]


def page_flagged(**flags):
    page = json.loads(fixture("page.json"))
    return FakeResponse(json.dumps({**page, **flags}).encode("utf-8"))


def listed_over_api(cursor, *outcomes, source=LIST_SOURCE):
    opener = FakeOpener(outcomes)
    return opener, notion.fetch(source, WINDOW, cursor, [], client(opener))


def listed_responses(*texts):
    return {f"docs-{number}": text for number, text in enumerate(texts, 1)}


def listed_plan(*texts):
    return notion.plan(LIST_RELAY_SOURCE, WINDOW, None, [], listed_responses(*texts), CONNECTOR)


def listed_over_relay(cursor, *texts):
    responses = listed_responses(*texts)
    return notion.parse(LIST_RELAY_SOURCE, WINDOW, cursor, [], responses, {call_id: None for call_id in responses})


def truncated_page(page_id, **changes):
    return json.dumps({**json.loads(connector_page(page_id)), "truncated": True, **changes})


def listed_failure(test, cursor, *texts):
    with test.assertRaises(_http.SourceUnreadable) as caught:
        listed_over_relay(cursor, *texts)
    return caught.exception


class ListedApiTest(unittest.TestCase):
    def test_reads_each_changed_page_in_the_configured_order(self):
        opener, _ = listed_over_api(None, *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(
            [endpoint(request)[1] for request in opener.requests],
            [
                "/v1/pages/page-one",
                "/v1/blocks/page-one/children",
                "/v1/pages/page-two",
                "/v1/blocks/page-two/children",
                "/v1/pages/page-three",
                "/v1/blocks/page-three/children",
            ],
        )

    def test_records_follow_the_configured_page_order(self):
        _, result = listed_over_api(None, *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [ONE, TWO, THREE])

    def test_record_holds_the_title_edit_time_link_and_blocks(self):
        _, result = listed_over_api(None, *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(
            result["records"]["pages"][0],
            {
                "id": ONE,
                "title": "First page",
                "last_edited": "2026-09-04T14:30:41Z",
                "link": "https://www.notion.so/pageone",
                "blocks": blocks_of(ONE),
            },
        )

    def test_page_without_a_cursor_is_read_whole(self):
        _, result = listed_over_api(stored_pages(page_two=SAME_MINUTE_AS_TWO), *api_read(ONE), api_meta(TWO), *api_read(THREE))

        self.assertEqual(result["entries"][ONE], READ)

    def test_no_stored_cursor_reads_every_page(self):
        _, result = listed_over_api({"pages": {}}, *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(result["entries"], {ONE: READ, TWO: READ, THREE: READ})

    def test_page_edited_in_the_cursor_minute_is_unchanged(self):
        _, result = listed_over_api(stored_pages(page_one=SAME_MINUTE_AS_ONE), api_meta(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(result["entries"][ONE], UNCHANGED)

    def test_unchanged_page_gives_no_record(self):
        _, result = listed_over_api(stored_pages(page_one=SAME_MINUTE_AS_ONE), api_meta(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [TWO, THREE])

    def test_unchanged_page_costs_only_its_metadata_request(self):
        opener, _ = listed_over_api(stored_pages(page_one=SAME_MINUTE_AS_ONE), api_meta(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(len(opener.requests), 5)

    def test_unchanged_page_keeps_its_stored_edit_time(self):
        _, result = listed_over_api(stored_pages(page_one=SAME_MINUTE_AS_ONE), api_meta(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(result["cursor"]["pages"][ONE], SAME_MINUTE_AS_ONE)

    def test_page_edited_in_a_later_minute_than_its_cursor_is_read(self):
        _, result = listed_over_api(stored_pages(page_one=MINUTE_BEFORE_ONE), *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(result["entries"][ONE], READ)

    def test_page_edited_in_an_earlier_minute_than_its_cursor_is_read(self):
        _, result = listed_over_api(stored_pages(page_one=MINUTE_AFTER_ONE), *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(result["entries"][ONE], READ)

    def test_read_page_moves_its_cursor_to_its_edit_time(self):
        _, result = listed_over_api(stored_pages(page_one=MINUTE_BEFORE_ONE), *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(result["cursor"]["pages"][ONE], "2026-09-04T14:30:41Z")

    def test_missing_page_is_a_failed_entry(self):
        _, result = listed_over_api(None, *api_read(ONE), status(404), *api_read(THREE))

        self.assertEqual(result["entries"], {ONE: READ, TWO: NOT_SHARED, THREE: READ})

    def test_other_pages_are_still_read_next_to_a_missing_one(self):
        _, result = listed_over_api(None, *api_read(ONE), status(404), *api_read(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [ONE, THREE])

    def test_missing_page_keeps_its_stored_edit_time(self):
        _, result = listed_over_api(stored_pages(page_two=SAME_MINUTE_AS_TWO), *api_read(ONE), status(404), *api_read(THREE))

        self.assertEqual(result["cursor"]["pages"][TWO], SAME_MINUTE_AS_TWO)

    def test_missing_page_never_read_has_no_cursor(self):
        _, result = listed_over_api(None, *api_read(ONE), status(404), *api_read(THREE))

        self.assertEqual(sorted(result["cursor"]["pages"]), [ONE, THREE])

    def test_cursor_follows_the_configured_pages_only(self):
        _, result = listed_over_api(stored_pages(page_gone=SAME_MINUTE_AS_ONE), *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(list(result["cursor"]["pages"]), [ONE, TWO, THREE])

    def test_forbidden_page_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            listed_over_api(None, *api_read(ONE), status(403))
        self.assertEqual(str(caught.exception), "HTTP 403 GET /v1/pages/page-two")

    def test_unauthorized_page_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            listed_over_api(None, *api_read(ONE), status(401))
        self.assertEqual(str(caught.exception), "HTTP 401 GET /v1/pages/page-two")

    def test_database_id_is_a_failed_entry(self):
        _, result = listed_over_api(None, *api_read(ONE), status(400), *api_read(THREE))

        self.assertEqual(result["entries"], {ONE: READ, TWO: NOT_A_PAGE, THREE: READ})

    def test_other_pages_are_still_read_next_to_a_database(self):
        opener, result = listed_over_api(None, *api_read(ONE), status(400), *api_read(THREE))

        self.assertEqual((len(opener.requests), [page["id"] for page in result["records"]["pages"]]), (5, [ONE, THREE]))

    def test_database_id_keeps_its_stored_edit_time(self):
        cursor = stored_pages(page_two=SAME_MINUTE_AS_TWO)

        _, result = listed_over_api(cursor, *api_read(ONE), status(400), *api_read(THREE))

        self.assertEqual(result["cursor"]["pages"][TWO], SAME_MINUTE_AS_TWO)

    def test_database_id_never_read_has_no_cursor(self):
        _, result = listed_over_api(None, *api_read(ONE), status(400), *api_read(THREE))

        self.assertEqual(list(result["cursor"]["pages"]), [ONE, THREE])

    def test_database_collection_passes_the_role_schema(self):
        _, result = listed_over_api(None, *api_read(ONE), status(400), *api_read(THREE))

        self.assertIsNone(roles.validate_collection({**collection(result), "source": "docs"}))

    def test_page_in_the_trash_is_a_failed_entry(self):
        _, result = listed_over_api(None, *api_read(ONE), page_flagged(in_trash=True), *api_read(THREE))

        self.assertEqual(result["entries"], {ONE: READ, TWO: NOT_SHARED, THREE: READ})

    def test_archived_page_is_a_failed_entry(self):
        _, result = listed_over_api(None, *api_read(ONE), page_flagged(archived=True), *api_read(THREE))

        self.assertEqual(result["entries"][TWO], NOT_SHARED)

    def test_page_in_the_trash_is_not_read(self):
        opener, result = listed_over_api(None, *api_read(ONE), page_flagged(in_trash=True), *api_read(THREE))

        self.assertEqual((len(opener.requests), [page["id"] for page in result["records"]["pages"]]), (5, [ONE, THREE]))

    def test_page_in_the_trash_in_the_cursor_minute_is_a_failed_entry(self):
        cursor = stored_pages(page_two="2026-09-04T14:30:07Z")

        _, result = listed_over_api(cursor, *api_read(ONE), page_flagged(in_trash=True), *api_read(THREE))

        self.assertEqual((result["entries"][TWO], result["cursor"]["pages"][TWO]), (NOT_SHARED, "2026-09-04T14:30:07Z"))

    def test_page_flags_set_to_false_do_not_hide_the_page(self):
        _, result = listed_over_api(None, *api_read(ONE), page_flagged(in_trash=False, archived=False), api_blocks(TWO), *api_read(THREE))

        self.assertEqual(result["entries"][TWO], READ)

    def test_returned_entries_are_not_shared_between_calls(self):
        _, first = listed_over_api(None, *api_read(ONE), *api_read(TWO), *api_read(THREE))
        first["entries"][ONE]["status"] = "failed"

        _, second = listed_over_api(None, *api_read(ONE), *api_read(TWO), *api_read(THREE))

        self.assertEqual(second["entries"][ONE], READ)

    def test_returned_entries_of_unchanged_and_missing_pages_are_copies(self):
        cursor = stored_pages(page_one=SAME_MINUTE_AS_ONE)
        _, first = listed_over_api(cursor, api_meta(ONE), status(404), *api_read(THREE))
        first["entries"][ONE]["reason"] = "changed"
        first["entries"][TWO]["reason"] = "changed"

        _, second = listed_over_api(cursor, api_meta(ONE), status(404), *api_read(THREE))

        self.assertEqual((second["entries"][ONE], second["entries"][TWO]), (UNCHANGED, NOT_SHARED))

    def test_server_error_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            listed_over_api(None, status(503), status(503))
        self.assertEqual(str(caught.exception), "HTTP 503 GET /v1/pages/page-one")

    def test_missing_block_list_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            listed_over_api(None, api_meta(ONE), status(404))
        self.assertEqual(str(caught.exception), "HTTP 404 GET /v1/blocks/page-one/children")

    def test_junk_edit_time_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            listed_over_api(None, *api_read(ONE), page_edited("yesterday"))
        self.assertEqual(str(caught.exception), "GET /v1/pages/page-two: response without a valid last_edited_time")

    def test_collection_passes_the_role_schema(self):
        _, result = listed_over_api(stored_pages(page_two=SAME_MINUTE_AS_TWO), *api_read(ONE), api_meta(TWO), status(404))

        self.assertIsNone(roles.validate_collection({**collection(result), "source": "docs"}))


class ListedRequestCapTest(unittest.TestCase):
    def test_requests_are_counted_across_the_pages_of_a_source(self):
        opener, _ = listed_over_api(stored_pages(page_two=SAME_MINUTE_AS_TWO), *page_with_tables(47), api_meta(TWO), source=TWO_PAGES)

        self.assertEqual(len(opener.requests), 50)

    def test_pages_that_take_more_than_50_requests_together_are_a_partial_read(self):
        with self.assertRaises(_http.PartialRead) as caught:
            listed_over_api(None, *page_with_tables(47), *api_read(TWO), source=TWO_PAGES)
        self.assertEqual(str(caught.exception), "partial: request cap")

    def test_a_missing_page_counts_as_a_request(self):
        cursor = stored_pages(page_three=SAME_MINUTE_AS_THREE)

        with self.assertRaises(_http.PartialRead) as caught:
            listed_over_api(cursor, *page_with_tables(47), status(404), api_meta(THREE))
        self.assertEqual(str(caught.exception), "partial: request cap")


EDITED_WINDOW = {"from_ts": 1788220800, "to_ts": 1790726400}
EDITOR = "user-editor"
OTHER_EDITOR = "user-other"
EDITED_SOURCE = {"name": "docs", "provider": "docs", "transport": TRANSPORT, "edited_by": EDITOR}
BEFORE_THE_WINDOW = "2026-08-31T23:59:59.000Z"
AFTER_THE_WINDOW = "2026-10-01T00:00:00.000Z"
SEARCH_PATH = "/v1/search"
SEARCH_BODY = {
    "filter": {"property": "object", "value": "page"},
    "sort": {"timestamp": "last_edited_time", "direction": "descending"},
    "page_size": 100,
}


def hit(page_id, edited=None, by=EDITOR):
    edited = edited or DOCUMENTS[page_id]["edited"]
    return {"object": "page", "id": page_id, "last_edited_time": edited, "last_edited_by": {"object": "user", "id": by}}


def search_page(*hits, next_cursor=None):
    return served_json({"object": "list", "results": list(hits), "has_more": next_cursor is not None, "next_cursor": next_cursor})


def edited_over_api(*outcomes, source=EDITED_SOURCE, cursor=None):
    opener = FakeOpener(outcomes)
    return opener, notion.fetch(source, EDITED_WINDOW, cursor, [], client(opener))


def search_bodies(opener):
    return [json.loads(request.data) for request in opener.requests if endpoint(request) == ("POST", SEARCH_PATH)]


def edited_failure(test, *outcomes, source=EDITED_SOURCE, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        edited_over_api(*outcomes, source=source)
    return caught.exception


class EditedByApiTest(unittest.TestCase):
    def test_searches_pages_by_last_edited_time_newest_first(self):
        opener, _ = edited_over_api(search_page())

        self.assertEqual(search_bodies(opener), [SEARCH_BODY])

    def test_next_search_page_follows_the_cursor(self):
        opener, _ = edited_over_api(search_page(next_cursor="cursor-1"), search_page())

        self.assertEqual(search_bodies(opener), [SEARCH_BODY, {**SEARCH_BODY, "start_cursor": "cursor-1"}])

    def test_paging_stops_at_the_first_page_older_than_the_window_start(self):
        opener, _ = edited_over_api(
            search_page(hit(THREE), hit(ONE, BEFORE_THE_WINDOW), next_cursor="cursor-1"), *api_read(THREE)
        )

        self.assertEqual(
            [endpoint(request) for request in opener.requests],
            [("POST", SEARCH_PATH), ("GET", "/v1/pages/page-three"), ("GET", "/v1/blocks/page-three/children")],
        )

    def test_page_edited_at_the_window_start_is_kept(self):
        _, result = edited_over_api(search_page(hit(ONE, "2026-09-01T00:00:00.000Z")), *api_read(ONE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [ONE])

    def test_page_edited_after_the_window_end_is_skipped(self):
        opener, _ = edited_over_api(search_page(hit(THREE, AFTER_THE_WINDOW), hit(TWO)), *api_read(TWO))

        self.assertEqual([endpoint(request)[1] for request in opener.requests][1:], ["/v1/pages/page-two", "/v1/blocks/page-two/children"])

    def test_page_edited_by_another_user_is_skipped(self):
        _, result = edited_over_api(search_page(hit(THREE, by=OTHER_EDITOR), hit(TWO)), *api_read(TWO))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [TWO])

    def test_kept_page_is_read_with_its_blocks(self):
        _, result = edited_over_api(search_page(hit(ONE)), *api_read(ONE))

        self.assertEqual(
            result["records"]["pages"],
            [
                {
                    "id": ONE,
                    "title": "First page",
                    "last_edited": "2026-09-04T14:30:41Z",
                    "link": "https://www.notion.so/pageone",
                    "blocks": blocks_of(ONE),
                }
            ],
        )

    def test_pages_are_read_in_search_order(self):
        _, result = edited_over_api(search_page(hit(THREE), hit(TWO), hit(ONE)), *api_read(THREE), *api_read(TWO), *api_read(ONE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [THREE, TWO, ONE])

    def test_hits_on_a_later_search_page_are_read(self):
        _, result = edited_over_api(search_page(hit(TWO), next_cursor="cursor-1"), search_page(hit(ONE)), *api_read(TWO), *api_read(ONE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [TWO, ONE])

    def test_cursor_maps_each_page_read_to_its_edit_time(self):
        _, result = edited_over_api(search_page(hit(TWO), hit(ONE)), *api_read(TWO), *api_read(ONE))

        self.assertEqual(result["cursor"], {"pages": {TWO: "2026-09-05T08:15:59Z", ONE: "2026-09-04T14:30:41Z"}})

    def test_page_edited_in_its_cursor_minute_is_unchanged(self):
        _, result = edited_over_api(search_page(hit(TWO), hit(ONE)), api_meta(TWO), *api_read(ONE), cursor=stored_pages(page_two=SAME_MINUTE_AS_TWO))

        self.assertEqual(([page["id"] for page in result["records"]["pages"]], result["entries"][TWO]), ([ONE], UNCHANGED))

    def test_no_matching_page_gives_no_record_and_an_empty_cursor(self):
        _, result = edited_over_api(search_page(hit(ONE, by=OTHER_EDITOR)))

        self.assertEqual((result["records"], result["cursor"]), ({"pages": []}, {"pages": {}}))

    def test_collection_passes_the_role_schema(self):
        _, result = edited_over_api(search_page(hit(ONE)), *api_read(ONE))

        self.assertIsNone(roles.validate_collection({**collection(result), "source": "docs"}))


class EditedCapTest(unittest.TestCase):
    CAPPED = {**EDITED_SOURCE, "edited_cap": 2}

    def test_reads_as_many_pages_as_the_cap(self):
        _, result = edited_over_api(search_page(hit(THREE), hit(TWO)), *api_read(THREE), *api_read(TWO), source=self.CAPPED)

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [THREE, TWO])

    def test_keeps_the_newest_pages_up_to_the_cap(self):
        _, result = edited_over_api(search_page(hit(THREE), hit(TWO), hit(ONE)), *api_read(THREE), *api_read(TWO), source=self.CAPPED)

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [THREE, TWO])

    def test_requests_no_further_search_page_once_the_cap_is_reached(self):
        opener = FakeOpener([search_page(hit(THREE), hit(TWO), next_cursor="cursor-1"), *api_read(THREE), *api_read(TWO)])

        notion.fetch(self.CAPPED, EDITED_WINDOW, None, [], client(opener))
        self.assertEqual(len(search_bodies(opener)), 1)

    def test_pages_of_other_users_do_not_count_against_the_cap(self):
        hits = [hit(THREE), hit(TWO, by=OTHER_EDITOR), hit(ONE)]

        _, result = edited_over_api(search_page(*hits), *api_read(THREE), *api_read(ONE), source=self.CAPPED)

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [THREE, ONE])

    def test_the_cap_defaults_to_10_pages(self):
        self.assertEqual(notion.EDITED_CAP, 10)


class EditedSearchTest(unittest.TestCase):
    def test_search_page_cap_ends_the_read_partial(self):
        pages = [search_page(hit(ONE, by=OTHER_EDITOR), next_cursor=f"cursor-{number}") for number in range(20)]

        error = edited_failure(self, *pages, error=_http.PartialRead)

        self.assertEqual(str(error), "partial: page cap")

    def test_stops_requesting_at_the_search_page_cap(self):
        opener = FakeOpener([search_page(hit(ONE, by=OTHER_EDITOR), next_cursor=f"cursor-{number}") for number in range(20)])
        with self.assertRaises(_http.PartialRead):
            notion.fetch(EDITED_SOURCE, EDITED_WINDOW, None, [], client(opener))
        self.assertEqual(len(opener.requests), 20)

    def test_more_pages_without_a_cursor_make_the_read_partial(self):
        body = served_json({"results": [], "has_more": True, "next_cursor": None})

        error = edited_failure(self, body, error=_http.PartialRead)

        self.assertEqual(str(error), "partial: POST /v1/search: has_more without next_cursor")

    def test_response_without_results_makes_the_source_unreadable(self):
        error = edited_failure(self, served_json({"object": "list"}))

        self.assertEqual(str(error), "POST /v1/search: response without results")

    def test_result_without_a_valid_edit_time_makes_the_source_unreadable(self):
        error = edited_failure(self, search_page(hit(ONE), hit(TWO, "yesterday")))

        self.assertEqual(str(error), "POST /v1/search: result 1 without a valid last_edited_time")

    def test_kept_result_without_an_id_makes_the_source_unreadable(self):
        error = edited_failure(self, search_page({**hit(ONE), "id": None}))

        self.assertEqual(str(error), "POST /v1/search: result 0 without an id")

    def test_search_error_makes_the_source_unreadable(self):
        error = edited_failure(self, status(401))

        self.assertEqual(str(error), "HTTP 401 POST /v1/search")


class ListedPlanTest(unittest.TestCase):
    def test_first_step_fetches_the_first_page(self):
        self.assertEqual(
            listed_plan()["calls"],
            [{"id": "docs-1", "connector": CONNECTOR, "tool": "notion-fetch", "arguments": {"id": ONE}, "digest": None}],
        )

    def test_next_step_fetches_the_next_page(self):
        self.assertEqual(
            listed_plan(connector_page(ONE))["calls"],
            [{"id": "docs-2", "connector": CONNECTOR, "tool": "notion-fetch", "arguments": {"id": TWO}, "digest": None}],
        )

    def test_last_step_fetches_the_last_page(self):
        calls = listed_plan(connector_page(ONE), connector_page(TWO))["calls"]

        self.assertEqual([(call["id"], call["arguments"]) for call in calls], [("docs-3", {"id": THREE})])

    def test_a_step_is_not_done_while_a_page_is_pending(self):
        self.assertEqual(listed_plan(connector_page(ONE))["done"], False)

    def test_saved_pages_end_the_plan(self):
        step = listed_plan(connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(step, {"done": True, "partial": None, "calls": []})

    def test_plan_stops_after_a_response_that_makes_the_source_unreadable(self):
        step = listed_plan(connector_page(ONE), saved("fetch_unauthorized.json"))

        self.assertEqual(step, {"done": True, "partial": None, "calls": []})

    def test_plan_stops_after_a_restricted_resource_response(self):
        step = listed_plan(saved("fetch_restricted_resource.json"))

        self.assertEqual(step["done"], True)

    def test_plan_goes_on_after_a_truncated_page(self):
        step = listed_plan(truncated_page(ONE))

        self.assertEqual([call["id"] for call in step["calls"]], ["docs-2"])

    def test_plan_goes_on_after_a_database(self):
        step = listed_plan(connector_page(ONE), saved("fetch_database.json"))

        self.assertEqual([call["id"] for call in step["calls"]], ["docs-3"])

    def test_plan_goes_on_after_a_page_with_unknown_blocks(self):
        step = listed_plan(truncated_page(ONE, truncated=False, unknown_block_count=3))

        self.assertEqual([call["id"] for call in step["calls"]], ["docs-2"])

    def test_plan_stops_after_a_response_that_is_not_json(self):
        self.assertEqual(listed_plan("not json")["done"], True)

    def test_plan_goes_on_after_a_not_found_response(self):
        step = listed_plan(connector_page(ONE), saved("fetch_object_not_found.json"))

        self.assertEqual([call["id"] for call in step["calls"]], ["docs-3"])

    def test_plan_goes_on_after_an_unchanged_truncated_page(self):
        cursor = stored_pages(page_one=SAME_MINUTE_AS_ONE)

        step = notion.plan(LIST_RELAY_SOURCE, WINDOW, cursor, [], listed_responses(truncated_page(ONE)), CONNECTOR)

        self.assertEqual([call["id"] for call in step["calls"]], ["docs-2"])

    def test_a_pending_page_is_asked_even_when_a_later_one_is_saved(self):
        step = notion.plan(LIST_RELAY_SOURCE, WINDOW, None, [], {"docs-2": connector_page(TWO)}, CONNECTOR)

        self.assertEqual([call["id"] for call in step["calls"]], ["docs-1"])


class ListedRelayTest(unittest.TestCase):
    def test_records_follow_the_configured_page_order(self):
        result = listed_over_relay(None, connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [ONE, TWO, THREE])

    def test_record_holds_the_title_edit_time_link_and_blocks(self):
        result = listed_over_relay(None, connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(
            result["records"]["pages"][0],
            {
                "id": ONE,
                "title": "First page",
                "last_edited": "2026-09-04T14:30:41Z",
                "link": "https://www.notion.so/pageone",
                "blocks": blocks_of(ONE),
            },
        )

    def test_page_without_a_cursor_is_read_whole(self):
        result = listed_over_relay(stored_pages(page_two=SAME_MINUTE_AS_TWO), connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["entries"][ONE], READ)

    def test_page_edited_in_the_cursor_minute_is_unchanged(self):
        result = listed_over_relay(stored_pages(page_one=SAME_MINUTE_AS_ONE), connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["entries"][ONE], UNCHANGED)

    def test_unchanged_page_gives_no_record(self):
        result = listed_over_relay(stored_pages(page_one=SAME_MINUTE_AS_ONE), connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [TWO, THREE])

    def test_unchanged_page_keeps_its_stored_edit_time(self):
        result = listed_over_relay(stored_pages(page_one=SAME_MINUTE_AS_ONE), connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["cursor"]["pages"][ONE], SAME_MINUTE_AS_ONE)

    def test_page_edited_in_a_later_minute_than_its_cursor_is_read(self):
        result = listed_over_relay(stored_pages(page_one=MINUTE_BEFORE_ONE), connector_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["entries"][ONE], READ)

    def test_unchanged_truncated_page_is_not_a_partial_read(self):
        result = listed_over_relay(stored_pages(page_one=SAME_MINUTE_AS_ONE), truncated_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["entries"][ONE], UNCHANGED)

    def test_changed_truncated_page_is_a_failed_entry(self):
        result = listed_over_relay(None, truncated_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["entries"], {ONE: TRUNCATED, TWO: READ, THREE: READ})

    def test_database_response_is_a_failed_entry(self):
        result = listed_over_relay(None, connector_page(ONE), saved("fetch_database.json"), connector_page(THREE))

        self.assertEqual(result["entries"], {ONE: READ, TWO: NOT_A_PAGE, THREE: READ})

    def test_other_pages_are_still_read_next_to_a_database_response(self):
        result = listed_over_relay(None, connector_page(ONE), saved("fetch_database.json"), connector_page(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [ONE, THREE])

    def test_database_response_keeps_the_stored_edit_time(self):
        cursor = stored_pages(page_two=SAME_MINUTE_AS_TWO)

        result = listed_over_relay(cursor, connector_page(ONE), saved("fetch_database.json"), connector_page(THREE))

        self.assertEqual(result["cursor"]["pages"][TWO], SAME_MINUTE_AS_TWO)

    def test_database_response_never_read_has_no_cursor(self):
        result = listed_over_relay(None, connector_page(ONE), saved("fetch_database.json"), connector_page(THREE))

        self.assertEqual(list(result["cursor"]["pages"]), [ONE, THREE])

    def test_page_response_without_an_edit_time_still_makes_the_source_unreadable(self):
        body = json.loads(connector_page(TWO))
        del body["page_last_edited_at"]
        body["metadata"] = {"type": "page"}

        error = listed_failure(self, None, connector_page(ONE), json.dumps(body), connector_page(THREE))

        self.assertEqual(str(error), "notion-fetch: response without a valid page_last_edited_at")

    def test_page_with_unknown_blocks_is_a_failed_entry(self):
        page = truncated_page(ONE, truncated=False, unknown_block_count=2)

        result = listed_over_relay(None, page, connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["entries"][ONE], TRUNCATED)

    def test_page_with_zero_unknown_blocks_is_read(self):
        page = truncated_page(ONE, truncated=False, unknown_block_count=0)

        result = listed_over_relay(None, page, connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["entries"][ONE], READ)

    def test_other_pages_are_still_read_next_to_a_truncated_one(self):
        result = listed_over_relay(None, connector_page(ONE), truncated_page(TWO), connector_page(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [ONE, THREE])

    def test_truncated_page_keeps_its_stored_edit_time(self):
        cursor = stored_pages(page_one=MINUTE_BEFORE_ONE)

        result = listed_over_relay(cursor, truncated_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(result["cursor"]["pages"][ONE], MINUTE_BEFORE_ONE)

    def test_truncated_page_never_read_has_no_cursor(self):
        result = listed_over_relay(None, truncated_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertEqual(list(result["cursor"]["pages"]), [TWO, THREE])

    def test_every_page_truncated_still_reads_the_source(self):
        result = listed_over_relay(None, truncated_page(ONE), truncated_page(TWO), truncated_page(THREE))

        self.assertEqual((result["records"], result["cursor"]), ({"pages": []}, {"pages": {}}))

    def test_truncated_collection_passes_the_role_schema(self):
        result = listed_over_relay(None, truncated_page(ONE), connector_page(TWO), connector_page(THREE))

        self.assertIsNone(roles.validate_collection({**collection(result), "source": "docs", "transport": "mcp"}))

    def test_response_reporting_object_not_found_is_a_failed_entry(self):
        result = listed_over_relay(None, connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))

        self.assertEqual(result["entries"], {ONE: READ, TWO: NOT_SHARED, THREE: READ})

    def test_response_reporting_a_restricted_resource_makes_the_source_unreadable(self):
        error = listed_failure(self, None, connector_page(ONE), saved("fetch_restricted_resource.json"), connector_page(THREE))

        self.assertEqual(str(error), "notion-fetch: response without text")

    def test_response_with_only_a_forbidden_status_makes_the_source_unreadable(self):
        error = listed_failure(self, None, connector_page(ONE), json.dumps({"status": 403}), connector_page(THREE))

        self.assertEqual(str(error), "notion-fetch: response without text")

    def test_response_with_only_a_restricted_resource_code_makes_the_source_unreadable(self):
        error = listed_failure(self, None, connector_page(ONE), json.dumps({"code": "restricted_resource"}), connector_page(THREE))

        self.assertEqual(str(error), "notion-fetch: response without text")

    def test_not_found_shape_next_to_a_text_is_a_page(self):
        body = {**json.loads(connector_page(TWO)), "status": 404}

        result = listed_over_relay(None, connector_page(ONE), json.dumps(body), connector_page(THREE))

        self.assertEqual(result["entries"][TWO], READ)

    def test_returned_entries_are_not_shared_between_calls(self):
        cursor = stored_pages(page_one=SAME_MINUTE_AS_ONE)
        first = listed_over_relay(cursor, connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))
        for entry in first["entries"].values():
            entry["reason"] = "changed"

        second = listed_over_relay(cursor, connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))

        self.assertEqual(second["entries"], {ONE: UNCHANGED, TWO: NOT_SHARED, THREE: READ})

    def test_response_with_only_a_not_found_status_is_a_failed_entry(self):
        result = listed_over_relay(None, connector_page(ONE), json.dumps({"status": 404}), connector_page(THREE))

        self.assertEqual(result["entries"][TWO], NOT_SHARED)

    def test_response_with_only_an_object_not_found_code_is_a_failed_entry(self):
        result = listed_over_relay(None, connector_page(ONE), json.dumps({"code": "object_not_found"}), connector_page(THREE))

        self.assertEqual(result["entries"][TWO], NOT_SHARED)

    def test_other_pages_are_still_read_next_to_a_missing_one(self):
        result = listed_over_relay(None, connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))

        self.assertEqual([page["id"] for page in result["records"]["pages"]], [ONE, THREE])

    def test_missing_page_keeps_its_stored_edit_time(self):
        result = listed_over_relay(stored_pages(page_two=SAME_MINUTE_AS_TWO), connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))

        self.assertEqual(result["cursor"]["pages"][TWO], SAME_MINUTE_AS_TWO)

    def test_missing_page_never_read_has_no_cursor(self):
        result = listed_over_relay(None, connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))

        self.assertEqual(sorted(result["cursor"]["pages"]), [ONE, THREE])

    def test_unauthorized_response_makes_the_source_unreadable(self):
        error = listed_failure(self, None, connector_page(ONE), saved("fetch_unauthorized.json"), connector_page(THREE))

        self.assertEqual(str(error), "notion-fetch: response without text")

    def test_missing_response_names_the_call(self):
        error = listed_failure(self, None, connector_page(ONE))

        self.assertEqual(str(error), "notion-fetch: no response docs-2")

    def test_response_without_an_edit_time_makes_the_source_unreadable(self):
        body = json.loads(connector_page(TWO))
        del body["page_last_edited_at"]

        error = listed_failure(self, None, connector_page(ONE), json.dumps(body), connector_page(THREE))

        self.assertEqual(str(error), "notion-fetch: response without a valid page_last_edited_at")

    def test_collection_passes_the_role_schema(self):
        result = listed_over_relay(stored_pages(page_one=SAME_MINUTE_AS_ONE), connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))

        self.assertIsNone(roles.validate_collection({**collection(result), "source": "docs", "transport": "mcp"}))


class ListedTransportEqualityTest(unittest.TestCase):
    CURSOR = stored_pages(page_two=SAME_MINUTE_AS_TWO, page_three=MINUTE_BEFORE_ONE)

    def over_both(self):
        _, over_api = listed_over_api(self.CURSOR, *api_read(ONE), api_meta(TWO), *api_read(THREE))
        over_relay = listed_over_relay(self.CURSOR, connector_page(ONE), connector_page(TWO), connector_page(THREE))
        return over_api, over_relay

    def test_both_transports_give_the_same_records(self):
        over_api, over_relay = self.over_both()

        self.assertEqual(state.dump(over_relay["records"]), state.dump(over_api["records"]))

    def test_both_transports_give_the_same_cursor(self):
        over_api, over_relay = self.over_both()

        self.assertEqual(state.dump(over_relay["cursor"]), state.dump(over_api["cursor"]))

    def test_both_transports_give_the_same_entries(self):
        over_api, over_relay = self.over_both()

        self.assertEqual(state.dump(over_relay["entries"]), state.dump(over_api["entries"]))

    def test_both_transports_give_the_same_collection_next_to_a_database(self):
        cursor = stored_pages(page_two=SAME_MINUTE_AS_TWO)
        _, over_api = listed_over_api(cursor, *api_read(ONE), status(400), *api_read(THREE))
        over_relay = listed_over_relay(cursor, connector_page(ONE), saved("fetch_database.json"), connector_page(THREE))

        self.assertEqual(state.dump(over_relay), state.dump(over_api))

    def test_the_data_set_has_a_read_an_unchanged_and_a_second_read_page(self):
        over_api, _ = self.over_both()

        self.assertEqual(over_api["entries"], {ONE: READ, TWO: UNCHANGED, THREE: READ})

    def test_both_transports_give_the_same_collection_next_to_a_missing_page(self):
        cursor = stored_pages(page_two=SAME_MINUTE_AS_TWO)
        _, over_api = listed_over_api(cursor, *api_read(ONE), status(404), *api_read(THREE))
        over_relay = listed_over_relay(cursor, connector_page(ONE), saved("fetch_object_not_found.json"), connector_page(THREE))

        self.assertEqual(state.dump(over_relay), state.dump(over_api))


class SourcesPageCursorTest(unittest.TestCase):
    SAME_MINUTE = stored_pages(sources_page="2026-09-04T14:30:07Z")

    def test_sources_page_is_read_whole_over_the_api_when_its_edit_minute_is_the_cursor(self):
        opener = FakeOpener([ok("page.json"), ok("blocks_empty.json")])

        result = notion.fetch(SOURCE, WINDOW, self.SAME_MINUTE, [], client(opener))

        self.assertEqual((len(opener.requests), len(result["records"]["pages"]), result["entries"]), (2, 1, {}))

    def test_sources_page_is_read_whole_over_the_connector_when_its_edit_minute_is_the_cursor(self):
        result = notion.parse(RELAY_SOURCE, WINDOW, self.SAME_MINUTE, [], {CALL_ID: saved("fetch_page.json")}, {CALL_ID: None})

        self.assertEqual((len(result["records"]["pages"]), result["entries"]), (1, {}))

    def test_sources_page_cursor_is_per_page_id(self):
        result = notion.parse(RELAY_SOURCE, WINDOW, None, [], {CALL_ID: saved("fetch_page.json")}, {CALL_ID: None})

        self.assertEqual(result["cursor"], {"pages": {PAGE_ID: "2026-09-04T14:30:00Z"}})

    def test_not_found_response_does_not_become_an_entry_for_a_sources_page(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            notion.parse(RELAY_SOURCE, WINDOW, None, [], {CALL_ID: saved("fetch_object_not_found.json")}, {CALL_ID: None})
        self.assertEqual(str(caught.exception), "notion-fetch: response without text")

    def test_database_response_does_not_become_an_entry_for_a_sources_page(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            notion.parse(RELAY_SOURCE, WINDOW, None, [], {CALL_ID: saved("fetch_database.json")}, {CALL_ID: None})
        self.assertEqual(str(caught.exception), "notion-fetch: response without a valid page_last_edited_at")

    def test_database_id_makes_the_sources_page_unreadable_over_the_api(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(status(400))
        self.assertEqual(str(caught.exception), f"HTTP 400 GET {PAGE_PATH}")

    def test_sources_page_plan_stays_one_call(self):
        self.assertEqual([call["id"] for call in relay_plan({})["calls"]], [CALL_ID])


CREATED_SOURCE = {
    "name": "created",
    "provider": "docs",
    "transport": {"cloud": "mcp", "local": "mcp"},
    "created_by": "me",
    "exclude_paths": ["Notes / Projects"],
}
CREATED_CALL = "created-1"
CREATED_ID = "created-page-one"
OTHER_CREATED_ID = "created-page-two"
CREATED_IN_WINDOW = "2025-10-09T09:10:00.000Z"
CREATED_BEFORE_START = "2025-10-09T08:00:00.000Z"
CREATED_AFTER_END = "2025-10-09T12:00:00.000Z"


def created_hit(page_id=CREATED_ID, timestamp=CREATED_IN_WINDOW, **changes):
    return {
        "id": page_id,
        "title": "Weekly plan",
        "url": "https://docs.example.test/p/" + page_id.replace("-", "") + "?pvs=204",
        "type": "page",
        "highlight": "",
        "timestamp": timestamp,
        "path": "Notes / Ideas",
        **changes,
    }


def created_search(*hits, **changes):
    return json.dumps({"results": list(hits), "type": "workspace_search", **changes})


def created_plan(responses):
    return notion.plan(CREATED_SOURCE, WINDOW, None, [], responses, CONNECTOR)


def created_parse(text, source=CREATED_SOURCE):
    return notion.parse(source, WINDOW, None, [], {CREATED_CALL: text}, {CREATED_CALL: None})


def created_ids(*hits):
    return [page["id"] for page in created_parse(created_search(*hits))["records"]["pages"]]


def created_failure(test, text, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        created_parse(text)
    return caught.exception


class CreatedPlanTest(unittest.TestCase):
    def test_first_step_searches_the_pages_the_user_created_since_the_window_start(self):
        self.assertEqual(
            created_plan({})["calls"],
            [
                {
                    "id": CREATED_CALL,
                    "connector": CONNECTOR,
                    "tool": "notion-search",
                    "arguments": {
                        "query": "",
                        "filters": {"created_by_user_ids": ["me"], "created_date_range": {"start_date": "2025-10-09"}},
                        "page_size": 50,
                        "max_highlight_length": 0,
                    },
                    "digest": None,
                }
            ],
        )

    def test_first_step_is_not_done(self):
        self.assertFalse(created_plan({})["done"])

    def test_saved_search_ends_the_plan(self):
        self.assertEqual(created_plan({CREATED_CALL: created_search()}), {"done": True, "partial": None, "calls": []})


class CreatedParseTest(unittest.TestCase):
    def test_keeps_a_page_created_in_the_window_as_a_pages_record(self):
        result = created_parse(created_search(created_hit()))

        self.assertEqual(
            result["records"]["pages"],
            [
                {
                    "id": CREATED_ID,
                    "title": "Weekly plan",
                    "last_edited": "2025-10-09T09:10:00Z",
                    "link": "https://www.notion.so/" + CREATED_ID.replace("-", ""),
                    "blocks": [],
                }
            ],
        )

    def test_drops_a_page_created_before_the_window_start(self):
        self.assertEqual(created_ids(created_hit(timestamp=CREATED_BEFORE_START)), [])

    def test_drops_a_page_created_after_the_window_end(self):
        self.assertEqual(created_ids(created_hit(timestamp=CREATED_AFTER_END)), [])

    def test_drops_a_page_under_an_excluded_path(self):
        excluded = created_hit(OTHER_CREATED_ID, path="Notes / Projects / Weekly")

        self.assertEqual(created_ids(excluded, created_hit()), [CREATED_ID])

    def test_keeps_a_page_without_a_path(self):
        top_level = {key: value for key, value in created_hit().items() if key != "path"}

        self.assertEqual(created_ids(top_level), [CREATED_ID])

    def test_skips_a_result_that_is_not_a_page(self):
        self.assertEqual(created_ids(created_hit(OTHER_CREATED_ID, type="database"), created_hit()), [CREATED_ID])

    def test_keeps_the_search_order(self):
        self.assertEqual(created_ids(created_hit(OTHER_CREATED_ID), created_hit()), [OTHER_CREATED_ID, CREATED_ID])

    def test_link_follows_the_links_base_of_the_provider(self):
        source = {**CREATED_SOURCE, "provider_config": {"links_base": "https://docs.example.test/"}}

        result = created_parse(created_search(created_hit()), source)

        self.assertEqual(result["records"]["pages"][0]["link"], "https://docs.example.test/" + CREATED_ID.replace("-", ""))

    def test_cursor_holds_the_creation_time_of_each_kept_page(self):
        result = created_parse(created_search(created_hit(), created_hit(OTHER_CREATED_ID, timestamp=CREATED_BEFORE_START)))

        self.assertEqual(result["cursor"], {"pages": {CREATED_ID: "2025-10-09T09:10:00Z"}})

    def test_collection_conforms_to_the_document_store_schema(self):
        result = created_parse(created_search(created_hit()))

        self.assertIsNone(roles.validate_collection({**collection(result), "source": "created", "transport": "mcp"}))

    def test_a_full_page_of_results_ends_the_read_partial(self):
        hits = [created_hit(f"id-{number}") for number in range(50)]

        error = created_failure(self, created_search(*hits), _http.PartialRead)

        self.assertEqual(str(error), "partial: result cap")

    def test_one_result_short_of_a_full_page_is_read(self):
        hits = [created_hit(f"id-{number}") for number in range(49)]

        self.assertEqual(len(created_ids(*hits)), 49)

    def test_a_response_that_is_not_json_makes_the_source_unreadable(self):
        self.assertEqual(str(created_failure(self, "not json")), "notion-search: response created-1 is not JSON")

    def test_a_response_without_results_makes_the_source_unreadable(self):
        self.assertEqual(str(created_failure(self, json.dumps({"type": "workspace_search"}))), "notion-search: response created-1 without results")

    def test_a_page_result_without_a_valid_timestamp_makes_the_source_unreadable(self):
        error = created_failure(self, created_search(created_hit(timestamp="yesterday")))

        self.assertEqual(str(error), "notion-search: response created-1 result 0 without a valid timestamp")

    def test_a_page_result_without_an_id_makes_the_source_unreadable(self):
        error = created_failure(self, created_search(created_hit(id="")))

        self.assertEqual(str(error), "notion-search: response created-1 result 0 without an id")


class CreatedApiRefusalTest(unittest.TestCase):
    def test_the_api_read_refuses_a_created_by_source(self):
        opener = FakeOpener([])

        with self.assertRaises(_http.SourceUnreadable) as caught:
            notion.fetch(CREATED_SOURCE, WINDOW, None, [], client(opener))

        self.assertEqual((str(caught.exception), opener.requests), ("created_by: reads over mcp only", []))


if __name__ == "__main__":
    unittest.main()
