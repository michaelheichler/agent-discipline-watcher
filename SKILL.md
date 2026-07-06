# Agent Discipline Watcher

Use this skill when agent output or edited files need the combined discipline gate.

This skill replaces punctuation-discipline, english-for-agents, clean-coder-discipline, and professional-agent-helper.

Runtime shape:

1. One SessionStart policy prompt with the Professional Agent Helper charter and the watcher reminder.
2. One scanner for fast punctuation, prose, and clean-code regex checks.
3. One ledger.
4. One UserPromptSubmit refresher with PAH REFLEX and correction NUDGE.
5. One Stop-time PAH tell gate for empty validators and flattery.
6. One Bash `git commit` guard over staged ACM files.
7. One Stop-time model jury for touched prose and code files when models can load.
8. One compact final report with a local full report path.
9. One Pi extension.

Codex note: `install.sh` writes the global Codex hook config, but Codex may still require `/hooks` approval after hook command changes. Review and trust the hooks there before relying on them.

Fix reported files before ending the task.
