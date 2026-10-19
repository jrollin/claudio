import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / ".githooks"
HOOKS = ("pre-commit", "pre-merge-commit", "commit-msg")
INSTALL = ROOT / "scripts" / "install-hooks.sh"
CHECK = ROOT / "scripts" / "check_protection.py"
SCANNER = ROOT / "scripts" / "leak_check.py"

AWS_ID = "1234" * 3
TOKEN = "ghp_" + "A1b2" * 9
DENY_WORD = "acme"
REPO = "example-owner/example-repo"
PROTECTION_ENDPOINT = f"api repos/{REPO}/branches/main/protection"
COULD_NOT_RUN = "leak check could not run"


def isolated_env(base, **overrides):
    home = base / "home"
    home.mkdir(exist_ok=True)
    dropped = ("LEAK_DENY_WORDS", "CLAUDIO_DENY_WORDS_FILE", "CLAUDIO_REQUIRE_DENY_WORDS", "CLAUDIO_REPO")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in dropped}
    env.update(HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    env.update(overrides)
    return env


def temp_dir(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


def run(cmd, cwd, env):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True)


def write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


class HookRepo:
    def __init__(self, test):
        self.base = temp_dir(test)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.env = isolated_env(self.base)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")
        (self.root / "scripts").mkdir()
        shutil.copy2(SCANNER, self.root / "scripts" / "leak_check.py")
        (self.root / "scripts" / "leak-allow.txt").write_text("", encoding="utf-8")
        (self.root / ".githooks").mkdir()
        for hook in HOOKS:
            shutil.copy2(HOOKS_DIR / hook, self.root / ".githooks" / hook)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "tooling")

    def git(self, *args):
        proc = run(["git", *args], self.root, self.env)
        if proc.returncode != 0:
            raise AssertionError(f"git {args[0]} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def install(self, cwd=None):
        return run([INSTALL], cwd or self.root, self.env)

    def hooks_path(self):
        return run(["git", "config", "--local", "--get", "core.hooksPath"], self.root, self.env).stdout.strip()

    def write(self, name, content):
        (self.root / name).write_text(content, encoding="utf-8")

    def stage(self, name, content):
        self.write(name, content)
        self.git("add", name)

    def commit_file(self, name, content, *flags, message=None):
        self.stage(name, content)
        return run(["git", "commit", "-q", *flags, "-m", message or f"add {name}"], self.root, self.env)

    def commit_with_editor(self, typed, *flags):
        typed_file = self.base / "typed-message.txt"
        typed_file.write_text(typed + "\n", encoding="utf-8")
        editor = self.base / "editor.sh"
        write_executable(editor, f'#!/bin/sh\n{{ cat "{typed_file}"; cat "$1"; }} > "$1.edited" && mv "$1.edited" "$1"\n')
        return run(["git", "commit", "-q", *flags], self.root, {**self.env, "GIT_EDITOR": str(editor)})

    def commit_count(self):
        return int(self.git("rev-list", "--count", "HEAD"))

    def break_scanner(self):
        self.write("scripts/leak-allow.txt", "not an entry\n")

    def default_deny_words(self, text):
        path = Path(self.env["HOME"]) / ".config" / "claudio" / "deny-words.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_hook(self, name, *args, cwd=None, env=None):
        return run([self.root / ".githooks" / name, *args], cwd or self.root, env or self.env)

    def merge_branch_adding(self, name, content):
        self.git("switch", "-q", "-c", "feature")
        self.commit_file(name, content, "--no-verify")
        self.git("switch", "-q", "-")
        return run(["git", "merge", "-q", "--no-ff", "-m", "merge feature", "feature"], self.root, self.env)


class HooksDirectoryTest(unittest.TestCase):
    def test_every_hook_file_is_executable(self):
        not_executable = [p.name for p in HOOKS_DIR.iterdir() if p.is_file() and not os.access(p, os.X_OK)]

        self.assertEqual(not_executable, [])


class InstallHooksTest(unittest.TestCase):
    def test_install_exits_0(self):
        repo = HookRepo(self)

        proc = repo.install()

        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_install_sets_hooks_path_to_githooks(self):
        repo = HookRepo(self)

        repo.install()

        self.assertEqual(repo.hooks_path(), ".githooks")

    def test_install_from_a_subdirectory_configures_the_toplevel(self):
        repo = HookRepo(self)

        repo.install(cwd=repo.root / "scripts")

        self.assertEqual(repo.hooks_path(), ".githooks")

    def test_second_install_leaves_the_config_unchanged(self):
        repo = HookRepo(self)
        repo.install()
        config_before = (repo.root / ".git" / "config").read_bytes()

        repo.install()

        self.assertEqual((repo.root / ".git" / "config").read_bytes(), config_before)

    def test_second_install_says_nothing_changed(self):
        repo = HookRepo(self)
        repo.install()

        proc = repo.install()

        self.assertIn("nothing changed", proc.stdout)

    def test_install_replacing_another_hooks_path_warns_on_stderr(self):
        repo = HookRepo(self)
        repo.git("config", "core.hooksPath", "other-hooks")

        proc = repo.install()

        self.assertIn("warning: core.hooksPath was other-hooks", proc.stderr)

    def test_install_replacing_another_hooks_path_sets_githooks(self):
        repo = HookRepo(self)
        repo.git("config", "core.hooksPath", "other-hooks")

        repo.install()

        self.assertEqual(repo.hooks_path(), ".githooks")

    def test_install_outside_a_git_repository_fails_with_a_message(self):
        base = temp_dir(self)
        plain = base / "plain"
        plain.mkdir()

        proc = run([INSTALL], plain, isolated_env(base, GIT_CEILING_DIRECTORIES=str(base)))

        self.assertEqual(proc.returncode, 2)
        self.assertIn("not inside a git repository", proc.stderr)

    def test_install_with_a_missing_commit_msg_hook_fails_naming_it(self):
        repo = HookRepo(self)
        (repo.root / ".githooks" / "commit-msg").unlink()

        proc = repo.install()

        self.assertEqual(proc.returncode, 2)
        self.assertIn(".githooks/commit-msg is missing or not executable", proc.stderr)

    def test_install_with_a_missing_pre_merge_commit_hook_fails_naming_it(self):
        repo = HookRepo(self)
        (repo.root / ".githooks" / "pre-merge-commit").unlink()

        proc = repo.install()

        self.assertEqual(proc.returncode, 2)
        self.assertIn(".githooks/pre-merge-commit is missing or not executable", proc.stderr)

    def test_install_with_a_non_executable_hook_fails_naming_it(self):
        repo = HookRepo(self)
        (repo.root / ".githooks" / "pre-commit").chmod(0o644)

        proc = repo.install()

        self.assertEqual(proc.returncode, 2)
        self.assertIn(".githooks/pre-commit is missing or not executable", proc.stderr)

    def test_failed_install_leaves_hooks_path_unset(self):
        repo = HookRepo(self)
        (repo.root / ".githooks" / "pre-commit").chmod(0o644)

        repo.install()

        self.assertEqual(repo.hooks_path(), "")


class PreCommitHookTest(unittest.TestCase):
    def setUp(self):
        self.repo = HookRepo(self)
        self.repo.install()

    def test_leak_shaped_line_blocks_the_commit(self):
        proc = self.repo.commit_file("settings.txt", f"account = {AWS_ID}\n")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.repo.commit_count(), 1)

    def test_blocked_commit_prints_path_line_and_rule(self):
        proc = self.repo.commit_file("settings.txt", f"account = {AWS_ID}\n")

        self.assertIn("settings.txt:1:aws-account", proc.stdout + proc.stderr)

    def test_clean_commit_passes(self):
        proc = self.repo.commit_file("notes.txt", "nothing private here\n")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.repo.commit_count(), 2)

    def test_commit_without_deny_words_prints_the_skip_notice(self):
        proc = self.repo.commit_file("notes.txt", "nothing private here\n")

        self.assertIn("deny-words skipped", proc.stderr)

    def test_unstaged_leak_does_not_block_a_clean_commit(self):
        self.repo.commit_file("notes.txt", "nothing private here\n")
        self.repo.write("notes.txt", f"account = {AWS_ID}\n")

        proc = self.repo.commit_file("other.txt", "still nothing private\n")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_committed_old_leak_does_not_block_a_clean_commit(self):
        self.repo.commit_file("settings.txt", f"account = {AWS_ID}\n", "--no-verify")

        proc = self.repo.commit_file("notes.txt", "nothing private here\n")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_deny_word_from_the_default_file_blocks_the_commit(self):
        self.repo.default_deny_words(DENY_WORD + "\n")

        proc = self.repo.commit_file("about.txt", "Built for Acme Corp\n")

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("about.txt:1:deny-word", proc.stdout + proc.stderr)

    def test_strict_mode_without_deny_words_blocks_the_commit(self):
        self.repo.env["CLAUDIO_REQUIRE_DENY_WORDS"] = "1"

        proc = self.repo.commit_file("notes.txt", "nothing private here\n")

        self.assertEqual(self.repo.commit_count(), 1)
        self.assertEqual(proc.stderr.count(COULD_NOT_RUN), 1)

    def test_strict_mode_with_deny_words_lets_a_clean_commit_pass(self):
        self.repo.env["CLAUDIO_REQUIRE_DENY_WORDS"] = "1"
        self.repo.default_deny_words(DENY_WORD + "\n")

        proc = self.repo.commit_file("notes.txt", "nothing private here\n")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_scanner_that_cannot_run_blocks_the_commit(self):
        self.repo.break_scanner()

        proc = self.repo.commit_file("notes.txt", "nothing private here\n")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.repo.commit_count(), 1)

    def test_scanner_that_cannot_run_prints_one_could_not_run_line(self):
        self.repo.break_scanner()

        proc = self.repo.commit_file("notes.txt", "nothing private here\n")

        self.assertEqual(proc.stderr.count(COULD_NOT_RUN), 1)

    def test_hook_exits_2_when_the_scanner_cannot_run(self):
        self.repo.break_scanner()

        proc = self.repo.run_hook("pre-commit")

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr.count(COULD_NOT_RUN), 1)

    def test_hook_exits_2_when_python3_is_missing(self):
        bin_dir = self.repo.base / "git-only"
        bin_dir.mkdir()
        write_executable(bin_dir / "git", f'#!/bin/sh\nexec "{shutil.which("git")}" "$@"\n')

        proc = self.repo.run_hook("pre-commit", env={**self.repo.env, "PATH": str(bin_dir)})

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr.count(COULD_NOT_RUN), 1)

    def test_hook_exits_2_outside_a_repository(self):
        plain = self.repo.base / "plain"
        plain.mkdir()

        proc = self.repo.run_hook(
            "pre-commit", cwd=plain, env={**self.repo.env, "GIT_CEILING_DIRECTORIES": str(self.repo.base)}
        )

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr.count(COULD_NOT_RUN), 1)


