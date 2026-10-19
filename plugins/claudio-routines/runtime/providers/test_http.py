import email.message
import http.client
import io
import json
import os
import ssl
import sys
import tempfile
import traceback
import types
import unittest
import urllib.error
import urllib.request
from unittest import mock

import providers
from providers import _http

BASE = "https://api.example.test"
PATH = "/v1/things"
VAR = "EXAMPLE_TOKEN"
SECRET = "-".join(["sentinel", "credential", "value"])


def bearer(values):
    return {"Authorization": "Bearer " + values["token"]}


def message(headers=None):
    msg = email.message.Message()
    for name, value in (headers or {}).items():
        msg[name] = value
    return msg


def shown(exc):
    pending, texts = [exc], []
    while pending:
        current = pending.pop()
        if current is not None:
            texts.append("".join(traceback.format_exception(current)) + repr(current) + repr(vars(current)))
            pending += [current.__cause__, current.__context__]
    return "".join(texts)


def leaking_auth(values):
    raise ValueError("rejected " + values["token"])


class ReadOnlyResponse:
    def __init__(self, body=b"{}", headers=None):
        self.stream = io.BytesIO(body)
        self.headers = message(headers)

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeResponse(ReadOnlyResponse):
    def __init__(self, body=b"{}", headers=None, chunk=_http.READ_CHUNK):
        super().__init__(body, headers)
        self.chunk = chunk

    def read1(self, size=-1):
        return self.stream.read(min(size, self.chunk))


class FakeOpener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def http_error(status, headers=None, body=b""):
    return urllib.error.HTTPError(BASE + PATH, status, "status", message(headers), io.BytesIO(body))


def make_client(opener, environ=None, sleeps=None, auth=bearer, base_url=BASE, credentials=None, clock=None):
    return _http.HttpClient(
        base_url,
        {"token": VAR} if credentials is None else credentials,
        auth,
        opener=opener,
        environ={VAR: SECRET} if environ is None else environ,
        sleep=(sleeps if sleeps is not None else []).append,
        clock=clock or (lambda: 0),
    )


class BaseUrlTest(unittest.TestCase):
    def test_rejects_plain_http(self):
        with self.assertRaises(ValueError):
            make_client(FakeOpener(), base_url="http://api.example.test")

    def test_rejects_user_info(self):
        with self.assertRaises(ValueError):
            make_client(FakeOpener(), base_url="https://reader@api.example.test")

    def test_rejects_a_query(self):
        with self.assertRaises(ValueError):
            make_client(FakeOpener(), base_url="https://api.example.test/?region=eu")

    def test_rejects_a_fragment(self):
        with self.assertRaises(ValueError):
            make_client(FakeOpener(), base_url="https://api.example.test/#top")

    def test_rejection_text_omits_the_user_info(self):
        with self.assertRaises(ValueError) as ctx:
            make_client(FakeOpener(), base_url="https://reader:" + SECRET + "@api.example.test")
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_request_url_is_the_base_url_plus_the_path(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener, base_url=BASE + "/v2/").get(PATH)
        self.assertEqual(opener.requests[0].full_url, BASE + "/v2" + PATH)

    def test_refuses_a_path_that_would_change_the_host(self):
        with self.assertRaises(ValueError):
            make_client(FakeOpener(FakeResponse())).get(".other.test/v1")


