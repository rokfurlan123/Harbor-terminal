# Harbor

A Linux/WSL AI workspace with local and remote model connections, the real Codex conversation on the left and a Trivia / Projects session tree on the right. Uses your installed Codex, its existing login, and its own session storage. The app uses Python's standard library; external model providers use their own authentication.

## Install on another computer (Linux/WSL)

AI agents: follow [installation and maintenance instructions](docs/INSTALLATION.md)
for setup, updates, missing-sidebar diagnosis, and package verification.

The complete Trivia / Projects sidebar is included in this repository and Python
package. Install it on each computer; running plain `codex` does not launch it.
Requires Python 3.10+, tmux, and an installed, signed-in Codex CLI on the Linux PATH.
Desktop launchers with a minimal PATH also discover Codex in `~/.local/bin` or
`~/bin`. `CODEX_WORKSPACE_CODEX` overrides automatic discovery.
On Ubuntu/WSL, install the packaging prerequisites if needed:

```bash
sudo apt-get install python3-venv pipx tmux git
```

Clone this private repository using your GitHub account, then install:

```bash
git clone git@github.com:rokfurlan123/codex-workspace.git
cd codex-workspace
pipx install .
pipx ensurepath
```

Open a new Linux/WSL terminal, then run:

```bash
harbor doctor
harbor
```

The installed command includes the sidebar, transport, native-session bridge, and
all three mode policies. It works outside the checkout and has no Python runtime
dependencies. Codex and tmux remain separately installed Linux tools. Sign in to
Codex separately on each computer. Project folders, conversations, credentials,
and local preferences are not bundled or synced by installing the app.

