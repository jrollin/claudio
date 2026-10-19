import http.client
import json
import os
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from ._errors import CredentialsMissing, PartialRead, SourceUnreadable

TIMEOUT = 30
RETRY_CAP = 30
RETRY_DEFAULT = 1
PAGE_CAP = 20
BODY_CAP = 10 * 1024 * 1024
READ_CHUNK = 64 * 1024


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def default_opener():
    return urllib.request.build_opener(
        RefuseRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )


def check_base_url(base_url):
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc or "?" in base_url or "#" in base_url:
        raise ValueError("base_url: must be an https URL without user info, query or fragment")
    return parts


def is_retryable(status):
    return status == 429 or status >= 500


def retry_delay(headers):
    try:
        seconds = int(headers.get("Retry-After", RETRY_DEFAULT))
    except ValueError:
        seconds = RETRY_DEFAULT
    return min(max(seconds, 0), RETRY_CAP)


def is_header_safe(value):
    return all(ord(char) <= 0xFF and unicodedata.category(char) != "Cc" for char in value)


def outcome(call, arg, errors):
    try:
        return True, call(arg)
    except errors:
        return False, None


def error_class(exc):
    reason = getattr(exc, "reason", None)
    return type(reason if isinstance(reason, BaseException) else exc).__name__


class HttpClient:
    def __init__(self, base_url, credentials, auth, opener=None, environ=None, sleep=None, clock=None):
        self.base = check_base_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.credentials = dict(credentials)
        self.auth = auth
        self.opener = opener if opener is not None else default_opener()
        self.environ = environ if environ is not None else os.environ
        self.sleep = sleep if sleep is not None else time.sleep
        self.clock = clock if clock is not None else time.monotonic
        self.response_headers = None

    def get(self, path, params=None):
        query = "?" + urllib.parse.urlencode(params, doseq=True) if params else ""
        return self._call("GET", self._url(path) + query, path, None)

    def post(self, path, body):
        return self._call("POST", self._url(path), path, json.dumps(body).encode("utf-8"))

    def get_url(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != self.base.scheme or parts.netloc.lower() != self.base.netloc.lower():
            raise SourceUnreadable(f"link refused GET {parts.path}: not on the base_url host")
        return self._call("GET", url, parts.path, None)

    def _url(self, path):
        if not path.startswith("/"):
            raise ValueError(f"request path {path!r}: must start with /")
        return self.base_url + path

    def _headers(self, data):
        values = {name: self.environ.get(var) for name, var in self.credentials.items()}
        missing = sorted(self.credentials[name] for name, value in values.items() if not value)
        if missing:
            raise CredentialsMissing("credentials missing: " + ", ".join(missing))
        invalid = sorted(self.credentials[name] for name, value in values.items() if not is_header_safe(value))
        if invalid:
            raise SourceUnreadable("credentials invalid: " + ", ".join(invalid))
        built, auth_headers = outcome(self.auth, values, Exception)
        if not built:
            raise SourceUnreadable("credentials invalid: auth")
        headers = {"Accept": "application/json", **auth_headers}
        if data is not None:
            headers["Content-Type"] = "application/json"
        return headers

    def _attempt(self, request, method, path):
        deadline = self.clock() + TIMEOUT
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                return None, response.headers, self._read(response, deadline, method, path)
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code, exc.headers, None
        except (OSError, ValueError, http.client.HTTPException) as exc:
            failure = error_class(exc)
        raise SourceUnreadable(f"{method} {path}: {failure}")

    def _read(self, response, deadline, method, path):
        read = getattr(response, "read1", response.read)
        chunks, size = [], 0
        while size <= BODY_CAP:
            if self.clock() > deadline:
                raise SourceUnreadable(f"{method} {path}: timeout")
            chunk = read(min(READ_CHUNK, BODY_CAP + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)

    def _call(self, method, url, path, data):
        self.response_headers = None
        request = urllib.request.Request(url, data=data, headers=self._headers(data), method=method)
        status, headers, body = self._attempt(request, method, path)
        if status is not None and is_retryable(status):
            self.sleep(retry_delay(headers))
            status, headers, body = self._attempt(request, method, path)
        if status is None:
            return self._decode(body, headers, method, path)
        if 300 <= status < 400:
            raise SourceUnreadable(f"redirect refused {method} {path}")
        raise SourceUnreadable(f"HTTP {status} {method} {path}", status)

    def _decode(self, body, headers, method, path):
        if len(body) > BODY_CAP:
            raise PartialRead("response over 10 MB")
        parsed, decoded = outcome(json.loads, body, ValueError)
        if not parsed:
            raise SourceUnreadable(f"{method} {path}: invalid JSON")
        self.response_headers = headers
        return decoded