class CredentialsTest(unittest.TestCase):
    def test_missing_variable_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), environ={}).get(PATH)
        self.assertEqual(str(ctx.exception), "credentials missing: " + VAR)

    def test_empty_variable_counts_as_missing(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), environ={VAR: ""}).get(PATH)
        self.assertEqual(str(ctx.exception), "credentials missing: " + VAR)

    def test_blank_variable_counts_as_missing(self):
        with self.assertRaises(_http.CredentialsMissing) as ctx:
            make_client(FakeOpener(), environ={VAR: " \t "}).get(PATH)
        self.assertEqual(str(ctx.exception), "credentials missing: " + VAR)

    def test_a_blank_variable_sends_no_request(self):
        opener = FakeOpener()
        with self.assertRaises(_http.CredentialsMissing):
            make_client(opener, environ={VAR: "  "}).get(PATH)
        self.assertEqual(opener.requests, [])

    def test_names_every_missing_variable(self):
        client = make_client(FakeOpener(), environ={}, credentials={"token": VAR, "app": "EXAMPLE_APP"})
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            client.get(PATH)
        self.assertEqual(str(ctx.exception), "credentials missing: EXAMPLE_APP, " + VAR)

    def test_missing_variable_sends_no_request(self):
        opener = FakeOpener()
        with self.assertRaises(_http.SourceUnreadable):
            make_client(opener, environ={}).get(PATH)
        self.assertEqual(opener.requests, [])

    def test_reads_the_variable_at_request_time(self):
        environ = {}
        opener = FakeOpener(FakeResponse())
        client = make_client(opener, environ=environ)
        environ[VAR] = SECRET
        client.get(PATH)
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer " + SECRET)

    def test_auth_receives_the_values_by_credential_name(self):
        received = []
        make_client(FakeOpener(FakeResponse()), auth=lambda values: received.append(values) or {}).get(PATH)
        self.assertEqual(received, [{"token": SECRET}])

    def test_failing_auth_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), auth=leaking_auth).get(PATH)
        self.assertEqual(str(ctx.exception), "credentials invalid: auth")

    def test_failing_auth_never_shows_the_credential_value(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), auth=leaking_auth).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_auth_headers_come_from_the_auth_callable(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener, auth=lambda values: {"X-Example-Key": values["token"]}).get(PATH)
        self.assertEqual(opener.requests[0].get_header("X-example-key"), SECRET)


class InvalidCredentialTest(unittest.TestCase):
    def test_names_the_variable_of_a_value_with_a_line_feed(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), environ={VAR: SECRET + "\n"}).get(PATH)
        self.assertEqual(str(ctx.exception), "credentials invalid: " + VAR)

    def test_line_feed_value_never_shows_the_credential_value(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), environ={VAR: SECRET + "\n"}).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_carriage_return_value_never_shows_the_credential_value(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), environ={VAR: SECRET + "\r"}).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_control_character_value_never_shows_the_credential_value(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), environ={VAR: SECRET + "\x00"}).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_non_latin1_value_never_shows_the_credential_value(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(), environ={VAR: SECRET + "€"}).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_invalid_value_sends_no_request(self):
        opener = FakeOpener()
        with self.assertRaises(_http.SourceUnreadable):
            make_client(opener, environ={VAR: SECRET + "\n"}).get(PATH)
        self.assertEqual(opener.requests, [])


class LeakTest(unittest.TestCase):
    def test_http_error_never_shows_the_credential_value(self):
        error = http_error(401, headers={"X-Echo": SECRET}, body=SECRET.encode())
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(error)).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_network_error_never_shows_the_credential_value(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(urllib.error.URLError("refused " + SECRET))).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_header_value_error_never_shows_the_credential_value(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(ValueError("Invalid header value " + SECRET))).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_invalid_json_never_shows_the_body(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(FakeResponse(b"<html>" + SECRET.encode()))).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_bad_status_line_never_shows_the_line(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http.client.BadStatusLine(SECRET))).get(PATH)
        self.assertNotIn(SECRET, shown(ctx.exception))

    def test_client_repr_never_shows_the_credential_value(self):
        client = make_client(FakeOpener(FakeResponse()))
        client.get(PATH)
        self.assertNotIn(SECRET, repr(client))


class ErrorTextTest(unittest.TestCase):
    def test_http_error_names_status_method_and_path_only(self):
        error = http_error(403, headers={"X-Detail": "header-marker"}, body=b"body-marker")
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(error)).get(PATH)
        self.assertEqual(str(ctx.exception), "HTTP 403 GET " + PATH)

    def test_http_error_omits_the_query_parameters(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http_error(404))).get(PATH, {"page": 2})
        self.assertEqual(str(ctx.exception), "HTTP 404 GET " + PATH)

    def test_post_error_names_the_post_method(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http_error(400))).post(PATH, {"q": "x"})
        self.assertEqual(str(ctx.exception), "HTTP 400 POST " + PATH)

    def test_network_error_names_the_error_class(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(urllib.error.URLError(ConnectionRefusedError()))).get(PATH)
        self.assertEqual(str(ctx.exception), "GET " + PATH + ": ConnectionRefusedError")

    def test_socket_timeout_names_the_error_class(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(TimeoutError())).get(PATH)
        self.assertEqual(str(ctx.exception), "GET " + PATH + ": TimeoutError")

    def test_value_error_names_the_error_class(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(ValueError("Invalid header value"))).get(PATH)
        self.assertEqual(str(ctx.exception), "GET " + PATH + ": ValueError")

    def test_invalid_url_names_the_error_class(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http.client.InvalidURL("control characters"))).get(PATH)
        self.assertEqual(str(ctx.exception), "GET " + PATH + ": InvalidURL")

    def test_invalid_json_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(FakeResponse(b"<html>"))).get(PATH)
        self.assertEqual(str(ctx.exception), "GET " + PATH + ": invalid JSON")

    def test_http_error_carries_the_status(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http_error(404))).get(PATH)
        self.assertEqual(ctx.exception.status, 404)

    def test_retried_http_error_carries_the_last_status(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http_error(500), http_error(502))).get(PATH)
        self.assertEqual(ctx.exception.status, 502)

    def test_network_error_carries_no_status(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(TimeoutError())).get(PATH)
        self.assertIsNone(ctx.exception.status)

    def test_redirect_carries_no_status(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http_error(302))).get(PATH)
        self.assertIsNone(ctx.exception.status)

    def test_http_error_is_closed(self):
        error = http_error(404)
        with self.assertRaises(_http.SourceUnreadable):
            make_client(FakeOpener(error)).get(PATH)
        self.assertTrue(error.fp.closed)


