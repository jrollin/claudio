from state import Rejected

from ._errors import CredentialsMissing, PartialRead, SourceUnreadable
from ._http import HttpClient

ERRORS = {error.__name__: error for error in (SourceUnreadable, PartialRead, CredentialsMissing)}
REQUEST = ("method", "path", "query", "body")
PARTIAL_PREFIX = "partial: "


class ReplayMismatch(Rejected):
    pass


class Offline:
    def open(self, request, timeout=None):
        raise ReplayMismatch(f"replay made a network call to {request.full_url}")


OFFLINE = Offline()


class ReplayClient(HttpClient):
    def __init__(self, provider, name, records):
        super().__init__(provider["api"]["base_url"], {}, None, opener=OFFLINE, environ={})
        self.name = name
        self.records = list(records)
        self.calls = 0

    def _exchange(self, method, url, path, data, record):
        self.response_headers = None
        self._check_host(method, url)
        self.calls += 1
        where = f"source {self.name} call {self.calls} {method} {record['path']}"
        if self.calls > len(self.records):
            raise ReplayMismatch(f"{where}: no record, {len(self.records)} recorded")
        held = self.records[self.calls - 1]
        differing = [key for key in REQUEST if held[key] != record[key]]
        if differing:
            raise ReplayMismatch(f"{where}: request differs from its record in {', '.join(differing)}")
        if held["error"] is not None:
            raise recorded_error(held["error"], where)
        if held["link"] is not None:
            self.response_headers = {"Link": held["link"]}
        return held["response"]


def recorded_error(error, where):
    kind = ERRORS.get(error["class"])
    if kind is None:
        raise ReplayMismatch(f"{where}: recorded error class {error['class']} is not replayable")
    if kind is PartialRead:
        return PartialRead(error["message"].removeprefix(PARTIAL_PREFIX))
    return kind(error["message"], error["status"])