class CommitMsgHookTest(unittest.TestCase):
    def setUp(self):
        self.repo = HookRepo(self)
        self.repo.install()

    def test_token_in_the_commit_message_blocks_the_commit(self):
        proc = self.repo.commit_file("notes.txt", "nothing private here\n", message=f"add notes {TOKEN}")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.repo.commit_count(), 1)

    def test_deny_word_in_the_kept_message_blocks_the_commit(self):
        self.repo.default_deny_words(DENY_WORD + "\n")
        self.repo.stage("notes.txt", "nothing private here\n")

        proc = self.repo.commit_with_editor("fix for Acme Corp")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.repo.commit_count(), 1)

    def test_verbose_commit_removing_a_deny_word_passes(self):
        self.repo.default_deny_words(DENY_WORD + "\n")
        self.repo.commit_file("about.txt", "Built for Acme Corp\n", "--no-verify")
        self.repo.stage("about.txt", "Built for a client\n")

        proc = self.repo.commit_with_editor("drop the client name", "-v")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.repo.commit_count(), 3)

    def test_branch_name_with_a_deny_word_in_the_message_template_passes(self):
        self.repo.default_deny_words(DENY_WORD + "\n")
        self.repo.git("switch", "-q", "-c", f"{DENY_WORD}-fix")
        self.repo.stage("notes.txt", "nothing private here\n")

        proc = self.repo.commit_with_editor("add notes")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.repo.commit_count(), 2)

    def test_configured_comment_char_is_used_for_comments_and_scissors(self):
        self.repo.git("config", "core.commentChar", ";")
        self.repo.default_deny_words(DENY_WORD + "\n")
        self.repo.git("switch", "-q", "-c", f"{DENY_WORD}-fix")
        self.repo.commit_file("about.txt", "Built for Acme Corp\n", "--no-verify")
        self.repo.stage("about.txt", "Built for a client\n")

        proc = self.repo.commit_with_editor("drop the client name", "-v")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.repo.commit_count(), 3)

    def test_hook_exits_2_when_the_scanner_cannot_run(self):
        message = self.repo.base / "message.txt"
        message.write_text("add notes\n", encoding="utf-8")
        self.repo.break_scanner()

        proc = self.repo.run_hook("commit-msg", message)

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr.count(COULD_NOT_RUN), 1)


