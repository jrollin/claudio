import argparse
import contextlib
import decimal
import fcntl
import json
import math
import os
import sys
from datetime import datetime, timezone

import providers
import state
import store

SCHEMA = 1
DAYS_DIR = "days"
RECORDS_FILE = "records.jsonl"
COVERAGE_FILE = "coverage.json"
LOCK_FILE = ".lock"
DAY_SECONDS = 86400
META_KEYS = ("fetch_id", "fetched_at", "transport")
SPAN, SNAPSHOT = "span", "snapshot"


def day_of(ts):
    return math.floor(decimal.Decimal(ts) / DAY_SECONDS)


def day_parts(day):
    moment = datetime.fromtimestamp(day * DAY_SECONDS, timezone.utc)
    return [f"year={moment.year:04d}", f"month={moment.month:02d}", f"day={moment.day:02d}"]


def day_text(day):
    return datetime.fromtimestamp(day * DAY_SECONDS, timezone.utc).strftime("%Y-%m-%d")


def span_days(span):
    low, high = (decimal.Decimal(bound) for bound in span)
    first, last = math.floor(low / DAY_SECONDS), math.ceil(high / DAY_SECONDS) - 1
    return range(first, last + 1)


def clipped(span, day):
    start, end = day * DAY_SECONDS, (day + 1) * DAY_SECONDS
    low = span[0] if decimal.Decimal(span[0]) >= start else str(start)
    high = span[1] if decimal.Decimal(span[1]) <= end else str(end)
    return [low, high]


def merged_spans(spans):
    result = []
    for low, high in sorted(spans, key=lambda span: (decimal.Decimal(span[0]), decimal.Decimal(span[1]))):
        if result and decimal.Decimal(low) <= decimal.Decimal(result[-1][1]):
            if decimal.Decimal(high) > decimal.Decimal(result[-1][1]):
                result[-1] = [result[-1][0], high]
            continue
        result.append([low, high])
    return result


def fetch_of(document):
    return {"fetch_id": f"{document['run']}.{document['source']}", "fetched_at": document["fetched_at"], "transport": document["transport"]}


def recency(meta):
    return (meta["fetched_at"], meta["fetch_id"])


def without_meta(row):
    return {key: value for key, value in row.items() if key not in META_KEYS}


class DayLayer:
    """The day folders of one store_dir; merges hold days/.lock, so concurrent publishes never interleave."""

    def __init__(self, store_dir):
        self.base = os.path.join(store_dir, DAYS_DIR)

    def merge(self, folder, document):
        adapter = providers.load(document["adapter"])
        style = getattr(adapter, "DAY_KINDS", {}).get(document["kind"])
        if style is None or document["outcome"]["status"] != "complete":
            return []
        rows = store.load_records(folder)
        with self.locked():
            return [self.merge_day(adapter, style, document, day, day_rows) for day, day_rows in self.by_day(adapter, style, document, rows).items()]

    @contextlib.contextmanager
    def locked(self):
        store.make_folders(self.base)
        path = os.path.join(self.base, LOCK_FILE)
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, store.FILE_MODE)
        except OSError as error:
            raise state.InputError(f"days: cannot open {path}: {error.strerror}") from error
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def by_day(self, adapter, style, document, rows):
        entity, span = document["entity"], document["span"]
        found = {}
        if style == SPAN and span is not None:
            found = {day: [] for day in span_days((span["from"], span["to"]))}
        for row in rows:
            ts, _ = adapter.day_row(document["kind"], entity, row)
            found.setdefault(day_of(ts), []).append(row)
        return found

    def folder(self, provider, kind, entity, day):
        parts = [store.folder_part("provider", provider), store.folder_part("kind", kind), *day_parts(day)]
        parts += [store.folder_part(key, entity[key]) for key in sorted(entity)]
        return os.path.join(self.base, *parts)

    def merge_day(self, adapter, style, document, day, rows):
        kind, entity, meta = document["kind"], document["entity"], fetch_of(document)
        folder = self.folder(document["provider"], kind, entity, day)
        held = store.load_records(folder) if os.path.isfile(os.path.join(folder, RECORDS_FILE)) else []
        coverage = load_coverage(folder) or empty_coverage(document, day)
        incoming = [{**row, **meta} for row in rows]
        if style == SNAPSHOT:
            stored = coverage["snapshot"]
            if stored is None or stored["fetch_id"] == meta["fetch_id"] or recency(meta) > recency(stored):
                held, coverage = incoming, {**coverage, "snapshot": meta}
        else:
            held = newest_per_key(adapter, kind, entity, [row for row in held if row["fetch_id"] != meta["fetch_id"]] + incoming)
            span = document["span"]
            spans = dict(coverage["spans"])
            spans[meta["transport"]] = merged_spans([*spans.get(meta["transport"], []), clipped((span["from"], span["to"]), day)])
            coverage = {**coverage, "spans": spans}
        ordered = sorted(held, key=lambda row: row_order(adapter, kind, entity, row))
        store.make_folders(folder)
        state.write_all([(os.path.join(folder, RECORDS_FILE), store.dump_lines(ordered))])
        state.write_all([(os.path.join(folder, COVERAGE_FILE), state.dump(coverage))])
        return folder

    def stored(self, folder):
        return os.path.relpath(folder, os.path.dirname(self.base)).replace(os.sep, "/")

    def holds(self, folder):
        return os.path.isfile(os.path.join(folder, COVERAGE_FILE))

    def closed_folders(self, provider, kind, entity, needed, window_end):
        found = []
        for day in span_days(needed):
            folder = self.folder(provider, kind, entity, day)
            if (day + 1) * DAY_SECONDS <= window_end and self.holds(folder):
                found.append(self.stored(folder))
        return found

    def use(self, folder, transport):
        """Rows and spans a source may reuse: an api source trusts only a folder every record of which came over api."""
        rows, coverage = store.load_records(folder), load_coverage(folder)
        if transport == "api" and any(row["transport"] != "api" for row in rows):
            return None
        trusted = ("api",) if transport == "api" else tuple(coverage["spans"])
        spans = sorted((tuple(span) for name in trusted for span in coverage["spans"].get(name, [])), key=lambda span: decimal.Decimal(span[0]))
        if not spans:
            return None
        return [without_meta(row) for row in rows], spans

    def link(self, stored, target_root):
        source = os.path.join(os.path.dirname(self.base), *stored.split("/"))
        target = os.path.join(target_root, *stored.split("/"))
        with self.locked():
            store.make_folders(target)
            for name in (RECORDS_FILE, COVERAGE_FILE):
                if not os.path.lexists(os.path.join(target, name)):
                    store.link_or_copy(os.path.join(source, name), os.path.join(target, name))
        return target


