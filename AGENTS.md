# Harbor instructions

Avoid duplicate session entries. Reuse an open unused session; empty sessions are temporary and must not appear as saved history. Preserve conversations that contain user messages.

Classify user intent before starting a development workflow. Questions, trivia, explanations, and brainstorming are discussion, even when they mention this project. Answer directly; inspect or research when needed. Do not edit files, write work logs, or run testing agents solely for discussion. Explicit requests to implement or fix authorize project work. If ambiguous, clarify before changing files. Questions during authorized work do not cancel that work by themselves.

For project changes, read docs/WORKFLOW.md. Keep application tools in Linux/WSL. Preserve native Codex approvals, login, and session history; never edit Codex's internal database tables or fabricate user turns. Use temporary CODEX_HOME, CODEX_WORKSPACE_DATA, and CODEX_WORKSPACE_SOCKET values for integration tests. Never use live conversations as destructive test fixtures.

Project testing skills are .agents/skills/black-box-test/SKILL.md and .agents/skills/change-review/SKILL.md. Read them when their review is needed. WORKLOG.md is the established project record; README.md documents user behavior. Workspace mode instructions live in policies/*.md and are loaded when a conversation terminal starts.

For authorized implementation work on this project, follow the Automatic GitHub workflow in policies/project.md: private repository setup when needed, scoped commits after checks, and pushes are authorized by default.

For installation, updates, packaging, another-computer setup, or a missing Trivia / Projects sidebar, read docs/INSTALLATION.md first and carry out the applicable steps. The sidebar belongs to this custom app, launched with `harbor` (`codex-workspace` remains an alias), not plain `codex`. Keep the complete app installable from this repository; do not rely on `/home/rokdbest/bin` or other machine-local launchers. Preserve both installed-package and direct-checkout execution. Include all runtime modules and mode policies when packaging. Record setup/verification results in WORKLOG.md and push authorized project changes to the existing remote.