class PreMergeCommitHookTest(unittest.TestCase):
    def setUp(self):
        self.repo = HookRepo(self)
        self.repo.install()

    def test_merge_of_a_branch_adding_a_leak_shaped_line_is_blocked(self):
        proc = self.repo.merge_branch_adding("settings.txt", f"account = {AWS_ID}\n")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.repo.commit_count(), 1)

    def test_merge_of_a_clean_branch_passes(self):
        proc = self.repo.merge_branch_adding("notes.txt", "nothing private here\n")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.repo.commit_count(), 3)


GH_STUB = """#!/bin/sh
dir=$(dirname "$0")
printf '%s\\n' "$*" >> "$dir/calls.log"
case "$1" in
  repo|api) name=$1 ;;
  *) echo "unexpected gh call: $*" >&2; exit 99 ;;
esac
cat "$dir/$name.out"
cat "$dir/$name.err" >&2
exit "$(cat "$dir/$name.exit")"
"""


def protection(**overrides):
    body = {
        "required_status_checks": {
            "strict": True,
            "contexts": ["leak-check"],
            "checks": [{"context": "leak-check", "app_id": None}],
        },
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": False,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 0,
        },
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
    }
    body.update(overrides)
    return json.dumps({k: v for k, v in body.items() if v is not None})


