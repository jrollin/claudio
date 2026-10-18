import argparse
import codecs
import fnmatch
import itertools
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

DENY_WORDS_ENV = "LEAK_DENY_WORDS"
DENY_WORDS_FILE_ENV = "CLAUDIO_DENY_WORDS_FILE"
REQUIRE_DENY_WORDS_ENV = "CLAUDIO_REQUIRE_DENY_WORDS"
DEFAULT_DENY_WORDS_FILE = "~/.config/claudio/deny-words.txt"
REDACTED = "<redacted>"
MESSAGE_PATH = "<message>"
COMMIT_RECORD = "\x1eCOMMIT "
DEFAULT_ALLOW_FILE = Path(__file__).resolve().parent / "leak-allow.txt"
ALLOW_ENTRY = re.compile(r"^(path|commit):(\S+)\s+(\S+)$")
SHORT_HASH = re.compile(r"^[0-9a-f]{7,40}$")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
WHITESPACE_RUN = r"[^\S\r\n]+"
UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
GIT_CONFIG = ("core.quotePath=false", "diff.suppressBlankEmpty=false")
DIFF_OPTIONS = ("--text", "--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/")
HISTORY_DIFF_OPTIONS = ("-p", "--root", "-M", "--diff-merges=remerge", *DIFF_OPTIONS, "--format=%x1eCOMMIT %H %h")
HISTORY_PATH_OPTIONS = ("--root", "-M", "--diff-merges=remerge", "--name-status", "-z", "--format=%x1eCOMMIT %H %h")
ALL_COMMITS = ("--all",)


