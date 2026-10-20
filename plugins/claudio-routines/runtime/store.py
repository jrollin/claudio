import argparse
import collections
import decimal
import errno
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import providers
import state
from providers._errors import PartialRead, SourceUnreadable
from providers._http import BODY_CAP
from providers._replay import ReplayMismatch

SCHEMA = 1
READ_FILE = "read.json"
RECORDS_FILE = "records.jsonl"
MANIFEST_FILE = "manifest.json"
INCOMING = ".incoming"
PAGE_SUFFIXES = {"api": ".json", "mcp": ".txt"}
STATUSES = ("complete", "failed", "partial")
REQUEST_FIELDS = {"api": ("method", "path", "query", "body"), "mcp": ("tool", "arguments")}
FOLDER_MODE = 0o700
FILE_MODE = 0o600
LINK_FALLBACK = (errno.EXDEV, errno.EPERM)
PUBLISHED_ALREADY = (errno.EEXIST, errno.ENOTEMPTY)
GIT_LOCATORS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
PART_CAP = 200
BARRED_IN_PART = ("/", "\\", "=", "\x00")
KEY = re.compile(r"[a-z][a-z0-9_]*")
TS = re.compile(r"[0-9]{1,16}(?:\.[0-9]{1,9})?")
PAGE_FILE = re.compile(r"page-[0-9]{3,}\.(?:json|txt)")
READ_NAME = re.compile(r"read=(?:(?P<start>[0-9.]+)_(?P<end>[0-9.]+)-)?(?P<fetch>[^/]+)")
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")
REPLACEMENT = "�"
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
GIT_TIMEOUT = 10
HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA_ONE = state.leaf(lambda value: state.is_integer(value) and value == SCHEMA, f"schema {SCHEMA}")
COUNT = state.leaf(lambda value: state.is_integer(value) and value >= 0, "a non-negative integer")
STATUS = state.leaf(lambda value: value in STATUSES, "one of " + ", ".join(STATUSES))
READ_SPEC = {
    "schema": SCHEMA_ONE,
    "adapter": state.TEXT,
    "provider": state.TEXT,
    "kind": state.TEXT,
    "entity": {"*": state.TEXT},
    "span": state.Nullable({"from": state.TEXT, "to": state.TEXT}),
    "transport": state.TRANSPORT,
    "run": state.TEXT,
    "source": state.TEXT,
    "fetched_at": state.TEXT,
    "pages": [{"file": state.TEXT, "request": state.PRESENT}],
    "outcome": {"status": STATUS, "reason": state.Nullable(state.TEXT)},
    "parsed_by": state.Nullable(state.TEXT),
}
MANIFEST_SPEC = {"schema": SCHEMA_ONE, "sources": {"*": {"reads": [state.TEXT], "fetched": COUNT, "reused": COUNT}}}

StoredRead = collections.namedtuple("StoredRead", "folder stored span fetch_id document")


class PagePending(Exception):
    def __init__(self, call_id, path, request):
        super().__init__(call_id)
        self.call_id = call_id
        self.path = path
        self.request = request


def utc_now():
    return datetime.now(timezone.utc).strftime(UTC_FORMAT)


def runtime_commit():
    try:
        result = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else None


def is_safe(value):
    return (
        isinstance(value, str)
        and value not in ("", ".", "..")
        and len(value.encode("utf-8", "surrogatepass")) <= PART_CAP
        and not any(barred in value for barred in BARRED_IN_PART)
    )


def folder_part(key, value):
    if not isinstance(key, str) or KEY.fullmatch(key) is None:
        raise state.Rejected("store: a folder key must be lowercase words")
    if not is_safe(value):
        raise state.Rejected(f"store: unsafe {key} value")
    return f"{key}={value}"


def read_part(span, fetch_id):
    if span is None:
        return f"read={fetch_id}"
    if len(span) != 2 or not all(isinstance(bound, str) and TS.fullmatch(bound) for bound in span):
        raise state.Rejected("store: a span bound must be a ts")
    return f"read={span[0]}_{span[1]}-{fetch_id}"


def replaced(value):
    if isinstance(value, str):
        return LONE_SURROGATE.sub(REPLACEMENT, value)
    if isinstance(value, list):
        return [replaced(item) for item in value]
    if isinstance(value, dict):
        return {replaced(key): replaced(item) for key, item in value.items()}
    return value