class RetryTest(unittest.TestCase):
    def test_retries_a_rate_limit_after_retry_after(self):
        sleeps = []
        opener = FakeOpener(http_error(429, headers={"Retry-After": "7"}), FakeResponse(b'{"ok": true}'))
        make_client(opener, sleeps=sleeps).get(PATH)
        self.assertEqual(sleeps, [7])

    def test_returns_the_retried_response(self):
        opener = FakeOpener(http_error(503), FakeResponse(b'{"ok": true}'))
        self.assertEqual(make_client(opener).get(PATH), {"ok": True})

    def test_caps_retry_after_at_thirty_seconds(self):
        sleeps = []
        opener = FakeOpener(http_error(429, headers={"Retry-After": "120"}), FakeResponse())
        make_client(opener, sleeps=sleeps).get(PATH)
        self.assertEqual(sleeps, [30])

    def test_clamps_a_negative_retry_after_to_zero(self):
        sleeps = []
        opener = FakeOpener(http_error(429, headers={"Retry-After": "-5"}), FakeResponse())
        make_client(opener, sleeps=sleeps).get(PATH)
        self.assertEqual(sleeps, [0])

    def test_waits_one_second_without_retry_after(self):
        sleeps = []
        make_client(FakeOpener(http_error(500), FakeResponse()), sleeps=sleeps).get(PATH)
        self.assertEqual(sleeps, [1])

    def test_waits_one_second_on_a_date_retry_after(self):
        sleeps = []
        error = http_error(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        make_client(FakeOpener(error, FakeResponse()), sleeps=sleeps).get(PATH)
        self.assertEqual(sleeps, [1])

    def test_retries_a_server_error_only_once(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http_error(500), http_error(502))).get(PATH)
        self.assertEqual(str(ctx.exception), "HTTP 502 GET " + PATH)

    def test_does_not_retry_another_client_error(self):
        sleeps = []
        with self.assertRaises(_http.SourceUnreadable):
            make_client(FakeOpener(http_error(404)), sleeps=sleeps).get(PATH)
        self.assertEqual(sleeps, [])

    def test_passes_the_timeout_on_the_retried_attempt(self):
        opener = FakeOpener(http_error(503), FakeResponse())
        make_client(opener).get(PATH)
        self.assertEqual(opener.timeouts, [30, 30])


class RedirectTest(unittest.TestCase):
    def test_redirect_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(http_error(302))).get(PATH)
        self.assertEqual(str(ctx.exception), "redirect refused GET " + PATH)

    def test_redirect_handler_raises(self):
        request = urllib.request.Request(BASE + PATH)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _http.RefuseRedirect().redirect_request(
                request, io.BytesIO(), 302, "Found", message(), "https://other.test/v1"
            )
        ctx.exception.close()


class DefaultOpenerTest(unittest.TestCase):
    def setUp(self):
        self.handlers = {type(handler): handler for handler in _http.HttpClient(BASE, {}, bearer).opener.handlers}

    def test_carries_the_redirect_refusal(self):
        self.assertIn(_http.RefuseRedirect, self.handlers)

    def test_drops_the_redirect_follower(self):
        self.assertNotIn(urllib.request.HTTPRedirectHandler, self.handlers)

    def test_checks_the_host_name(self):
        self.assertTrue(self.handlers[urllib.request.HTTPSHandler]._context.check_hostname)

    def test_requires_a_certificate(self):
        self.assertEqual(self.handlers[urllib.request.HTTPSHandler]._context.verify_mode, ssl.CERT_REQUIRED)


