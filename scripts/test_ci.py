import re
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
LINT_RUN = "run: python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public"


def steps(text):
    blocks = re.split(r"\n\s*- (?=name:|uses:)", text)
    return blocks[1:]


def listed_files(root):
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    )
    return [PurePosixPath(name) for name in result.stdout.decode().split("\0") if name]


def test_dirs(root=ROOT):
    found = {
        path.parent.as_posix()
        for path in listed_files(root)
        if path.name.startswith("test_") and path.suffix == ".py"
    }
    return sorted(directory for directory in found if not covered(root, directory, found))


def covered(root, directory, found):
    # unittest discovery only recurses into importable packages below its start directory.
    current = PurePosixPath(directory)
    while current.name and (root / current / "__init__.py").is_file():
        current = current.parent
        if str(current) in found:
            return True
    return False


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()
        cls.steps = steps(cls.text)

    def test_leak_check_job_id(self):
        self.assertRegex(self.text, r"(?m)^  leak-check:\s*$")

    def test_leak_check_job_times_out_after_15_minutes(self):
        job = re.search(r"(?ms)^  leak-check:\s*$(.*?)(?=^  \S|\Z)", self.text).group(1)
        self.assertRegex(job, r"(?m)^    timeout-minutes: 15\s*$")

    def test_no_pull_request_target(self):
        self.assertNotIn("pull_request_target", self.text)

    def test_runs_on_push_and_pull_request(self):
        self.assertRegex(self.text, r"(?m)^  push:")
        self.assertRegex(self.text, r"(?m)^  pull_request:")

    def test_push_and_pull_request_run_on_main_only(self):
        triggers = re.search(r"(?ms)^on:\s*$(.*?)(?=^\S|\Z)", self.text).group(1)
        self.assertRegex(triggers, r"(?m)^  push:[ \t]*\n    branches: \[main\]\s*$")
        self.assertRegex(triggers, r"(?m)^  pull_request:[ \t]*\n    branches: \[main\]\s*$")

    def test_read_only_permissions(self):
        self.assertRegex(self.text, r"(?m)^permissions:\s*\n\s+contents: read\s*$")

    def test_fork_guard_runs_first(self):
        first = self.steps[0]
        self.assertIn("head.repo.full_name != github.repository", first)
        self.assertIn("exit 1", first)

    def test_fork_guard_names_the_secret(self):
        self.assertIn("not available to forks", self.steps[0])

    def test_checkout_after_fork_guard(self):
        checkout = next(i for i, s in enumerate(self.steps) if "actions/checkout" in s)
        self.assertGreater(checkout, 0)

    def test_checkout_fetches_full_history(self):
        checkout = next(s for s in self.steps if "actions/checkout" in s)
        self.assertIn("fetch-depth: 0", checkout)
        self.assertIn("persist-credentials: false", checkout)

    def test_actions_pinned_by_commit(self):
        uses = re.findall(r"uses: (\S+)", self.text)
        self.assertTrue(uses)
        self.assertEqual([ref for ref in uses if not re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref)], [])

    def test_secret_only_in_leak_check_step(self):
        self.assertEqual(self.text.count("secrets."), 1)
        holders = [s for s in self.steps if "secrets.LEAK_DENY_WORDS" in s]
        self.assertEqual(len(holders), 1)
        self.assertIn("leak_check.py --tree --require-deny-words", holders[0])

    def test_secret_set_in_step_env(self):
        holder = next(s for s in self.steps if "secrets.LEAK_DENY_WORDS" in s)
        self.assertRegex(holder, r"env:\s*\n(\s+\w+: .*\n)*?\s+LEAK_DENY_WORDS: \$\{\{ secrets\.LEAK_DENY_WORDS \}\}")

    def test_leak_check_scans_new_commits(self):
        holder = next(s for s in self.steps if "secrets.LEAK_DENY_WORDS" in s)
        self.assertIn('--range "$PR_BASE..$PR_HEAD" --require-deny-words', holder)
        self.assertIn('--range "$PUSH_BEFORE..$PUSH_AFTER" --require-deny-words', holder)
        self.assertIn("--history --require-deny-words", holder)

    def test_no_step_may_fail_silently(self):
        self.assertNotIn("continue-on-error", self.text)

    def test_no_commented_command(self):
        self.assertNotRegex(self.text, r"(?m)^\s*#.*(run:|python3)")

    def test_template_lint_runs_once(self):
        self.assertEqual(self.text.count(LINT_RUN + "\n"), 1)

    def test_one_unittest_run_per_test_directory(self):
        dirs = test_dirs()
        self.assertTrue(dirs)
        counts = {directory: self.text.count(f"run: python3 -m unittest discover -s {directory}\n") for directory in dirs}
        self.assertEqual(counts, dict.fromkeys(dirs, 1))

    def test_no_unittest_run_for_a_missing_directory(self):
        listed = re.findall(r"unittest discover -s (\S+)", self.text)
        self.assertEqual(sorted(listed), test_dirs())


class TestDirsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)

    def tree(self, *files):
        for name in files:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_package_under_a_listed_directory_is_covered(self):
        self.tree("top/test_a.py", "top/pkg/__init__.py", "top/pkg/test_b.py")
        self.assertEqual(test_dirs(self.root), ["top"])

    def test_package_under_package_intermediates_is_covered(self):
        self.tree("top/test_a.py", "top/mid/__init__.py", "top/mid/pkg/__init__.py", "top/mid/pkg/test_b.py")
        self.assertEqual(test_dirs(self.root), ["top"])

    def test_non_package_subdirectory_is_listed(self):
        self.tree("top/test_a.py", "top/sub/test_b.py")
        self.assertEqual(test_dirs(self.root), ["top", "top/sub"])

    def test_package_behind_a_non_package_intermediate_is_listed(self):
        self.tree("top/test_a.py", "top/mid/pkg/__init__.py", "top/mid/pkg/test_b.py")
        self.assertEqual(test_dirs(self.root), ["top", "top/mid/pkg"])

    def test_ignored_directory_is_not_listed(self):
        (self.root / ".gitignore").write_text("build/\n")
        self.tree("top/test_a.py", "build/lib/test_b.py")
        self.assertEqual(test_dirs(self.root), ["top"])

    def test_tracked_directory_is_listed(self):
        self.tree("top/test_a.py")
        subprocess.run(["git", "-C", str(self.root), "add", "top/test_a.py"], check=True, capture_output=True)
        self.assertEqual(test_dirs(self.root), ["top"])


class GitignoreTest(unittest.TestCase):
    def test_ignores_python_caches(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertIn("__pycache__/", lines)

    def test_ignores_local_claude_settings(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertIn(".claude/settings.local.json", lines)


if __name__ == "__main__":
    unittest.main()