To upgrade from Codex Workspace, follow [the Harbor migration guide](docs/INSTALLATION.md#upgrade-codex-workspace-to-harbor). It preserves conversations and preferences; the old command remains an alias.

To build a distributable wheel and source archive:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

The files in `dist/` can be copied to another Linux/WSL computer and installed
with `pipx install /path/to/harbor-0.2.0-py3-none-any.whl`.
No files in your Windows installation are modified by these commands.

## Run from this checkout

```bash
harbor
```

Or run `python3 /home/rokdbest/codex-workspace/workspace.py` in a Linux/WSL terminal. Use a terminal at least 100 columns wide for comfortable viewing. The sidebar uses 33% of the window width and adjusts when the terminal is resized.

Every ordinary launch creates an independent workspace window with its own panes, focus, temporary sessions, and app-server connection. Saved Codex history and login remain shared. Select different conversations in different windows; opening the same saved conversation in both still refers to the same history.

For a workspace you want to reconnect to, use `harbor --instance work` (names accept 1–16 letters, digits, hyphens or underscores). Repeating that command deliberately attaches to the same workspace. Automatically generated instance names and reconnect commands appear on the welcome screen. Use `harbor --instance legacy` to reconnect to the workspace that was running before this change.

New instance settings live under `<data-directory>/instances/<name>/`. Each starts with a snapshot of the original workspace's preferences, modes, and project assignments, then keeps its own settings. Empty draft sessions are never copied. `CODEX_WORKSPACE_SOCKET` explicitly selects an existing/custom socket and retains the previous launcher behavior for automation; unset it for automatic new instances.

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
| + / Click [+] beside a project | Start a session directly in that project, without setup prompts |
| C | Manage model connections; list, load, unload, or download Ollama models |
| M | Choose the selected session’s model; on a folder, choose the default for new sessions |
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

## Models and quick project sessions

Click `[+]` at the right edge of a project heading, or select the project and
press `+`, to open a new session directly in its folder using Project work mode.
There are no name or folder prompts. An open unused session with the same folder,
mode, and model is reused. Once it has messages, another click creates a fresh
session. This also works for projects with no saved conversations.

Click the **M Model** line at the top of the sidebar to choose the model for new
sessions. Use arrows and Enter or click a model; Escape cancels. The picker lists
the Codex model catalog, models installed in local Ollama, and named model connections, including Qwen on another computer.
The default is remembered per workspace instance and applies to blank, quick
project, and guided new sessions. Catalog entries do not guarantee account access.
Ollama must be installed and running for local discovery and execution; models
are not downloaded automatically.

To change an existing conversation, select it and press `M` (or right-click →
Change session model), even while its terminal is open. The choice is saved for
its next launch; the picker never interrupts or restarts running work. Open
terminals keep their current model until you close and reopen them. The sidebar
labels their saved choice **Next open**, and the picker confirms **Saved for next
reopen**. Saved history is retained. **Codex default** restores the configured
model/provider on next launch. These are launch preferences, not live telemetry
of changes made through native Codex controls. The right-click menu also lets you
change the default for new sessions while a conversation is selected.

Model selection uses native app-server start/resume fields, keeping the Codex
approval interface and history. Local model response quality and tool support
depend on the installed model and Ollama version. Integration checks verify
selection and native startup without submitting model prompts.

## Model connections and remote Qwen

Press **C** in the sidebar or choose **Connections / manage models** in the
right-click menu. Add a connection, list its models, and select one with **M**.
The connection ID appears beside the model so two servers with the same model
name are distinguishable. Switching a saved conversation requires closing its
terminal first; running conversations and their tunnels are not changed.

Supported connections:

- **Local Ollama**: automatically discovered; built-in connection ID `local`.
- **Ollama over SSH**: authenticated forwarding to the other machine's loopback
  port. Harbor opens and closes the tunnel with the operation or conversation.
- **Direct Ollama**: loopback HTTP or an HTTPS endpoint you configure.
- **Responses API**: a compatible server, with an optional API-key environment
  variable name. Chat-Completions-only servers are not supported by native Codex.

Examples (run on the PC that will use the remote model):

```bash
# First verify SSH host identity and login normally.
ssh rokdbest@100.124.226.26 true
harbor connections add laptop --kind ssh --ssh rokdbest@100.124.226.26
harbor connections test laptop
harbor models list --connection laptop
harbor models use local-qwen --connection laptop
harbor
```

Our Qwen host is `strawberry-laptop-linux` (100.124.226.26); its SSH policy
currently permits only `strawberry` (100.89.111.39), as `rokdbest`. Another PC
needs its own authorized Tailscale SSH access before this works. The app never
changes network ACLs or exposes Ollama publicly. The old Local AI web app and
its access key are separate: Harbor uses SSH to reach Ollama, not that web API.

```bash
harbor connections add studio --kind responses --url https://models.example.com/v1 --key-env MODEL_API_KEY --models my-model
harbor connections list
harbor models load local-qwen --connection local
harbor models unload local-qwen --connection local
harbor models pull qwen3:8b --connection local
harbor models default
```

Set API keys outside Harbor before launching it; only the environment-variable
name is stored. Start a fresh workspace after changing authentication variables
so its app server inherits them. SSH uses your normal Linux SSH configuration,
strict host-key checking, and noninteractive authentication. Complete any first
login/host-key check in a terminal; Harbor does not collect passwords.

Load retains a model for ten minutes; unload releases its memory. Download can
use substantial disk/network resources. The UI asks for confirmation for these
operations; CLI commands perform the requested operation directly. Unloading a
shared remote model can affect other users. No models are downloaded on startup.

Connections are saved privately in `connections.json` in the base data directory
and shared by Harbor instances on that machine. CLI `models use` writes the
current data directory's default; for an already-open instance, use its **M**
picker. Removed connections never silently fall back to a cloud provider. API
catalog discovery is not proof of model/tool compatibility. Explicit model IDs
for Responses providers are listed as configured, without claiming a live test.

See [installation and other-PC instructions](docs/INSTALLATION.md) for setup,
troubleshooting, package migration, and the limits of verification.

## Trivia, projects, and AI modes

The sidebar has three peer sections: **Trivia**, **Projects**, and **Misc**.
Misc contains **Tailscale** and **Local models → Qwen**. These are conversation
topics, independent of project folders and the model used to answer a session.
Putting a conversation under Qwen does not switch its AI model.

Select a topic and press `+` (or click `[+]`) for an Auto-mode session in your
Linux home folder. `n` lets you name it and choose a mode. An unused session is
reused only within the same topic. The global blank-session button still starts
outside topics. Select a conversation and press `g`, or use the right-click
menu, to move it to Tailscale, Qwen, Local models, or Misc; `r` in that prompt
restores its original Trivia/Projects grouping. Moving a conversation preserves
its history, working folder, model, mode, and running terminal.

Topic assignments live in the workspace's `session_topics` metadata table,
survive archive/restore and native draft-ID binding, and are removed on deletion.
Search includes ancestor topic names; Left navigates to the immediate parent.
As with other workspace preferences, assignments belong to each instance;
new instances inherit the base workspace's assignments.

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
- `AGENTS.md`: rules for developing Harbor itself, including discussion versus implementation.
- `docs/WORKFLOW.md`: development stages and proportionate testing expectations.
- `.agents/skills/black-box-test/SKILL.md`: independent behavioral testing procedure.
- `.agents/skills/change-review/SKILL.md`: development-aware review procedure.
- `WORKLOG.md`: decisions, evidence, and unresolved issues.

These project rules/skills belong to Harbor. Other projects use their own applicable instructions and skills; this update does not create files in every project or change global Codex settings. The testing procedures distinguish fresh-context independent review from code-aware review; installing a skill alone does not schedule or isolate agents.

## Automatic GitHub repositories and commits

When you ask a workspace session to create or implement a project, it is instructed to set up a private GitHub repository when needed, commit completed changes after appropriate checks, and push them. Existing projects retain their intended remote and branch conventions. Discussion does not trigger Git operations, and explicit instructions such as “keep this local” override the default. Changes outside the task are not included in commits.

This workflow applies in Auto, Conversation, and Project work modes. It is agent guidance, not a background Git service: the agent performs the work during your task and reports the repository, commit, and push result. GitHub login and native command approvals remain required. New or reopened conversation terminals load the policy; already running conversations must be reopened when convenient to receive it.

Install GitHub CLI (`gh`) in Linux/WSL and complete the one-time browser login:

```bash
gh auth login --hostname github.com --git-protocol ssh --web --skip-ssh-key
gh auth status
```

`--skip-ssh-key` retains the existing GitHub SSH key setup. If you have no working GitHub SSH key, configure one or use HTTPS instead. Authentication failures leave local work intact and are reported as blockers. Repository names default to the project folder name in the authenticated personal account; name collisions with unrelated repositories require resolution.

## What persists

Codex owns the conversation history under `$CODEX_HOME` (normally `~/.codex`). The workspace reads and manages this history through the installed Codex app-server protocol; it never edits Codex database tables or copies credentials. Existing CLI, editor, and app-server conversations appear automatically, including conversations started outside this app.

New empty sessions are temporary: they appear only while their terminal is open and are excluded from saved-history counts. Creating another session in the same context reuses the open unused one. Closing it, or restarting WSL, discards its placeholder. Once you send a message, Codex owns the saved conversation and reopening uses Codex resume. Local draft records coordinate terminal startup and native thread identity; they are not saved conversation history. Older explicitly named drafts remain available.

Harbor uses `~/.local/share/harbor/` for new installations. Existing installations automatically keep `~/.local/share/codex-workspace/` to preserve settings and instance paths. Preferences and connection diagnostics live there. Its `drafts.sqlite` also stores per-session modes and explicit project assignments in separate tables, retained when a draft becomes recorded history. Tree expansion and the project-folder registry are stored in `preferences.json`. Project code stays in its original project folder.

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

See WORKLOG.md for the latest native launch and model execution evidence and its limits.

The catalog and native terminals share one Codex app server. `transport.py` implements its WebSocket-over-Unix connection; `bridge.py` links the matching native `thread/start` response to a draft. New and resumed terminals use this bridge to append mode instructions to `thread/start` and `thread/resume`, preserving existing request/configuration developer instructions. It leaves turn requests and permission settings intact and does not submit prompts. The supported instruction field is documented in the [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

The app-server protocol is experimental. `doctor` checks the installed integration. If the sidebar encounters a connection error, press `r`; diagnostics are in `app-server.log`. Normal terminal sessions continue independently of the catalog connection. Reconnecting with the same `--instance` repairs crashed support panes; press `r` to reconnect the sidebar. A crashed shared service interrupts its attached conversations; reopen them afterward.

Detaching keeps processes running and uses RAM. Close conversation panes with `c` when finished. To stop the entire workspace after saving work, run `tmux -L codex-workspace-<instance> kill-server` (or `tmux -L codex-workspace kill-server` for legacy); this interrupts open work but retains recorded conversation history and local drafts.

Project display names can be set in the workspace preferences `project_names` mapping, keyed by project folder. Names appear in Projects and are included in search.