def row_order(adapter, kind, entity, row):
    ts, key = adapter.day_row(kind, entity, row)
    return (decimal.Decimal(ts), key, recency(row))


def newest_per_key(adapter, kind, entity, rows):
    kept = {}
    for row in rows:
        _, key = adapter.day_row(kind, entity, row)
        if key not in kept or recency(row) > recency(kept[key]):
            kept[key] = row
    return list(kept.values())


def empty_coverage(document, day):
    return {
        "schema": SCHEMA,
        "provider": document["provider"],
        "kind": document["kind"],
        "entity": document["entity"],
        "day": day_text(day),
        "spans": {},
        "snapshot": None,
    }


def load_coverage(folder):
    path = os.path.join(folder, COVERAGE_FILE)
    raw = store.saved_bytes(path)
    if raw is None:
        return None
    try:
        document = json.loads(raw)
    except ValueError as error:
        raise state.InvalidJson(f"days: invalid JSON in {path}: {error}") from error
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise state.Rejected(f"days: {path} is not a schema {SCHEMA} coverage")
    return document


def build_filter(args):
    return store.ReadFilter(argparse.Namespace(**vars(args), channel=None, thread=None))


def run_build(args):
    if not os.path.isdir(args.root):
        raise state.InputError(f"build: root {args.root} is not a folder")
    layer, selector, counts, rejected = DayLayer(args.root), build_filter(args), {}, 0
    for _, path in store.provider_folders(args.root):
        for read in store.walk_reads(path):
            if not selector.matches(read):
                continue
            try:
                written = layer.merge(read.folder, read.document)
            except Exception as error:
                rejected += 1
                print(f"rejected {read.stored}: {store.rejection(error)}")
                continue
            if written:
                key = (read.document["provider"], read.document["kind"])
                reads, folders = counts.get(key, (0, set()))
                counts[key] = (reads + 1, folders | set(written))
    for (provider, kind), (reads, folders) in sorted(counts.items()):
        print(f"{provider} {kind} reads {reads} days {len(folders)}")
    return 3 if rejected else 0


def date_of(text, flag):
    try:
        moment = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise state.InputError(f"{flag}: {text!r} is not a date like 2026-10-26") from None
    return int(moment.timestamp()) // DAY_SECONDS


def subfolders(path):
    try:
        names = sorted(os.listdir(path))
    except FileNotFoundError:
        return []
    return [os.path.join(path, name) for name in names if not name.startswith(".") and os.path.isdir(os.path.join(path, name))]


def leaf_folders(folder):
    for path, folders, files in os.walk(folder):
        folders.sort()
        if COVERAGE_FILE in files:
            yield path


def day_folders(base, day):
    for provider_path in subfolders(base):
        for kind_path in subfolders(provider_path):
            yield from leaf_folders(os.path.join(kind_path, *day_parts(day)))


