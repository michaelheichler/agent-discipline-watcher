"""Contract tests for hook payload accessors, with literal on-stdin fixtures, because every hook must agree on the same field names and coercions."""

from __future__ import annotations

import unittest

import record
from lib import payloads
from testing import CollidingKey, HostileDict, HostileString

PRE_TOOL_USE: dict[str, object] = {
    "session_id": "sess-1",
    "cwd": "/repo",
    "hook_event_name": "PreToolUse",
    "tool_name": "Write",
    "tool_use_id": "toolu_01",
    "tool_input": {"file_path": "/repo/a.py", "content": "x = 1"},
}


class BoundaryProjectionTests(unittest.TestCase):
    HOSTILE_FAILURE_PAYLOAD = {
        "session_id": HostileString("hidden"),
        "cwd": "/repo",
        "tool_name": "Write",
        "tool_use_id": "call-1",
        "tool_input": {"file_path": HostileString("secret.py")},
        "error": "failed",
        "is_interrupt": 1,
        "duration_ms": True,
    }
    EXPECTED_FAILURE_PROJECTION = {
        "session_id": "",
        "cwd": "/repo",
        "tool_name": "Write",
        "tool_use_id": "call-1",
        "file_path": "",
        "error": "failed",
        "is_interrupt": False,
        "duration_ms": 0,
    }

    def test_failure_projection_accepts_only_exact_schema_types(self):
        projected = payloads.failure_payload(self.HOSTILE_FAILURE_PAYLOAD)

        self.assertEqual(projected, self.EXPECTED_FAILURE_PROJECTION)
        self.assertEqual(HostileString.calls, 0)

    def test_record_projection_rejects_hostile_containers_without_dispatch(self):
        HostileDict.calls = 0
        self.assertEqual(
            payloads.record_payload(HostileDict(PRE_TOOL_USE)),
            {
                "session_id": "",
                "cwd": "",
                "tool_name": "",
                "tool_use_id": "",
                "file_path": "",
                "edit_text": "",
            },
        )
        self.assertEqual(HostileDict.calls, 0)

        payload = dict(PRE_TOOL_USE)
        payload["tool_input"] = HostileDict(file_path="secret.py")
        self.assertEqual(payloads.record_payload(payload)["file_path"], "")
        self.assertEqual(HostileDict.calls, 0)

        self.assertEqual(record.run(HostileDict(PRE_TOOL_USE), {})["decision"], "block")
        self.assertEqual(HostileDict.calls, 0)

    def test_non_string_keys_are_filtered_before_field_lookup(self):
        key = CollidingKey()
        payload: dict[object, object] = {key: "hidden", "session_id": "safe"}
        CollidingKey.calls = 0
        self.assertEqual(payloads.session_id(payload), "safe")
        self.assertEqual(CollidingKey.calls, 0)

    def test_edit_text_list_requires_exact_strings(self):
        exact = {"tool_input": {"command": ["first", "second"]}}
        hostile = {"tool_input": {"command": ["first", HostileString("second")]}}
        self.assertEqual(payloads.record_payload(exact)["edit_text"], "first\nsecond")
        self.assertEqual(payloads.record_payload(hostile)["edit_text"], "")
        self.assertEqual(HostileString.calls, 0)


class SessionIdTests(unittest.TestCase):
    def test_reads_documented_session_id(self):
        self.assertEqual(payloads.session_id(PRE_TOOL_USE), "sess-1")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.session_id({}), "")


class CwdTests(unittest.TestCase):
    def test_reads_documented_cwd(self):
        self.assertEqual(payloads.cwd(PRE_TOOL_USE), "/repo")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.cwd({}), "")


class ToolNameTests(unittest.TestCase):
    def test_reads_documented_tool_name(self):
        self.assertEqual(payloads.tool_name(PRE_TOOL_USE), "Write")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.tool_name({}), "")


class ToolUseIdTests(unittest.TestCase):
    def test_reads_documented_tool_use_id_on_pretooluse(self):
        self.assertEqual(payloads.tool_use_id(PRE_TOOL_USE), "toolu_01")

    def test_absent_returns_empty_string(self):
        # because the plan exposes tool_use_id only where the event documents it
        self.assertEqual(payloads.tool_use_id({"tool_name": "Write"}), "")


class AgentTranscriptPathTests(unittest.TestCase):
    def test_reads_documented_subagent_transcript(self):
        # assumed because agent_transcript_path is not in the published docs, only plan-named
        payload = {
            "hook_event_name": "SubagentStop",
            "agent_transcript_path": "fixtures/agent-7.jsonl",
        }
        self.assertEqual(
            payloads.agent_transcript_path(payload), "fixtures/agent-7.jsonl"
        )

    def test_falls_back_to_common_transcript_path(self):
        # because transcript_path is documented as a common field on every hook event
        payload = {
            "hook_event_name": "SubagentStop",
            "transcript_path": "fixtures/main.jsonl",
        }
        self.assertEqual(payloads.agent_transcript_path(payload), "fixtures/main.jsonl")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.agent_transcript_path({}), "")


class PromptTests(unittest.TestCase):
    def test_reads_prompt_key(self):
        # assumed because the plan names this field prompt
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "refactor the loop"}
        self.assertEqual(payloads.prompt(payload), "refactor the loop")

    def test_reads_user_prompt_alias(self):
        # assumed because the published schema summary names this field user_prompt
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "user_prompt": "refactor the loop",
        }
        self.assertEqual(payloads.prompt(payload), "refactor the loop")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.prompt({}), "")