class GetUrlTest(unittest.TestCase):
    def test_follows_a_link_on_the_base_host(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener).get_url(BASE + PATH + "?page=2")
        self.assertEqual(opener.requests[0].full_url, BASE + PATH + "?page=2")

    def test_matches_the_host_case_insensitively(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener).get_url("https://API.Example.TEST" + PATH)
        self.assertEqual(opener.requests[0].full_url, "https://API.Example.TEST" + PATH)

    def test_refuses_another_host(self):
        with self.assertRaises(_http.SourceUnreadable):
            make_client(FakeOpener(FakeResponse())).get_url("https://other.test" + PATH)

    def test_refuses_another_scheme(self):
        with self.assertRaises(_http.SourceUnreadable):
            make_client(FakeOpener(FakeResponse())).get_url("http://api.example.test" + PATH)

    def test_refuses_user_info_on_the_base_host(self):
        with self.assertRaises(_http.SourceUnreadable):
            make_client(FakeOpener(FakeResponse())).get_url("https://reader@api.example.test" + PATH)


class BodyTest(unittest.TestCase):
    def test_body_over_ten_mb_is_a_partial_read(self):
        opener = FakeOpener(FakeResponse(b" " * (_http.BODY_CAP + 1)))
        with self.assertRaisesRegex(_http.PartialRead, "^partial: "):
            make_client(opener).get(PATH)

    def test_partial_read_carries_no_status(self):
        opener = FakeOpener(FakeResponse(b" " * (_http.BODY_CAP + 1)))
        with self.assertRaises(_http.PartialRead) as ctx:
            make_client(opener).get(PATH)
        self.assertIsNone(ctx.exception.status)

    def test_body_at_ten_mb_is_read(self):
        opener = FakeOpener(FakeResponse(b"{}" + b" " * (_http.BODY_CAP - 2)))
        self.assertEqual(make_client(opener).get(PATH), {})


class DeadlineTest(unittest.TestCase):
    def test_request_over_thirty_seconds_times_out(self):
        clock = iter([0, 31]).__next__
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(FakeOpener(FakeResponse()), clock=clock).get(PATH)
        self.assertEqual(str(ctx.exception), "GET " + PATH + ": timeout")

    def test_slow_body_times_out_between_chunks(self):
        clock = iter([0, 10, 20, 31]).__next__
        opener = FakeOpener(FakeResponse(b"{}" + b" " * 8, chunk=4))
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            make_client(opener, clock=clock).get(PATH)
        self.assertEqual(str(ctx.exception), "GET " + PATH + ": timeout")

    def test_request_within_thirty_seconds_is_read(self):
        clock = iter([0, 30, 30]).__next__
        self.assertEqual(make_client(FakeOpener(FakeResponse()), clock=clock).get(PATH), {})

    def test_reads_a_response_without_read1(self):
        opener = FakeOpener(ReadOnlyResponse(b'{"ok": true}'))
        self.assertEqual(make_client(opener).get(PATH), {"ok": True})


class RequestTest(unittest.TestCase):
    def test_passes_a_thirty_second_timeout(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener).get(PATH)
        self.assertEqual(opener.timeouts, [30])

    def test_get_encodes_the_params_in_the_query(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener).get(PATH, {"from": 1, "q": "a b"})
        self.assertEqual(opener.requests[0].full_url, BASE + PATH + "?from=1&q=a+b")

    def test_get_returns_the_decoded_json(self):
        opener = FakeOpener(FakeResponse(b'{"items": [1, 2]}'))
        self.assertEqual(make_client(opener).get(PATH), {"items": [1, 2]})

    def test_post_sends_the_body_as_json(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener).post(PATH, {"q": "x"})
        self.assertEqual(json.loads(opener.requests[0].data), {"q": "x"})

    def test_post_declares_a_json_content_type(self):
        opener = FakeOpener(FakeResponse())
        make_client(opener).post(PATH, {"q": "x"})
        self.assertEqual(opener.requests[0].get_header("Content-type"), "application/json")

    def test_exposes_the_last_response_headers(self):
        opener = FakeOpener(FakeResponse(headers={"Link": "<" + BASE + PATH + "?page=2>; rel=next"}))
        client = make_client(opener)
        client.get(PATH)
        self.assertEqual(client.response_headers["Link"], "<" + BASE + PATH + "?page=2>; rel=next")

    def test_resets_the_response_headers_after_a_failed_call(self):
        client = make_client(FakeOpener(FakeResponse(headers={"Link": "<" + BASE + PATH + ">"}), http_error(404)))
        client.get(PATH)
        with self.assertRaises(_http.SourceUnreadable):
            client.get(PATH)
        self.assertIsNone(client.response_headers)


