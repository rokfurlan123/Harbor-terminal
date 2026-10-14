# Codex Workspace

A Linux terminal app with the real Codex conversation on the left and a Trivia / Projects session tree on the right. Uses your installed Codex, its existing login, and its own session storage. No Python packages or API key setup required.

## Run

```bash
/home/rokdbest/bin/codex-workspace
```

Or run `python3 /home/rokdbest/codex-workspace/workspace.py` in a Linux/WSL terminal. Use a terminal at least 100 columns wide for comfortable viewing. The sidebar uses 33% of the window width and adjusts when the terminal is resized.

Every ordinary launch creates an independent workspace window with its own panes, focus, temporary sessions, and app-server connection. Saved Codex history and login remain shared. Select different conversations in different windows; opening the same saved conversation in both still refers to the same history.

For a workspace you want to reconnect to, use `codex-workspace --instance work` (names accept 1–16 letters, digits, hyphens or underscores). Repeating that command deliberately attaches to the same workspace. Automatically generated instance names and reconnect commands appear on the welcome screen. Use `codex-workspace --instance legacy` to reconnect to the workspace that was running before this change.

New instance settings live under `~/.local/share/codex-workspace/instances/<name>/`. Each starts with a snapshot of the original workspace's preferences, modes, and project assignments, then keeps its own settings. Empty draft sessions are never copied. `CODEX_WORKSPACE_SOCKET` explicitly selects an existing/custom socket and retains the previous launcher behavior for automation; unset it for automatic new instances.

## Controls

| Key | Action |
| --- | --- |
| F2 | Native Codex warnings (with the conversation focused) |
| F6 | Focus the sidebar |
| F3 | Focus the conversation |
| F4 | Detach the workspace; open conversations stay running |
| Up / Down / j / k | Select a tree row |
| Click / Enter | Expand or collapse a folder, or open a session |
| Left / Right | Collapse / expand; Left on a session selects its parent |
| Right-click in sidebar | Select the clicked session and show all actions plus copy options |
| b / Click Start blank session | Immediately open a fresh session in your Linux home folder, using Auto mode |
| n | New conversation under the selected category/project; choose mode and, when relevant, project folder |
| m | Change a closed session's mode (also in the right-click menu) |
| c | Close its terminal after confirmation; retain saved history |
| e | Rename the saved conversation |
| a | Archive a closed conversation, or restore an archived one |
| v | Switch between saved and archived conversations |
| / | Search names and project paths; empty search shows all |
| r | Refresh / reconnect |
| D | Permanently delete an archived conversation after typing `yes` |
| q | Detach from the sidebar |

In text prompts, Ctrl-U clears the field and Escape cancels. Codex's own shortcuts and approval interface remain available in the conversation pane. For terminal copy/paste, Shift bypasses tmux mouse handling in many terminals.

The right-click menu includes every footer action and copies the selected session's reference (name, ID, project), ID alone, project path, or a shell-quoted Linux resume command. Drafts need saved history before a resume command is available. Copy uses tmux's terminal clipboard integration (OSC 52), supported by Windows Terminal; other terminals may require clipboard permission. Use arrows and Enter or click an item; Escape dismisses the menu. Short terminals scroll the menu with the arrow keys or mouse wheel. Close and delete retain their confirmation prompts.

## Trivia, projects, and AI modes

Click **Start blank session** at the top of the sidebar, or press **F6**, then **b**. This opens an empty Codex prompt, or returns to the existing unused session, without asking for a name, mode, or project. It appears under Trivia as “New session” with an Unsaved status; you can rename it with `e`. Repeated clicks reuse it until you send a message. Closing an unused session discards its placeholder. A newly created blank uses Auto mode and your Linux home folder regardless of the selected project, search, or archived view. Your normal Codex configuration and applicable instructions still apply. Use `n` for the existing guided creation flow.

Trivia is the top-level category for general conversations. Projects groups other sessions by their existing working folder; expand a project to see its sessions. Select Trivia and press `n` for a new general conversation. Select Projects and press `n` to choose a project folder, or select an existing project to reuse its folder. On first setup, the app lists immediate Linux home subfolders that contain a README, Git metadata, or a supported project manifest, including projects with no sessions. To add a folder elsewhere, select Projects and create a session in it; it is remembered thereafter. This is a folder registry, not a recursive scan or a change to project files. Search finds matching names and paths even inside collapsed branches. The archived view uses the same tree. Expansion preferences survive reopening. Top-level headings use cyan, project headings use yellow, and session titles use the normal text color. Each child level adds one column of indentation. App projects show a compact `[sd]` (Software development) tag beneath their names. Project tags are stored separately from AI modes in `preferences.json` under `project_tags`; their folder paths remain available through right-click → Copy project path.

New sessions under Trivia default to Conversation; sessions under Projects default to Project work. At the mode prompt, use `a`, `c`, or `p`; Enter keeps the displayed default and Escape cancels.

| Mode | Behavior |
| --- | --- |
| Auto | Infer discussion versus project work from each request. |
| Conversation | Default to explanations, learning, trivia, and brainstorming; skip project edits, logs, and testing workflows unless explicitly requested. New sessions use your Linux home folder. |
| Project work | Use the selected project's instructions and workflow for implementation requests. Ordinary questions still receive direct answers without initiating edits. |

Explicit user intent takes precedence over the default: “just discussing” stays discussion; “implement this” authorizes the requested work even in Conversation mode. Modes are behavioral guidance, not sandbox or permission settings. They do not automatically launch testing agents.

