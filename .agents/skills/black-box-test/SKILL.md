---
name: black-box-test
description: Test Harbor user behavior independently from implementation explanations when behavioral validation or an independent review is requested. Not for trivia or general discussion.
---

Receive intended behavior, user scenarios, launch instructions, and isolated fixtures. If already exposed to implementation or developer reasoning, disclose that limitation; do not label the review blind. Do not read source, diffs, or WORKLOG.md during an independent pass. Report missing requirements rather than inventing expected behavior.

Exercise relevant user paths: new/open/resume, mode selection, context-menu actions, cancellation, narrow terminal layouts, persistence across reopen, and recovery. Choose cases based on the requested feature; do not run all lifecycle actions for every small change. Never close, archive, delete, or modify real user conversations. Use an isolated Codex home, workspace data directory, and tmux socket. Do not send model prompts without task authorization for model execution.

Report each finding with reproduction steps, expected/actual behavior, severity, and evidence. Separate confirmed defects from unclear requirements. Do not fix code during this pass. For a four-perspective review, separate normal use, edge cases, recovery, and usability without sharing conclusions before independent reports are complete.