LINK = "<" + BASE + PATH + "?page=2>; rel=next"


def recording_client(*outcomes, **options):
    records = []
    client = make_client(FakeOpener(*outcomes), **options)
    client.recorder = records.append
    return client, records


def success(response, **fields):
    return {"status": 200, "link": None, "response": response, "error": None, **fields}


class RecorderTest(unittest.TestCase):
    def test_is_off_by_default(self):
        self.assertIsNone(make_client(FakeOpener()).recorder)

    def test_a_get_records_its_request_and_its_response(self):
        client, records = recording_client(FakeResponse(b'{"items": [1]}', headers={"Link": LINK}))
        client.get(PATH, {"from": 1, "q": "a b"})
        expected = {"method": "GET", "path": PATH, "query": "from=1&q=a+b", "body": None, **success({"items": [1]}, link=LINK)}
        self.assertEqual(records, [expected])

    def test_a_get_without_params_records_an_empty_query(self):
        client, records = recording_client(FakeResponse())
        client.get(PATH)
        self.assertEqual(records[0]["query"], "")

    def test_a_post_records_its_body(self):
        client, records = recording_client(FakeResponse(b'{"ok": true}'))
        client.post(PATH, {"q": ["x"]})
        expected = {"method": "POST", "path": PATH, "query": "", "body": {"q": ["x"]}, **success({"ok": True})}
        self.assertEqual(records, [expected])

    def test_a_get_url_records_the_path_and_the_query_of_the_url(self):
        client, records = recording_client(FakeResponse())
        client.get_url(BASE + PATH + "?page=2&per_page=50")
        self.assertEqual((records[0]["method"], records[0]["path"], records[0]["query"]), ("GET", PATH, "page=2&per_page=50"))

    def test_a_get_records_the_url_path_with_the_base_url_path(self):
        client, records = recording_client(FakeResponse(), base_url=BASE + "/api")
        client.get(PATH)
        self.assertEqual(records[0]["path"], "/api" + PATH)

    def test_an_interrupted_call_writes_no_record(self):
        client, records = recording_client(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            client.get(PATH)
        self.assertEqual(records, [])

    def test_records_one_entry_per_call_in_call_order(self):
        client, records = recording_client(FakeResponse(b"1"), FakeResponse(b"2"), FakeResponse(b"3"))
        client.get(PATH)
        client.post(PATH, {})
        client.get_url(BASE + PATH)
        self.assertEqual([(record["method"], record["response"]) for record in records], [("GET", 1), ("POST", 2), ("GET", 3)])

    def test_a_record_holds_no_request_header_and_no_credential(self):
        client, records = recording_client(FakeResponse(), auth=lambda values: {"X-Example-Key": values["token"]})
        client.post(PATH, {"q": "x"})
        self.assertEqual((SECRET in json.dumps(records), "X-Example-Key" in json.dumps(records), "Content-Type" in json.dumps(records)), (False, False, False))

    def test_a_failed_http_call_is_recorded_with_its_status_and_error(self):
        client, records = recording_client(http_error(404))
        with self.assertRaises(_http.SourceUnreadable):
            client.get(PATH)
        error = {"class": "SourceUnreadable", "message": "HTTP 404 GET " + PATH, "status": 404}
        self.assertEqual(records, [{"method": "GET", "path": PATH, "query": "", "body": None, "status": 404, "link": None, "response": None, "error": error}])

    def test_a_failed_call_raises_as_without_a_recorder(self):
        client, _ = recording_client(http_error(403))
        with self.assertRaises(_http.SourceUnreadable) as ctx:
            client.get(PATH)
        self.assertEqual((str(ctx.exception), ctx.exception.status), ("HTTP 403 GET " + PATH, 403))

    def test_a_call_without_an_answer_records_no_status(self):
        client, records = recording_client(TimeoutError())
        with self.assertRaises(_http.SourceUnreadable):
            client.get(PATH)
        error = {"class": "SourceUnreadable", "message": "GET " + PATH + ": TimeoutError", "status": None}
        self.assertEqual((records[0]["status"], records[0]["error"]), (None, error))

    def test_a_refused_redirect_records_its_status_and_an_error_without_one(self):
        client, records = recording_client(http_error(302))
        with self.assertRaises(_http.SourceUnreadable):
            client.get(PATH)
        error = {"class": "SourceUnreadable", "message": "redirect refused GET " + PATH, "status": None}
        self.assertEqual((records[0]["status"], records[0]["error"]), (302, error))

    def test_an_invalid_body_records_the_answer_status_and_no_response(self):
        client, records = recording_client(FakeResponse(b"<html>"))
        with self.assertRaises(_http.SourceUnreadable):
            client.get(PATH)
        error = {"class": "SourceUnreadable", "message": "GET " + PATH + ": invalid JSON", "status": None}
        self.assertEqual((records[0]["status"], records[0]["response"], records[0]["error"]), (200, None, error))

    def test_an_oversized_body_records_a_partial_read(self):
        client, records = recording_client(FakeResponse(b"{}" + b" " * _http.BODY_CAP))
        with self.assertRaises(_http.PartialRead):
            client.get(PATH)
        self.assertEqual(records[0]["error"], {"class": "PartialRead", "message": "partial: response over 10 MB", "status": None})

    def test_missing_credentials_are_recorded_without_a_status(self):
        client, records = recording_client(environ={})
        with self.assertRaises(_http.CredentialsMissing):
            client.get(PATH)
        error = {"class": "CredentialsMissing", "message": "credentials missing: " + VAR, "status": None}
        self.assertEqual((records[0]["status"], records[0]["error"]), (None, error))

    def test_a_refused_link_is_recorded_as_a_failed_call(self):
        client, records = recording_client()
        with self.assertRaises(_http.SourceUnreadable):
            client.get_url("https://other.test" + PATH + "?page=2")
        error = {"class": "SourceUnreadable", "message": "link refused GET " + PATH + ": not on the base_url host", "status": None}
        self.assertEqual(records, [{"method": "GET", "path": PATH, "query": "page=2", "body": None, "status": None, "link": None, "response": None, "error": error}])

    def test_a_retried_call_records_only_its_final_outcome(self):
        client, records = recording_client(http_error(503), FakeResponse(b'{"ok": true}'))
        client.get(PATH)
        self.assertEqual(records, [{"method": "GET", "path": PATH, "query": "", "body": None, **success({"ok": True})}])

    def test_a_call_that_fails_after_a_retry_records_the_last_status(self):
        client, records = recording_client(http_error(500), http_error(502))
        with self.assertRaises(_http.SourceUnreadable):
            client.get(PATH)
        self.assertEqual((len(records), records[0]["status"], records[0]["error"]["status"]), (1, 502, 502))

    def test_a_path_that_is_not_absolute_is_not_a_call(self):
        client, records = recording_client()
        with self.assertRaises(ValueError):
            client.get("v1/things")
        self.assertEqual(records, [])


class LoadTest(unittest.TestCase):
    def test_returns_the_adapter_module(self):
        adapter = types.ModuleType("providers.fakevendor")
        with mock.patch.dict(sys.modules, {"providers.fakevendor": adapter}):
            self.assertIs(providers.load("fakevendor"), adapter)

    def test_rejects_a_private_module_name(self):
        with self.assertRaises(ValueError):
            providers.load("_http")

    def test_rejects_a_dotted_name(self):
        with self.assertRaises(ValueError):
            providers.load("os.path")

    def test_names_an_absent_adapter(self):
        with self.assertRaisesRegex(ValueError, "absentvendor"):
            providers.load("absentvendor")


class NamesTest(unittest.TestCase):
    def test_lists_only_loadable_adapter_modules_sorted(self):
        files = ("zeta.py", "alpha.py", "_private.py", "test_alpha.py", "two_words.py", "Upper.py", "notes.txt")
        with tempfile.TemporaryDirectory() as tmp:
            for name in files:
                open(os.path.join(tmp, name), "w").close()
            with mock.patch.object(providers, "__path__", [tmp]):
                self.assertEqual(providers.names(), ["alpha", "zeta"])

    def test_omits_the_client_and_the_tests_of_the_package(self):
        self.assertEqual(set(providers.names()) & {"_http", "test_http"}, set())


if __name__ == "__main__":
    unittest.main()
