import datetime
import json
import re
import urllib.parse

from ._http import HttpClient
from ._errors import SourceUnreadable

FRACTION = re.compile(r"(?<=:[0-9]{2})\.[0-9]+")
UTC = datetime.timezone.utc
BASE_URL_INVALID = "api.base_url: must be an https URL without user info, query or fragment"


def api_client(provider, required, auth, opener=None, environ=None, sleep=None):
    api = provider["api"]
    missing = [name for name in required if name not in api["credentials"]]
    if missing:
        raise SourceUnreadable(_must_name(required, missing))
    return _client(api["base_url"], api["credentials"], auth, opener, environ, sleep)


def injected_client(provider, static_headers, opener=None):
    return _client(provider["api"]["base_url"], {}, lambda values: static_headers, opener, None, None)


def _client(base_url, credentials, auth, opener, environ, sleep):
    try:
        return HttpClient(base_url, credentials, auth, opener=opener, environ=environ, sleep=sleep)
    except ValueError:
        raise SourceUnreadable(BASE_URL_INVALID) from None


def _must_name(required, missing):
    named = "api.credentials: must name " + " and ".join(required)
    return named if len(required) == 1 else f"{named}; missing " + ", ".join(missing)


def ended(partial=None):
    return {"done": True, "partial": partial, "calls": []}


def json_object(text, not_json, not_object):
    try:
        document = json.loads(text)
    except ValueError:
        raise SourceUnreadable(not_json) from None
    if not isinstance(document, dict):
        raise SourceUnreadable(not_object)
    return document


def utc_text(value):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.datetime.fromisoformat(FRACTION.sub("", value, count=1).replace("Z", "+00:00"))
        utc = moment.replace(tzinfo=moment.tzinfo or UTC).astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    return utc.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def read_start(window, cursor_ts):
    first = window["first_read_from_ts"]
    return cursor_ts if cursor_ts is not None and cursor_ts > first else first


def quote(value):
    return urllib.parse.quote(value, safe="")


def dig(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def as_list(value):
    return value if isinstance(value, list) else []