class ScanError(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    accept: Callable[[str], bool] | None = None

    def finditer(self, text: str) -> Iterator[re.Match]:
        return (m for m in self.pattern.finditer(text) if self.accept is None or self.accept(m.group(0)))

    def matches(self, text: str) -> bool:
        return next(self.finditer(text), None) is not None


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    commit: str | None = None
    short: str | None = None
    in_message: bool = False

    def display(self, rules: list[Rule]) -> str:
        location = f"{redact(self.path, rules)}:{self.line}:{self.rule}"
        return f"{self.short}:{location}" if self.short else location


@dataclass(frozen=True)
class AddedLine:
    record: str | None
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Allowlist:
    paths: tuple[tuple[str, str], ...] = ()
    commits: tuple[tuple[str, str], ...] = ()

    def allows(self, finding: Finding) -> bool:
        by_commit = finding.commit is not None and any(
            finding.commit.startswith(prefix) and rule == finding.rule for prefix, rule in self.commits
        )
        by_path = not finding.in_message and any(
            rule == finding.rule and fnmatch.fnmatchcase(finding.path, glob) for glob, rule in self.paths
        )
        return by_commit or by_path


def _bounded(body: str) -> str:
    return rf"(?<![0-9A-Za-z]){body}(?![0-9A-Za-z])"


def _has_digit_after_first(match: str) -> bool:
    return any(c.isdigit() for c in match[1:])


GENERIC_RULES = (
    Rule(
        "slack-id",
        re.compile(r"(?<![A-Za-z0-9])[UCDGWTBAS][A-Z0-9]{8,11}(?![A-Za-z0-9])"),
        _has_digit_after_first,
    ),
    Rule(
        "notion-id",
        re.compile(
            _bounded("[0-9a-fA-F]{32}")
            + r"|(?<![0-9a-fA-F])(?i:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-fA-F])"
        ),
    ),
    Rule(
        "aws-account",
        re.compile(
            r"(?<![0-9A-Za-z])(?<![0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-)"
            r"(?:[0-9]{12}|[0-9]{4}-[0-9]{4}-[0-9]{4})(?![0-9A-Za-z])"
        ),
    ),
    Rule("atlassian-account", re.compile(r"[0-9]{6}:[0-9a-f-]{36}|" + _bounded("[0-9a-f]{24}"))),
    Rule(
        "token",
        re.compile(
            "|".join(
                (
                    r"ghp_[A-Za-z0-9]{36}",
                    r"gh[ousr]_[A-Za-z0-9]{36}",
                    r"github_pat_[A-Za-z0-9_]{22,}",
                    r"xox[abprs]-[A-Za-z0-9-]{10,}",
                    r"(?:AKIA|ASIA)[0-9A-Z]{16}",
                    r"AIza[0-9A-Za-z_-]{35}",
                    r"figd_[A-Za-z0-9_-]{30,}",
                    r"sk-ant-[A-Za-z0-9_-]{20,}",
                    r"sk-proj-[A-Za-z0-9_-]{20,}",
                    r"glpat-[A-Za-z0-9_-]{20}",
                    r"npm_[A-Za-z0-9]{36}",
                    r"ATATT[A-Za-z0-9_=-]{20,}",
                    r"eyJ[A-Za-z0-9_-]{7,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
                    r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----",
                )
            )
        ),
    ),
    Rule(
        "home-path",
        re.compile(
            r"(?<![\w.])/(?:(?i:users)|home)/[A-Za-z0-9._-]+"
            r"|(?<![A-Za-z])[A-Za-z]:\\{1,2}(?i:users)\\{1,2}[A-Za-z0-9._-]+"
            r"|(?i:%2F(?:users|home)%2F)[A-Za-z0-9._-]+"
        ),
    ),
)
RULE_NAMES = tuple(rule.name for rule in GENERIC_RULES) + ("deny-word",)


def parse_deny_words(text: str) -> list[str]:
    entries = (line.strip() for line in text.splitlines())
    return [e for e in entries if e and not e.startswith("#") and e.lstrip("=").strip()]


def _deny_pattern(entry: str) -> str:
    whole_word = entry.startswith("=")
    body = WHITESPACE_RUN.join(re.escape(word) for word in entry.lstrip("=").split())
    return _bounded(body) if whole_word else body


def deny_word_rule(entries: list[str]) -> Rule:
    alternatives = (_deny_pattern(e) for e in sorted(entries, key=len, reverse=True))
    return Rule("deny-word", re.compile("|".join(alternatives), re.IGNORECASE))


def build_rules(deny_entries: list[str]) -> list[Rule]:
    return list(GENERIC_RULES) + ([deny_word_rule(deny_entries)] if deny_entries else [])


def scan_text(text: str, rules: list[Rule]) -> list[str]:
    return [rule.name for rule in rules if rule.matches(text)]


def redact(text: str, rules: list[Rule]) -> str:
    hidden = [False] * len(text)
    for rule in rules:
        for match in rule.finditer(text):
            hidden[match.start() : match.end()] = [True] * (match.end() - match.start())
    return "".join(
        REDACTED if is_hidden else "".join(c for c, _ in group)
        for is_hidden, group in itertools.groupby(zip(text, hidden), key=lambda pair: pair[1])
    )


def decode_text(data: bytes) -> str:
    if b"\0" not in data:
        return data.decode("utf-8", "replace")
    if data[:2] in UTF16_BOMS:
        return data.decode("utf-16", "replace")
    return data.decode("latin-1")


def _read_deny_words_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except UnicodeDecodeError as exc:
        raise ScanError("the deny-words file is not valid UTF-8") from exc
    except OSError as exc:
        raise ScanError(f"cannot read the deny-words file: {exc.strerror}") from exc


def load_deny_words(environ: dict[str, str], required: bool) -> list[str]:
    env_text = environ.get(DENY_WORDS_ENV, "")
    if env_text.strip():
        source, text = DENY_WORDS_ENV, env_text
    else:
        configured = environ.get(DENY_WORDS_FILE_ENV)
        source = DENY_WORDS_FILE_ENV if configured else DEFAULT_DENY_WORDS_FILE
        text = _read_deny_words_file(Path(configured or DEFAULT_DENY_WORDS_FILE).expanduser())
    entries = parse_deny_words(text)
    if entries:
        return entries
    if required:
        raise ScanError(
            f"deny-words required but none found in {DENY_WORDS_ENV} or {source}; "
            f"set {DENY_WORDS_ENV} or {DENY_WORDS_FILE_ENV}"
        )
    print(f"leak_check: deny-words skipped: no entry in {source}; generic rules only", file=sys.stderr)
    return []


def parse_allowlist(text: str, source: str) -> Allowlist:
    paths, commits = [], []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry = ALLOW_ENTRY.match(line)
        if not entry or entry.group(3) not in RULE_NAMES:
            raise ScanError(f"{source}:{line_no}: expected 'path:<glob> <rule>' or 'commit:<short-hash> <rule>'")
        kind, target, rule = entry.groups()
        if kind == "commit" and not SHORT_HASH.match(target):
            raise ScanError(f"{source}:{line_no}: commit entry needs 7 to 40 lowercase hex characters")
        (paths if kind == "path" else commits).append((target, rule))
    return Allowlist(tuple(paths), tuple(commits))


def load_allowlist(path: Path) -> Allowlist:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ScanError(f"allowlist {path.name} is not valid UTF-8") from exc
    except OSError as exc:
        raise ScanError(f"cannot read allowlist {path.name}: {exc.strerror}") from exc
    return parse_allowlist(text, path.name)


def git(root: Path, *args: str) -> str:
    config = [arg for setting in GIT_CONFIG for arg in ("-c", setting)]
    try:
        proc = subprocess.run(["git", *config, *args], cwd=root, capture_output=True)
    except OSError as exc:
        raise ScanError(f"cannot start git: {exc.strerror}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines() or ["no error output"]
        raise ScanError(f"git {args[0]} exited {proc.returncode}: {detail[0]}")
    return proc.stdout.decode("utf-8", "replace")


def _diff_path(target: str) -> str | None:
    if target.startswith('"') and target.endswith('"'):
        try:
            target = codecs.escape_decode(target[1:-1].encode())[0].decode("utf-8", "replace")
        except (ValueError, UnicodeError) as exc:
            raise ScanError("cannot decode a quoted path in the git diff output") from exc
    return target[2:] if target.startswith("b/") else None


def added_lines(diff: str) -> Iterator[AddedLine]:
    record = path = None
    # Hunk counters, not line prefixes, end a hunk: an added line may look like a diff header.
    old_left = new_left = line_no = 0
    for raw in diff.split("\n"):
        if old_left > 0 or new_left > 0:
            tag, body = raw[:1], raw[1:]
            if tag == "+":
                if path is not None:
                    yield AddedLine(record, path, line_no, body)
                line_no += 1
                new_left -= 1
            elif tag == "-":
                old_left -= 1
            elif tag == " ":
                line_no += 1
                old_left -= 1
                new_left -= 1
            continue
        header = HUNK_HEADER.match(raw)
        if header:
            old_left = int(header.group(1) or 1)
            line_no = int(header.group(2))
            new_left = int(header.group(3) or 1)
        elif raw.startswith(COMMIT_RECORD):
            record, path = raw[len(COMMIT_RECORD) :], None
        elif raw.startswith("+++ "):
            path = _diff_path(raw[4:].rstrip("\t"))
        elif raw.startswith("diff --git "):
            path = None


def added_paths(log: str) -> Iterator[tuple[str | None, str]]:
    tokens = iter(log.split("\0"))
    record = None
    for token in tokens:
        status = token.lstrip("\n")
        if status.startswith(COMMIT_RECORD):
            record = status[len(COMMIT_RECORD) :]
        elif status[:1] in ("R", "C"):
            old, new = next(tokens), next(tokens)
            yield from ((record, path) for path in ((old, new) if status[0] == "R" else (new,)))
        elif status[:1] == "A":
            yield record, next(tokens)
        elif status:
            next(tokens)


def line_findings(path: str, line_no: int, text: str, rules: list[Rule]) -> Iterator[Finding]:
    return (Finding(path, line_no, name) for name in scan_text(text, rules))


def message_findings(
    message: str, rules: list[Rule], commit: str | None = None, short: str | None = None
) -> Iterator[Finding]:
    for line_no, text in enumerate(message.split("\n"), 1):
        for name in scan_text(text, rules):
            yield Finding(MESSAGE_PATH, line_no, name, commit, short, in_message=True)


def scan_staged(root: Path, rules: list[Rule]) -> Iterator[Finding]:
    names = git(root, "diff", "--cached", "--name-only", "-z", "--no-renames", "--diff-filter=d")
    for path in filter(None, names.split("\0")):
        yield from line_findings(path, 0, path, rules)
    diff = git(root, "diff", "--cached", "--no-renames", "-U0", *DIFF_OPTIONS)
    for added in added_lines(diff):
        yield from line_findings(added.path, added.line, added.text, rules)


def scan_tree(root: Path, rules: list[Rule]) -> Iterator[Finding]:
    listing = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for path in dict.fromkeys(filter(None, listing.split("\0"))):
        yield from line_findings(path, 0, path, rules)
        full = root / path
        if full.is_symlink():
            yield from line_findings(path, 1, os.readlink(full), rules)
            continue
        if not full.is_file():
            continue
        try:
            data = full.read_bytes()
        except OSError as exc:
            raise ScanError(f"cannot read {redact(path, rules)}: {exc.strerror}") from exc
        for line_no, text in enumerate(decode_text(data).split("\n"), 1):
            yield from line_findings(path, line_no, text, rules)


def _history_diff_findings(root: Path, rules: list[Rule], selection: Sequence[str]) -> Iterator[Finding]:
    for added in added_lines(git(root, "log", *HISTORY_DIFF_OPTIONS, *selection)):
        commit, short = added.record.split(" ")
        for name in scan_text(added.text, rules):
            yield Finding(added.path, added.line, name, commit, short)


def _history_path_findings(root: Path, rules: list[Rule], selection: Sequence[str]) -> Iterator[Finding]:
    for record, path in added_paths(git(root, "log", *HISTORY_PATH_OPTIONS, *selection)):
        commit, short = record.split(" ")
        for name in scan_text(path, rules):
            yield Finding(path, 0, name, commit, short)


def _history_message_findings(root: Path, rules: list[Rule], selection: Sequence[str]) -> Iterator[Finding]:
    parts = git(root, "log", "--format=%H %h%x00%B%x00", *selection).split("\0")
    for header, message in zip(parts[0::2], parts[1::2]):
        commit, short = header.split()
        yield from message_findings(message, rules, commit, short)


def scan_history(root: Path, rules: list[Rule], selection: Sequence[str] = ALL_COMMITS) -> Iterator[Finding]:
    yield from _history_diff_findings(root, rules, selection)
    yield from _history_path_findings(root, rules, selection)
    yield from _history_message_findings(root, rules, selection)


def scan_message(path: Path, rules: list[Rule]) -> Iterator[Finding]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ScanError(f"cannot read the message file: {exc.strerror}") from exc
    return message_findings(decode_text(data), rules)


SCANNERS = {"staged": scan_staged, "tree": scan_tree, "history": scan_history}


def scan(args: argparse.Namespace, rules: list[Rule]) -> Iterator[Finding]:
    if args.message is not None:
        return scan_message(args.message, rules)
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    if args.range is not None:
        return scan_history(root, rules, ("--end-of-options", args.range))
    return SCANNERS[args.mode](root, rules)


def summary(findings: list[Finding], reported: list[Finding]) -> list[str]:
    found = Counter(f.rule for f in reported)
    total = Counter(f.rule for f in findings)
    lines = [
        f"leak_check: {rule}: {found[rule]} found, {total[rule] - found[rule]} allowed"
        for rule in RULE_NAMES
        if total[rule]
    ]
    return lines + [f"leak_check: total: {len(reported)} found, {len(findings) - len(reported)} allowed"]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="leak_check.py", description="Scan for private identifiers; print path:line:rule, never the match."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", dest="mode", action="store_const", const="staged", help="added lines of the index")
    mode.add_argument("--tree", dest="mode", action="store_const", const="tree", help="tracked and untracked files")
    mode.add_argument(
        "--history", dest="mode", action="store_const", const="history", help="added lines, paths and messages of all commits"
    )
    mode.add_argument("--range", metavar="REV_RANGE", help="added lines, paths and messages of the commits in a range")
    mode.add_argument("--message", type=Path, metavar="FILE", help="one commit message file")
    parser.add_argument("--require-deny-words", action="store_true", help="exit 2 when no deny-word is configured")
    parser.add_argument(
        "--allow",
        type=Path,
        default=DEFAULT_ALLOW_FILE,
        metavar="FILE",
        help="allowlist (default: leak-allow.txt next to this script)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace, rules: list[Rule]) -> int:
    allowlist = load_allowlist(args.allow)
    findings = list(scan(args, rules))
    reported = [f for f in findings if not allowlist.allows(f)]
    for finding in reported:
        print(finding.display(rules))
    print("\n".join(summary(findings, reported)), file=sys.stderr)
    return 1 if reported else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rules = list(GENERIC_RULES)
    try:
        required = args.require_deny_words or os.environ.get(REQUIRE_DENY_WORDS_ENV) == "1"
        rules = build_rules(load_deny_words(dict(os.environ), required))
        return run(args, rules)
    except ScanError as exc:
        print(f"leak_check: cannot run: {redact(str(exc), rules)}", file=sys.stderr)
    # Never print the error itself: its text may hold a match.
    except Exception as exc:
        print(f"leak_check: cannot run: {type(exc).__name__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
