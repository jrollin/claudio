import decimal
import unittest

import providers
from providers import _common
from providers._errors import SourceUnreadable
from providers.test_http import FakeOpener, FakeResponse

FIRST_READ_FROM_TS = 1_760_000_000
WINDOW = {"from_ts": 1_760_003_600, "to_ts": 1_760_007_200, "first_read_from_ts": FIRST_READ_FROM_TS}


class ReadStartTest(unittest.TestCase):
    def test_starts_at_the_first_read_start_when_there_is_no_cursor(self):
        self.assertEqual(_common.read_start(WINDOW, None), FIRST_READ_FROM_TS)

    def test_starts_at_a_cursor_later_than_the_first_read_start(self):
        self.assertEqual(_common.read_start(WINDOW, FIRST_READ_FROM_TS + 500), FIRST_READ_FROM_TS + 500)

    def test_starts_at_the_first_read_start_when_the_cursor_is_earlier(self):
        self.assertEqual(_common.read_start(WINDOW, FIRST_READ_FROM_TS - 500), FIRST_READ_FROM_TS)

    def test_starts_at_the_first_read_start_when_the_cursor_equals_it(self):
        self.assertEqual(_common.read_start(WINDOW, FIRST_READ_FROM_TS), FIRST_READ_FROM_TS)

    def test_keeps_the_exact_value_of_a_later_decimal_cursor(self):
        cursor = decimal.Decimal("1760000500.000050")
        self.assertEqual(_common.read_start(WINDOW, cursor), cursor)

    def test_starts_at_the_first_read_start_when_a_decimal_cursor_is_earlier(self):
        self.assertEqual(_common.read_start(WINDOW, decimal.Decimal("1759999999.999999")), FIRST_READ_FROM_TS)

    def test_ignores_the_run_window_start(self):
        window = {**WINDOW, "from_ts": FIRST_READ_FROM_TS + 9000}
        self.assertEqual(_common.read_start(window, FIRST_READ_FROM_TS + 100), FIRST_READ_FROM_TS + 100)


PROVIDER = {"api": {"base_url": "https://api.example.test", "credentials": {}}}
JSON_ACCEPT = {"accept": "application/json"}
GITHUB_STATIC = {"accept": "application/vnd.github+json", "x-github-api-version": "2022-11-28"}


def sent_headers(name, provider=PROVIDER):
    opener = FakeOpener(FakeResponse())
    _common.injected_client(provider, providers.load(name).STATIC_HEADERS, opener=opener).get("/v1/things")
    return {header.lower(): value for header, value in opener.requests[0].header_items()}


class InjectedClientTest(unittest.TestCase):
    def test_the_document_store_sends_its_api_version_and_no_credential_header(self):
        self.assertEqual(sent_headers("notion"), {**JSON_ACCEPT, "notion-version": "2026-03-11"})

    def test_the_code_host_sends_its_media_type_and_api_version_and_no_credential_header(self):
        self.assertEqual(sent_headers("github"), GITHUB_STATIC)

    def test_the_observability_adapter_sends_no_credential_header(self):
        self.assertEqual(sent_headers("datadog"), JSON_ACCEPT)

    def test_the_issue_tracker_sends_no_credential_header(self):
        self.assertEqual(sent_headers("jira"), JSON_ACCEPT)

    def test_the_chat_adapter_sends_no_credential_header(self):
        self.assertEqual(sent_headers("slack"), JSON_ACCEPT)

    def test_reads_no_variable_even_when_the_provider_names_one(self):
        opener = FakeOpener(FakeResponse(b'{"ok": true}'))
        provider = {"api": {"base_url": "https://api.example.test", "credentials": {"token": "EXAMPLE_TOKEN"}}}
        self.assertEqual(_common.injected_client(provider, {}, opener=opener).get("/v1/things"), {"ok": True})

    def test_refuses_a_base_url_that_is_not_https(self):
        with self.assertRaises(SourceUnreadable) as caught:
            _common.injected_client({"api": {"base_url": "http://api.example.test", "credentials": {}}}, {})
        self.assertEqual(str(caught.exception), _common.BASE_URL_INVALID)


if __name__ == "__main__":
    unittest.main()
