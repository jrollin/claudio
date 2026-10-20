import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import relay_capture
from support import RELAY_START_NS, isolate_relay

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "relay_capture.py")
TOOL = "mcp__docs__read-page"
ARGUMENTS = {"page": 1}
NS = RELAY_START_NS
HOUR_NS = 3600 * 10**9
NOW_LINE = "2026-05-28T20:26:40Z"
EMOJI = chr(0x1F600)


def blocks(*texts):
    return [{"type": "text", "text": text} for text in texts]


def pointer(path):
    return (
        "Error: result (106,888 characters across 1 line) exceeds maximum allowed tokens. "
        f"Output has been saved to {path}.\nFormat: Plain text\nUse offset and limit to read it in parts."
    )


class RelayCase(unittest.TestCase):
    def setUp(self):
        _, self.clock = isolate_relay(self)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dir = os.path.join(self.tmp, "relay")
        self.project = os.path.join(self.tmp, "projects", "proj")
        self.transcript = os.path.join(self.project, "sess.jsonl")

    def payload(self, response, tool_name=TOOL, arguments=ARGUMENTS, tool_use_id="toolu_01"):
        return {
            "hook_event_name": "PostToolUse",
            "tool_name": tool_name,
            "tool_input": arguments,
            "tool_response": response,
            "tool_use_id": tool_use_id,
            "transcript_path": self.transcript,
        }

    def run_hook(self, document=None, raw=None, directory=None):
        data = json.dumps(document).encode("utf-8") if raw is None else raw
        return relay_capture.hook(io.BytesIO(data), self.dir if directory is None else directory)

    def hook_text(self, response, **fields):
        self.assertEqual(self.run_hook(self.payload(response, **fields)), 0)
        return self.taken()

    def taken(self, arguments=ARGUMENTS, tool_name=TOOL, not_before=NS, now=NS):
        return relay_capture.take(self.dir, tool_name, arguments, not_before, now_ns=now)

    def mismatched(self, arguments=ARGUMENTS, tool_name=TOOL, not_before=NS, now=NS):
        found = relay_capture.mismatch(self.dir, tool_name, arguments, not_before, now_ns=now)
        return None if found is None else [relay_capture.difference_text(item) for item in found]

    def put(self, text, arguments=ARGUMENTS, tool_name=TOOL, at=NS, use_id="toolu_01"):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        document = {"tool_name": tool_name, "arguments": arguments, "text": text, "captured_at_ns": at}
        relay_capture.write_capture(self.dir, f"{at}-{use_id}.json", document)

    def plant(self, name, data):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        with open(os.path.join(self.dir, name), "wb") as handle:
            handle.write(data)

    def listing(self):
        return sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else None

    def capture_files(self):
        return [name for name in (self.listing() or []) if name.endswith(".json")]

    def saved_file(self, content, name="mcp-docs-read-page-1792483743918.txt"):
        folder = os.path.join(self.project, "sess", "tool-results")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def errors(self):
        with open(os.path.join(self.dir, relay_capture.ERRORS_LOG), encoding="utf-8") as handle:
            return handle.read()


class CaptureDirTest(unittest.TestCase):
    def test_uses_the_variable_when_it_is_set(self):
        self.assertEqual(relay_capture.capture_dir({relay_capture.ENV_DIR: "/srv/relay"}), "/srv/relay")

    def test_uses_the_default_without_the_variable(self):
        self.assertEqual(relay_capture.capture_dir({}), relay_capture.DEFAULT_DIR)

    def test_uses_the_default_for_an_empty_variable(self):
        self.assertEqual(relay_capture.capture_dir({relay_capture.ENV_DIR: ""}), relay_capture.DEFAULT_DIR)

    def test_uses_the_default_for_a_blank_variable(self):
        self.assertEqual(relay_capture.capture_dir({relay_capture.ENV_DIR: " \t"}), relay_capture.DEFAULT_DIR)

    def test_the_default_is_a_folder_of_the_temporary_directory(self):
        self.assertEqual(relay_capture.DEFAULT_DIR, "/tmp/claudio-relay")