class FakeGh:
    def __init__(self, test):
        self.base = temp_dir(test)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        write_executable(self.bin / "gh", GH_STUB)
        (self.bin / "calls.log").write_text("", encoding="utf-8")
        self.respond("repo", out=REPO + "\n")
        self.respond("api", out=protection())

    def respond(self, name, out="", err="", code=0):
        (self.bin / f"{name}.out").write_text(out, encoding="utf-8")
        (self.bin / f"{name}.err").write_text(err, encoding="utf-8")
        (self.bin / f"{name}.exit").write_text(str(code), encoding="utf-8")

    def check(self, **env):
        path = str(self.bin) + os.pathsep + os.environ.get("PATH", "")
        return run([CHECK], self.base, isolated_env(self.base, PATH=path, **env))

    def calls(self):
        return (self.bin / "calls.log").read_text(encoding="utf-8").splitlines()


class CheckProtectionTest(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGh(self)

    def test_fully_protected_main_exits_0(self):
        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_leak_check_listed_only_in_checks_exits_0(self):
        self.gh.respond(
            "api",
            out=protection(required_status_checks={"strict": True, "contexts": [], "checks": [{"context": "leak-check"}]}),
        )

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_leak_check_listed_only_in_contexts_exits_0(self):
        self.gh.respond("api", out=protection(required_status_checks={"strict": True, "contexts": ["leak-check"]}))

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_repository_comes_from_gh_repo_view_when_unset(self):
        self.gh.check()

        self.assertIn(PROTECTION_ENDPOINT, self.gh.calls())

    def test_claudio_repo_overrides_the_repository(self):
        self.gh.check(CLAUDIO_REPO="other-owner/other-repo")

        self.assertEqual(self.gh.calls(), ["api repos/other-owner/other-repo/branches/main/protection"])

    def test_admins_not_enforced_exits_1_naming_enforce_admins(self):
        self.gh.respond("api", out=protection(enforce_admins={"enabled": False}))

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 1)
        self.assertIn("enforce_admins", proc.stdout)

    def test_missing_leak_check_status_exits_1_naming_leak_check(self):
        self.gh.respond(
            "api",
            out=protection(required_status_checks={"strict": True, "contexts": ["build"], "checks": [{"context": "build"}]}),
        )

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 1)
        self.assertIn("leak-check", proc.stdout)

    def test_no_pull_request_requirement_exits_1_naming_it(self):
        self.gh.respond("api", out=protection(required_pull_request_reviews=None))

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 1)
        self.assertIn("required_pull_request_reviews", proc.stdout)

    def test_each_missing_setting_is_named(self):
        self.gh.respond(
            "api",
            out=protection(required_pull_request_reviews=None, required_status_checks=None, enforce_admins={"enabled": False}),
        )

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(len(proc.stdout.strip().splitlines()), 3, proc.stdout)

    def test_unprotected_main_exits_1(self):
        self.gh.respond(
            "api",
            out=json.dumps({"message": "Branch not protected", "status": "404"}),
            err="gh: Branch not protected (HTTP 404)\n",
            code=1,
        )

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 1)
        self.assertIn("main is not protected", proc.stdout)

    def test_api_failure_exits_2_with_the_gh_reason(self):
        self.gh.respond(
            "api",
            out=json.dumps({"message": "Not Found", "status": "404"}),
            err="gh: Not Found (HTTP 404)\n",
            code=1,
        )

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 2)
        self.assertIn("gh: Not Found (HTTP 404)", proc.stderr)

    def test_unresolvable_repository_exits_2_with_the_gh_reason(self):
        self.gh.respond("repo", err="no git remotes found\n", code=1)

        proc = self.gh.check()

        self.assertEqual(proc.returncode, 2)
        self.assertIn("no git remotes found", proc.stderr)

    def test_enforce_admins_of_unexpected_type_exits_2(self):
        self.gh.respond("api", out=protection(enforce_admins=True))

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_required_status_checks_of_unexpected_type_exits_2(self):
        self.gh.respond("api", out=protection(required_status_checks=["leak-check"]))

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_required_pull_request_reviews_of_unexpected_type_exits_2(self):
        self.gh.respond("api", out=protection(required_pull_request_reviews=True))

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_empty_body_exits_2(self):
        self.gh.respond("api", out="")

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_malformed_json_exits_2(self):
        self.gh.respond("api", out='{"enforce_admins": ')

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_json_that_is_not_an_object_exits_2(self):
        self.gh.respond("api", out="[]")

        proc = self.gh.check(CLAUDIO_REPO=REPO)

        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_gh_exits_2(self):
        empty_path = self.gh.base / "empty-path"
        empty_path.mkdir()

        proc = run(
            [sys.executable, CHECK], self.gh.base, isolated_env(self.gh.base, PATH=str(empty_path), CLAUDIO_REPO=REPO)
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("gh is not installed", proc.stderr)


if __name__ == "__main__":
    unittest.main()