Explicit content-reviewed project assignments take priority over folder/mode grouping. They organize the tree without changing a session’s original working folder or AI mode; see [session organization](docs/SESSION_ORGANIZATION.md) for the reviewed assignments. Without an explicit assignment, existing sessions default to Auto. Conversation-mode sessions and Auto sessions whose working folder is your Linux home appear under Trivia; all others appear under their project folder. Changing a closed session's mode may therefore move it between categories. History and project files are not moved.

Mode instructions take effect when a conversation terminal starts or resumes. Close its terminal before changing mode; open work is never restarted automatically. Older running terminals show “Reopen” beside their mode until reopened. The copied native `codex resume` command runs outside the workspace and does not explicitly apply its selected mode; reopen through this app to apply the latest mode policy.

## Instruction files

- `policies/auto.md`, `policies/conversation.md`, `policies/project.md`: editable instructions for workspace sessions, applied on their next launch.
- `AGENTS.md`: rules for developing Codex Workspace itself, including discussion versus implementation.
- `docs/WORKFLOW.md`: development stages and proportionate testing expectations.
- `.agents/skills/black-box-test/SKILL.md`: independent behavioral testing procedure.
- `.agents/skills/change-review/SKILL.md`: development-aware review procedure.
- `WORKLOG.md`: decisions, evidence, and unresolved issues.

These project rules/skills belong to Codex Workspace. Other projects use their own applicable instructions and skills; this update does not create files in every project or change global Codex settings. The testing procedures distinguish fresh-context independent review from code-aware review; installing a skill alone does not schedule or isolate agents.

## What persists

Codex owns the conversation history under `$CODEX_HOME` (normally `~/.codex`). The workspace reads and manages this history through the installed Codex app-server protocol; it never edits Codex database tables or copies credentials. Existing CLI, editor, and app-server conversations appear automatically, including conversations started outside this app.

New empty sessions are temporary: they appear only while their terminal is open and are excluded from saved-history counts. Creating another session in the same context reuses the open unused one. Closing it, or restarting WSL, discards its placeholder. Once you send a message, Codex owns the saved conversation and reopening uses Codex resume. Local draft records coordinate terminal startup and native thread identity; they are not saved conversation history. Older explicitly named drafts remain available.

Workspace preferences and connection diagnostics live in `~/.local/share/codex-workspace/`. Its `drafts.sqlite` also stores per-session modes and explicit project assignments in separate tables, retained when a draft becomes recorded history. Tree expansion and the project-folder registry are stored in `preferences.json`. Project code stays in its original project folder.

Switching conversations keeps the same terminal process alive. Detaching or closing the terminal window leaves the tmux workspace running while Linux/WSL stays alive. After a computer/WSL restart, run the app and select a saved conversation to resume it. An interrupted command is not automatically restarted. Closing a conversation terminal may interrupt its current work and requires confirmation; it does not delete history.

Statuses distinguish **Saved**, **Open**, **Viewing**, and **Exited**. These describe terminal state, not whether the AI has verified a task. The catalog connection may not see execution status from separate Codex processes. There are no scheduled AI jobs in this first version.

Avoid opening the same conversation simultaneously in this app and another Codex window. Switching within this app reuses its existing pane.

## Implementation and checks

- Python 3.12.3: `/usr/bin/python3` (standard library only).
- tmux 3.4: `/usr/bin/tmux`, isolated socket named `codex-workspace-<instance>` (`codex-workspace` for legacy); does not change your normal tmux configuration.
- Codex CLI 0.156.1: `/home/rokdbest/.nvm/versions/node/v24.16.0/bin/codex`.
- Session protocol: [official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server).
- Model execution and approvals remain inside native Codex. The sidebar does not submit model prompts or bypass permission checks.

```bash
cd /home/rokdbest/codex-workspace
python3 workspace.py doctor
python3 -m unittest discover -s tests -v
```

Tests use a temporary Codex home and separate tmux sockets. They cover temporary-session reuse/discard, native-ID handoff, legacy draft persistence and rename, recorded history resume/archive/restore/delete using a synthetic rollout fixture, terminal switching, native login-screen startup, support-process crash recovery, and exact matching of new-thread responses across fragmented WebSocket frames. They do not generate model responses.

A separate manual smoke check has verified native create and close/reopen with the existing login, correct sidebar linking, and the ready prompt. Sending a first real message and receiving model output has not been tested in this workspace yet.

The catalog and native terminals share one Codex app server. `transport.py` implements its WebSocket-over-Unix connection; `bridge.py` links the matching native `thread/start` response to a draft. New and resumed terminals use this bridge to append mode instructions to `thread/start` and `thread/resume`, preserving existing request/configuration developer instructions. It leaves turn requests and permission settings intact and does not submit prompts. The supported instruction field is documented in the [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

The app-server protocol is experimental. `doctor` checks the installed integration. If the sidebar encounters a connection error, press `r`; diagnostics are in `app-server.log`. Normal terminal sessions continue independently of the catalog connection. Reconnecting with the same `--instance` repairs crashed support panes; press `r` to reconnect the sidebar. A crashed shared service interrupts its attached conversations; reopen them afterward.

Detaching keeps processes running and uses RAM. Close conversation panes with `c` when finished. To stop the entire workspace after saving work, run `tmux -L codex-workspace-<instance> kill-server` (or `tmux -L codex-workspace kill-server` for legacy); this interrupts open work but retains recorded conversation history and local drafts.

Project display names can be set in the workspace preferences `project_names` mapping, keyed by project folder. Names appear in Projects and are included in search.
