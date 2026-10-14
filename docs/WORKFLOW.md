# Development workflow

Apply this workflow to authorized project changes, not to casual questions or brainstorming. Discussion remains discussion in every UI mode. Resolve unclear intent before edits.

1. Establish the requested behavior and practical acceptance checks. Inspect relevant code and project rules.
2. Implement within scope. Preserve existing history, credentials, permissions, and active conversation processes.
3. Verify changed behavior and affected integrations. Run `python3 -m unittest discover -s tests -v` for changes to session lifecycle, transport, or terminal actions. Integration tests require local Unix sockets and may need execution outside the sandbox. Tests must use isolated data and must not generate model responses merely to verify plumbing.
4. For substantial behavior changes, evaluate both perspectives: independent behavior testing using `.agents/skills/black-box-test/SKILL.md`, and development-aware review using `.agents/skills/change-review/SKILL.md`. For small changes, focused checks suffice. If separate agents are requested, give independent testers a fresh context with only requirements, task scenarios, launch instructions, and isolated fixtures. Do not pass developer discussions, diffs, or expected findings. Shared filesystem access is not a security boundary; report any exposure to implementation. No fixed four-agent requirement. A four-perspective review may cover normal tasks, edge cases, recovery, and usability when warranted and authorized.
5. Reproduce findings, fix confirmed defects, and rerun affected scenarios. Record unverified behavior honestly.
6. Update README.md for user-visible changes and WORKLOG.md for meaningful decisions, test evidence, and remaining issues. Reload only support UI when appropriate; never restart working conversations to apply instructions silently.

Mode files guide behavior rather than enforce read-only access. New or reopened terminals get the selected mode. Existing running terminals keep their current instructions. A mode change must not interrupt work or imply that a running agent has already adopted it.
