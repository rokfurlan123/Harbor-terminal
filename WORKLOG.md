# Harbor — project notes

## 2026-10-16 — Misc topics alongside Trivia and Projects

- Added peer Misc section with Tailscale and Local models → Qwen. Topic
  placement overrides displayed project grouping without changing execution
  folder, history, mode, model, or running conversation. Qwen is a topic label,
  not an automatic model selection.
- Added topic-aware new/quick sessions, reuse isolation, search by ancestor
  labels, parent navigation, and `g`/context-menu placement with original-group
  restoration. Assignments use the app-owned session_topics table and follow
  archive/restore, deletion, and native draft-ID handoff.
- Applied three reviewed assignments across base and 23 existing instance
  metadata stores, backing up existing databases locally before changes. This
  conversation is in Tailscale; Create qwen project and Install an always-on
  Qwen model are in Local models → Qwen. No native Codex storage was edited.
- Reloaded only the current sidebar and verified other pane identities/statuses
  were unchanged. Live capture shows Misc (3), Tailscale (1), Local models (2),
  and Qwen (2). Collapsed Trivia/Projects in the current view to expose Misc.
- Validation: 52 tests passed, including five topic behavior/persistence tests.
  Integration suite required execution outside sandbox socket restrictions.
  Isolated terminal smoke passed at 140×40 and 85×28 with nested topics and Qwen
  search; screenshots represented by terminal captures under /tmp. No model
  prompts sent. Reviewed persistence and active-session invariants using the
  project testing/review skills; review was development-aware, not independent.
- Runtime launcher uses this checkout. Other already-running sidebar processes
  load the new UI when reopened; active conversations were not restarted.

## 2026-09-21 — work resumed; working terminal prototype

- Fixed tmux window allocation (`workspace:` target), catalog transport (the Unix endpoint uses WebSockets, not the stdio proxy protocol), stale-socket readiness, and recovery of crashed support panes.
- New sessions are durable local drafts. The native TUI creates its own thread; a socket bridge matches the exact `thread/start` request/response, verifies a fresh empty thread in the requested project, and replaces the draft ID with the real ID. Metadata reads and other thread responses cannot claim the draft. Empty close/reopen creates a fresh native thread while preserving name/project; saved history uses normal resume.
- The earlier direct-resume approach remains unsuitable for empty threads: the native TUI requests paginated history and fails without a source rollout. Do not restore that approach.
- Added shared-service transport, native startup/recovery, fragmented message/session identity, and synthetic recorded-history lifecycle integration tests. No model generation during these checks. Native ready-prompt create and close/reopen were also tested with the existing login; smoke tests clean up their own drafts.
- Reduced idle tmux subprocess polling; added locking for concurrent preferences writes and explicit SQLite connection closure. Native processes replace wrappers where possible.
- Routine update installed: Codex 0.155.0 → 0.155.1 (we got update). Linux executable: `/home/rokdbest/.nvm/versions/node/v24.16.0/bin/codex`. Python/tmux unchanged. No Windows changes.
- Launcher remains `/home/rokdbest/bin/codex-workspace`. Project adds `transport.py`, `bridge.py`, `scripts/smoke_native.py`, and tests. Runtime uses one shared service plus one native terminal per open conversation.
- Final verification: all 6 integration tests passed; the authenticated native create/reopen smoke test passed after the identity safeguards; doctor connected and listed 21 saved conversations. Temporary test services stopped. The production workspace remains running with only home/sidebar/service support panes and no open conversation terminals.
- Remaining validation: sending a first real message and receiving output, interactive approvals during model work, and extended daily use. Scheduling is still deferred. Detach keeps RAM allocated; close unused conversations or stop the isolated workspace server as documented.
- Official lifecycle reference: https://learn.chatgpt.com/docs/app-server . Installed help and OpenAI transport/TUI source were also checked because the Unix framing and native empty-resume behavior required implementation-level verification.

## 2026-09-21 — implementation paused and saved at user request

User requested a separate terminal app that embeds the native Codex conversation with a permanent right sidebar for physically saved sessions. It should create, reopen, close, rename, archive/restore, and explicitly delete conversations. Closing must retain history. Scheduling was discussed earlier but deferred from this first version.

### Files and runtime

