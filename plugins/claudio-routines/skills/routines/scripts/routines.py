import argparse
import contextlib
import difflib
import importlib
import importlib.util
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

import lint

SCRIPT_PATH = Path(os.path.abspath(__file__))
SCRIPT_DIR = str(SCRIPT_PATH.parent)
TEMPLATES_DIR = str(SCRIPT_PATH.parents[1] / "templates")
SKILL_PATH = str(SCRIPT_PATH.parents[1] / "SKILL.md")
README_PATH = str(SCRIPT_PATH.parents[3] / "README.md")
RUNTIME_PATH = str(SCRIPT_PATH.parents[3] / "runtime")
PLUGIN_IN_REPO = "plugins/claudio-routines"
RUNTIME_IN_REPO = "plugins/claudio-routines/runtime"
PLACES = ("cloud", "local")
SETUP_TEMPLATE = "setup-env.sh"
TEMP_PREFIX = ".routines-"
HTTP_LINE = re.compile(r"HTTP\s+([0-9]{3})(?:\s.*)?")
TAG_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
TEMPLATE_NAME = re.compile(r"[a-z0-9-]+")
RUNTIME_DIR = re.compile(r"(/[A-Za-z0-9._-]+){2,}/?")
RUNTIME_DIR_PREFIX = "claudio-runtime"
TIMEZONE_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*")
STATE_DIR = re.compile(r"(/[A-Za-z0-9._-]+)+/?")
REPO_URL = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?/[^\s@?#]+")
PLACEHOLDER = re.compile(r"\\\{\{|\{\{([^{}]*)\}\}|\{\{")
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
NEXT_PAGE_MARKERS = ("has_more", "next_page", "next_cursor")


class UsageError(Exception):
    pass


class RenderError(UsageError):
    def __init__(self, path, problems):
        self.path = path
        self.problems = problems
        super().__init__("; ".join(
            f"unresolved placeholder {{{{{key}}}}} in template {path}:{line}" for line, key in problems
        ))


def read_text(path):
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError as error:
        raise UsageError(f"cannot read {path}: {error.strerror}") from error
    except UnicodeDecodeError as error:
        raise UsageError(f"cannot read {path}: not UTF-8") from error


def write_bytes(path, data):
    try:
        with open(path, "wb") as handle:
            handle.write(data)
    except OSError as error:
        raise UsageError(f"cannot write {path}: {error.strerror}") from error


def git_toplevel(path):
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            env=dict(os.environ, LC_ALL="C", LANGUAGE="C"),
        )
    except OSError as error:
        raise UsageError(f"cannot run git to check {path}: {error.strerror}") from error
    if result.returncode == 0:
        return os.path.realpath(result.stdout.strip())
    if "not a git repository" in result.stderr:
        return None
    detail = (result.stderr.strip().splitlines() or [f"exit code {result.returncode}"])[-1]
    raise UsageError(f"cannot tell whether {path} is in a git work tree: {detail}")


def resolve_private(value):
    path = value or os.environ.get("CLAUDIO_PRIVATE_DIR")
    if not path:
        raise UsageError("private directory not set: pass --private DIR or set CLAUDIO_PRIVATE_DIR")
    if not os.path.isdir(path):
        problem = "is not a directory" if os.path.exists(path) else "does not exist"
        raise UsageError(f"private directory {path} {problem}")
    real = os.path.realpath(path)
    own = git_toplevel(real)
    if own is not None and own != real:
        raise UsageError(f"private directory {path} is inside the git work tree {own}")
    if own == real and (os.path.isdir(os.path.join(real, PLUGIN_IN_REPO)) or real == git_toplevel(SCRIPT_DIR)):
        raise UsageError(f"private directory {path} is a claudio checkout, not a private repository")
    outer = git_toplevel(os.path.dirname(real))
    if outer is not None:
        raise UsageError(f"private directory {path} is nested in the git work tree {outer}")
    return real


def read_listing(path):
    text = read_text(path)
    first, _, rest = text.partition("\n")
    status = HTTP_LINE.fullmatch(first.strip())
    if status:
        if status.group(1) != "200":
            raise UsageError(f"routines API answered HTTP {status.group(1)}: nothing exported")
        text = rest
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise UsageError(f"listing {path} is not JSON: {error.msg}") from error
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        raise UsageError(f"listing {path} has no data list")
    marker = next((key for key in NEXT_PAGE_MARKERS if document.get(key)), None)
    if marker is not None:
        raise UsageError(f"listing {path} has more pages ({marker} is set): export needs every routine, nothing exported")
    return document["data"]


