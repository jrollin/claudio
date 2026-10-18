import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leak_check

SCRIPT = Path(__file__).resolve().parent / "leak_check.py"

SLACK_ID = "U0" + "AB12CD3E"
NOTION_HEX = "1a2b3c4d" * 4
UUID = "-".join(("1a2b3c4d", "5e6f", "7a8b", "9c0d", "1e2f" * 3))
UUID_PREFIX = "1a2b3c4d-5e6f-7a8b-9c0d-"
AWS_ID = "1234" * 3
AWS_DASHED = "-".join(("1234", "5678", "9012"))
ATLASSIAN_NUMERIC = "5" * 6 + ":" + UUID
ATLASSIAN_HEX = "5f" * 12
COMMIT_HASH = "ab" * 20
HOME_PATH = "/" + "Users" + "/someone/project"
DENY_WORD = "acme"


def rules_matching(text, deny=()):
    return leak_check.scan_text(text, leak_check.build_rules(list(deny)))


def scan_env(home, **overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "LEAK_", "CLAUDIO_"))}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        HOME=str(home),
        LEAK_DENY_WORDS=DENY_WORD,
        PYTHONIOENCODING="utf-8",
    )
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def run_script(cwd, env, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, encoding="utf-8"
    )


class TempRepo:
    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "repo"
        self.home = self.base / "home"
        self.root.mkdir()
        self.home.mkdir()
        self.empty_allow = self.write_outside("empty-allow.txt", "")
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")

    def env(self, **overrides):
        return scan_env(self.home, **overrides)

    def git(self, *args, check=True):
        proc = subprocess.run(
            ["git", *args], cwd=self.root, env=self.env(), capture_output=True, encoding="utf-8", check=check
        )
        return proc.stdout.strip()

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))

    def write_outside(self, name, content):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return str(path)

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "--short", "HEAD")

    def branch(self):
        return self.git("branch", "--show-current")

    def scan(self, *args, **env):
        allow = () if "--allow" in args else ("--allow", self.empty_allow)
        return run_script(self.root, self.env(**env), *args, *allow)

    def allow_file(self, content):
        return self.write_outside("allow.txt", content)


class SlackIdRuleTest(unittest.TestCase):
    def test_id_with_two_digits_matches(self):
        self.assertIn("slack-id", rules_matching(f"channel {SLACK_ID} here"))

    def test_id_with_one_digit_matches(self):
        self.assertIn("slack-id", rules_matching("U" + "ABCD" + "EFG1H"))

    def test_id_with_other_first_letter_does_not_match(self):
        self.assertNotIn("slack-id", rules_matching("X0" + "AB12CD3E"))

    def test_uppercase_word_without_digits_does_not_match(self):
        self.assertNotIn("slack-id", rules_matching("CONTRIBUTING"))

    def test_id_inside_longer_word_does_not_match(self):
        self.assertNotIn("slack-id", rules_matching("x" + SLACK_ID))

    def test_twelve_character_id_matches(self):
        self.assertIn("slack-id", rules_matching("U0" + "AB1" + "2CD3EFG"))

    def test_thirteen_character_id_does_not_match(self):
        self.assertNotIn("slack-id", rules_matching("U0" + "AB1" + "2CD3EFGH"))


class NotionIdRuleTest(unittest.TestCase):
    def test_bare_hex_id_matches(self):
        self.assertIn("notion-id", rules_matching(f"page {NOTION_HEX}"))

    def test_uppercase_bare_hex_id_matches(self):
        self.assertIn("notion-id", rules_matching(NOTION_HEX.upper()))

    def test_uuid_next_to_dash_matches(self):
        self.assertIn("notion-id", rules_matching("1a2b3c4d-" + UUID))

    def test_uuid_inside_hex_run_does_not_match(self):
        self.assertNotIn("notion-id", rules_matching("a" + UUID))

    def test_uppercase_uuid_matches(self):
        self.assertIn("notion-id", rules_matching(UUID.upper()))

    def test_commit_hash_does_not_match(self):
        self.assertEqual(rules_matching(f"commit {COMMIT_HASH}"), [])