- Project: `/home/rokdbest/codex-workspace`.
- Implementation: `workspace.py`; Python standard library, curses and tmux.
- Launcher: `/home/rokdbest/bin/codex-workspace` (executable).
- Documentation: `README.md`; integration tests: `tests/test_workspace.py`.
- Workspace state: `~/.local/share/codex-workspace/` (preferences, draft SQLite index, service socket, logs).
- Existing Codex owns real session history in `~/.codex`; do not edit its database directly.
- Tools already installed: Python 3.12.3, tmux 3.4, Codex CLI 0.155.0; Linux/WSL only. No installations or updates performed.

### Implemented, but not release-ready

Native Codex pane plus curses sidebar, search, new/rename/open/close/archive/restore/confirmed delete; hidden tmux panes preserve other open terminals while switching. F2 sidebar, F3 conversation, F4 detach. Uses isolated tmux socket `codex-workspace`.

Initial independent stdio app-server catalog passed the doctor check against 21 existing saved conversations. Managed `codex app-server daemon start` does NOT work with this npm installation: it requires a separate standalone installer. Do not install it merely to work around this.

Latest design instead starts a dedicated `codex app-server --listen unix://.../server.sock` in a hidden tmux pane; catalog uses `codex app-server proxy --sock ...` and the conversation CLI uses `codex resume ID --remote unix://...`. This design has not yet passed an end-to-end launch test.

### Verified and unresolved

- Python syntax compilation passed before latest shared-service changes.
- Real tmux integration test PASSED: open A, open B, switch back preserving A's pane, close A, reopen A, close B without affecting A.
- Latest persistence test FAILED at `thread/resume`: `no rollout found for thread id ...`, including after `ensure()` creates a replacement draft.
- Important discovery: `thread/start` plus `thread/name/set` creates metadata but no persisted rollout before the first user message. `thread/list` omits these empty conversations. Local `drafts.sqlite` now preserves empty names/project references, but native CLI resume of an empty draft still needs a correct solution. Do not claim new conversations are working yet.
- Test archive/restore/delete assertions after the failing resume were NOT reached. They are not yet verified.
- Tests use temporary Codex homes and fake sleeping terminals for pane switching, with no model generation and no changes to existing user conversations.
- Production `--detached` launch was blocked by sandbox Unix-socket restrictions. Escalated launch was interrupted by the user before a confirmed result; process inspection afterward showed no running workspace, test tmux, or app-server processes.
- README describes intended behavior; update it to reflect actual verified behavior before delivery.

### Next work

1. Resolve new empty conversations using the supported server/CLI lifecycle. Consider starting native Codex with no resume ID and reliably discovering its resulting thread rather than resuming an unpersisted empty thread. Do not fabricate a user message.
2. Verify shared Unix socket transport and native Codex TUI attachment.
3. Rerun persistence, archive/restore/delete and pane integration tests; visually inspect the real sidebar.
4. Check app-server shutdown, stale socket recovery, draft rename after restart, and sidebar crash recovery. Keep process and RAM use bounded.
5. Update README and report only tested features. Scheduled AI work is not implemented.

### Save/close request

User stopped implementation because of lag and requested saving the project, closing the terminal, and reducing RAM usage. Implementation work paused; do not automatically relaunch. Host process inspection found no leftover project/test processes. The current Codex process was PID 2594, approximately 536 MiB RSS; unrelated Codex instances were left alone. These PIDs are historical evidence, never reuse them as shutdown targets without fresh verification.

## 2026-09-21 — Windows desktop shortcut

Created and verified `C:\Users\rocky\Desktop\Codex Workspace.lnk` at user request. Opens a new Windows Terminal window, Ubuntu WSL, and `/home/rokdbest/bin/codex-workspace` through an interactive login shell so Linux Node/Codex are available. Target and arguments were read back successfully. Reusable creator: `scripts/create_windows_shortcut.py`. No Windows toolchains installed; the application remains entirely in Linux.

## 2026-09-22 — Sidebar right-click actions and copy

Added a curses context menu for sidebar right-clicks, with every footer action plus copy session reference (name/ID/project), ID, project path, and a shell-quoted Linux resume command. Right-click selects the clicked session; empty space keeps the existing selection. Existing close/delete confirmations are reused. Drafts without history cannot copy a resume command. Menu supports keyboard navigation, mouse selection, scrolling in short terminals, and Escape dismissal.

