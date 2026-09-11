STALE_WATCHER_RUN_SH = "/stale/agent-discipline-watcher/hooks/run.sh"
SKILL_DIR = "/opt/adw-checkout"

WIRED_EVENTS = frozenset({
    "ConfigChange",
    "InstructionsLoaded",
    "PostToolBatch",
    "PostToolUse",
    "PostToolUseFailure",
    "PreCompact",
    "PreToolUse",
    "SessionEnd",
    "SessionStart",
    "Stop",
    "SubagentStop",
    "TaskCompleted",
    "UserPromptSubmit",
})

CLAUDE_SETTINGS = {
    "hooks": {
        "Stop": [
            {
                "hooks": [
                    {"type": "command", "command": "python punctuation-discipline/hooks/stop.py"},
                    {"type": "command", "command": "python /x/unrelated-stop.py"},
                ]
            }
        ],
        "PostToolUse": [
            {
                "hooks": [
                    {"type": "command", "command": "python english-for-agents/hooks/post.py"},
                    {
                        "type": "command",
                        "command": "python /x/unrelated-search-skill/hooks/method_inject.py",
                    },
                ]
            }
        ],
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/prompt_inject.py",
                    }
                ]
            }
        ],
    }
}

UNCLE_BOBS_CC_SETTINGS = {
    "model": "claude-opus-4",
    "env": {"SOME_FLAG": "1"},
    "statusLine": {"type": "command", "command": "echo hi"},
    "permissions": {"allow": ["Bash(ls:*)"], "deny": []},
    "hooks": {
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/session_start.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/punct_session_start.py"
                        ),
                    },
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/gate.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/punct_gate.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/record.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/punct_record.py"
                        ),
                    },
                    {"type": "command", "command": "python /x/unrelated-stop.py"},
                ]
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit|NotebookEdit|apply_patch",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/pre_write.py"
                        ),
                    },
                    {
                        "type": "command",
                        "command": "/stale/agent-discipline-watcher/hooks/run.sh PreToolUse",
                    },
                ],
            },
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "/x/uncle-bobs-cc/hooks/run.sh "
                            "/x/uncle-bobs-cc/hooks/pre_commit_hook.py"
                        ),
                    }
                ],
            },
        ],
    },
}

CODEX_CONFIG = """
[hooks]
Stop = [{ command = "python professional-agent-helper/hooks/stop.py" }, { command = "python /x/unrelated-inline.py" }]
SessionStart = [{ command = "python punctuation-discipline/hooks/start.py" }]
UserPromptSubmit = [{ command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/prompt_inject.py" }]

[[hooks.UserPromptSubmit]]

[[hooks.UserPromptSubmit]]

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "python /x/unrelated-search-skill/hooks/prompt_inject.py"

# >>> agent-discipline-watcher >>>
[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/tmp/agent-discipline-watcher/hooks/run.sh Stop"

[mcp_servers.unrelated-search-skill]
command = "/x/unrelated-runtime/.venv/bin/python"
args = ["/x/unrelated-search-skill/server/mcp_server.py"]

[mcp_servers.unrelated-context-skill]
command = "/x/unrelated-context-skill/bin/unrelated-context-skill"
args = ["serve", "--config", "/x/unrelated-context-skill/config.toml"]
# <<< agent-discipline-watcher <<<

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "python /x/unrelated-stop.py"
"""

CODEX_CONFIG_UNCLE_BOBS_CC = """
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/session_start.py"
[[hooks.SessionStart.hooks]]
type = "command"
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/punct_session_start.py"

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "/x/uncle-bobs-cc/hooks/run.sh /x/uncle-bobs-cc/hooks/punct_gate.py"
[[hooks.Stop.hooks]]
type = "command"
command = "python /x/unrelated-stop.py"
"""

CODEX_CONFIG_TRAILING_TABLES = """
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/session_start.py"

[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/gate.py"

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "/x/professional-agent-helper/hooks/run.sh /x/professional-agent-helper/hooks/prompt_inject.py"

[[hooks.state.trusted_projects]]
path = "/x/project1"
trust = "trusted"

[[hooks.state.trusted_projects]]
path = "/x/project2"
trust = "trusted"

[projects."/x/project1"]
trust_level = "trusted"

[tui.model_availability_nux]
shown = true

[mcp_servers.alpha]
command = "alpha-bin"
args = ["serve"]

[mcp_servers.alpha.http_headers]
Authorization = "Bearer alpha"

[mcp_servers.beta]
command = "beta-bin"

[mcp_servers.gamma]
command = "gamma-bin"
"""

CODEX_CONFIG_NEW_EVENT_INLINE_ARRAYS = (
    "\n[hooks]\n"
    'SubagentStop = [{ command = "python professional-agent-helper/hooks/sub.py" },'
    ' { command = "python /x/unrelated-subagent.py" }]\n'
    'PostToolBatch = [{ command = "python punctuation-discipline/hooks/batch.py" }]\n'
    'TaskCompleted = [{ command = "python english-for-agents/hooks/task.py" }]\n'
    'PostToolUseFailure = [{ command = "python clean-coder-discipline/hooks/fail.py" }]\n'
    'InstructionsLoaded = [{ command = "python uncle-bobs-cc/hooks/loaded.py" }]\n'
    f'ConfigChange = [{{ command = "{STALE_WATCHER_RUN_SH} ConfigChange" }},'
    ' { command = "python /x/unrelated-config.py" }]\n'
)

UNRELATED_SURVIVORS = ("unrelated-search-skill", "unrelated-context-skill", "unrelated-third-skill")
UNRELATED_PACKAGE_SETTINGS = {
    "hooks": {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {"type": "command", "command": "python /x/unrelated-search-skill/hooks/skill_gate.py"},
                    {"type": "command", "command": "/x/unrelated-context-skill/bin/unrelated-context-skill serve"},
                ]
            }
        ],
        "PostToolUse": [
            {
                "hooks": [
                    {"type": "command", "command": "python /x/unrelated-third-skill/hooks/post.py"},
                    {"type": "command", "command": "python punctuation-discipline/hooks/post.py"},
                ]
            }
        ],
    }
}

ARBITRARY_EVENT_SETTINGS = {
    "hooks": {
        "SubagentStop": [
            {
                "hooks": [
                    {"type": "command", "command": f"{STALE_WATCHER_RUN_SH} SubagentStop"},
                    {"type": "command", "command": "python /x/unrelated-subagent.py"},
                ]
            }
        ],
        "ConfigChange": [
            {
                "hooks": [
                    {"type": "command", "command": "python punctuation-discipline/hooks/config.py"},
                ]
            }
        ],
    }
}
