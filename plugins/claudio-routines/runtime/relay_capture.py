import json
import os
import re
import stat
import sys
import time
from collections import namedtuple
from time import time_ns

ENV_DIR = "CLAUDIO_RELAY_DIR"
DEFAULT_DIR = "/tmp/claudio-relay"
ERRORS_LOG = "errors.log"
SAVED_FOLDER = "tool-results"
TOOL_PREFIX = "mcp__"
TEXT_CAP = 10 * 1024 * 1024
MAX_AGE_NS = 24 * 3600 * 10**9
TOOL_USE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
CAPTURE_NAME = re.compile(r"([0-9]+)-" + TOOL_USE_ID.pattern + r"\.json")
SAVED_POINTER = re.compile(r"Error: result \([^)\n]*\) exceeds maximum allowed tokens\. Output has been saved to (/[^\n]+)\.(?:\n|\Z)")
CAPTURE_KEYS = {"tool_name", "arguments", "text", "captured_at_ns"}

Difference = namedtuple("Difference", "path kind detail")


class Skipped(Exception):
    pass


class Refused(Exception):
    pass


def capture_dir(environ=os.environ):
    value = environ.get(ENV_DIR)
    return value if value is not None and value.strip() else DEFAULT_DIR


def checked_directory(directory, create):
    if create:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode):
        raise Refused(f"{directory} is not a directory")
    if info.st_uid != os.getuid():
        raise Refused(f"{directory} belongs to another user")


def canonical(arguments):
    return json.dumps(arguments, sort_keys=True)


def is_text_block(block):
    return isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)


def read_saved(path, transcript_path):
    if not isinstance(transcript_path, str) or not os.path.isabs(transcript_path):
        raise Skipped("transcript_path is not an absolute path")
    root = os.path.realpath(os.path.dirname(transcript_path))
    real = os.path.realpath(path)
    if not real.startswith(root + os.sep):
        raise Skipped("saved result is outside the session folder")
    if os.path.basename(os.path.dirname(real)) != SAVED_FOLDER:
        raise Skipped(f"saved result is not in a {SAVED_FOLDER} folder")
    descriptor = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise Skipped("saved result is not a regular file")
        data = handle.read(TEXT_CAP + 1)
    if len(data) > TEXT_CAP:
        raise Skipped("saved result is over 10 MB")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise Skipped("saved result is not UTF-8 text") from None


def result_text(response, transcript_path):
    if isinstance(response, list) and response and all(is_text_block(block) for block in response):
        return "".join(block["text"] for block in response)
    pointer = SAVED_POINTER.match(response) if isinstance(response, str) else None
    if pointer is None:
        raise Skipped("tool_response is neither a list of text blocks nor a saved-result pointer")
    return read_saved(pointer.group(1), transcript_path)


def checked_text(text):
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise Skipped("result text is not UTF-8 encodable") from None
    if size > TEXT_CAP:
        raise Skipped("result text is over 10 MB")
    return text


def discard(directory, name):
    try:
        os.unlink(os.path.join(directory, name))
    except OSError:
        pass


def sweep(directory, now_ns):
    kept = []
    for name in os.listdir(directory):
        found = CAPTURE_NAME.fullmatch(name)
        if found is None:
            continue
        taken_ns = int(found.group(1))
        if now_ns - taken_ns > MAX_AGE_NS:
            discard(directory, name)
        else:
            kept.append((taken_ns, name))
    return sorted(kept)