MouseDown3Pane forwards the event through tmux to the application. Clipboard text is sent over stdin to `tmux load-buffer -w -` (OSC 52); no Windows files or tools changed. Running sidebar reloaded without restarting conversation panes. README updated.

Validation: 13 tests passed, including seven focused menu/copy tests and a real curses right-button press/release integration check using tmux-256color's X10 mouse encoding. One earlier full run had an intermittent support-pane crash-recovery assertion failure; the final full run passed. Windows GUI paste has not been manually verified. Production sidebar capture confirmed the new hint; shortened it to fit the current narrow pane.

## 2026-09-22 — AI usage modes, project instructions, and session tree

Implemented the discussed conversation/project distinction in Codex Workspace. Mode policies are editable in `policies/auto.md`, `policies/conversation.md`, and `policies/project.md`. Auto infers intent per request; Conversation defaults to learning/discussion; Project work follows applicable project rules for authorized changes. Explicit user requests still take precedence. These modes guide behavior and do not change sandbox permissions or automatically start test agents.

Added this project's `AGENTS.md`, `docs/WORKFLOW.md`, and `.agents/skills/{black-box-test,change-review}/SKILL.md`. Both skills passed the skill-creator validator. Other projects/global Codex configuration were not modified. The workflow distinguishes independent behavioral review from development-aware review and avoids imposing four agents on every task.

Added a Trivia / Projects tree. Trivia contains Conversation sessions and Auto sessions rooted in the Linux home folder. Other sessions group by existing working folder. Branches expand/collapse with click/Enter and left/right navigation; expansion preferences persist. Search exposes matches in collapsed branches; archived history uses the same tree. Right-click group actions create sessions or copy a project path; session actions remain available on leaves. New sessions inherit category defaults; `m` changes a closed session's mode. New projects appear when a session is created in their existing folder.

Per-session modes live in the workspace's own SQLite table, independent of Codex history, and follow draft-to-native ID mapping. Running sessions cannot change mode silently. Older running panes show a reopen hint. Both new and resumed terminals use the bridge, appending mode instructions to supported `thread/start` and `thread/resume` fields while preserving request/config developer instructions and permission fields. Other requests, including model turns, are forwarded untouched. Native copied resume commands run outside this policy injection; README explains reopening through the workspace to apply current policies.

Validation: 27 tests passed, covering tree grouping, collapse/search/navigation, context-sensitive creation, mode persistence through archive/delete and draft cleanup, prevention of mode changes on live panes, fragmented bridge messages, preservation/replacement of mode instruction blocks, acceptance by a real isolated app server, native terminal startup/right-click, history operations, and pane lifecycle. The pane-only test now launches its sleeping fake directly because real conversation startup correctly requires the shared service. No model turns were generated; this validates plumbing, not the model's adherence across natural-language scenarios. No independent fresh-context agent review or Windows GUI clipboard test was performed. The existing live conversation processes are left running when the sidebar is reloaded.

### Existing folders and live rollout

Live catalog inspection showed all 21 existing sessions use the Linux home folder, so they cannot be reliably assigned to projects from recorded cwd. They remain in Trivia without guessing from titles. Added one-time discovery of immediate home subfolders with README/Git/build manifests into the workspace preference registry; empty project branches can now be opened and used for new sessions. Creating a project session registers additional paths. Tests use `CODEX_WORKSPACE_PROJECTS_ROOT` to isolate discovery. Final suite: 29 tests passed; the seven menu tests also passed after removing their dependency on live user preferences. Sidebar reload preserves conversation pane identities. AI behavioral adherence still has not been evaluated with generated model turns.

## 2026-09-22 — Organize existing chats by content

At user request, reviewed all 22 saved chats (no archived chats) using user messages and relevant assistant implementation summaries. Assigned 17 to their primary projects and 5 to Trivia. Added explicit workspace-owned `session_projects` metadata so organization is independent of original cwd and AI mode. Search, tree selection, context-sensitive new sessions, copied project paths, and reference text respect the assignment; native resume retains the original working folder. Assignments survive archive and draft identity changes, and are removed with deleted sessions. Mapping and mixed-topic rationale: `docs/SESSION_ORGANIZATION.md`. Backed up the workspace SQLite database before applying assignments. No Codex internal database edits.