class AwsAccountRuleTest(unittest.TestCase):
    def test_twelve_digits_match(self):
        self.assertIn("aws-account", rules_matching(f"account {AWS_ID}"))

    def test_thirteen_digits_do_not_match(self):
        self.assertNotIn("aws-account", rules_matching(AWS_ID + "5"))

    def test_last_uuid_group_does_not_match(self):
        self.assertNotIn("aws-account", rules_matching(UUID_PREFIX + AWS_ID))

    def test_twelve_digits_after_short_hex_group_match(self):
        self.assertIn("aws-account", rules_matching("ab12-" + AWS_ID))

    def test_dashed_console_form_matches(self):
        self.assertIn("aws-account", rules_matching("account " + AWS_DASHED))

    def test_dashed_form_after_full_uuid_prefix_does_not_match(self):
        self.assertNotIn("aws-account", rules_matching(UUID_PREFIX + AWS_DASHED))


class AtlassianAccountRuleTest(unittest.TestCase):
    def test_numeric_prefixed_account_matches(self):
        self.assertIn("atlassian-account", rules_matching(ATLASSIAN_NUMERIC))

    def test_hex_account_matches(self):
        self.assertIn("atlassian-account", rules_matching(f"user {ATLASSIAN_HEX}"))

    def test_thirty_two_hex_does_not_match(self):
        self.assertNotIn("atlassian-account", rules_matching(NOTION_HEX))


class TokenRuleTest(unittest.TestCase):
    def test_github_classic_token_matches(self):
        self.assertIn("token", rules_matching("gh" + "p_" + "a1" * 18))

    def test_github_app_and_oauth_tokens_match(self):
        self.assertIn("token", rules_matching("gh" + "o_" + "a1" * 18))

    def test_github_fine_grained_token_matches(self):
        self.assertIn("token", rules_matching("github" + "_pat_" + "A1" * 11))

    def test_slack_token_matches(self):
        self.assertIn("token", rules_matching("xo" + "xb-" + "abcd" * 3))

    def test_aws_access_key_matches(self):
        self.assertIn("token", rules_matching("AK" + "IA" + "B2" * 8))

    def test_aws_temporary_access_key_matches(self):
        self.assertIn("token", rules_matching("AS" + "IA" + "B2" * 8))

    def test_google_api_key_matches(self):
        self.assertIn("token", rules_matching("AI" + "za" + "x1" * 17 + "y"))

    def test_figma_token_matches(self):
        self.assertIn("token", rules_matching("fi" + "gd_" + "a1" * 15))

    def test_openai_project_key_matches(self):
        self.assertIn("token", rules_matching("sk-" + "proj-" + "a1" * 10))

    def test_gitlab_token_matches(self):
        self.assertIn("token", rules_matching("gl" + "pat-" + "a1" * 10))

    def test_npm_token_matches(self):
        self.assertIn("token", rules_matching("np" + "m_" + "a1" * 18))

    def test_atlassian_api_token_matches(self):
        self.assertIn("token", rules_matching("AT" + "ATT" + "a1" * 10))

    def test_jwt_matches(self):
        self.assertIn("token", rules_matching(".".join(("ey" + "J" + "hbGciOi", "p" * 12, "s" * 12))))

    def test_anthropic_key_matches(self):
        self.assertIn("token", rules_matching("sk-" + "ant-" + "x9" * 10))

    def test_private_key_header_matches(self):
        self.assertIn("token", rules_matching("-----BEGIN " + "RSA PRIVATE KEY-----"))

    def test_pgp_private_key_block_matches(self):
        self.assertIn("token", rules_matching("-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"))


class HomePathRuleTest(unittest.TestCase):
    def test_users_path_matches(self):
        self.assertIn("home-path", rules_matching(f"cd {HOME_PATH}"))

    def test_lowercase_users_path_matches(self):
        self.assertIn("home-path", rules_matching("/" + "users/someone"))

    def test_home_path_matches(self):
        self.assertIn("home-path", rules_matching("/" + "home/someone"))

    def test_windows_users_path_matches(self):
        self.assertIn("home-path", rules_matching("C:" + "\\" + "Users" + "\\" + "someone"))

    def test_url_encoded_users_path_matches(self):
        self.assertIn("home-path", rules_matching("file=" + "%2f" + "users%2F" + "someone"))

    def test_url_encoded_home_path_matches(self):
        self.assertIn("home-path", rules_matching("%2F" + "home%2F" + "someone"))

    def test_relative_home_segment_does_not_match(self):
        self.assertEqual(rules_matching("a/" + "home/someone"), [])

    def test_plain_prose_matches_nothing(self):
        self.assertEqual(rules_matching("Run the scanner before every commit."), [])