class SourceTests(unittest.TestCase):
    def test_reads_documented_sessionstart_source(self):
        payload = {"hook_event_name": "SessionStart", "source": "compact"}
        self.assertEqual(payloads.source(payload), "compact")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.source({}), "")


class FilePathAliasTests(unittest.TestCase):
    def test_reads_file_path_from_tool_input(self):
        self.assertEqual(payloads.file_path(PRE_TOOL_USE), "/repo/a.py")

    def test_tolerates_toolinput_camel_alias(self):
        # because pre_write.py accepts toolInput, this contract must agree
        payload = {"toolInput": {"file_path": "/repo/b.py"}}
        self.assertEqual(payloads.file_path(payload), "/repo/b.py")

    def test_tolerates_input_alias(self):
        payload = {"input": {"file_path": "/repo/c.py"}}
        self.assertEqual(payloads.file_path(payload), "/repo/c.py")

    def test_reads_path_key_inside_tool_input(self):
        # because some tools emit path rather than file_path, as pre_write.py accepts
        payload = {"tool_input": {"path": "/repo/d.py"}}
        self.assertEqual(payloads.file_path(payload), "/repo/d.py")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.file_path({}), "")

    def test_empty_tool_input_falls_through_to_next_alias(self):
        # because pre_write.py or-chains past an empty dict, this contract must agree
        payload = {"tool_input": {}, "input": {"file_path": "/repo/e.py"}}
        self.assertEqual(payloads.file_path(payload), "/repo/e.py")


class ErrorTests(unittest.TestCase):
    def test_reads_documented_failure_error(self):
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_use_id": "toolu_02",
            "error": "command not found",
        }
        self.assertEqual(payloads.error(payload), "command not found")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.error({}), "")


class IsInterruptTests(unittest.TestCase):
    def test_true_when_flag_set(self):
        # assumed because failure events are expected to signal a user interrupt
        payload = {"hook_event_name": "PostToolUseFailure", "is_interrupt": True}
        self.assertIs(payloads.is_interrupt(payload), True)

    def test_absent_returns_false(self):
        self.assertIs(payloads.is_interrupt({}), False)

    def test_string_false_does_not_coerce_to_true(self):
        self.assertIs(payloads.is_interrupt({"is_interrupt": "false"}), False)


class DurationMsTests(unittest.TestCase):
    def test_reads_documented_failure_duration(self):
        # assumed because failure events are expected to carry duration_ms
        payload = {"hook_event_name": "PostToolUseFailure", "duration_ms": 1250}
        self.assertEqual(payloads.duration_ms(payload), 1250)

    def test_absent_returns_zero(self):
        self.assertEqual(payloads.duration_ms({}), 0)

    def test_bool_does_not_coerce_to_one(self):
        # because bool is an int subclass, True must not return as 1
        self.assertEqual(payloads.duration_ms({"duration_ms": True}), 0)


class ToolCallsTests(unittest.TestCase):
    def test_reads_documented_posttoolbatch_array(self):
        # assumed because PostToolBatch is expected to carry a tool_calls array keyed by tool_use_id
        payload: dict[str, object] = {
            "hook_event_name": "PostToolBatch",
            "tool_calls": [
                {"tool_use_id": "toolu_01", "tool_name": "Write"},
                {"tool_use_id": "toolu_02", "tool_name": "Edit"},
            ],
        }
        self.assertEqual(
            payloads.tool_calls(payload),
            [
                {"tool_use_id": "toolu_01", "tool_name": "Write"},
                {"tool_use_id": "toolu_02", "tool_name": "Edit"},
            ],
        )

    def test_absent_returns_empty_list(self):
        self.assertEqual(payloads.tool_calls({}), [])


class TaskIdTests(unittest.TestCase):
    def test_reads_documented_task_id(self):
        payload = {"hook_event_name": "TaskCompleted", "task_id": "task-9"}
        self.assertEqual(payloads.task_id(payload), "task-9")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.task_id({}), "")


class TaskSubjectTests(unittest.TestCase):
    def test_reads_task_subject(self):
        # assumed because the plan corrects this field to task_subject over task_result
        payload = {
            "hook_event_name": "TaskCompleted",
            "task_subject": "wire the stop gate",
        }
        self.assertEqual(payloads.task_subject(payload), "wire the stop gate")

    def test_reads_task_name_alias(self):
        # assumed because the published summary names task_name, so it is carried as an alias
        payload = {
            "hook_event_name": "TaskCompleted",
            "task_name": "wire the stop gate",
        }
        self.assertEqual(payloads.task_subject(payload), "wire the stop gate")

    def test_absent_returns_empty_string(self):
        self.assertEqual(payloads.task_subject({}), "")


class PatchFilePathsTests(unittest.TestCase):
    def test_reads_add_and_update_headers(self):
        patch = "*** Add File: src/new.py\n+print(1)\n*** Update File: src/old.py\n+print(2)\n"
        self.assertEqual(payloads.patch_file_paths(patch), ("src/new.py", "src/old.py"))

    def test_reads_delete_header(self):
        patch = "*** Delete File: src/gone.py\n"
        self.assertEqual(payloads.patch_file_paths(patch), ("src/gone.py",))

    def test_reads_move_to_destination_alongside_its_update_header(self):
        patch = "*** Update File: src/old.py\n*** Move to: src/new.py\n@@\n-x = 1\n+x = 2\n"
        self.assertEqual(payloads.patch_file_paths(patch), ("src/old.py", "src/new.py"))

    def test_absent_returns_empty_tuple(self):
        self.assertEqual(payloads.patch_file_paths("no headers here"), ())


if __name__ == "__main__":
    unittest.main()