Validation: 32 tests passed, including explicit category precedence, persistence/archive/delete, project-path search, and distinct project/reference versus resume paths. Live rollout verifies all 22 assignments, unchanged cwd/modes, and preserved active conversation pane identities.

## 2026-09-22 — Software development project tags

Added persistent project tags in workspace `preferences.json` (`project_tags`, keyed by project path). Tagged advertiser, bank-information, codex-workspace, dutch-learning, guide, and product-scrapper as Software development. The tree shows the full tag on the project's second line to fit narrow sidebars; right-click still provides the project path. Tags describe projects independently from AI modes and conversation categories. Untagged projects retain their path display; Trivia is untagged. README updated. All 11 existing tree tests passed; sidebar reloaded for live display verification.


## 2026-09-23 — Start blank session

Added a clickable Start blank session action at the top of the sidebar, the b shortcut, and a right-click menu entry. Opens a fresh native session immediately with no name/mode/project prompts, in the Linux home folder using Auto mode. Local draft title is New session. Clears search and archived view and selects the draft under Trivia. Guided n creation remains available. README and welcome text updated.

Validation: full existing suite passed (32 tests); all 13 tree tests passed after adding two blank-session checks covering project independence, draft creation, selection, mouse click, and busy guard. No model responses generated. Reloaded live sidebar and preserved other pane identities. Capture revealed the initial button label was clipped in the narrow live sidebar; shortened it to fit.


## 2026-09-23 — Wider sidebar and compact tags

Sidebar now uses 40% of window width on launch/reopen and a tmux client-resized hook maintains that share when the terminal changes size. Software development tags render as [sd], retaining the full metadata value. README updated. Applied the layout and reloaded only the sidebar in the running workspace: live capture confirms [sd] and 41 sidebar columns in a 103-column window (previously 14). Conversation, service, and welcome pane PIDs remained unchanged.

Validation: all 34 tests passed outside the sandbox, including isolated native launch and support recovery. Initial sandbox run failed because Unix socket access was denied; rerun with escalation succeeded. Verified the live resize hook is installed; an actual GUI window resize was not exercised.


## 2026-09-23 — Sidebar width adjustment

Changed the sidebar share from 40% to 33% at user request, including startup, resize hook, README, and the running workspace.


## 2026-09-23 — Tree heading colors and indentation

Top-level Trivia/Projects headings now use cyan; child project headings use yellow. Session titles retain the default text color and supporting tags are dimmed. Reduced horizontal indentation from two columns to one per level. Kept the 33% sidebar width. Updated README and reloaded only the sidebar. All 13 tree tests and seven menu tests passed.


## 2026-09-23 — Reuse unused sessions; do not save empty chats

Clarified user requirement: accidentally opened empty sessions must not accumulate as saved conversations. New UI-created sessions are temporary, reused in the same context while open, and excluded from saved-history counts. Trivia reuses its unused home session regardless of mode. Closing the terminal or finding no surviving pane removes the local placeholder; recorded Codex history takes precedence and is preserved. Native-ID binding carries temporary metadata and the original draft ID to protect against a stale pane snapshot during handoff. Blank sessions no longer force a permanent New session title on the native thread. Existing named legacy drafts remain available. Added no-duplicate guidance to AGENTS.md and updated README.

Live cleanup found five placeholders still at the CLI update screen, before any native thread was created. Rechecked each terminal and closed four duplicates; retained/restarted only the verified unused fifth terminal. It reached the native empty prompt with a new native ID. Other saved conversation panes were not restarted. Sidebar reloaded; saved-history count is 23, excluding the temporary blank. No Codex internal database edits or synthetic user messages.

Routine Linux update: we got update — Codex CLI 0.155.1 to 0.156.1 via npm, executable /home/rokdbest/.nvm/versions/node/v24.16.0/bin/codex. The shared existing service was not restarted, and the updated native client reached its ready prompt against it.