class HookCaptureTest(RelayCase):
    def test_captures_a_text_block_byte_exact(self):
        text = '{"title": "café ' + EMOJI + '"}\r\n\ttrailing  '
        self.assertEqual(self.hook_text(blocks(text)), text)

    def test_joins_the_text_blocks_of_a_result(self):
        self.assertEqual(self.hook_text(blocks("first ", "second")), "first second")

    def test_keeps_an_escaped_surrogate_sequence_inside_a_text(self):
        text = '{"note": "\\ud800 and \\u00e9"}'
        self.assertEqual(self.hook_text(blocks(text)), text)

    def test_keeps_an_emoji_given_as_a_surrogate_pair_escape(self):
        raw = b'{"tool_name": "mcp__docs__read-page", "tool_input": {"page": 1}, "tool_use_id": "t1", "tool_response": [{"type": "text", "text": "\\ud83d\\ude00"}]}'
        self.assertEqual(self.run_hook(raw=raw), 0)
        self.assertEqual(self.taken(), EMOJI)

    def test_captures_the_empty_text(self):
        self.assertEqual(self.hook_text(blocks("")), "")

    def test_writes_the_name_the_arguments_and_the_time_with_the_text(self):
        self.run_hook(self.payload(blocks("body"), arguments={"b": [1, {"c": None}], "a": "x"}))
        (name,) = self.capture_files()
        with open(os.path.join(self.dir, name), encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertEqual(
            (name, document),
            (
                f"{NS}-toolu_01.json",
                {"tool_name": TOOL, "arguments": {"b": [1, {"c": None}], "a": "x"}, "text": "body", "captured_at_ns": NS},
            ),
        )

    def test_creates_the_folder_private_to_the_user(self):
        self.run_hook(self.payload(blocks("body")))
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)

    def test_writes_the_capture_private_to_the_user(self):
        self.run_hook(self.payload(blocks("body")))
        (name,) = self.capture_files()
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, name)).st_mode), 0o600)

    def test_leaves_no_temporary_file(self):
        self.run_hook(self.payload(blocks("body")))
        self.assertEqual(self.listing(), [f"{NS}-toolu_01.json"])

    def test_keeps_two_results_of_one_tool_apart(self):
        self.run_hook(self.payload(blocks("one"), tool_use_id="toolu_01"))
        self.run_hook(self.payload(blocks("two"), tool_use_id="toolu_02"))
        self.assertEqual(len(self.capture_files()), 2)

    def test_keeps_both_captures_of_one_tool_use_id_made_at_two_times(self):
        self.run_hook(self.payload(blocks("one")))
        self.clock.now_ns = NS + 1
        self.run_hook(self.payload(blocks("two")))
        self.assertEqual(len(self.capture_files()), 2)

    def test_removes_the_captures_older_than_a_day_while_it_writes(self):
        self.put("old", at=NS - 25 * HOUR_NS, use_id="old")
        self.run_hook(self.payload(blocks("new")))
        self.assertEqual(self.capture_files(), [f"{NS}-toolu_01.json"])

    def test_the_hook_prints_nothing(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            self.run_hook(self.payload(blocks("body")))
        self.assertEqual(out.getvalue(), "")


class HookPointerTest(RelayCase):
    def test_captures_the_file_a_saved_result_pointer_names(self):
        content = '[{"type": "text", "text": "big ' + EMOJI + '"}]\n'
        path = self.saved_file(content)
        self.assertEqual(self.hook_text(pointer(path)), content)

    def test_captures_a_saved_file_byte_exact_with_carriage_returns(self):
        path = self.saved_file(b"line one\r\nline two\r\n\xe2\x82\xac")
        self.assertEqual(self.hook_text(pointer(path)), "line one\r\nline two\r\n€")

    def test_follows_a_session_folder_that_is_reached_through_a_link(self):
        path = self.saved_file("body")
        link = os.path.join(self.tmp, "linked-projects")
        os.symlink(os.path.join(self.tmp, "projects"), link)
        self.transcript = os.path.join(link, "proj", "sess.jsonl")
        self.assertEqual(self.hook_text(pointer(path)), "body")

    def test_ignores_a_pointer_outside_the_session_folder(self):
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("secret")
        self.assertEqual((self.hook_text(pointer(outside)), self.capture_files()), (None, []))

    def test_ignores_a_pointer_to_a_sibling_folder_sharing_the_prefix(self):
        sibling = os.path.join(self.tmp, "projects", "proj-other")
        os.makedirs(sibling)
        path = os.path.join(sibling, "result.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("secret")
        self.assertEqual((self.hook_text(pointer(path)), self.capture_files()), (None, []))

    def test_ignores_a_pointer_through_a_link_that_leaves_the_session_folder(self):
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("secret")
        folder = os.path.join(self.project, "sess", "tool-results")
        os.makedirs(folder)
        link = os.path.join(folder, "result.txt")
        os.symlink(outside, link)
        self.assertEqual((self.hook_text(pointer(link)), self.capture_files()), (None, []))

    def test_ignores_a_pointer_to_a_session_file_outside_a_tool_results_folder(self):
        os.makedirs(self.project)
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write("transcript")
        self.assertEqual((self.hook_text(pointer(self.transcript)), self.capture_files()), (None, []))

    def test_ignores_a_pointer_that_climbs_out_with_dot_dot(self):
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("secret")
        climbing = os.path.join(self.project, "sess", "..", "..", "..", "outside.txt")
        self.assertEqual((self.hook_text(pointer(climbing)), self.capture_files()), (None, []))

    def test_ignores_a_pointer_to_a_folder(self):
        folder = os.path.join(self.project, "sess", "tool-results")
        os.makedirs(folder)
        self.assertEqual((self.hook_text(pointer(folder)), self.capture_files()), (None, []))

    def test_ignores_a_pointer_to_a_missing_file(self):
        self.assertEqual((self.hook_text(pointer(os.path.join(self.project, "none.txt"))), self.capture_files()), (None, []))

    def test_ignores_a_saved_file_that_is_not_utf_8(self):
        path = self.saved_file(b"\xff\xfe broken")
        self.assertEqual((self.hook_text(pointer(path)), self.capture_files()), (None, []))

    def test_ignores_a_pointer_with_a_relative_transcript_path(self):
        path = self.saved_file("body")
        self.transcript = "sess.jsonl"
        self.assertEqual((self.hook_text(pointer(path)), self.capture_files()), (None, []))

    def test_ignores_a_text_that_only_looks_like_a_pointer(self):
        path = self.saved_file("body")
        self.assertEqual(self.hook_text("a note: " + pointer(path)), None)

    def test_a_list_of_blocks_that_quotes_a_pointer_is_captured_as_text(self):
        path = self.saved_file("body")
        self.assertEqual(self.hook_text(blocks(pointer(path))), pointer(path))

    def test_a_saved_file_over_the_cap_is_skipped(self):
        path = self.saved_file("123456789")
        with mock.patch.object(relay_capture, "TEXT_CAP", 8):
            self.assertEqual((self.hook_text(pointer(path)), self.capture_files()), (None, []))

    def test_a_saved_file_at_the_cap_is_captured(self):
        path = self.saved_file("12345678")
        with mock.patch.object(relay_capture, "TEXT_CAP", 8):
            self.assertEqual(self.hook_text(pointer(path)), "12345678")


class HookSkipTest(RelayCase):
    def test_ignores_a_tool_that_is_not_a_connector_tool(self):
        self.assertEqual(self.hook_text(blocks("body"), tool_name="Bash"), None)

    def test_a_tool_that_is_not_a_connector_tool_leaves_the_folder_alone(self):
        self.run_hook(self.payload(blocks("body"), tool_name="Read"))
        self.assertIsNone(self.listing())

    def test_ignores_a_tool_name_that_only_contains_the_prefix(self):
        self.assertEqual(self.hook_text(blocks("body"), tool_name="x_mcp__docs__read-page"), None)

    def test_ignores_a_response_that_is_a_json_object(self):
        self.assertEqual(self.hook_text({"content": blocks("body")}), None)

    def test_ignores_a_response_with_an_image_block(self):
        self.assertEqual(self.hook_text([{"type": "image", "data": "x"}]), None)

    def test_ignores_a_response_mixing_text_and_other_blocks(self):
        self.assertEqual(self.hook_text(blocks("body") + [{"type": "image", "data": "x"}]), None)

    def test_ignores_an_empty_list_of_blocks(self):
        self.assertEqual(self.hook_text([]), None)

    def test_ignores_a_plain_error_string(self):
        self.assertEqual(self.hook_text("Error: connector unavailable"), None)

    def test_ignores_tool_input_that_is_not_an_object(self):
        self.assertEqual(self.hook_text(blocks("body"), arguments=["page", 1]), None)

    def test_ignores_a_tool_use_id_that_is_not_a_plain_identifier(self):
        self.assertEqual(self.hook_text(blocks("body"), tool_use_id="../escape"), None)

    def test_ignores_a_missing_tool_use_id(self):
        document = self.payload(blocks("body"))
        del document["tool_use_id"]
        self.run_hook(document)
        self.assertEqual(self.capture_files(), [])

    def test_ignores_a_text_over_the_cap(self):
        with mock.patch.object(relay_capture, "TEXT_CAP", 8):
            self.assertEqual((self.hook_text(blocks("123456789")), self.capture_files()), (None, []))

    def test_counts_the_cap_in_bytes(self):
        with mock.patch.object(relay_capture, "TEXT_CAP", 8):
            self.assertEqual(self.hook_text(blocks("€€€")), None)

    def test_captures_a_text_at_the_cap(self):
        with mock.patch.object(relay_capture, "TEXT_CAP", 8):
            self.assertEqual(self.hook_text(blocks("12345678")), "12345678")

    def test_ignores_a_text_with_a_lone_surrogate(self):
        raw = b'{"tool_name": "mcp__docs__read-page", "tool_input": {}, "tool_use_id": "t1", "tool_response": [{"type": "text", "text": "\\ud800"}]}'
        self.run_hook(raw=raw)
        self.assertEqual(self.capture_files(), [])

    def test_the_skips_are_logged_without_the_result_text(self):
        self.run_hook(self.payload([{"type": "image", "data": "SECRET-TEXT"}]))
        self.assertEqual(
            self.errors(),
            f"{NOW_LINE} Skipped tool_response is neither a list of text blocks nor a saved-result pointer\n",
        )


class HookFailureTest(RelayCase):
    def test_malformed_input_exits_0_and_writes_no_capture(self):
        self.assertEqual((self.run_hook(raw=b"{not json"), self.capture_files()), (0, []))

    def test_malformed_input_is_logged_as_one_line(self):
        self.run_hook(raw=b"{not json SECRET-TEXT")
        self.assertEqual(self.errors(), f"{NOW_LINE} Skipped stdin is not UTF-8 JSON\n")

    def test_input_that_is_not_utf_8_is_logged(self):
        self.run_hook(raw=b"\xff\xfe")
        self.assertEqual(self.errors(), f"{NOW_LINE} Skipped stdin is not UTF-8 JSON\n")

    def test_input_that_is_not_an_object_is_logged(self):
        self.run_hook(raw=b"[1, 2]")
        self.assertEqual(self.errors(), f"{NOW_LINE} Skipped stdin is not a JSON object\n")

    def test_empty_input_exits_0(self):
        self.assertEqual(self.run_hook(raw=b""), 0)

    def test_a_deeply_nested_input_exits_0(self):
        self.assertEqual(self.run_hook(raw=b"[" * 100000), 0)

    def test_errors_append_one_line_each(self):
        self.run_hook(raw=b"{")
        self.clock.now_ns = NS + 10**9
        self.run_hook(raw=b"[1]")
        self.assertEqual(self.errors().count("\n"), 2)

    def test_the_error_log_is_private_to_the_user(self):
        self.run_hook(raw=b"{")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, relay_capture.ERRORS_LOG)).st_mode), 0o600)

    def test_a_failing_write_exits_0_and_logs_the_cause(self):
        with mock.patch.object(relay_capture.os, "rename", side_effect=PermissionError(13, "Permission denied")):
            code = self.run_hook(self.payload(blocks("body")))
        self.assertEqual((code, self.errors(), self.listing()), (0, f"{NOW_LINE} PermissionError Permission denied\n", [relay_capture.ERRORS_LOG]))

    def test_a_folder_that_cannot_be_created_exits_0(self):
        blocked = os.path.join(self.tmp, "file")
        with open(blocked, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertEqual(self.run_hook(self.payload(blocks("body")), directory=os.path.join(blocked, "relay")), 0)

    def test_an_unexpected_error_exits_0(self):
        with mock.patch.object(relay_capture, "capture", side_effect=RuntimeError("SECRET-TEXT")):
            code = self.run_hook(self.payload(blocks("body")))
        self.assertEqual((code, self.errors()), (0, f"{NOW_LINE} RuntimeError\n"))


class HookFolderTest(RelayCase):
    def test_writes_nothing_when_the_folder_is_a_link(self):
        target = os.path.join(self.tmp, "target")
        os.mkdir(target)
        os.symlink(target, self.dir)
        self.assertEqual((self.run_hook(self.payload(blocks("body"))), os.listdir(target)), (0, []))

    def test_writes_nothing_when_the_folder_is_a_link_to_a_missing_target(self):
        os.symlink(os.path.join(self.tmp, "missing"), self.dir)
        self.assertEqual((self.run_hook(self.payload(blocks("body"))), os.path.exists(os.path.join(self.tmp, "missing"))), (0, False))

    def test_writes_nothing_when_the_folder_is_a_file(self):
        with open(self.dir, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertEqual((self.run_hook(self.payload(blocks("body"))), os.path.isfile(self.dir)), (0, True))

    def test_writes_nothing_when_another_user_owns_the_folder(self):
        os.mkdir(self.dir, 0o700)
        with mock.patch.object(relay_capture.os, "getuid", return_value=os.getuid() + 1):
            code = self.run_hook(self.payload(blocks("body")))
        self.assertEqual((code, os.listdir(self.dir)), (0, []))

    def test_writes_nothing_through_a_link_planted_as_the_error_log(self):
        os.mkdir(self.dir, 0o700)
        target = os.path.join(self.tmp, "target.log")
        os.symlink(target, os.path.join(self.dir, relay_capture.ERRORS_LOG))
        self.run_hook(raw=b"{")
        self.assertFalse(os.path.exists(target))

    def test_accepts_an_existing_private_folder(self):
        os.mkdir(self.dir, 0o700)
        self.run_hook(self.payload(blocks("body")))
        self.assertEqual(self.capture_files(), [f"{NS}-toolu_01.json"])


class TakeMatchTest(RelayCase):
    def test_returns_the_text_of_the_capture_with_the_same_call(self):
        self.put("body")
        self.assertEqual(self.taken(), "body")

    def test_ignores_a_different_argument_value(self):
        self.put("body", arguments={"page": 2})
        self.assertIsNone(self.taken())

    def test_ignores_a_capture_with_an_extra_argument(self):
        self.put("body", arguments={"page": 1, "size": 10})
        self.assertIsNone(self.taken())

    def test_ignores_a_capture_with_a_missing_argument(self):
        self.put("body", arguments={})
        self.assertIsNone(self.taken({"page": 1, "size": 10}))

    def test_ignores_another_connector_prefix(self):
        self.put("body", tool_name="mcp__other__read-page")
        self.assertIsNone(self.taken())

    def test_ignores_another_tool_of_the_connector(self):
        self.put("body", tool_name="mcp__docs__list-pages")
        self.assertIsNone(self.taken())

    def test_ignores_an_argument_of_another_type(self):
        self.put("body", arguments={"page": "1"})
        self.assertIsNone(self.taken())

    def test_ignores_a_boolean_where_a_number_is_asked(self):
        self.put("body", arguments={"page": True})
        self.assertIsNone(self.taken())

    def test_matches_arguments_whatever_their_key_order(self):
        self.put("body", arguments={"b": 2, "a": {"d": 1, "c": [1, 2]}})
        self.assertEqual(self.taken({"a": {"c": [1, 2], "d": 1}, "b": 2}), "body")

    def test_matches_arguments_with_non_ascii_text(self):
        self.put("body", arguments={"query": "café " + EMOJI})
        self.assertEqual(self.taken({"query": "café " + EMOJI}), "body")

    def test_a_nested_value_must_match_exactly(self):
        self.put("body", arguments={"filters": {"ids": [1, 2]}})
        self.assertIsNone(self.taken({"filters": {"ids": [2, 1]}}))

    def test_keeps_a_capture_it_did_not_match(self):
        self.put("body", arguments={"page": 2})
        self.taken()
        self.assertEqual(self.capture_files(), [f"{NS}-toolu_01.json"])

    def test_returns_none_without_a_folder(self):
        self.assertEqual((self.taken(), self.listing()), (None, None))

    def test_returns_none_for_a_folder_that_is_a_link(self):
        target = os.path.join(self.tmp, "target")
        os.mkdir(target)
        os.symlink(target, self.dir)
        relay_capture.write_capture(target, f"{NS}-toolu_01.json", {"tool_name": TOOL, "arguments": ARGUMENTS, "text": "body", "captured_at_ns": NS})
        self.assertIsNone(self.taken())

    def test_returns_none_when_another_user_owns_the_folder(self):
        self.put("body")
        with mock.patch.object(relay_capture.os, "getuid", return_value=os.getuid() + 1):
            self.assertIsNone(self.taken())

    def test_returns_the_text_a_hook_captured(self):
        self.run_hook(self.payload(blocks("from the hook"), arguments={"page": 1}))
        self.assertEqual(self.taken({"page": 1}), "from the hook")


class TakeFreshnessTest(RelayCase):
    def test_ignores_a_capture_older_than_the_planned_time(self):
        self.put("body", at=NS - 1)
        self.assertIsNone(self.taken(not_before=NS))

    def test_keeps_a_capture_older_than_the_planned_time(self):
        self.put("body", at=NS - 1)
        self.taken(not_before=NS)
        self.assertEqual(self.capture_files(), [f"{NS - 1}-toolu_01.json"])

    def test_takes_a_capture_made_at_the_planned_time(self):
        self.put("body", at=NS)
        self.assertEqual(self.taken(not_before=NS), "body")

    def test_takes_a_capture_made_after_the_planned_time(self):
        self.put("body", at=NS + 5)
        self.assertEqual(self.taken(not_before=NS, now=NS + 5), "body")

    def test_takes_the_newest_of_two_captures(self):
        self.put("older", at=NS + 1, use_id="a")
        self.put("newer", at=NS + 2, use_id="b")
        self.assertEqual(self.taken(now=NS + 2), "newer")

    def test_takes_the_newest_whatever_the_order_of_the_identifiers(self):
        self.put("newer", at=NS + 2, use_id="a")
        self.put("older", at=NS + 1, use_id="z")
        self.assertEqual(self.taken(now=NS + 2), "newer")

    def test_deletes_both_captures_it_matched(self):
        self.put("older", at=NS + 1, use_id="a")
        self.put("newer", at=NS + 2, use_id="b")
        self.taken(now=NS + 2)
        self.assertEqual(self.capture_files(), [])

    def test_a_taken_capture_is_not_given_twice(self):
        self.put("body")
        self.taken()
        self.assertIsNone(self.taken())

    def test_the_newest_stale_capture_does_not_hide_a_fresh_one(self):
        self.put("stale", at=NS - 1, use_id="a")
        self.put("fresh", at=NS + 1, use_id="b")
        self.assertEqual(self.taken(not_before=NS, now=NS + 1), "fresh")


class TakeCleanupTest(RelayCase):
    def test_deletes_a_capture_older_than_a_day(self):
        self.put("old", at=NS - 25 * HOUR_NS, use_id="old", arguments={"page": 9})
        self.taken()
        self.assertEqual(self.capture_files(), [])

    def test_never_gives_a_capture_older_than_a_day(self):
        self.put("old", at=NS - 25 * HOUR_NS)
        self.assertIsNone(self.taken(not_before=0))

    def test_keeps_a_capture_exactly_a_day_old(self):
        self.put("recent", at=NS - 24 * HOUR_NS, use_id="recent", arguments={"page": 9})
        self.taken()
        self.assertEqual(self.capture_files(), [f"{NS - 24 * HOUR_NS}-recent.json"])

    def test_keeps_what_is_not_a_capture(self):
        self.plant("errors.log", b"line\n")
        self.plant("notes.txt", b"x")
        self.plant(f"{NS - 48 * HOUR_NS}-x.txt", b"x")
        self.taken()
        self.assertEqual(self.listing(), [f"{NS - 48 * HOUR_NS}-x.txt", "errors.log", "notes.txt"])

    def test_a_stale_folder_named_like_a_capture_does_not_stop_a_take(self):
        os.makedirs(os.path.join(self.dir, f"{NS - 48 * HOUR_NS}-dir.json", "inner"))
        self.put("body")
        self.assertEqual(self.taken(), "body")


class TakeSkipTest(RelayCase):
    def test_skips_a_capture_that_is_not_json(self):
        self.plant(f"{NS}-bad.json", b"{not json")
        self.put("body", use_id="good")
        self.assertEqual(self.taken(), "body")

    def test_skips_a_capture_that_is_not_utf_8(self):
        self.plant(f"{NS}-bad.json", b"\xff\xfe")
        self.put("body", use_id="good")
        self.assertEqual(self.taken(), "body")

    def test_skips_a_capture_that_is_not_an_object(self):
        self.plant(f"{NS}-bad.json", b"[1]")
        self.put("body", use_id="good")
        self.assertEqual(self.taken(), "body")

    def test_skips_a_capture_with_another_set_of_keys(self):
        document = {"tool_name": TOOL, "arguments": ARGUMENTS, "text": "extra", "captured_at_ns": NS, "more": 1}
        self.plant(f"{NS + 1}-bad.json", json.dumps(document).encode("ascii"))
        self.put("body", use_id="good")
        self.assertEqual(self.taken(now=NS + 1), "body")

    def test_skips_a_capture_whose_time_differs_from_its_name(self):
        document = {"tool_name": TOOL, "arguments": ARGUMENTS, "text": "liar", "captured_at_ns": NS - 1}
        self.plant(f"{NS + 1}-bad.json", json.dumps(document).encode("ascii"))
        self.put("body", use_id="good")
        self.assertEqual(self.taken(now=NS + 1), "body")

    def test_skips_a_capture_whose_text_is_not_a_string(self):
        document = {"tool_name": TOOL, "arguments": ARGUMENTS, "text": 5, "captured_at_ns": NS + 1}
        self.plant(f"{NS + 1}-bad.json", json.dumps(document).encode("ascii"))
        self.put("body", use_id="good")
        self.assertEqual(self.taken(now=NS + 1), "body")

    def test_skips_a_capture_whose_text_has_a_lone_surrogate(self):
        data = b'{"tool_name": "%s", "arguments": {"page": 1}, "text": "\\ud800", "captured_at_ns": %d}' % (TOOL.encode(), NS + 1)
        self.plant(f"{NS + 1}-bad.json", data)
        self.put("body", use_id="good")
        self.assertEqual(self.taken(now=NS + 1), "body")

    def test_skips_a_capture_whose_arguments_are_not_an_object(self):
        document = {"tool_name": TOOL, "arguments": [1], "text": "x", "captured_at_ns": NS + 1}
        self.plant(f"{NS + 1}-bad.json", json.dumps(document).encode("ascii"))
        self.put("body", use_id="good")
        self.assertEqual(self.taken(now=NS + 1), "body")

    def test_skips_a_folder_named_like_a_capture(self):
        os.makedirs(os.path.join(self.dir, f"{NS + 1}-dir.json"))
        self.put("body", use_id="good")
        self.assertEqual(self.taken(now=NS + 1), "body")

    def test_skips_a_link_named_like_a_capture(self):
        target = os.path.join(self.tmp, "target.json")
        document = {"tool_name": TOOL, "arguments": ARGUMENTS, "text": "linked", "captured_at_ns": NS + 1}
        with open(target, "w", encoding="ascii") as handle:
            json.dump(document, handle)
        os.makedirs(self.dir, mode=0o700)
        os.symlink(target, os.path.join(self.dir, f"{NS + 1}-link.json"))
        self.put("body", use_id="good")
        self.assertEqual(self.taken(now=NS + 1), "body")

    def test_skips_a_file_with_a_name_outside_the_capture_pattern(self):
        document = {"tool_name": TOOL, "arguments": ARGUMENTS, "text": "stray", "captured_at_ns": NS}
        self.plant("stray.json", json.dumps(document).encode("ascii"))
        self.assertIsNone(self.taken())

    def test_a_skipped_capture_is_left_in_place(self):
        self.plant(f"{NS}-bad.json", b"{not json")
        self.taken()
        self.assertEqual(self.capture_files(), [f"{NS}-bad.json"])


class MismatchDifferenceTest(RelayCase):
    def test_reports_the_first_differing_character_and_both_lengths_of_a_changed_string(self):
        self.put("body", arguments={"content": "abXdefg"})
        self.assertEqual(self.mismatched({"content": "abcdef"}), ["content changed at char 2 (planned 6, called 7)"])

    def test_reports_the_difference_as_a_path_a_kind_and_a_detail(self):
        self.put("body", arguments={"content": "abXdef"})
        found = relay_capture.mismatch(self.dir, TOOL, {"content": "abcdef"}, NS, now_ns=NS)
        self.assertEqual(found, [relay_capture.Difference("content", "changed", "at char 2 (planned 6, called 6)")])

    def test_reports_the_shorter_length_when_the_called_string_is_a_prefix(self):
        self.put("body", arguments={"content": "abc"})
        self.assertEqual(self.mismatched({"content": "abcde"}), ["content changed at char 3 (planned 5, called 3)"])

    def test_reports_the_shorter_length_when_the_planned_string_is_a_prefix(self):
        self.put("body", arguments={"content": "abcde"})
        self.assertEqual(self.mismatched({"content": "abc"}), ["content changed at char 3 (planned 3, called 5)"])

    def test_counts_characters_not_bytes(self):
        self.put("body", arguments={"content": EMOJI + "b"})
        self.assertEqual(self.mismatched({"content": EMOJI + "a"}), ["content changed at char 1 (planned 2, called 2)"])

    def test_reports_a_key_the_call_lacks_as_missing(self):
        self.put("body", arguments={"page": 1})
        self.assertEqual(self.mismatched({"page": 1, "size": 10}), ["size missing"])

    def test_reports_a_key_the_plan_lacks_as_extra(self):
        self.put("body", arguments={"page": 1, "size": 10})
        self.assertEqual(self.mismatched({"page": 1}), ["size extra"])

    def test_reports_a_missing_list_item_by_its_index(self):
        self.put("body", arguments={"ids": [1]})
        self.assertEqual(self.mismatched({"ids": [1, 2, 3]}), ["ids[1] missing", "ids[2] missing"])

    def test_reports_an_extra_list_item_by_its_index(self):
        self.put("body", arguments={"ids": [1, 2, 3]})
        self.assertEqual(self.mismatched({"ids": [1]}), ["ids[1] extra", "ids[2] extra"])

    def test_reports_a_changed_type_by_its_type_names(self):
        self.put("body", arguments={"page": "1"})
        self.assertEqual(self.mismatched({"page": 1}), ["page changed (planned int, called str)"])

    def test_reports_a_boolean_where_a_number_is_planned_by_its_type_names(self):
        self.put("body", arguments={"page": True})
        self.assertEqual(self.mismatched({"page": 1}), ["page changed (planned int, called bool)"])

    def test_reports_a_null_by_its_type_name(self):
        self.put("body", arguments={"page": None})
        self.assertEqual(self.mismatched({"page": 1}), ["page changed (planned int, called NoneType)"])

    def test_reports_a_changed_container_by_its_type_names(self):
        self.put("body", arguments={"filters": [1]})
        self.assertEqual(self.mismatched({"filters": {"id": 1}}), ["filters changed (planned dict, called list)"])

    def test_reports_a_changed_value_of_the_same_type_without_detail(self):
        self.put("body", arguments={"page": 2})
        self.assertEqual(self.mismatched({"page": 1}), ["page changed"])

    def test_joins_object_keys_with_dots_and_list_indexes_in_brackets(self):
        called = {"pages": [{"title": "t", "content": "abXd"}]}
        self.put("body", arguments=called)
        planned = {"pages": [{"title": "t", "content": "abcd"}]}
        self.assertEqual(self.mismatched(planned), ["pages[0].content changed at char 2 (planned 4, called 4)"])

    def test_reports_the_nested_lists_of_a_list(self):
        self.put("body", arguments={"grid": [[1, 2], [3, 5]]})
        self.assertEqual(self.mismatched({"grid": [[1, 2], [3, 4]]}), ["grid[1][1] changed"])

    def test_lists_the_differences_in_key_order(self):
        self.put("body", arguments={"b": 2, "a": 2, "c": 2})
        self.assertEqual(self.mismatched({"c": 1, "b": 1, "a": 1}), ["a changed", "b changed", "c changed"])

    def test_reports_every_kind_of_difference_of_one_capture(self):
        self.put("body", arguments={"b": "x", "c": 1})
        self.assertEqual(self.mismatched({"a": 1, "b": "y"}), ["a missing", "b changed at char 0 (planned 1, called 1)", "c extra"])


class MismatchSelectionTest(RelayCase):
    def test_returns_none_for_an_exact_match(self):
        self.put("body")
        self.assertIsNone(self.mismatched())

    def test_returns_none_for_an_exact_match_whatever_the_key_order(self):
        self.put("body", arguments={"b": 2, "a": 1})
        self.assertIsNone(self.mismatched({"a": 1, "b": 2}))

    def test_returns_none_without_a_capture(self):
        os.makedirs(self.dir, mode=0o700)
        self.assertIsNone(self.mismatched())

    def test_ignores_another_tool_name(self):
        self.put("body", arguments={"page": 2}, tool_name="mcp__docs__list-pages")
        self.assertIsNone(self.mismatched())

    def test_ignores_another_connector(self):
        self.put("body", arguments={"page": 2}, tool_name="mcp__other__read-page")
        self.assertIsNone(self.mismatched())

    def test_ignores_a_capture_older_than_the_planned_time(self):
        self.put("body", arguments={"page": 2}, at=NS - 1)
        self.assertIsNone(self.mismatched(not_before=NS))

    def test_reports_a_capture_made_at_the_planned_time(self):
        self.put("body", arguments={"page": 2}, at=NS)
        self.assertEqual(self.mismatched(not_before=NS), ["page changed"])

    def test_ignores_a_capture_older_than_a_day(self):
        self.put("body", arguments={"page": 2}, at=NS - 25 * HOUR_NS)
        self.assertIsNone(self.mismatched(not_before=0))

    def test_the_closest_of_two_captures_wins(self):
        self.put("far", arguments={"a": 2, "b": 2}, at=NS + 1, use_id="a")
        self.put("near", arguments={"a": 2, "b": 1}, at=NS, use_id="b")
        self.assertEqual(self.mismatched({"a": 1, "b": 1}, now=NS + 1), ["a changed"])

    def test_the_closest_wins_even_when_it_is_the_older_one(self):
        self.put("near", arguments={"a": 2, "b": 1}, at=NS, use_id="a")
        self.put("far", arguments={"a": 2, "b": 2}, at=NS + 1, use_id="b")
        self.assertEqual(self.mismatched({"a": 1, "b": 1}, now=NS + 1), ["a changed"])

    def test_a_tie_goes_to_the_newest(self):
        self.put("older", arguments={"a": 2, "b": 1}, at=NS, use_id="a")
        self.put("newer", arguments={"a": 1, "b": 2}, at=NS + 1, use_id="b")
        self.assertEqual(self.mismatched({"a": 1, "b": 1}, now=NS + 1), ["b changed"])

    def test_a_tie_goes_to_the_newest_whatever_the_order_of_the_identifiers(self):
        self.put("newer", arguments={"a": 1, "b": 2}, at=NS + 1, use_id="a")
        self.put("older", arguments={"a": 2, "b": 1}, at=NS, use_id="z")
        self.assertEqual(self.mismatched({"a": 1, "b": 1}, now=NS + 1), ["b changed"])

    def test_counts_one_difference_per_path_not_per_character(self):
        self.put("whole string", arguments={"a": "yyyyyyyy", "b": 1, "c": 1}, at=NS, use_id="a")
        self.put("two paths", arguments={"a": "xxxxxxxx", "b": 2, "c": 2}, at=NS + 1, use_id="b")
        self.assertEqual(self.mismatched({"a": "xxxxxxxx", "b": 1, "c": 1}, now=NS + 1), ["a changed at char 0 (planned 8, called 8)"])

    def test_an_exact_capture_does_not_hide_a_near_one(self):
        self.put("exact", at=NS, use_id="a")
        self.put("near", arguments={"page": 2}, at=NS + 1, use_id="b")
        self.assertEqual(self.mismatched(now=NS + 1), ["page changed"])

    def test_skips_a_malformed_capture(self):
        self.plant(f"{NS}-bad.json", b"{not json")
        self.put("body", arguments={"page": 2}, use_id="good")
        self.assertEqual(self.mismatched(), ["page changed"])

    def test_returns_none_without_a_folder_and_creates_none(self):
        self.assertEqual((self.mismatched(), self.listing()), (None, None))

    def test_returns_none_for_a_folder_that_is_a_link(self):
        target = os.path.join(self.tmp, "target")
        os.mkdir(target)
        os.symlink(target, self.dir)
        relay_capture.write_capture(target, f"{NS}-toolu_01.json", {"tool_name": TOOL, "arguments": {"page": 2}, "text": "body", "captured_at_ns": NS})
        self.assertIsNone(self.mismatched())

    def test_returns_none_when_another_user_owns_the_folder(self):
        self.put("body", arguments={"page": 2})
        with mock.patch.object(relay_capture.os, "getuid", return_value=os.getuid() + 1):
            self.assertIsNone(self.mismatched())

    def test_returns_none_for_a_folder_it_cannot_list(self):
        self.put("body", arguments={"page": 2})
        with mock.patch.object(relay_capture.os, "listdir", side_effect=PermissionError):
            self.assertIsNone(self.mismatched())


class MismatchReadOnlyTest(RelayCase):
    def test_deletes_no_capture_it_read(self):
        self.put("near", arguments={"page": 2}, at=NS, use_id="a")
        self.put("far", arguments={"page": 3, "size": 1}, at=NS + 1, use_id="b")
        self.put("exact", at=NS + 2, use_id="c")
        self.put("other", arguments={"page": 2}, tool_name="mcp__other__read-page", at=NS + 3, use_id="d")
        before = self.capture_files()
        self.mismatched(now=NS + 3)
        self.assertEqual((self.capture_files(), len(before)), (before, 4))

    def test_leaves_a_capture_it_reported_for_a_later_take(self):
        self.put("body", arguments={"page": 2})
        self.mismatched()
        self.assertEqual(self.taken({"page": 2}), "body")

    def test_removes_a_capture_older_than_a_day_like_take(self):
        self.put("stale", arguments={"page": 2}, at=NS - 25 * HOUR_NS)
        self.mismatched()
        self.assertEqual(self.capture_files(), [])

    def test_keeps_a_capture_exactly_a_day_old(self):
        self.put("body", arguments={"page": 2}, at=NS - 24 * HOUR_NS)
        self.mismatched(not_before=0)
        self.assertEqual(self.capture_files(), [f"{NS - 24 * HOUR_NS}-toolu_01.json"])


class MismatchValueFreeTest(RelayCase):
    PLANNED_VALUE = "planned-secret-value-91"
    CALLED_VALUE = "called-secret-value-47"

    def output(self, planned, called):
        self.put("result text of the call", arguments=called)
        found = relay_capture.mismatch(self.dir, TOOL, planned, NS, now_ns=NS)
        return repr(found) + " ".join(relay_capture.difference_text(item) for item in found)

    def test_a_changed_string_shows_neither_value(self):
        shown = self.output({"content": self.PLANNED_VALUE}, {"content": self.CALLED_VALUE})
        self.assertEqual([value in shown for value in (self.PLANNED_VALUE, self.CALLED_VALUE, "secret")], [False, False, False])

    def test_a_changed_nested_value_shows_no_value(self):
        shown = self.output({"pages": [{"content": self.PLANNED_VALUE}]}, {"pages": [{"content": self.CALLED_VALUE}]})
        self.assertEqual([value in shown for value in (self.PLANNED_VALUE, self.CALLED_VALUE)], [False, False])

    def test_an_extra_key_shows_its_name_but_not_its_value(self):
        shown = self.output({"page": 1}, {"page": 1, "note": self.CALLED_VALUE})
        self.assertEqual((self.CALLED_VALUE in shown, "note extra" in shown), (False, True))

    def test_a_missing_key_shows_its_name_but_not_its_value(self):
        shown = self.output({"page": 1, "note": self.PLANNED_VALUE}, {"page": 1})
        self.assertEqual((self.PLANNED_VALUE in shown, "note missing" in shown), (False, True))

    def test_a_changed_type_shows_no_value(self):
        shown = self.output({"note": self.PLANNED_VALUE}, {"note": [self.CALLED_VALUE]})
        self.assertEqual([value in shown for value in (self.PLANNED_VALUE, self.CALLED_VALUE)], [False, False])

    def test_list_items_show_no_value(self):
        shown = self.output({"ids": [self.PLANNED_VALUE]}, {"ids": [self.CALLED_VALUE, self.CALLED_VALUE]})
        self.assertEqual([value in shown for value in (self.PLANNED_VALUE, self.CALLED_VALUE)], [False, False])

    def test_the_result_text_is_not_shown(self):
        self.assertNotIn("result text", self.output({"page": 1}, {"page": 2}))


class HookScriptTest(RelayCase):
    def run_script(self, data, directory):
        return subprocess.run(
            [sys.executable, "-I", SCRIPT], input=data, capture_output=True, timeout=20, env={relay_capture.ENV_DIR: directory}
        )

    def test_captures_a_result_read_from_stdin(self):
        done = self.run_script(json.dumps(self.payload(blocks("from stdin"))).encode("utf-8"), self.dir)
        text = relay_capture.take(self.dir, TOOL, ARGUMENTS, 0, now_ns=time.time_ns())
        self.assertEqual((done.returncode, done.stdout, done.stderr, text), (0, b"", b"", "from stdin"))

    def test_exits_0_without_output_on_malformed_stdin(self):
        done = self.run_script(b"{not json", self.dir)
        self.assertEqual((done.returncode, done.stdout, done.stderr, self.capture_files()), (0, b"", b"", []))

    def test_logs_malformed_stdin_in_the_folder_the_variable_names(self):
        self.run_script(b"{not json", self.dir)
        self.assertEqual(self.listing(), [relay_capture.ERRORS_LOG])

    def test_exits_0_for_a_tool_that_is_not_a_connector_tool(self):
        done = self.run_script(json.dumps(self.payload(blocks("x"), tool_name="Bash")).encode("utf-8"), self.dir)
        self.assertEqual((done.returncode, done.stdout, self.listing()), (0, b"", None))


if __name__ == "__main__":
    unittest.main()