def entity_text(entity):
    return " ".join(f"{key}={entity[key]}" for key in sorted(entity))


def is_selected(coverage, args):
    return (
        (args.provider is None or coverage["provider"] in args.provider)
        and (args.kind is None or coverage["kind"] in args.kind)
        and (args.channel is None or coverage["entity"].get("channel") in args.channel)
    )


def coverage_text(coverage, day):
    if coverage["snapshot"] is not None:
        return f"read {coverage['snapshot']['fetched_at']}"
    needed = (str(day * DAY_SECONDS), str((day + 1) * DAY_SECONDS))
    spans = [tuple(span) for spans in coverage["spans"].values() for span in spans]
    gaps = store.gaps(needed, spans)
    return "full" if not gaps else "partial " + " ".join(f"{low}_{high}" for low, high in gaps)


def path_values(coverage, day):
    year, month, day_number = (part.split("=", 1)[1] for part in day_parts(day))
    return {"provider": coverage["provider"], "kind": coverage["kind"], "year": year, "month": month, "day": day_number, **coverage["entity"]}


def show_day(base, day, args):
    for folder in day_folders(base, day):
        coverage = load_coverage(folder)
        if not is_selected(coverage, args):
            continue
        if args.records:
            for row in store.load_records(folder):
                print(json.dumps({**row, **path_values(coverage, day)}, sort_keys=True, ensure_ascii=False))
            continue
        print(f"{day_text(day)} {coverage['provider']} {coverage['kind']} {entity_text(coverage['entity'])} {coverage_text(coverage, day)}")


def run_show(args):
    first = date_of(args.date, "--date")
    last = first if args.to is None else date_of(args.to, "--to")
    if last < first:
        raise state.InputError(f"--to: {args.to} is before --date {args.date}")
    base = os.path.join(args.root, DAYS_DIR)
    for day in range(first, last + 1):
        show_day(base, day, args)
    return 0


def dated_folders(provider_path):
    for kind_path in subfolders(provider_path):
        for year in subfolders(kind_path):
            for month in subfolders(year):
                for day in subfolders(month):
                    yield day, os.path.relpath(day, kind_path).replace(os.sep, "/")


def folder_day(parts):
    try:
        moment = datetime.strptime(parts, "year=%Y/month=%m/day=%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(moment.timestamp()) // DAY_SECONDS


def remove_empty_parents(folder, stop):
    parent = os.path.dirname(folder)
    while parent != stop and os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)
        parent = os.path.dirname(parent)


def run_prune(args):
    if not os.path.isdir(args.root):
        raise state.InputError(f"prune: root {args.root} is not a folder")
    base = os.path.join(args.root, DAYS_DIR)
    cutoff = store.now_epoch() - args.older_than_days * DAY_SECONDS
    for key, provider_path in store.provider_folders(base) if os.path.isdir(base) else []:
        deleted = kept = 0
        for folder, parts in list(dated_folders(provider_path)):
            day = folder_day(parts)
            if day is None or (day + 1) * DAY_SECONDS >= cutoff:
                kept += day is not None
                continue
            deleted += 1
            if not args.dry_run:
                store.remove_folder(folder)
                remove_empty_parents(folder, provider_path)
        print(f"{key} deleted {deleted} kept {kept}")
    return 0


COMMANDS = {"build": run_build, "show": run_show, "prune": run_prune}


def build_parser():
    parser = argparse.ArgumentParser(prog="days.py", description="Maintain and query the day layer of a read store")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="file every complete read of the store by day")
    build.add_argument("--root", required=True)
    for flag in ("--provider", "--kind"):
        build.add_argument(flag, action="append")
    build.add_argument("--from", dest="from_text", metavar="UTC_TIME")
    build.add_argument("--to", dest="to_text", metavar="UTC_TIME")
    show = commands.add_parser("show", help="print the coverage or the records of a day or a range of days")
    show.add_argument("--root", required=True)
    show.add_argument("--date", required=True, metavar="YYYY-MM-DD")
    show.add_argument("--to", metavar="YYYY-MM-DD")
    for flag in ("--provider", "--kind", "--channel"):
        show.add_argument(flag, action="append")
    show.add_argument("--records", action="store_true")
    prune = commands.add_parser("prune", help="delete the day folders whose day ended before an age in days")
    prune.add_argument("--root", required=True)
    prune.add_argument("--older-than-days", required=True, type=store.positive_days, metavar="N")
    prune.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        try:
            args.start = None if args.from_text is None else store.utc_time(args.from_text)
            args.end = None if args.to_text is None else store.utc_time(args.to_text)
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))
    try:
        return COMMANDS[args.command](args)
    except state.InputError as error:
        print(f"days.py: {error}", file=sys.stderr)
        return 2
    except state.Rejected as error:
        print(f"days.py: rejected: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