Validation: all 40 tests passed with isolated Codex home, workspace data, and tmux sockets. Added coverage for repeated New reuse, close/restart discard, saved-history precedence after first-message catalog appearance, legacy blank migration, sidebar identity deduplication, and native-ID handoff. Real isolated native launch verifies reuse preserves the pane and closure removes the temporary listing. Syntax check passed. Behavior and change review performed by the implementation agent, not an independent/blind agent; no model responses generated. First-message promotion is covered with catalog fixtures and existing synthetic recorded-history tests. Live thread/read includeTurns is unsupported by the existing service (list_turns is not supported yet), so cleanup relied on the explicitly verified pre-session update screens instead.


## 2026-09-23 — Free F2 for native warnings

The tmux root F2 binding intercepted Codex's warnings shortcut and selected the sidebar. Removed that binding and moved sidebar focus to F6. F3 still focuses the conversation and F4 detaches. Shortcut configuration runs on both new and existing workspace launches, migrating the previous F2 binding. Updated sidebar footer, welcome text, and README. Applied bindings live and reloaded only sidebar/welcome panes.

Validation: all 40 isolated tests passed, including assertions that the tmux root table has no F2 binding and contains F6. Live F6 binding verified. Native warnings UI was not opened programmatically in user conversations; user should focus the conversation with F3, then press F2.


## 2026-09-24 — Independent workspace launches

Ordinary launcher invocations now allocate a unique tmux socket and workspace data directory. Each has its own sidebar, panes, app server, and draft lifecycle; Codex home/login/recorded history remain shared. Added --instance NAME for deliberate reconnection, with legacy reserved for the original running workspace. Explicit CODEX_WORKSPACE_SOCKET preserves automation behavior. Child processes inherit selected paths. Initial settings, modes, and project assignments are snapshotted from the original workspace under an initialization lock; draft placeholders are excluded. Settings subsequently remain instance-local. Welcome and detached output supply reconnect commands. Existing processes and Windows shortcuts were not modified.

Validation: isolated integration launches two default instances, changes the first pane layout and checks the second is unchanged, reconnects to the first without losing panes, checks separate service sockets, and verifies settings copy without copying or deleting original temporary drafts. Full suite: 41 tests passed. Behavior testing and change review performed by implementation agent using project skills, not a blind independent review. No model prompts sent; Windows GUI launch not exercised. Existing shortcut invokes the updated Linux launcher. Saved history remains common, so users should select separate conversations for independent tasks; no cross-instance same-conversation editing lock was added. Detached instances retain processes until explicitly stopped.

## 2026-10-09 — Metronome Pulse project entry

Added `/home/rokdbest/metronome` as Metronome Pulse in the active workspace and base preferences used by future instances. Assigned existing development session `01a11bf2-c823-7d91-9636-d383b9de3109` using the workspace assignment API. Added optional project display names to sidebar rendering and search. Original Codex history, execution folder, and mode are preserved. All 13 tree tests passed; checked custom-name search includes the project and its session. Reloaded only the active sidebar and verified other pane identities were unchanged.


## 2026-10-14 — GitHub upload preparation

Prepared the existing project for its first Git commit and GitHub upload at user request. Added ignore rules for local credentials, virtual environments, runtime databases, and logs. Source, tests, project instructions, and existing documentation are included. SSH authentication verified for rokfurlan123. Target repository codex-workspace was not found; upload awaits creation of the remote repository. No application behavior changed; application tests were not rerun for repository setup.


## 2026-10-14 — Automatic project repositories and commits

User authorized automatic repository creation and commits when asking for project implementation. All three workspace mode policies now instruct agents to create private repositories in the authenticated personal GitHub account when needed, commit scoped completed work after proportionate checks, and push the task branch. Existing remotes/history and unrelated changes are preserved; discussion and explicit local-only requests do not trigger this workflow. Added README setup/behavior documentation and project AGENTS guidance. This is agent policy, not a background Git daemon. Newly started/reopened terminals receive it; live conversations were not restarted.

Installed GitHub CLI 2.102.0 in Linux at /home/rokdbest/tools/github-cli/gh_2.102.0_linux_amd64/bin/gh, linked from /home/rokdbest/.local/bin/gh. Verified the release archive SHA-256 against the official release checksums. Existing SSH authentication identifies rokfurlan123. Browser device authorization is pending; remote repository creation/push cannot complete until login succeeds.