def dump_lines(records):
    lines = (json.dumps(replaced(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for record in records)
    return "".join(lines).encode("utf-8")


def make_folders(folder):
    missing, path = [], folder
    while not os.path.isdir(path):
        missing.append(path)
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    for path in reversed(missing):
        try:
            os.mkdir(path, FOLDER_MODE)
        except FileExistsError:
            continue
        except OSError as error:
            raise state.InputError(f"store: cannot create {path}: {error.strerror}") from error
        os.chmod(path, FOLDER_MODE)


def saved_bytes(path):
    try:
        with open(path, "rb") as stream:
            return stream.read()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise state.InputError(f"store: cannot read {path}: {error.strerror}") from error


def page_bytes(path, call_id):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SourceUnreadable(f"response {call_id} is not a regular file") from None
        raise state.InputError(f"store: cannot read {path}: {error.strerror}") from error
    try:
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SourceUnreadable(f"response {call_id} is not a regular file")
            if info.st_size > BODY_CAP:
                raise PartialRead(f"response over 10 MB {call_id}")
            return stream.read()
    except OSError as error:
        raise state.InputError(f"store: cannot read {path}: {error.strerror}") from error


def is_regular(path):
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def copy_file(source, target):
    data = saved_bytes(source)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except OSError as error:
        raise state.InputError(f"store: cannot copy {source} to {target}: {error.strerror}") from error


def link_or_copy(source, target):
    try:
        os.link(source, target)
    except OSError as error:
        if error.errno not in LINK_FALLBACK:
            raise state.InputError(f"store: cannot link {source} to {target}: {error.strerror}") from error
        copy_file(source, target)


def read_file_names(document):
    pages = [page["file"] for page in document["pages"]]
    if not all(isinstance(name, str) and PAGE_FILE.fullmatch(name) for name in pages):
        raise state.Rejected("store: a read lists a page file outside its folder")
    return [*pages, RECORDS_FILE, READ_FILE]


def link_read(folder, target, document):
    for name in read_file_names(document):
        source = os.path.join(folder, name)
        if is_regular(source) and not os.path.lexists(os.path.join(target, name)):
            link_or_copy(source, os.path.join(target, name))


def rename_read(staging, final):
    try:
        os.rename(staging, final)
    except OSError as error:
        if error.errno not in PUBLISHED_ALREADY:
            raise state.InputError(f"store: cannot publish {final}: {error.strerror}") from error


def existing_folder(path):
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def in_git_repository(path, label):
    environment = {key: value for key, value in os.environ.items() if key not in GIT_LOCATORS}
    try:
        result = subprocess.run(
            ["git", "-C", existing_folder(path), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
            env={**environment, "LC_ALL": "C", "LANGUAGE": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise state.InputError(f"{label}: cannot run git to check that the folder lies outside every repository") from error
    if result.returncode == 0:
        return True
    if "not a git repository" in result.stderr:
        return False
    raise state.InputError(f"{label}: cannot tell whether the folder lies inside a git repository")


def check_store_dir(path, label):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    except OSError as error:
        raise state.InputError(f"{label}: cannot inspect the folder: {error.strerror}") from error
    if info is not None and stat.S_ISLNK(info.st_mode):
        raise state.InputError(f"{label}: is a link, set the folder it points to")
    if info is not None and not stat.S_ISDIR(info.st_mode):
        raise state.InputError(f"{label}: is not a folder")
    if info is not None and info.st_uid != os.getuid():
        raise state.InputError(f"{label}: belongs to another user")
    if in_git_repository(path, label):
        raise state.InputError(f"{label}: lies inside a git working tree, keep the store outside every repository")


def check_read(document):
    state.check(document, READ_SPEC, "")


def check_manifest(document):
    state.check(document, MANIFEST_SPEC, "")


def load_document(folder):
    return state.load(os.path.join(folder, READ_FILE), "read", check_read)


def load_records(folder):
    path = os.path.join(folder, RECORDS_FILE)
    raw = saved_bytes(path)
    if raw is None:
        raise state.InputError(f"store: {path} is missing")
    records = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except ValueError as error:
            raise state.InvalidJson(f"store: invalid JSON in {path} line {number}: {error}") from error
        if not isinstance(record, dict):
            raise state.Rejected(f"store: {path} line {number} is not an object")
        records.append(record)
    return records


def read_order(read):
    if read.span is None:
        return (decimal.Decimal(-1), decimal.Decimal(-1), read.fetch_id)
    return (decimal.Decimal(read.span[0]), decimal.Decimal(read.span[1]), read.fetch_id)


def list_reads(root, folder):
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return []
    except OSError as error:
        raise state.InputError(f"store: cannot list {folder}: {error.strerror}") from error
    found = []
    for name in names:
        match = READ_NAME.fullmatch(name)
        path = os.path.join(folder, name)
        if match is None or not os.path.isfile(os.path.join(path, READ_FILE)):
            continue
        span = None if match["start"] is None else (match["start"], match["end"])
        stored = os.path.relpath(path, root).replace(os.sep, "/")
        found.append(StoredRead(path, stored, span, match["fetch"], load_document(path)))
    return sorted(found, key=read_order)


class ReadSession:
    def __init__(self, root, provider, run, source, adapter, transport, clock=None, runtime=None, shared=None):
        if transport not in PAGE_SUFFIXES:
            raise state.Rejected(f"store: unknown transport {transport}")
        if not is_safe(run) or not is_safe(source):
            raise state.Rejected("store: unsafe run or source name")
        self.root = root
        self.provider = provider
        self.base = os.path.join(root, folder_part("provider", provider))
        self.shared = shared
        self.shared_base = None if shared is None else os.path.join(shared, folder_part("provider", provider))
        self.run = run
        self.source = source
        self.fetch_id = f"{run}.{source}"
        self.adapter = adapter
        self.transport = transport
        self.suffix = PAGE_SUFFIXES[transport]
        self.clock = clock or utc_now
        self.runtime = runtime
        self._used = {}

    def entity_parts(self, kind, entity):
        return [folder_part("kind", kind), *(folder_part(key, value) for key, value in entity)]

    def entity_folder(self, kind, entity):
        return os.path.join(self.base, *self.entity_parts(kind, entity))

    def open(self, kind, entity, span=None):
        parts = [*self.entity_parts(kind, entity), read_part(span, self.fetch_id)]
        handle = self.make_handle(kind, dict(entity), span, parts)
        self._used.setdefault(handle.stored, self.fetch_id)
        return handle

    def make_handle(self, kind, entity, span, parts):
        return ReadHandle(self, kind, entity, span, parts)

    def reads(self, kind, entity):
        return list_reads(self.root, self.entity_folder(kind, entity))

    def shared_reads(self, kind, entity):
        if self.shared is None:
            return []
        return list_reads(self.shared, os.path.join(self.shared_base, *self.entity_parts(kind, entity)))

    def link_in(self, read):
        target = os.path.join(self.root, *read.stored.split("/"))
        make_folders(target)
        link_read(read.folder, target, read.document)
        self._used.setdefault(read.stored, read.fetch_id)
        return read._replace(folder=target)

    def publish(self, handle):
        if self.shared_base is None:
            return
        final = os.path.join(self.shared_base, *handle.relative.split("/"))
        if os.path.isfile(os.path.join(final, READ_FILE)):
            return
        incoming = os.path.join(self.shared_base, INCOMING)
        make_folders(incoming)
        staging = tempfile.mkdtemp(prefix="read-", dir=incoming)
        try:
            link_read(handle.folder, staging, handle.document())
            make_folders(os.path.dirname(final))
            rename_read(staging, final)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def used(self):
        return list(self._used)

    def page_path(self, call_id):
        parts = call_id.split("/") if isinstance(call_id, str) else [""]
        if any(part in ("", ".", "..") for part in parts):
            raise state.Rejected("store: a call id must name a page inside the store")
        return os.path.join(self.base, *parts) + self.suffix

    def saved_pages(self):
        count = 0
        for folder, _, files in os.walk(self.base):
            match = READ_NAME.fullmatch(os.path.basename(folder))
            if match is not None and match["fetch"] == self.fetch_id:
                count += sum(1 for name in files if name.startswith("page-"))
        return count

    def counts(self):
        fetched = sum(1 for fetch_id in self._used.values() if fetch_id == self.fetch_id)
        return {"fetched": fetched, "reused": len(self._used) - fetched}


class ReadHandle:
    def __init__(self, session, kind, entity, span, parts):
        self.session = session
        self.kind = kind
        self.entity = entity
        self.span = span
        self.relative = "/".join(parts)
        self.stored = "/".join((os.path.basename(session.base), *parts))
        self.folder = os.path.join(session.base, *parts)
        self.last_id = None
        self._pages = []

    def done(self):
        return os.path.isfile(os.path.join(self.folder, READ_FILE))

    def next_page(self, request):
        number = len(self._pages) + 1
        name = f"page-{number:03d}{self.session.suffix}"
        self._pages.append({"file": name, "request": request})
        self.last_id = f"{self.relative}/page-{number:03d}"
        return number, os.path.join(self.folder, name)

    def page(self, request, fetch=None):
        _, path = self.next_page(request)
        saved = page_bytes(path, self.last_id)
        if saved is not None:
            return saved
        if fetch is None:
            raise PagePending(self.last_id, path, request)
        data = fetch()
        make_folders(self.folder)
        state.write_all([(path, data)])
        return data

    def finish(self, status, reason=None, records=None):
        if status not in STATUSES:
            raise state.Rejected(f"store: unknown read status {status}")
        if not self.done():
            make_folders(self.folder)
            if status == "complete":
                state.write_all([(os.path.join(self.folder, RECORDS_FILE), dump_lines(records or []))])
            state.write_all([(os.path.join(self.folder, READ_FILE), state.dump(replaced(self._document(status, reason))))])
        self.session.publish(self)

    def document(self):
        return load_document(self.folder)

    def records(self):
        if self.document()["outcome"]["status"] != "complete":
            raise state.InputError(f"store: {self.relative} holds no records")
        return load_records(self.folder)

    def _document(self, status, reason):
        session = self.session
        return {
            "schema": SCHEMA,
            "adapter": session.adapter,
            "provider": session.provider,
            "kind": self.kind,
            "entity": self.entity,
            "span": None if self.span is None else {"from": self.span[0], "to": self.span[1]},
            "transport": session.transport,
            "run": session.run,
            "source": session.source,
            "fetched_at": session.clock(),
            "pages": list(self._pages),
            "outcome": {"status": status, "reason": reason},
            "parsed_by": session.runtime,
        }


def request_label(request):
    if "tool" in request:
        return str(request["tool"])
    return f"{request.get('method')} {request.get('path')}"


class ReplaySession(ReadSession):
    def __init__(self, root, provider, run, source, adapter, transport, reads):
        super().__init__(root, provider, run, source, adapter, transport)
        self.recorded = frozenset(reads)

    def make_handle(self, kind, entity, span, parts):
        handle = ReplayHandle(self, kind, entity, span, parts)
        if handle.stored not in self.recorded:
            raise ReplayMismatch(f"replay: source {self.source} asks {handle.stored}, a read the run did not make")
        return handle


class ReplayHandle(ReadHandle):
    def page(self, request, fetch=None):
        number, path = self.next_page(request)
        if self.done():
            listed = self.document()["pages"]
            where = f"replay: {self.stored} call {number} {request_label(request)}"
            if number > len(listed):
                raise ReplayMismatch(f"{where}: no record, {len(listed)} recorded")
            held = listed[number - 1]["request"]
            differing = [field for field in REQUEST_FIELDS[self.session.transport] if held.get(field) != request.get(field)]
            if differing:
                raise ReplayMismatch(f"{where}: request differs from its record in {', '.join(differing)}")
        saved = page_bytes(path, self.last_id)
        if saved is None:
            raise PagePending(self.last_id, path, request)
        return saved

    def finish(self, status, reason=None, records=None):
        return None


def write_manifest(run_dir, source, session):
    path = os.path.join(run_dir, MANIFEST_FILE)
    document = state.load(path, "manifest", check_manifest) if os.path.exists(path) else {"schema": SCHEMA, "sources": {}}
    entry = {"reads": session.used(), **session.counts()}
    make_folders(run_dir)
    state.write_all([(path, state.dump({"schema": SCHEMA, "sources": {**document["sources"], source: entry}}))])


def utc_time(value):
    try:
        moment = datetime.strptime(value, UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a UTC time like 2026-10-20T07:30:00Z") from None
    return decimal.Decimal(int(moment.timestamp()))


def walk_reads(root):
    for folder, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if not name.startswith("."))
        match = READ_NAME.fullmatch(os.path.basename(folder))
        if match is None:
            continue
        folders[:] = []
        if READ_FILE in files:
            span = None if match["start"] is None else (match["start"], match["end"])
            yield StoredRead(folder, os.path.relpath(folder, root).replace(os.sep, "/"), span, match["fetch"], load_document(folder))


class ReadFilter:
    def __init__(self, args):
        self.args = args
        self.providers = args.provider
        self.channels = args.channel
        self.threads = args.thread
        self.kinds = args.kind
        self.start = args.start
        self.end = args.end

    def matches(self, read):
        document, entity = read.document, read.document["entity"]
        checks = (
            self.providers is None or document["provider"] in self.providers,
            self.kinds is None or document["kind"] in self.kinds,
            self.channels is None or entity.get("channel") in self.channels,
            self.threads is None or (document["kind"] == "thread" and f"{entity.get('channel')}:{entity.get('root')}" in self.threads),
            self.overlaps(read.span),
        )
        return document["outcome"]["status"] == "complete" and all(checks)

    def overlaps(self, span):
        if self.start is None and self.end is None:
            return True
        if span is None:
            return False
        low, high = decimal.Decimal(span[0]), decimal.Decimal(span[1])
        return (self.end is None or low < self.end) and (self.start is None or high > self.start)

    def text(self):
        args = self.args
        pairs = [("--provider", args.provider), ("--channel", args.channel), ("--thread", args.thread), ("--kind", args.kind)]
        parts = [f"{flag} {value}" for flag, values in pairs for value in values or ()]
        parts += [f"{flag} {raw}" for flag, raw in (("--from", args.from_text), ("--to", args.to_text)) if raw is not None]
        return " ".join(parts) or "no filter"


def reparsed_rows(read):
    document, pages = read.document, []
    for page in document["pages"]:
        data = page_bytes(os.path.join(read.folder, page["file"]), page["file"])
        if data is None:
            raise SourceUnreadable(f"page {page['file']} is missing")
        pages.append(data)
    adapter = providers.load(document["adapter"])
    return adapter.to_rows(document["kind"], adapter.parse_read(document["kind"], document, pages))


def reparse_read(read, commit):
    records = dump_lines(reparsed_rows(read))
    path = os.path.join(read.folder, RECORDS_FILE)
    changed = saved_bytes(path) != records
    if changed:
        state.write_all([(path, records)])
    if changed or read.document["parsed_by"] != commit:
        state.write_all([(os.path.join(read.folder, READ_FILE), state.dump(replaced({**read.document, "parsed_by": commit})))])
    return changed


def rejection(error):
    if isinstance(error, (SourceUnreadable, state.Rejected, state.InputError)):
        return state.blank_controls(str(error))
    return f"adapter error: {type(error).__name__}"


def run_reparse(args):
    if not os.path.isdir(args.root):
        raise state.InputError(f"reparse: root {args.root} is not a folder")
    selector = ReadFilter(args)
    selected = [read for read in walk_reads(args.root) if selector.matches(read)]
    if not selected:
        raise state.InputError(f"reparse: no read matches {selector.text()}")
    commit, changed, rejected = runtime_commit(), 0, 0
    for read in selected:
        try:
            moved = reparse_read(read, commit)
        except Exception as error:
            rejected += 1
            print(f"rejected {read.stored}: {rejection(error)}")
            continue
        changed += moved
        print(f"{'changed' if moved else 'same'} {read.stored}")
    print(f"reparsed {len(selected) - rejected}, changed {changed}, rejected {rejected}")
    return 3 if rejected else 0


COMMANDS = {"reparse": run_reparse}


def build_parser():
    parser = argparse.ArgumentParser(prog="store.py", description="Maintain the read store of routine sources")
    commands = parser.add_subparsers(dest="command", required=True)
    reparse = commands.add_parser("reparse", help="rewrite the records of the selected reads from their saved pages")
    reparse.add_argument("--root", required=True)
    for flag in ("--provider", "--channel", "--thread", "--kind"):
        reparse.add_argument(flag, action="append")
    reparse.add_argument("--from", dest="from_text", metavar="UTC_TIME")
    reparse.add_argument("--to", dest="to_text", metavar="UTC_TIME")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.start = None if args.from_text is None else utc_time(args.from_text)
        args.end = None if args.to_text is None else utc_time(args.to_text)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    try:
        return COMMANDS[args.command](args)
    except state.InputError as error:
        print(f"store.py: {error}", file=sys.stderr)
        return 2
    except state.Rejected as error:
        print(f"store.py: rejected: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
