---
name: change-review
description: Review Codex Workspace implementation changes against requirements, session invariants, and regression risks. Use for development-aware verification, not casual project discussion.
---

Read requirements, relevant implementation, and test evidence. Trace each material requirement to observable behavior and check failure paths. Prioritize native approval preservation, session identity/persistence, draft-to-thread mapping, subprocess and socket cleanup, shell quoting, and changes that could disturb live work.

Use isolated CODEX_HOME, CODEX_WORKSPACE_DATA, and CODEX_WORKSPACE_SOCKET values. Run targeted checks and the relevant integration suite; avoid tests that merely repeat the implementation or match prose. For mode changes, check that UI labels, persisted preferences, and delivered instructions agree for new and resumed sessions. Confirm prior instructions are preserved and mode changes cannot silently interrupt open work.

Report concrete findings with location, trigger, expected/actual behavior, and a reproducer. State test limits, including whether actual model behavior or Windows GUI interactions were exercised. Recheck confirmed fixes. This review is development-aware; do not claim black-box independence.