Validation: all seven existing mode tests passed; git diff --check passed. No runtime Python changes or synthetic model turns. Actual GitHub creation/push remains unverified pending user browser login.


## 2026-10-14 — GitHub login and upload completed

User completed GitHub CLI browser authorization as rokfurlan123. Created private repository https://github.com/rokfurlan123/codex-workspace and successfully pushed main through workflow commit 0261624. Local main now tracks origin/main. GitHub CLI authentication and SSH push both verified with network access. The automatic repository/commit workflow is ready for new or reopened workspace conversations; existing sessions were not restarted.

## 2026-10-15 — Portable installable workspace package

Added setuptools packaging (version 0.1.0), an installed codex-workspace entry point, bundled mode policies, and source archives containing docs, scripts, tests, and project skills. Package imports preserve direct checkout execution. README now covers Linux/WSL prerequisites, pipx installation on another computer, updates, and wheel builds. The optional Windows shortcut helper now uses the default WSL distribution and installed command rather than this machine's username/path; it was not executed and no Windows files were changed. Credentials, conversation history, local preferences, and build outputs are excluded from Git/package runtime contents.

Validation: built wheel and source archive; installed wheel in /tmp/codex-workspace-package-build and ran from /tmp outside the checkout. Verified all three policy files, CLI help, doctor connection, and actual Trivia / Projects sidebar capture with temporary Codex home/data and isolated tmux socket. All 41 tests passed on the final run. Initial sandbox execution could not use sockets; an initial unrestricted run had one timing-sensitive sidebar navigation failure, which passed individually and in the complete rerun. No user conversations were modified and no model prompts were sent. git diff --check passed.

Build tools installed only in the temporary Linux environment: build 1.6.1, setuptools 84.0.0, wheel 0.48.0 (Python 3.12.3). System ensurepip is unavailable here, so this verification environment was bootstrapped with the existing pip --python facility. Documented end-user setup installs python3-venv and pipx normally. Runtime verified with Codex 0.162.1 and tmux 3.4.

## 2026-10-15 — Persist cross-computer setup instructions for AI agents

Added docs/INSTALLATION.md with executable setup/update steps, prerequisite and authentication handling, installed-versus-checkout behavior, missing-sidebar diagnosis, isolated verification, packaging contents, and Git completion requirements. AGENTS.md explicitly routes future agents to it; README.md and docs/WORKFLOW.md link it. Instructions preserve Linux/WSL toolchains, live conversations, local changes, and Windows approval boundaries. Existing MANIFEST.in includes the new guide in source archives. Documentation-only change: checked links, packaging inclusion rule, and git diff --check; application tests were not rerun.

## 2026-10-16 — Model selection and quick project sessions

- Added a clickable model default at the top of the sidebar and `M` / context-menu model selection for closed sessions. Catalog discovery combines native `model/list` pagination with installed Ollama models; unavailable catalogs are reported without blocking the other source. Confirmed this machine has `qwen3:8b` and `local-qwen:latest`.
- Persisted model/provider preferences in workspace-owned storage, transfer them during native thread identity handoff, and apply them through native start/resume fields. Default restoration resolves the configured model (or native catalog default). Existing permissions, native approvals, login, and history remain intact. Open conversations cannot have their provider changed through the sidebar; close/reopen is required.
- Added `[+]` at each project heading and `+` keyboard/context-menu creation without setup prompts, using that folder and Project work mode. Unused sessions are reused only with matching model choices. Missing directories are reported. Search no longer hides matching empty project headings with a no-results overlay.
- Followed project behavioral testing and change-review skills in a code-aware review; no independent testing claim. All 47 unit/integration tests passed using temporary Codex homes/data and isolated tmux sockets. Coverage includes picker scrolling/click/cancel/narrow layouts, catalog failures, reuse/persistence, live-session protection, and native bridge acceptance of Qwen/Ollama. Separately verified actual app-server thread/start returns `qwen3:8b` / `ollama` without a prompt. Model generation and local tool-call quality were not tested.
- Reloaded only this workspace's sidebar pane after tests, preserving its service and active conversation processes. Existing Linux checkout launcher uses the updated source; no Windows changes or dependency updates.
- Official reference: https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server (catalog use), plus installed CLI-generated thread/start and thread/resume schemas.
## 2026-10-17 — Harbor rename and model connections