def write_capture(directory, name, document):
    final = os.path.join(directory, name)
    temp = os.path.join(directory, f".{name}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(document, sort_keys=True).encode("ascii"))
        os.rename(temp, final)
    except OSError:
        os.unlink(temp)
        raise


def capture(raw, directory, now_ns):
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise Skipped("stdin is not UTF-8 JSON") from None
    if not isinstance(payload, dict):
        raise Skipped("stdin is not a JSON object")
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.startswith(TOOL_PREFIX):
        return
    arguments, tool_use_id = payload.get("tool_input"), payload.get("tool_use_id")
    if not isinstance(arguments, dict):
        raise Skipped("tool_input is not an object")
    if not isinstance(tool_use_id, str) or TOOL_USE_ID.fullmatch(tool_use_id) is None:
        raise Skipped("tool_use_id is missing or not a plain identifier")
    text = checked_text(result_text(payload.get("tool_response"), payload.get("transcript_path")))
    checked_directory(directory, create=True)
    document = {"tool_name": tool_name, "arguments": arguments, "text": text, "captured_at_ns": now_ns}
    write_capture(directory, f"{now_ns}-{tool_use_id}.json", document)
    sweep(directory, now_ns)


def describe(error):
    if isinstance(error, Skipped):
        return str(error)
    if isinstance(error, OSError):
        return error.strerror or ""
    return ""


def log_error(directory, error, now_ns):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ns // 10**9))
    line = " ".join(part for part in (stamp, type(error).__name__, describe(error)) if part) + "\n"
    try:
        checked_directory(directory, create=True)
        descriptor = os.open(os.path.join(directory, ERRORS_LOG), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(line)
    except (OSError, Refused):
        pass


def hook(stream, directory):
    now_ns = time_ns()
    try:
        capture(stream.read(), directory, now_ns)
    except Refused:
        pass
    except Exception as error:
        log_error(directory, error, now_ns)
    return 0


def read_capture(directory, name, taken_ns):
    try:
        descriptor = os.open(os.path.join(directory, name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return None
            document = json.loads(handle.read().decode("utf-8"))
        if not isinstance(document, dict) or set(document) != CAPTURE_KEYS or document["captured_at_ns"] != taken_ns:
            return None
        if not isinstance(document["tool_name"], str) or not isinstance(document["arguments"], dict):
            return None
        document["text"].encode("utf-8")
    except (OSError, ValueError, RecursionError, AttributeError):
        return None
    return document


def captures_of(directory, tool_name, not_before_ns, now_ns):
    now_ns = time_ns() if now_ns is None else now_ns
    try:
        checked_directory(directory, create=False)
        kept = sweep(directory, now_ns)
    except (OSError, Refused):
        return []
    found = []
    for taken_ns, name in kept:
        document = read_capture(directory, name, taken_ns) if taken_ns >= not_before_ns else None
        if document is not None and document["tool_name"] == tool_name:
            found.append((taken_ns, name, document))
    return found


def take(directory, tool_name, arguments, not_before_ns, now_ns=None):
    wanted = canonical(arguments)
    matched = [
        (taken_ns, name, document["text"])
        for taken_ns, name, document in captures_of(directory, tool_name, not_before_ns, now_ns)
        if canonical(document["arguments"]) == wanted
    ]
    for _, name, _ in matched:
        discard(directory, name)
    return max(matched)[2] if matched else None


def first_difference(planned, called):
    shared = min(len(planned), len(called))
    return next((index for index in range(shared) if planned[index] != called[index]), shared)


def changed_detail(planned, called):
    if type(planned) is not type(called):
        return f"(planned {type(planned).__name__}, called {type(called).__name__})"
    if isinstance(planned, str):
        return f"at char {first_difference(planned, called)} (planned {len(planned)}, called {len(called)})"
    return ""


def keyed_differences(planned, called, path):
    found = []
    for key in sorted(planned.keys() | called.keys()):
        where = f"{path}.{key}" if path else key
        if key not in called:
            found.append(Difference(where, "missing", ""))
        elif key not in planned:
            found.append(Difference(where, "extra", ""))
        else:
            found.extend(differences(planned[key], called[key], where))
    return found


def indexed_differences(planned, called, path):
    found = []
    for index in range(max(len(planned), len(called))):
        where = f"{path}[{index}]"
        if index >= len(called):
            found.append(Difference(where, "missing", ""))
        elif index >= len(planned):
            found.append(Difference(where, "extra", ""))
        else:
            found.extend(differences(planned[index], called[index], where))
    return found


def differences(planned, called, path=""):
    if isinstance(planned, dict) and isinstance(called, dict):
        return keyed_differences(planned, called, path)
    if isinstance(planned, list) and isinstance(called, list):
        return indexed_differences(planned, called, path)
    if canonical(planned) == canonical(called):
        return []
    return [Difference(path, "changed", changed_detail(planned, called))]


def difference_text(difference):
    return " ".join(part for part in difference if part)


def mismatch(directory, tool_name, arguments, not_before_ns, now_ns=None):
    closest = None
    for _, _, document in reversed(captures_of(directory, tool_name, not_before_ns, now_ns)):
        found = differences(arguments, document["arguments"])
        if found and (closest is None or len(found) < len(closest)):
            closest = found
    return closest


if __name__ == "__main__":
    sys.exit(hook(sys.stdin.buffer, capture_dir()))
