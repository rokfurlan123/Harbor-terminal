# Installation and maintenance instructions for AI agents

Use this guide when asked to set up Codex Workspace on another computer, update
it, package it, or investigate a missing Trivia / Projects sidebar. Perform the
authorized work and verify it; do not merely give the user commands when you can
execute them on the target machine. If you only have access to another machine,
state that limitation and provide these instructions for the agent on the target.

## Identify the installation

- Work in Linux/WSL. Never install a Windows Python, Node, Codex, or tmux toolchain.
- Locate the actual checkout; do not assume a username, home directory, or WSL
  distribution name. Inspect `git status --short`, `git remote -v`, and the current
  branch before changing an existing checkout. Preserve unrelated changes.
- Check `command -v codex-workspace`, `command -v codex`, `python3 --version`,
  `tmux -V`, and `pipx list`. Python 3.10+ is required. Codex must be installed and
  signed in separately on the target computer.
- The app repository is `https://github.com/rokfurlan123/codex-workspace` (private).
  Use the user's authenticated GitHub access. Do not request tokens in chat or
  copy credentials from another computer.

## First installation

On Ubuntu/WSL, missing packaging prerequisites can be installed with:

```bash
sudo apt-get install python3-venv pipx tmux git
```

Follow the current environment's approval rules for privileged commands. If
Codex itself is missing, follow current official Codex Linux installation
instructions; this Python package does not install it. Preserve any existing
working Codex installation and login.

If no intended checkout exists, clone into an appropriate Linux project folder:

```bash
git clone git@github.com:rokfurlan123/codex-workspace.git
cd codex-workspace
pipx install .
pipx ensurepath
```

HTTPS cloning is also supported when GitHub authentication is configured for it.
Open a new Linux terminal for PATH changes, or use the executable in the pipx
binary directory reported by `pipx environment`. Do not hardcode this computer's
`/home/rokdbest/bin/codex-workspace` launcher on another machine.

## Update an existing installation

In the correct checkout, inspect local changes and branch/upstream first. For a
clean checkout on its intended tracking branch:

```bash
git pull --ff-only
pipx install --force .
pipx ensurepath
```

Do not discard local changes, reset branches, or force-push to make an update
succeed. Resolve divergence within the authorized scope or report the blocker.
An installed package is a copy: pulling source alone does not update that copy.
Already-running workspaces also retain loaded code; preserve active conversations
and verify with a fresh workspace instead of killing live sessions.

## Verify and diagnose the sidebar

```bash
codex-workspace --help
codex-workspace doctor
codex-workspace
```

Run the last command in an interactive Linux/WSL terminal, preferably at least
100 columns wide. Confirm the right sidebar displays **TRIVIA / PROJECTS** with
Trivia and Projects entries. Plain `codex` opens native Codex without this sidebar.
Use `command -v codex-workspace` to identify an obsolete launcher if the expected
app does not appear. `F6` focuses the sidebar; `r` refreshes it. A missing project
inside a visible sidebar is different from a missing sidebar: projects come from
local folders and preferences, as described in README.md.

For automated checks, use temporary `CODEX_HOME`, `CODEX_WORKSPACE_DATA`,
`CODEX_WORKSPACE_PROJECTS_ROOT`, and a unique `CODEX_WORKSPACE_SOCKET`. Clear
inherited `CODEX_WORKSPACE_BASE_DATA` and `CODEX_WORKSPACE_INSTANCE` to avoid
misleading instance information. Launch with `--detached`, inspect the isolated
tmux panes, then stop only that test socket. Never send model prompts just to
verify installation or use real user conversations as test fixtures.

Installation does not sync project files, conversations, credentials, or workspace
preferences between computers. Do not silently copy those into Git or a package.

## Maintain the complete package

`pyproject.toml` defines the package and `codex-workspace` entry point.
The wheel must contain `workspace.py`, `bridge.py`, `transport.py`, `__init__.py`,
and all three `policies/*.md` files. `MANIFEST.in` includes documentation, scripts,
tests, and agent skills in the source archive. Update these definitions when
adding runtime resources. Preserve direct `python3 workspace.py` execution too.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

Build outputs go in ignored `dist/`. Test the generated wheel in a separate
environment from outside the checkout, including bundled policies, CLI help,
doctor, and sidebar startup. A wheel can be installed on another Linux/WSL
computer using `pipx install /path/to/the-built.whl`. Do not commit build outputs,
virtual environments, credentials, or runtime/session data. Follow
docs/WORKFLOW.md for proportionate tests and update README.md and WORKLOG.md.
Commit intended changes and push to the existing intended remote; report the
commit and push result. Publishing releases is a separate action.

The optional `scripts/create_windows_shortcut.py` uses the default WSL
distribution and installed `codex-workspace` command. Ask before executing it
because it writes a Windows desktop shortcut. Installing the Linux package does
not require this helper. Verify the Linux installation first.
