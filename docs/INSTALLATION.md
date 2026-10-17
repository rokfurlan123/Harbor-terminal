# Harbor installation, migration, and another-PC setup

Harbor is the new name of Codex Workspace. Perform authorized setup on the target
machine when access is available. If working only on the laptop, give the PC's
agent this guide and state that the PC itself has not been updated.

## Identify the installation

Work entirely in Linux/WSL. Inspect the actual checkout's `git status --short`,
branch, and `git remote -v`; preserve unrelated changes and existing history.
Check `command -v harbor`, `command -v codex-workspace`, `command -v codex`,
`python3 --version`, `tmux -V`, and `pipx list`. Python 3.10+ is required.
Codex and its sign-in are installed separately on each computer.

The private repository remains
`https://github.com/rokfurlan123/codex-workspace` to preserve existing remotes.
Existing checkout directories may retain that name. The installed application,
package, command, sidebar, and new shortcut are Harbor. Do not move an active
checkout or change Git remotes just to update its display name.

Never copy credentials, conversations, project files, or preferences into Git or
between computers as an implicit installation step. Use the user's authenticated
GitHub access; never request tokens or passwords in chat.

## First installation

On Ubuntu/WSL, install missing prerequisites using the environment's approval and
sudo-authentication rules:

```bash
sudo apt-get install python3-venv pipx tmux git
```

Preserve a working Codex installation. If it is missing, follow current official
Codex Linux installation instructions. Then clone/install this private app:

```bash
git clone git@github.com:rokfurlan123/codex-workspace.git
cd codex-workspace
pipx install .
pipx ensurepath
harbor --help
harbor doctor
harbor
```

Use a new Linux terminal if PATH was changed, or locate the executable using
`pipx environment`. Do not copy this laptop's hardcoded launcher onto the PC.
Direct checkout execution remains `python3 workspace.py`.

## Upgrade Codex Workspace to Harbor

On the PC, find the existing checkout and installation first. Save ongoing work;
leave active conversation panes running. With a clean checkout on the intended
tracking branch:

```bash
git pull --ff-only
```

The Python distribution was renamed from `codex-workspace` to `harbor`. Inspect
`pipx list`. If the OLD distribution is installed, first build/verify the Harbor
wheel as below, then replace only the application package:

```bash
pipx uninstall codex-workspace
pipx install .
pipx ensurepath
```

If Harbor is already installed, update its installed copy instead:

```bash
pipx install --force .
```

Uninstalling the Python package does not delete Codex history or Harbor's data.
An installed package is a copy: pulling source alone does not update it. If
installation fails, keep the checkout and data intact; report the exact error.
Do not reset branches, discard changes, or kill tmux sessions to force an update.

Run `type -a harbor codex-workspace` to find stale shell scripts earlier on PATH.
An old script that executes the updated checkout will still work, but the new
primary command must be `harbor`. Check before replacing any machine-local
wrapper. The package supplies `codex-workspace` as a compatibility alias.

When a desktop launcher bypasses shell initialization, Harbor also searches
`~/.local/bin/codex` and `~/bin/codex` if Codex is absent from PATH. For other
locations set `HARBOR_CODEX` (or `CODEX_WORKSPACE_CODEX`) to the executable's absolute Linux path;
explicit overrides are honored without fallback. No interactive shell is needed.

On a machine with the old `~/.local/share/codex-workspace/` directory, Harbor
continues using it automatically. New machines use `~/.local/share/harbor/`.
Existing named instance sockets retain the `codex-workspace-<name>` spelling for
reconnection. No conversation-history migration or Codex database edits occur.
`HARBOR_DATA`, `HARBOR_BASE_DATA`, `HARBOR_SOCKET`, `HARBOR_INSTANCE`,
`HARBOR_CODEX`, and `HARBOR_PROJECTS_ROOT` are aliases for the corresponding old
`CODEX_WORKSPACE_*` variables. Harbor names win when both are explicitly set.

Open a fresh Harbor workspace to see the new UI. Running native conversation
panes keep their loaded code, models, instructions, and approval state. Reopen
individual conversations when convenient; never restart them silently.

## Verify the update

```bash
harbor --help
harbor doctor
harbor connections list
harbor models list
harbor
```

The right sidebar should say **HARBOR**, with Trivia, Projects, and Misc. Plain
`codex` opens native Codex without the sidebar. Use a terminal at least 100 columns
wide. The Harbor-owned top bar stays above the native child terminal: click
**Model** or press **F5** from either pane to open a model child while preserving
existing conversations. Use F6 to focus the sidebar, **C** for connections/model
management, and **M**
for model selection. The picker identifies remote models by connection ID.
The Qwen topic under Misc is organizational; selecting that topic alone does
not change the inference model.

For isolated automated checks, set temporary `CODEX_HOME`, `HARBOR_DATA`,
`HARBOR_PROJECTS_ROOT`, and a unique `HARBOR_SOCKET`. Clear inherited aliases in
both namespaces, especially BASE_DATA and INSTANCE, before setting test values.
Use `--detached`, inspect only the test tmux panes, and stop only the test socket.
Never use live conversations as fixtures. Model inference tests require task
scope that authorizes model execution; ordinary package checks need no prompts.

## Connect the PC to Qwen on the laptop