def dotted(path):
    return "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in path).lstrip(".")


def field(entry, path, kind, label):
    value = entry
    for key in path:
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError):
            value = None
            break
    if not isinstance(value, kind):
        raise UsageError(f"malformed routine {label}: {dotted(path)} is missing or has the wrong type")
    return value


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def normalize(entry, index):
    raw_id = entry.get("id") if isinstance(entry, dict) else None
    label = raw_id if isinstance(raw_id, str) and raw_id else f"at index {index}"
    ccr = ("job_config", "ccr")
    routine_id = field(entry, ("id",), str, label)
    name = field(entry, ("name",), str, label)
    session_context = field(entry, ccr + ("session_context",), dict, label)
    connections = entry.get("mcp_connections", [])
    if not isinstance(connections, list) or not all(
        isinstance(connection, dict) and isinstance(connection.get("name"), str) for connection in connections
    ):
        raise UsageError(f"malformed routine {label}: mcp_connections must list objects with a name")
    snapshot = {
        "id": routine_id,
        "name": name,
        "cron_expression": field(entry, ("cron_expression",), str, label),
        "enabled": field(entry, ("enabled",), bool, label),
        "environment_id": field(entry, ccr + ("environment_id",), str, label),
        "model": session_context.get("model"),
        "allowed_tools": session_context.get("allowed_tools"),
        "session_context": session_context,
        "connectors": sorted(connection["name"] for connection in connections),
    }
    prompt = field(entry, ccr + ("events", 0, "data", "message", "content"), str, label)
    slug = slugify(name)
    if not slug:
        raise UsageError(f"malformed routine {label}: its name gives an empty slug")
    try:
        files = [
            (f"{slug}.json", (json.dumps(snapshot, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")),
            (f"{slug}.prompt.md", prompt.encode("utf-8")),
        ]
    except UnicodeEncodeError as error:
        raise UsageError(f"malformed routine {label}: text is not valid UTF-8") from error
    return slug, routine_id, files


def listed_slugs(directory):
    names = set(os.listdir(directory)) if os.path.isdir(directory) else set()
    slugs = {name[: -len(".json")] for name in names if name.endswith(".json") and name != ".json"}
    return {slug for slug in slugs if f"{slug}.prompt.md" in names}


def clean_temps(directory):
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if name.startswith(TEMP_PREFIX) and name.endswith(".tmp"):
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(directory, name))


def stage(directory, data):
    handle, temp = tempfile.mkstemp(dir=directory, prefix=TEMP_PREFIX, suffix=".tmp")
    with os.fdopen(handle, "wb") as stream:
        stream.write(data)
    return temp


def set_aside(directory, path):
    handle, backup = tempfile.mkstemp(dir=directory, prefix=TEMP_PREFIX, suffix=".tmp")
    os.close(handle)
    os.replace(path, backup)
    return backup


def restore(directory, moved, placed):
    originals = {target for _, target in moved}
    for target in placed:
        if target not in originals:
            with contextlib.suppress(OSError):
                os.unlink(target)
    for backup, target in reversed(moved):
        with contextlib.suppress(OSError):
            os.replace(backup, target)
    clean_temps(directory)


def replace_snapshots(directory, files, stale):
    moved, placed = [], []
    try:
        staged = [(stage(directory, data), os.path.join(directory, name)) for name, data in files]
        for temp, target in staged:
            if os.path.exists(target):
                moved.append((set_aside(directory, target), target))
            os.replace(temp, target)
            placed.append(target)
        for path in stale:
            moved.append((set_aside(directory, path), path))
    except OSError as error:
        restore(directory, moved, placed)
        raise UsageError(f"cannot update snapshots in {directory}: {error.strerror or error}") from error
    clean_temps(directory)


def cmd_check_private(args):
    resolve_private(args.private)
    print("ok")
    return 0


def cmd_export(args):
    private = resolve_private(args.private)
    snapshots = {}
    for index, entry in enumerate(read_listing(args.input)):
        slug, routine_id, files = normalize(entry, index)
        if slug in snapshots:
            raise UsageError(f"routines {snapshots[slug][0]} and {routine_id} share the slug {slug}: nothing exported")
        snapshots[slug] = (routine_id, files)
    directory = os.path.join(private, "routines")
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        raise UsageError(f"cannot create {directory}: {error.strerror}") from error
    clean_temps(directory)
    removed = sorted(listed_slugs(directory) - set(snapshots))
    stale = [os.path.join(directory, f"{slug}{suffix}") for slug in removed for suffix in (".json", ".prompt.md")]
    replace_snapshots(directory, [file for _, files in snapshots.values() for file in files], stale)
    for slug in sorted(snapshots):
        print(f"exported {slug}")
    for slug in removed:
        print(f"removed {slug}")
    return 0


def require(mapping, key, kind, where):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(value, kind):
        raise UsageError(f"config.json: {where}{key} is missing or has the wrong type")
    return value


def plain_path(pattern, value):
    return pattern.fullmatch(value) is not None and not any(part in (".", "..") for part in value.strip("/").split("/"))


def check_runtime_dir(value, key):
    if not plain_path(RUNTIME_DIR, value) or not value.strip("/").split("/")[-1].startswith(RUNTIME_DIR_PREFIX):
        raise UsageError(
            f"config.json: {key} must match ^(/[A-Za-z0-9._-]+){{2,}}/?$ without . or .. parts, "
            f"and its last part must start with {RUNTIME_DIR_PREFIX}"
        )


def check_state_dir(value, key):
    if not plain_path(STATE_DIR, value):
        raise UsageError(f"config.json: {key} must match ^(/[A-Za-z0-9._-]+)+/?$ without . or .. parts")


def removed_key(key, replacement):
    return UsageError(f"config.json: {key} is removed: set places.cloud.{replacement} and places.local.{replacement}")


def check_places(config):
    if "dir" in config["runtime"]:
        raise removed_key("runtime.dir", "runtime_dir")
    if "state.dir" in flatten(config.get("values", {})):
        raise removed_key("values.state.dir", "state_dir")
    places = require(config, "places", dict, "")
    for place in PLACES:
        settings = require(places, place, dict, "places.")
        check_runtime_dir(require(settings, "runtime_dir", str, f"places.{place}."), f"places.{place}.runtime_dir")
        check_state_dir(require(settings, "state_dir", str, f"places.{place}."), f"places.{place}.state_dir")


def load_config(private):
    path = os.path.join(private, "config.json")
    try:
        config = json.loads(read_text(path))
    except json.JSONDecodeError as error:
        raise UsageError(f"config {path} is not JSON: {error.msg}") from error
    if not TIMEZONE_PATTERN.fullmatch(require(config, "timezone", str, "")):
        raise UsageError(f"config.json: timezone must match ^{TIMEZONE_PATTERN.pattern}$")
    runtime = require(config, "runtime", dict, "")
    for key in ("repo", "tag", "sha"):
        require(runtime, key, str, "runtime.")
    if not REPO_URL.fullmatch(runtime["repo"]):
        raise UsageError("config.json: runtime.repo must be https://<host>/<path> without @, ?, # or whitespace")
    if not TAG_PATTERN.fullmatch(runtime["tag"]):
        raise UsageError("config.json: runtime.tag must match ^[A-Za-z0-9._-]+$")
    if not SHA_PATTERN.fullmatch(runtime["sha"]):
        raise UsageError("config.json: runtime.sha must be 40 lowercase hex characters")
    if not isinstance(config.get("values", {}), dict):
        raise UsageError("config.json: values must be an object")
    check_places(config)
    for slug, routine in require(config, "routines", dict, "").items():
        for key in ("id", "template", "cron"):
            require(routine, key, str, f"routines.{slug}.")
        if not TEMPLATE_NAME.fullmatch(routine["template"]):
            raise UsageError(f"config.json: routines.{slug}.template must match ^[a-z0-9-]+$")
        if not isinstance(routine.get("values", {}), dict):
            raise UsageError(f"config.json: routines.{slug}.values must be an object")
        if "state.dir" in flatten(routine.get("values", {})):
            raise removed_key(f"routines.{slug}.values.state.dir", "state_dir")
    return config


def merge(base, extra):
    merged = dict(base)
    for key, value in extra.items():
        both_objects = isinstance(value, dict) and isinstance(merged.get(key), dict)
        merged[key] = merge(merged[key], value) if both_objects else value
    return merged


def flatten(tree, prefix=""):
    flat = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            flat.update(flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def build_context(config, routine, place, post):
    settings = config["places"][place]
    context = flatten(merge(config.get("values", {}), routine.get("values", {})))
    context.update(flatten({"runtime": config["runtime"]}))
    context["timezone"] = config["timezone"]
    context.update({
        "runtime.dir": settings["runtime_dir"],
        "state.dir": settings["state_dir"],
        "place": place,
        "run.post": "yes" if place == "cloud" or post else "no",
    })
    return context, set(flatten(routine.get("values", {})))


def render_text(text, context, source):
    used, problems = set(), []

    def replace(match):
        if match.group(0) == "\\{{":
            return "{{"
        key = (match.group(1) or "").strip()
        if match.group(1) is not None and KEY_PATTERN.fullmatch(key) and key in context:
            used.add(key)
            value = context[key]
            return value if isinstance(value, str) else json.dumps(value)
        problems.append((text.count("\n", 0, match.start()) + 1, key))
        return match.group(0)

    rendered = PLACEHOLDER.sub(replace, text)
    if problems:
        raise RenderError(source, problems)
    return rendered, used


def template_path(private, name):
    for directory in (os.path.join(private, "templates"), TEMPLATES_DIR):
        path = os.path.join(directory, f"{name}.md")
        if os.path.isfile(path):
            return path
    raise UsageError(f"template {name} found neither in {private}/templates nor in the public skeletons")


def configured(config, slug):
    routine = config["routines"].get(slug)
    if routine is None:
        raise UsageError(f"routine {slug} is not in config.json")
    return routine


def render_routine(private, config, slug, place="cloud", post=False):
    routine = configured(config, slug)
    path = template_path(private, routine["template"])
    context, own_keys = build_context(config, routine, place, post)
    rendered, used = render_text(read_text(path), context, path)
    for key in sorted(own_keys - used):
        print(
            f"routines.py: warning: routines.{slug}.values.{key} is not used by template {routine['template']}",
            file=sys.stderr,
        )
    return rendered, used


def render_setup_script(runtime, runtime_dir):
    context = {f"runtime.{key}": shlex.quote(runtime[key]) for key in ("repo", "tag", "sha")}
    context["runtime.dir"] = shlex.quote(runtime_dir)
    path = os.path.join(TEMPLATES_DIR, SETUP_TEMPLATE)
    return render_text(read_text(path), context, path)[0]


def cmd_render(args):
    private = resolve_private(args.private)
    rendered, _ = render_routine(private, load_config(private), args.slug, args.place, args.post)
    if args.out:
        write_bytes(args.out, rendered.encode("utf-8"))
    else:
        sys.stdout.write(rendered)
    return 0


def cmd_setup_script(args):
    config = load_config(resolve_private(args.private))
    sys.stdout.write(render_setup_script(config["runtime"], config["places"][args.place]["runtime_dir"]))
    return 0


def load_snapshot(private, config, slug):
    base = os.path.join(private, "routines", slug)
    if not (os.path.isfile(base + ".json") and os.path.isfile(base + ".prompt.md")):
        return None
    try:
        snapshot = json.loads(read_text(base + ".json"))
    except json.JSONDecodeError as error:
        raise UsageError(f"snapshot {base}.json is not JSON: {error.msg}") from error
    for key, kind in (("id", str), ("cron_expression", str), ("environment_id", str), ("session_context", dict)):
        value = snapshot.get(key) if isinstance(snapshot, dict) else None
        if not isinstance(value, kind):
            raise UsageError(f"snapshot {base}.json: {key} is missing or has the wrong type")
    if snapshot["id"] != configured(config, slug)["id"]:
        raise UsageError(f"routine {slug}: routines.{slug}.id in config.json differs from the exported id")
    return snapshot, read_text(base + ".prompt.md")


def unified(before, after, label):
    lines = difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"live/{label}", f"rendered/{label}")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


def listing_text(values):
    return ", ".join(str(value) for value in values or []) or "none"


def diff_routine(private, config, slug):
    found = load_snapshot(private, config, slug)
    if found is None:
        print(f"{slug}: not exported")
        return True
    snapshot, live = found
    rendered, _ = render_routine(private, config, slug)
    cron = configured(config, slug)["cron"]
    changes = [
        ("prompt", unified(live, rendered, f"{slug}.prompt.md")),
        ("cron", unified(snapshot["cron_expression"] + "\n", cron + "\n", f"{slug}.cron")),
    ]
    drifted = [(name, text) for name, text in changes if text]
    for name, text in drifted:
        print(f"{slug}: drift in {name}")
        sys.stdout.write(text)
    if not drifted:
        print(f"{slug}: in sync")
    print(f"{slug}: info connectors: {listing_text(snapshot.get('connectors'))}")
    print(f"{slug}: info model: {snapshot.get('model') or 'none'}")
    print(f"{slug}: info tools: {listing_text(snapshot.get('allowed_tools'))}")
    return bool(drifted)


def cmd_diff(args):
    private = resolve_private(args.private)
    config = load_config(private)
    exported = listed_slugs(os.path.join(private, "routines"))
    if args.slug and args.slug not in config["routines"] and args.slug not in exported:
        raise UsageError(f"routine {args.slug} is neither in config.json nor exported")
    drift = False
    for slug in [args.slug] if args.slug else sorted(set(config["routines"]) | exported):
        if slug in config["routines"]:
            drift = diff_routine(private, config, slug) or drift
        else:
            print(f"{slug}: untracked")
    return 1 if drift else 0


def event_uuid(value):
    if value is None:
        return str(uuid.uuid4())
    try:
        uuid.UUID(value)
    except ValueError as error:
        raise UsageError(f"--uuid {value} is not a UUID") from error
    return value


def cmd_body(args):
    private = resolve_private(args.private)
    config = load_config(private)
    event = event_uuid(args.uuid)
    rendered, _ = render_routine(private, config, args.slug)
    found = load_snapshot(private, config, args.slug)
    if found is None:
        raise UsageError(f"routine {args.slug} is not exported: run export first")
    snapshot, routine = found[0], configured(config, args.slug)
    body = {
        "trigger_id": routine["id"],
        "body": {
            "cron_expression": routine["cron"],
            "job_config": {"ccr": {
                "environment_id": snapshot["environment_id"],
                "session_context": snapshot["session_context"],
                "events": [{"data": {
                    "uuid": event,
                    "session_id": "",
                    "type": "user",
                    "parent_tool_use_id": None,
                    "message": {"role": "user", "content": rendered},
                }}],
            }},
        },
    }
    sys.stdout.write(json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 0


@contextlib.contextmanager
def runtime_imports(directory):
    try:
        local = {name.removesuffix(".py") for name in os.listdir(directory)}
    except OSError as error:
        raise UsageError(f"cannot list the runtime scripts in {directory}: {error.strerror}") from error
    saved_modules, saved_path, saved_bytecode = dict(sys.modules), list(sys.path), sys.dont_write_bytecode
    for name in [name for name in sys.modules if name.partition(".")[0] in local]:
        del sys.modules[name]
    sys.path.insert(0, directory)
    sys.dont_write_bytecode = True
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.dont_write_bytecode = saved_bytecode
        sys.path[:] = saved_path
        for name in [name for name in set(sys.modules) - set(saved_modules) if name.partition(".")[0] in local]:
            del sys.modules[name]
        sys.modules.update(saved_modules)


def load_contract(path, origin):
    spec = importlib.util.spec_from_file_location(f"claudio_routines_{Path(path).stem}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        parser = module.build_parser()
    except (Exception, SystemExit) as error:
        raise UsageError(f"cannot load build_parser() from {origin}: {type(error).__name__}: {error}") from error
    return lint.parser_contract(parser)


def load_contracts(directory, origin):
    paths = {name: os.path.join(directory, name) for name in lint.RUNTIME_SCRIPTS}
    return {name: load_contract(path, f"{origin}/{name}") for name, path in paths.items() if os.path.isfile(path)}


def provider_names():
    try:
        return importlib.import_module("providers").names()
    except (Exception, SystemExit) as error:
        raise UsageError(f"cannot list the provider adapters of {RUNTIME_PATH}: {type(error).__name__}: {error}") from error


def run_git(root, *args):
    try:
        return subprocess.run(["git", "-C", root, *args], capture_output=True)
    except OSError as error:
        raise UsageError(f"cannot run git in {root}: {error.strerror}") from error


def extract_runtime(claudio, tag, sha, directory):
    root = claudio or git_toplevel(SCRIPT_DIR)
    if root is None:
        raise UsageError("cannot find the claudio checkout of this script: pass --claudio DIR")
    tagged = run_git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if tagged.returncode != 0 or tagged.stdout.decode(errors="replace").strip() != sha:
        raise UsageError(f"runtime.tag {tag} does not resolve to runtime.sha {sha} in {root}: fetch the tags or fix the config")
    if run_git(root, "cat-file", "-e", f"{sha}:{RUNTIME_IN_REPO}").returncode != 0:
        return
    result = run_git(root, "archive", "--format=tar", f"{sha}:{RUNTIME_IN_REPO}")
    if result.returncode != 0:
        detail = (result.stderr.decode(errors="replace").strip().splitlines() or [f"exit code {result.returncode}"])[-1]
        raise UsageError(f"cannot extract {RUNTIME_IN_REPO} at runtime commit {sha} from {root}: {detail}")
    if not hasattr(tarfile, "data_filter"):
        raise UsageError("this Python cannot extract the pinned runtime safely: use Python 3.10.12 or later")
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            archive.extractall(directory, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise UsageError(f"cannot extract {RUNTIME_IN_REPO} at runtime commit {sha} into {directory}: {error}") from error


def templates_in(directory):
    names = sorted(os.listdir(directory)) if os.path.isdir(directory) else []
    return [os.path.join(directory, name) for name in names if name.endswith(".md")]


def findings_in(path, line_rules, contracts):
    return lint.template_findings(path, read_text(path), line_rules, contracts)


def public_findings():
    with runtime_imports(RUNTIME_PATH):
        contracts = load_contracts(RUNTIME_PATH, RUNTIME_PATH)
        provider_rule = lint.provider_rule(provider_names())
    findings = set()
    for path in templates_in(TEMPLATES_DIR):
        findings |= findings_in(path, lint.combined(lint.public_rules, provider_rule), contracts)
    setup = os.path.join(TEMPLATES_DIR, SETUP_TEMPLATE)
    if os.path.isfile(setup):
        findings |= findings_in(setup, lint.combined(lint.setup_rules, provider_rule), contracts)
    for path in (README_PATH, SKILL_PATH):
        if os.path.isfile(path):
            findings |= lint.line_findings(path, read_text(path), provider_rule)
    return findings


def private_findings(args):
    private = resolve_private(args.private)
    config = load_config(private)
    sha = config["runtime"]["sha"]
    with tempfile.TemporaryDirectory(prefix="claudio-runtime-") as directory:
        extract_runtime(args.claudio, config["runtime"]["tag"], sha, directory)
        with runtime_imports(directory):
            contracts = load_contracts(directory, f"{sha}:{RUNTIME_IN_REPO}")
    findings = set()
    for path in templates_in(os.path.join(private, "templates")):
        findings |= findings_in(path, lint.no_rules, contracts)
    used = set()
    for slug in sorted(config["routines"]):
        try:
            used |= render_routine(private, config, slug)[1]
        except RenderError as error:
            findings.update((error.path, line, "placeholder") for line, _ in error.problems)
    for key in sorted(set(flatten(config.get("values", {}))) - used):
        print(f"routines.py: warning: shared value {key} is not used by any configured routine", file=sys.stderr)
    return findings


def cmd_lint(args):
    findings = public_findings() if args.public else private_findings(args)
    for path, line, rule in sorted(findings):
        print(f"{path}:{line}:{rule}")
    return 1 if findings else 0


def build_parser():
    parser = argparse.ArgumentParser(prog="routines.py", description="Render, diff and export claude.ai routines")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, help_text):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--private", help="private repository, default $CLAUDIO_PRIVATE_DIR")
        return sub

    command("check-private", "check the private repository path")
    command("export", "write snapshots from a RemoteTrigger listing").add_argument("--input", required=True)
    render = command("render", "render a routine prompt")
    render.add_argument("slug")
    render.add_argument("--place", choices=PLACES, default="cloud", help="place to render for, default cloud")
    render.add_argument("--post", action="store_true", help="post the digest from the local place")
    render.add_argument("--out")
    command("diff", "compare rendered routines with their snapshots").add_argument("slug", nargs="?")
    body = command("body", "print the RemoteTrigger update body")
    body.add_argument("slug")
    body.add_argument("--uuid")
    command("setup-script", "render the environment setup script").add_argument(
        "--place", choices=PLACES, default="cloud", help="place to install the runtime in, default cloud"
    )
    lint_command = commands.add_parser("lint", help="lint public skeletons or private templates")
    target = lint_command.add_mutually_exclusive_group(required=True)
    target.add_argument("--public", action="store_true")
    target.add_argument("--private")
    lint_command.add_argument("--claudio", help="claudio checkout holding the runtime commit, default this script's checkout")
    return parser


COMMANDS = {
    "check-private": cmd_check_private,
    "export": cmd_export,
    "render": cmd_render,
    "diff": cmd_diff,
    "body": cmd_body,
    "setup-script": cmd_setup_script,
    "lint": cmd_lint,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except UsageError as error:
        print(f"routines.py: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