Renamed the application to **Harbor**, version 0.2.0: sidebar, welcome screen,
CLI/help/errors, package/module, project display name, developer instructions,
and optional desktop-shortcut helper. The primary command is `harbor`;
`codex-workspace` remains an installed compatibility alias. The existing Git
remote and checkout path remain intact so active sessions and other-PC updates
keep working. Existing data directories and tmux socket names are retained for
compatibility; fresh machines use ~/.local/share/harbor. HARBOR_* environment
aliases are supported alongside the old namespace. Historical worklog entries
retain their original product names.

Added named connections for direct Ollama, Ollama through authenticated SSH,
and Responses-compatible model APIs. C / the context menu manages connections
and lists, loads, unloads, or downloads Ollama models. M selects local, Codex, or
named-connection models for new sessions or closed saved conversations. Labels
include the connection ID. SSH forwarding binds only to loopback and is scoped
to the operation/conversation, with strict host-key checks and noninteractive
authentication. Native model selection/configuration preserves approval and
sandbox settings. Missing/deleted connections fail explicitly rather than
falling back to another provider. Running conversations are not switched.

Connection profiles are private, locked, atomically written JSON in the machine's
base data directory, separate from instance preferences. They contain API-key
environment-variable names, never key values. Remote HTTP without TLS and URLs
with embedded credentials are rejected; loopback HTTP is supported. Model
requests reject redirects and report authentication/catalog failures without
printing server response bodies or keys. No public Ollama listener, network ACL
change, or change to Local AI's authentication was made.

Rewrote docs/INSTALLATION.md with an exact old-package → Harbor migration,
verification, stale-launcher diagnosis, model-management commands, authenticated
remote-Qwen setup for the PC, current strawberry-only SSH restriction, and
optional Windows shortcut steps. The shortcut helper now creates Harbor.lnk,
but was not run. The other PC was not accessed or upgraded in this session;
the guide is ready for the agent on that computer. Existing Local AI/Ollama
services and data were retained.

Validation and review:

- All **62** tests pass, including real native app-server acceptance of custom
  provider configuration, lifecycle/history regression coverage, connection
  persistence, credentials/redirect handling, model discovery and management,
  tunnel failure/cleanup, deleted connections, and native permission preservation.
- Installed-wheel testing outside the checkout verified help, doctor, model
  discovery, connection setup, default model selection, HARBOR sidebar startup,
  and the Connections UI with isolated Codex home/data/tmux sockets.
- Actual local Qwen inference through Harbor's native conversation launcher
  produced a saved agent reply `HARBOR_OK`. The test read that reply from the
  native transcript, closed the disposable conversation, and reopened it with
  its selected connection and history. Only disposable test history was used.
  Native onboarding used a synthetic invalid API-key fixture; no live credentials
  were copied. The model catalog attempted authentication and received 401 for
  that fixture; inference itself went to local Ollama. A prior isolated Codex
  exec check also exercised the same custom Responses provider against Qwen.
- Found and fixed implicit Ollama :latest name matching, menu ordering, clipped
  connection prompts in narrow sidebars, and malformed remote catalog errors.
- Behavioral checks and development-aware review were performed by the same
  implementation-aware agent; no independent/blind review is claimed. A full
  source-PC → laptop SSH inference test and a real external hosted API provider
  remain unverified. SSH behavior has command/failure/cleanup coverage, and the
  other-PC guide explicitly requires testing from that source computer.
- Built the complete wheel/source archive with isolated Linux build tooling
  (build 1.6.1, setuptools 84.0.0, wheel 0.48.0); Python 3.12.3, tmux 3.4, and
  Codex 0.163.0 were used for verification. Runtime has no Python dependencies.
  System ensurepip is unavailable, so test/install environments used venv
  --without-pip plus the existing pip --python facility.
- Installed this laptop's package in ~/.local/share/harbor-app/venv and the
  primary launcher at ~/.local/bin/harbor. Updated this project's display name
  in workspace preferences, then reloaded only the sidebar; all other pane IDs
  and processes were verified unchanged. Shell source/package compatibility,
  bundled runtime modules/policies, and git diff --check passed.