The model host is **strawberry-laptop-linux**, Tailscale IP **100.124.226.26**.
The laptop's local Ollama endpoint is **127.0.0.1:11434**. Harbor forwards that
endpoint over authenticated SSH. It does not disable authentication or publish
Ollama, and it does not need the separate Local AI web-app access key.

The current laptop SSH policy allows only the **strawberry Linux device**
(100.89.111.39) as **rokdbest**, via the dedicated
`tag:strawberry-ssh-client` → `tag:local-ai-ssh` rule. If this PC is strawberry,
use its Linux Tailscale connection. If it is a different device, authenticated
Tailscale administration must grant that specific Linux device access first;
do not broaden the source to all tailnet members or allow root.

On the PC, use Harbor’s guided Tailscale setup (Harbor 0.2.1+):

```bash
harbor connections devices
harbor connections setup laptop --host strawberry-laptop-linux --user rokdbest --model local-qwen
harbor connections test laptop
harbor models list --connection laptop
harbor
```

If `laptop` is already saved, add `--replace` to authorize changing that profile.
Without flags, `harbor connections setup` prompts for the required values.
The Tailscale connector verifies SSH host keys using the coordination server,
resolves devices from the authenticated tailnet, and handles userspace routing.
It requires no manual host-key acceptance, SSH alias or fixed local tunnel port.
The regular `--kind ssh` connector retains its normal OpenSSH behavior for
existing connections and non-Tailscale SSH servers.
See [TAILSCALE.md](TAILSCALE.md) for the reusable setup/diagnostic recipe.

In an already-open workspace, **C → s Setup Tailscale** adds a verified connection, then **M** selects
`laptop · local-qwen`. You can select a model while a terminal is open; the
saved choice takes effect on its next reopen without interrupting work. Saved
history remains. CLI `models use` sets the base/default data scope
unless launched with that instance's DATA environment. The UI picker targets the
current instance directly.

A refusal connecting TO strawberry does not test strawberry connecting TO the
laptop. Test from the PC itself. A full test includes a short model reply through
Harbor, followed by closing/reopening that isolated test conversation. Report
whether the source-side test actually ran; do not claim remote success based
only on laptop-local inference or a model list.

For a full connection diagnostic, run on the PC:

```bash
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:11435:127.0.0.1:11434 rokdbest@100.124.226.26
```

In another Linux terminal, `curl --noproxy '*' http://127.0.0.1:11435/api/tags`
should list the laptop's models. Stop this diagnostic SSH process afterward;
Harbor manages its own loopback-only tunnels per operation/conversation.
The laptop must remain awake with WSL and Ollama running.

## Other endpoints and model management

```bash
harbor connections add studio --kind responses --url https://models.example.com/v1 --key-env MODEL_API_KEY --models model-id
harbor connections add office --kind ollama --url https://ollama.example.com --key-env OFFICE_MODEL_KEY
harbor models load local-qwen --connection laptop
harbor models unload local-qwen --connection laptop
harbor models pull qwen3:8b --connection laptop
harbor models default
harbor connections remove office
```

Set real API keys outside Harbor before starting it. Profiles store only the
variable name, never its value. Start a fresh workspace if those environment
variables change, because the shared native app server inherits its startup
environment. URLs cannot contain credentials, query strings or fragments; use
HTTPS for network endpoints. HTTP is accepted only on loopback.

Responses endpoints must support Codex's `/responses` protocol, including tools
and streaming. Chat-Completions-only APIs are insufficient. An optional model-ID
list avoids requiring a `/models` endpoint; its output is labeled configured,
not a live connection test. Discovery alone cannot prove inference compatibility.
Ollama version/model capability can also affect tools and context limits.

Only Ollama connections support load, unload and download. Downloads can take
time and consume disk space; unload can affect another user of the same server.
The UI confirms these operations. No automatic download, public port binding,
ACL edits, or fallback to a different provider occurs. If a connection disappears,
re-add it or explicitly choose another model. Connections are shared by Harbor
instances in the machine's base data directory; no credentials are synced.

## Package and Windows shortcut maintenance

The wheel must include the `harbor` package's `workspace.py`, `connections.py`,
`bridge.py`, `transport.py`, `tailscale_support.py`, `__init__.py`, and all three mode policies. Both
`harbor` and the old `codex-workspace` command must work outside the checkout.
The source archive also includes docs, scripts, tests and project skills.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

Install the wheel into a separate temporary environment and test CLI help,
connections, doctor and an isolated sidebar from outside the checkout. Keep
build outputs, environments, keys, sessions, models and connections.json out of
Git. See docs/WORKFLOW.md for required checks and update WORKLOG.md with evidence.
Commit scoped changes and push to the existing intended remote.

The optional `scripts/create_windows_shortcut.py` now creates **Harbor.lnk**,
launching `harbor` in the default WSL distribution. It does not remove the old
shortcut. Ask the user before running it or modifying/deleting Windows files.
A PC's desktop shortcut is not updated merely by pulling Git. Verify Linux
installation first; then, with permission, run the helper and verify its output.
Inspect an existing shortcut before changing it: preserve its chosen WSL
distribution and any explicit Linux PATH that avoids shell-autostart interception.
The other PC previously used Ubuntu-24.04 with a direct installed-package launch;
do not replace that with a different distribution or plain Codex.
Do not install a Windows Python/Node/Codex toolchain for this app.
