#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys

PROG = "check_protection"


class Unreadable(Exception):
    pass


def gh(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True)
    except OSError as exc:
        raise Unreadable(f"cannot start gh: {exc.strerror}") from exc


def gh_reason(proc: subprocess.CompletedProcess) -> str:
    lines = proc.stderr.strip().splitlines()
    return lines[0] if lines else f"gh exited with status {proc.returncode}"


def resolve_repo() -> str:
    if os.environ.get("CLAUDIO_REPO"):
        return os.environ["CLAUDIO_REPO"]
    proc = gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    if proc.returncode != 0:
        raise Unreadable(f"cannot resolve the repository with gh repo view: {gh_reason(proc)}; set CLAUDIO_REPO=owner/name")
    if not proc.stdout.strip():
        raise Unreadable("gh repo view printed no repository; set CLAUDIO_REPO=owner/name")
    return proc.stdout.strip()


def section(protection: dict, key: str) -> dict | None:
    value = protection.get(key)
    if value is not None and not isinstance(value, dict):
        raise Unreadable(f"{key} is not an object")
    return value


def missing_settings(protection: dict) -> list[str]:
    reviews = section(protection, "required_pull_request_reviews")
    status_checks = section(protection, "required_status_checks") or {}
    admins = section(protection, "enforce_admins") or {}
    try:
        contexts = set(status_checks.get("contexts") or [])
        contexts.update(check.get("context") for check in status_checks.get("checks") or [])
    except (AttributeError, TypeError) as exc:
        raise Unreadable("required_status_checks has unexpected contexts or checks") from exc
    missing = []
    if reviews is None:
        missing.append("main does not require a pull request (required_pull_request_reviews)")
    if "leak-check" not in contexts:
        missing.append("main does not require the leak-check status (required_status_checks)")
    if admins.get("enabled") is not True:
        missing.append("main does not enforce its rules for admins (enforce_admins)")
    return missing


def main() -> int:
    if shutil.which("gh") is None:
        print(f"{PROG}: gh is not installed or not on PATH", file=sys.stderr)
        return 2
    try:
        repo = resolve_repo()
        proc = gh("api", f"repos/{repo}/branches/main/protection")
        if proc.returncode != 0 and "Branch not protected" in proc.stdout + proc.stderr:
            print(f"{PROG}: main is not protected in {repo}")
            return 1
        if proc.returncode != 0:
            raise Unreadable(f"cannot read the protection of main in {repo}: {gh_reason(proc)}")
        try:
            protection = json.loads(proc.stdout)
        except ValueError as exc:
            raise Unreadable("gh api returned a body that is not JSON") from exc
        if not isinstance(protection, dict):
            raise Unreadable("gh api returned JSON that is not an object")
        missing = missing_settings(protection)
    except Unreadable as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    for setting in missing:
        print(f"{PROG}: {setting}")
    if missing:
        return 1
    print(f"{PROG}: main requires a pull request, the leak-check status and enforcement for admins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