class DenyWordRuleTest(unittest.TestCase):
    def test_entry_matches_capitalised_word(self):
        self.assertIn("deny-word", rules_matching("Acme", [DENY_WORD]))

    def test_entry_matches_inside_hyphenated_name(self):
        self.assertIn("deny-word", rules_matching("acme-api", [DENY_WORD]))

    def test_entry_matches_inside_camel_case_name(self):
        self.assertIn("deny-word", rules_matching("AcmeApp", [DENY_WORD]))

    def test_whole_word_entry_matches_hyphenated_name(self):
        self.assertIn("deny-word", rules_matching("acme-api", ["=" + DENY_WORD]))

    def test_whole_word_entry_ignores_camel_case_name(self):
        self.assertNotIn("deny-word", rules_matching("AcmeApp", ["=" + DENY_WORD]))

    def test_whole_word_entry_ignores_name_next_to_digits(self):
        self.assertNotIn("deny-word", rules_matching(DENY_WORD + "2", ["=" + DENY_WORD]))

    def test_entry_with_space_matches_any_whitespace_run(self):
        self.assertIn("deny-word", rules_matching("Acme \t Corp", ["acme corp"]))

    def test_entry_with_space_does_not_match_across_line_wrap(self):
        self.assertNotIn("deny-word", rules_matching("acme\ncorp", ["acme corp"]))

    def test_entry_special_characters_are_literal(self):
        self.assertNotIn("deny-word", rules_matching("abc", ["a.c"]))

    def test_parse_drops_blank_and_comment_lines(self):
        self.assertEqual(leak_check.parse_deny_words("# names\n\n acme \n=corp\n"), ["acme", "=corp"])


class AddedLinesTest(unittest.TestCase):
    def added(self, diff):
        return [(a.path, a.line, a.text) for a in leak_check.added_lines("\n".join(diff))]

    def test_reports_added_lines_across_files_and_hunks(self):
        diff = [
            "diff --git a/one.md b/one.md",
            "--- a/one.md",
            "+++ b/one.md",
            "@@ -1,2 +1,3 @@",
            " keep",
            "-old",
            "+new",
            "+more",
            "@@ -10 +11 @@",
            "-x",
            "+y",
            "diff --git a/two.md b/two.md",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/two.md",
            "@@ -0,0 +1 @@",
            "+fresh",
        ]
        expected = [("one.md", 2, "new"), ("one.md", 3, "more"), ("one.md", 11, "y"), ("two.md", 1, "fresh")]
        self.assertEqual(self.added(diff), expected)

    def test_deleted_file_yields_nothing(self):
        diff = ["diff --git a/gone.md b/gone.md", "--- a/gone.md", "+++ /dev/null", "@@ -1 +0,0 @@", "-bye"]
        self.assertEqual(self.added(diff), [])

    def test_decodes_quoted_path_with_escapes(self):
        diff = ['+++ "b/a\\"\\303\\251.md"', "@@ -0,0 +1 @@", "+text"]
        self.assertEqual(self.added(diff), [('a"é.md', 1, "text")])

    def test_records_follow_commit_headers(self):
        diff = [
            "\x1eCOMMIT first f",
            "+++ b/a.md",
            "@@ -0,0 +1 @@",
            "+one",
            "\x1eCOMMIT second s",
            "+++ b/b.md",
            "@@ -0,0 +1 @@",
            "+two",
        ]
        records = [a.record for a in leak_check.added_lines("\n".join(diff))]
        self.assertEqual(records, ["first f", "second s"])


class AddedPathsTest(unittest.TestCase):
    def test_lists_added_paths_and_both_sides_of_renames(self):
        log = "\0".join(("\x1eCOMMIT h1 s1", "\nA", "new.md", "D", "gone.md", "R100", "old.md", "moved.md", "M", "edit.md", ""))
        expected = [("h1 s1", "new.md"), ("h1 s1", "old.md"), ("h1 s1", "moved.md")]
        self.assertEqual(list(leak_check.added_paths(log)), expected)


class TreeModeTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.repo.write("README.md", "clean\n")
        self.repo.commit()

    def test_clean_tree_exits_zero(self):
        self.assertEqual(self.repo.scan("--tree").returncode, 0)

    def test_tracked_line_prints_path_line_and_rule(self):
        self.repo.write("notes.md", f"intro\nchannel {SLACK_ID}\n")
        self.repo.commit()
        result = self.repo.scan("--tree")
        self.assertEqual((result.returncode, result.stdout), (1, "notes.md:2:slack-id\n"))

    def test_untracked_file_is_scanned(self):
        self.repo.write("draft.md", f"account {AWS_ID}\n")
        self.assertEqual(self.repo.scan("--tree").stdout, "draft.md:1:aws-account\n")

    def test_ignored_file_is_not_scanned(self):
        self.repo.write(".gitignore", "local.md\n")
        self.repo.write("local.md", f"account {AWS_ID}\n")
        self.assertEqual(self.repo.scan("--tree").returncode, 0)

    def test_file_with_nul_byte_is_scanned(self):
        self.repo.write("image.bin", b"\x00\x01" + SLACK_ID.encode() + b"\n")
        self.assertEqual(self.repo.scan("--tree").stdout, "image.bin:1:slack-id\n")

    def test_utf16_file_is_decoded(self):
        self.repo.write("wide.txt", f"for {DENY_WORD}\n".encode("utf-16"))
        self.assertEqual(self.repo.scan("--tree").stdout, "wide.txt:1:deny-word\n")

    def test_path_with_deny_word_is_reported_redacted(self):
        self.repo.write("docs/acme-notes.md", "clean\n")
        self.assertEqual(self.repo.scan("--tree").stdout, "docs/<redacted>-notes.md:0:deny-word\n")

    def test_output_never_contains_matched_text(self):
        secrets = [SLACK_ID, NOTION_HEX, AWS_ID, ATLASSIAN_HEX, HOME_PATH, DENY_WORD]
        self.repo.write(f"{DENY_WORD}/{SLACK_ID}.md", "\n".join(secrets) + "\n")
        result = self.repo.scan("--tree")
        leaked = [s for s in secrets if s.lower() in (result.stdout + result.stderr).lower()]
        self.assertEqual((result.returncode, leaked), (1, []))

    def test_symlink_target_is_scanned_as_line_one(self):
        os.symlink("/" + "home/someone/notes", self.repo.root / "link")
        self.assertEqual(self.repo.scan("--tree").stdout, "link:1:home-path\n")

    def test_summary_counts_findings_per_rule(self):
        self.repo.write("ids.md", f"{SLACK_ID}\n{SLACK_ID}\n{AWS_ID}\n")
        self.assertIn("slack-id: 2 found", self.repo.scan("--tree").stderr)


class StagedModeTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.repo.write("notes.md", "one\ntwo\nthree\n")
        self.repo.write("old.md", f"legacy {SLACK_ID}\n")
        self.repo.write("acme-old.md", "clean\n")
        self.repo.commit()

    def test_added_line_prints_path_line_and_rule(self):
        self.repo.write("notes.md", f"one\ntwo\naccount {AWS_ID}\nthree\n")
        self.repo.git("add", "notes.md")
        self.assertEqual(self.repo.scan("--staged").stdout, "notes.md:3:aws-account\n")

    def test_removed_line_is_not_reported(self):
        self.repo.write("old.md", "legacy\n")
        self.repo.git("add", "old.md")
        self.assertEqual(self.repo.scan("--staged").returncode, 0)

    def test_deleted_file_is_skipped(self):
        self.repo.git("rm", "-q", "old.md")
        result = self.repo.scan("--staged")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_deleted_file_named_with_deny_word_does_not_block(self):
        self.repo.git("rm", "-q", "acme-old.md")
        self.assertEqual(self.repo.scan("--staged").returncode, 0)

    def test_staged_binary_file_lines_are_scanned(self):
        self.repo.write("image.bin", b"\x00\x01" + SLACK_ID.encode() + b"\n")
        self.repo.git("add", "image.bin")
        self.assertEqual(self.repo.scan("--staged").stdout, "image.bin:1:slack-id\n")

    def test_file_marked_minus_diff_is_scanned(self):
        self.repo.write(".gitattributes", "secret.txt -diff\n")
        self.repo.write("secret.txt", f"{SLACK_ID}\n")
        self.repo.git("add", ".gitattributes", "secret.txt")
        self.assertEqual(self.repo.scan("--staged").stdout, "secret.txt:1:slack-id\n")

    def test_staged_path_with_deny_word_is_reported(self):
        self.repo.write("acme.md", "clean\n")
        self.repo.git("add", "acme.md")
        self.assertEqual(self.repo.scan("--staged").stdout, "<redacted>.md:0:deny-word\n")

    def test_added_line_starting_with_plus_signs_is_scanned(self):
        self.repo.write("plus.md", f"++ {SLACK_ID}\n")
        self.repo.git("add", "plus.md")
        self.assertEqual(self.repo.scan("--staged").stdout, "plus.md:1:slack-id\n")

    def test_quoted_path_with_accent_is_decoded(self):
        name = 'a"é.md'
        self.repo.write(name, f"{SLACK_ID}\n")
        self.repo.git("add", name)
        self.assertEqual(self.repo.scan("--staged").stdout, f"{name}:1:slack-id\n")

    def test_unstaged_change_is_not_scanned(self):
        self.repo.write("notes.md", f"one\n{AWS_ID}\n")
        self.assertEqual(self.repo.scan("--staged").returncode, 0)


class MessageModeTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)

    def test_message_line_prints_message_line_and_rule(self):
        message = self.repo.write_outside("COMMIT_EDITMSG", f"subject\n\nfor {DENY_WORD}\n")
        result = self.repo.scan("--message", message)
        self.assertEqual((result.returncode, result.stdout), (1, "<message>:3:deny-word\n"))

    def test_clean_message_exits_zero(self):
        message = self.repo.write_outside("COMMIT_EDITMSG", "subject\n\nbody\n")
        self.assertEqual(self.repo.scan("--message", message).returncode, 0)


class DenyWordsSourceTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.repo.write("notes.md", f"for {DENY_WORD}\n")
        self.repo.commit()
        self.missing_file = str(self.repo.base / "missing-deny-words.txt")
        self.deny_file = self.repo.write_outside("deny.txt", f"{DENY_WORD}\n")

    def test_missing_source_prints_one_notice_and_runs_generic_rules(self):
        self.repo.write("ids.md", f"{SLACK_ID}\n")
        result = self.repo.scan("--tree", LEAK_DENY_WORDS=None, CLAUDIO_DENY_WORDS_FILE=self.missing_file)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr.count("deny-words skipped")),
            (1, "ids.md:1:slack-id\n", 1),
        )

    def test_required_without_source_exits_two_naming_the_secret(self):
        result = self.repo.scan(
            "--tree", "--require-deny-words", LEAK_DENY_WORDS=None, CLAUDIO_DENY_WORDS_FILE=self.missing_file
        )
        self.assertEqual((result.returncode, "LEAK_DENY_WORDS" in result.stderr), (2, True))

    def test_required_by_environment_without_source_exits_two(self):
        result = self.repo.scan(
            "--tree", LEAK_DENY_WORDS=None, CLAUDIO_DENY_WORDS_FILE=self.missing_file, CLAUDIO_REQUIRE_DENY_WORDS="1"
        )
        self.assertEqual(result.returncode, 2)

    def test_required_with_empty_env_exits_two(self):
        self.assertEqual(self.repo.scan("--tree", "--require-deny-words", LEAK_DENY_WORDS="").returncode, 2)

    def test_whitespace_only_env_falls_back_to_file(self):
        result = self.repo.scan("--tree", LEAK_DENY_WORDS=" \n", CLAUDIO_DENY_WORDS_FILE=self.deny_file)
        self.assertEqual(result.stdout, "notes.md:1:deny-word\n")

    def test_required_with_comment_only_file_exits_two(self):
        deny_file = self.repo.write_outside("comments.txt", "# none yet\n\n")
        result = self.repo.scan(
            "--tree", "--require-deny-words", LEAK_DENY_WORDS=None, CLAUDIO_DENY_WORDS_FILE=deny_file
        )
        self.assertEqual(result.returncode, 2)

    def test_file_source_blocks_deny_word(self):
        result = self.repo.scan("--tree", LEAK_DENY_WORDS=None, CLAUDIO_DENY_WORDS_FILE=self.deny_file)
        self.assertEqual(result.stdout, "notes.md:1:deny-word\n")

    def test_default_file_under_home_blocks_staged_line(self):
        default_file = self.repo.home / ".config" / "claudio" / "deny-words.txt"
        default_file.parent.mkdir(parents=True)
        default_file.write_text(f"{DENY_WORD}\n", encoding="utf-8")
        self.repo.write("staged.md", f"for {DENY_WORD}\n")
        self.repo.git("add", "staged.md")
        self.assertEqual(self.repo.scan("--staged", LEAK_DENY_WORDS=None).stdout, "staged.md:1:deny-word\n")

    def test_non_utf8_file_exits_two_without_traceback_or_path(self):
        deny_file = self.repo.write_outside("binary-deny.txt", b"\xff\xfe" + DENY_WORD.encode() + b"\n")
        result = self.repo.scan("--tree", LEAK_DENY_WORDS=None, CLAUDIO_DENY_WORDS_FILE=deny_file)
        self.assertEqual(
            (result.returncode, "Traceback" in result.stderr, Path(deny_file).name in result.stderr),
            (2, False, False),
        )

    def test_env_source_wins_over_file(self):
        result = self.repo.scan("--tree", LEAK_DENY_WORDS="other", CLAUDIO_DENY_WORDS_FILE=self.deny_file)
        self.assertEqual(result.returncode, 0)


class CannotRunTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.repo.write("README.md", "clean\n")
        self.repo.commit()

    def outcome(self, result):
        return result.returncode, "Traceback" in result.stderr

    def test_outside_git_repository_exits_two(self):
        outside = self.repo.base / "outside"
        outside.mkdir()
        env = self.repo.env(GIT_CEILING_DIRECTORIES=str(self.repo.base))
        result = run_script(outside, env, "--tree", "--allow", self.repo.empty_allow)
        self.assertEqual(self.outcome(result), (2, False))

    @unittest.skipIf(os.geteuid() == 0, "root reads files whatever their mode")
    def test_unreadable_file_exits_two(self):
        self.repo.write("locked.md", "clean\n")
        (self.repo.root / "locked.md").chmod(0)
        self.assertEqual(self.outcome(self.repo.scan("--tree")), (2, False))

    def test_git_missing_from_path_exits_two(self):
        empty_bin = self.repo.base / "empty-bin"
        empty_bin.mkdir()
        self.assertEqual(self.outcome(self.repo.scan("--tree", PATH=str(empty_bin))), (2, False))

    def test_corrupt_index_exits_two(self):
        (self.repo.root / ".git" / "index").write_bytes(b"not an index")
        self.assertEqual(self.outcome(self.repo.scan("--tree")), (2, False))

    def test_git_error_text_is_redacted(self):
        result = self.repo.scan("--range", f"{DENY_WORD}..HEAD")
        self.assertEqual((result.returncode, DENY_WORD in result.stderr.lower()), (2, False))


class HistoryModeTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.repo.write("README.md", "clean\n")
        self.repo.commit("start")

    def test_clean_history_exits_zero(self):
        self.assertEqual(self.repo.scan("--history").returncode, 0)

    def test_finding_only_in_old_commit_is_reported_with_short_hash(self):
        self.repo.write("notes.md", f"intro\naccount {AWS_ID}\n")
        leak = self.repo.commit("add notes")
        self.repo.write("notes.md", "intro\n")
        self.repo.commit("drop account")
        result = self.repo.scan("--history")
        self.assertEqual((result.returncode, result.stdout), (1, f"{leak}:notes.md:2:aws-account\n"))

    def test_commit_message_finding_is_reported(self):
        self.repo.write("notes.md", "intro\n")
        commit = self.repo.commit(f"notes\n\nasked by {DENY_WORD}")
        self.assertEqual(self.repo.scan("--history").stdout, f"{commit}:<message>:3:deny-word\n")

    def test_finding_on_other_branch_is_reported(self):
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.write("side.md", f"{SLACK_ID}\n")
        commit = self.repo.commit("side work")
        self.repo.git("checkout", "-q", "-")
        self.assertEqual(self.repo.scan("--history").stdout, f"{commit}:side.md:1:slack-id\n")

    def test_binary_file_lines_are_scanned(self):
        self.repo.write("image.bin", b"\x00\x01" + SLACK_ID.encode() + b"\n")
        commit = self.repo.commit("image")
        self.assertEqual(self.repo.scan("--history").stdout, f"{commit}:image.bin:1:slack-id\n")

    def test_pure_rename_to_deny_word_name_is_reported(self):
        self.repo.write("notes.md", "clean\n")
        self.repo.commit("notes")
        self.repo.git("mv", "notes.md", "acme.md")
        renamed = self.repo.commit("rename")
        self.assertEqual(self.repo.scan("--history").stdout, f"{renamed}:<redacted>.md:0:deny-word\n")

    def test_rename_away_from_deny_word_name_reports_old_path(self):
        self.repo.write("acme-old.md", "clean\n")
        added = self.repo.commit("add")
        self.repo.git("mv", "acme-old.md", "clean.md")
        renamed = self.repo.commit("rename")
        expected = f"{renamed}:<redacted>-old.md:0:deny-word\n{added}:<redacted>-old.md:0:deny-word\n"
        self.assertEqual(self.repo.scan("--history").stdout, expected)

    def test_deleted_file_reports_only_the_commit_that_added_the_leak(self):
        self.repo.write("gone.md", f"{SLACK_ID}\n")
        added = self.repo.commit("add")
        self.repo.git("rm", "-q", "gone.md")
        self.repo.commit("remove")
        self.assertEqual(self.repo.scan("--history").stdout, f"{added}:gone.md:1:slack-id\n")

    def test_leak_added_while_resolving_merge_conflict_is_reported(self):
        main = self.repo.branch()
        self.repo.write("conf.md", "base\n")
        self.repo.commit("base")
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.write("conf.md", "side\n")
        self.repo.commit("side")
        self.repo.git("checkout", "-q", main)
        self.repo.write("conf.md", "main\n")
        self.repo.commit("main")
        self.repo.git("merge", "-q", "side", check=False)
        self.repo.write("conf.md", f"{SLACK_ID}\n")
        merge = self.repo.commit("merge side")
        self.assertEqual(self.repo.scan("--history").stdout, f"{merge}:conf.md:1:slack-id\n")

    def test_late_nul_byte_in_text_file_does_not_break_parsing(self):
        self.repo.write("big.txt", b"x\n" * 4500 + b"\x00\n")
        self.repo.commit("big")
        self.repo.write("leak.md", f"{SLACK_ID}\n")
        leak = self.repo.commit("leak")
        result = self.repo.scan("--history")
        self.assertEqual((result.returncode, result.stdout), (1, f"{leak}:leak.md:1:slack-id\n"))

    def test_blank_context_lines_keep_line_numbers_whatever_the_user_config(self):
        self.repo.git("config", "diff.suppressBlankEmpty", "true")
        self.repo.write("f.md", "a\n\nb\n")
        self.repo.commit("f")
        self.repo.write("f.md", f"a\n\nb\n{SLACK_ID}\n")
        leak = self.repo.commit("leak")
        self.assertEqual(self.repo.scan("--history").stdout, f"{leak}:f.md:4:slack-id\n")

    def test_root_commit_is_scanned_whatever_the_user_config(self):
        repo = TempRepo(self)
        repo.git("config", "log.showRoot", "false")
        repo.write("a.md", f"{SLACK_ID}\n")
        root = repo.commit("root")
        self.assertEqual(repo.scan("--history").stdout, f"{root}:a.md:1:slack-id\n")

    def test_scan_leaves_refs_unchanged(self):
        self.repo.write("notes.md", f"{SLACK_ID}\n")
        self.repo.commit()
        before = self.repo.git("for-each-ref")
        self.repo.scan("--history")
        self.assertEqual(self.repo.git("for-each-ref"), before)

    def test_summary_counts_findings_per_rule(self):
        self.repo.write("notes.md", f"{SLACK_ID}\n")
        self.repo.commit()
        self.assertIn("slack-id: 1 found", self.repo.scan("--history").stderr)


class RangeModeTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.repo.write("old.md", f"{SLACK_ID}\n")
        self.base = self.repo.commit(f"old leak for {DENY_WORD}")
        self.repo.write("new.md", f"{AWS_ID}\n")
        self.head = self.repo.commit(f"for {DENY_WORD}")

    def test_range_scans_only_its_commits_and_their_messages(self):
        result = self.repo.scan("--range", f"{self.base}..HEAD")
        self.assertEqual(result.stdout, f"{self.head}:new.md:1:aws-account\n{self.head}:<message>:1:deny-word\n")

    def test_range_reports_deny_word_path_added_then_deleted(self):
        self.repo.write("acme-notes.md", "clean\n")
        added = self.repo.commit("notes")
        self.repo.git("rm", "-q", "acme-notes.md")
        self.repo.commit("drop notes")
        result = self.repo.scan("--range", f"{self.head}..HEAD")
        self.assertEqual(result.stdout, f"{added}:<redacted>-notes.md:0:deny-word\n")

    def test_range_applies_commit_entries(self):
        allow = self.repo.allow_file(f"commit:{self.head} aws-account\ncommit:{self.head} deny-word\n")
        self.assertEqual(self.repo.scan("--range", f"{self.base}..HEAD", "--allow", allow).returncode, 0)


class AllowlistTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(self)
        self.repo.write("docs/example.md", f"{UUID}\n{AWS_ID}\n")
        self.commit = self.repo.commit("examples")

    def test_path_entry_allows_its_rule(self):
        allow = self.repo.allow_file("path:docs/*.md notion-id\npath:docs/*.md aws-account\n")
        self.assertEqual(self.repo.scan("--tree", "--allow", allow).returncode, 0)

    def test_path_entry_does_not_allow_other_rule(self):
        allow = self.repo.allow_file("path:docs/*.md notion-id\n")
        self.assertEqual(self.repo.scan("--tree", "--allow", allow).stdout, "docs/example.md:2:aws-account\n")

    def test_commit_entry_allows_history_finding(self):
        allow = self.repo.allow_file(f"# acknowledged\ncommit:{self.commit} notion-id\ncommit:{self.commit} aws-account\n")
        self.assertEqual(self.repo.scan("--history", "--allow", allow).returncode, 0)

    def test_commit_entry_for_other_hash_does_not_allow_finding(self):
        self.repo.write("other.md", "clean\n")
        other = self.repo.commit("other")
        allow = self.repo.allow_file(f"commit:{other} notion-id\ncommit:{other} aws-account\n")
        self.assertEqual(self.repo.scan("--history", "--allow", allow).returncode, 1)

    def test_commit_entry_does_not_allow_tree_finding(self):
        allow = self.repo.allow_file(f"commit:{self.commit} aws-account\n")
        self.assertEqual(self.repo.scan("--tree", "--allow", allow).returncode, 1)

    def test_path_entry_never_allows_commit_message_finding(self):
        self.repo.write("notes.md", "intro\n")
        self.repo.commit(f"notes for {DENY_WORD}")
        allow = self.repo.allow_file("path:* deny-word\npath:docs/*.md notion-id\npath:docs/*.md aws-account\n")
        self.assertEqual(self.repo.scan("--history", "--allow", allow).returncode, 1)

    def test_summary_counts_allowed_findings(self):
        allow = self.repo.allow_file("path:docs/*.md notion-id\n")
        self.assertIn("notion-id: 0 found, 1 allowed", self.repo.scan("--tree", "--allow", allow).stderr)

    def test_commit_entry_shorter_than_seven_hex_exits_two_naming_the_line(self):
        allow = self.repo.allow_file("# acknowledged\ncommit:abc12 aws-account\n")
        result = self.repo.scan("--history", "--allow", allow)
        self.assertEqual((result.returncode, f"{Path(allow).name}:2:" in result.stderr), (2, True))

    def test_non_utf8_allow_file_exits_two_without_traceback(self):
        allow = self.repo.allow_file(b"\xff\xfe path:docs/*.md notion-id\n")
        result = self.repo.scan("--tree", "--allow", allow)
        self.assertEqual((result.returncode, "Traceback" in result.stderr), (2, False))

    def test_malformed_entry_exits_two(self):
        allow = self.repo.allow_file("docs/example.md notion-id\n")
        self.assertEqual(self.repo.scan("--tree", "--allow", allow).returncode, 2)

    def test_unknown_rule_exits_two(self):
        allow = self.repo.allow_file("path:docs/*.md notion\n")
        self.assertEqual(self.repo.scan("--tree", "--allow", allow).returncode, 2)

    def test_missing_allow_file_exits_two(self):
        missing = str(self.repo.base / "missing-allow.txt")
        self.assertEqual(self.repo.scan("--tree", "--allow", missing).returncode, 2)


if __name__ == "__main__":
    unittest.main()
