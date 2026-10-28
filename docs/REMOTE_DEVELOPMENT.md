# Remote development (Harbor 0.3.0)

**Remote development moves the whole workspace, not just inference.** This
computer displays an authenticated SSH terminal; Harbor, Codex's shell and
filesystem tools, repositories, dependency installation, builds, tests and Git
operations run on the destination Linux/WSL computer. Inference can still use
OpenAI or another model selected on that computer. A model connection alone
(`connections setup`) does not move development execution.

## Connect once

Install Harbor 0.3.0+ on both computers using [INSTALLATION.md](INSTALLATION.md).
The destination needs Python 3.10+, tmux, Git, Codex and its own sign-in. GitHub
CLI is optional but useful for repository discovery/creation and authentication.
Authenticate there; Harbor never copies client credentials or forwards an SSH
agent. A headless Codex login can use `codex login --device-auth`; see the
[official authentication documentation](https://learn.chatgpt.com/docs/auth).

On this client, after Linux Tailscale is running:

```bash
harbor remote setup laptop --host strawberry-laptop --user rokdbest
harbor remote test laptop
harbor remote list
harbor --remote laptop
```

Setup resolves the authenticated Tailscale device, verifies SSH and remote tools,
and saves only after a successful protocol check. `signed_in: false` means the
remote Codex login still needs completing; tools can be installed without a
login. It sends no model prompt. Profiles are separate from model connections,
private (0600), and shared by this client's Harbor instances. Replacing a profile
requires `--replace`. Use `--root /home/USER/projects` to choose a remote Linux
projects directory; the default is `~/projects` on the destination, not here.
Do not use Windows-mounted roots. `--kind ssh` supports regular OpenSSH with
preverified host keys; the default Tailscale path verifies coordination-server
host keys. Custom local userspace sockets use `--tailscale-socket`.

The remote bootstrap finds Harbor in the destination's PATH, `~/.local/bin`, or
`~/bin`, and includes that host's installed NVM Node bin directories for
noninteractive SSH. It does not install software or change startup files.

## Use the option in Harbor

In a **newly opened Harbor workspace**, focus the sidebar (F6), then press
**R — Remote dev**. Choose the saved host, optionally an existing remote project
folder and/or Git URL (GitHub `owner/repo` also works). Escape at any prompt
cancels without connecting. The remote workspace occupies a full-size popup.
The header, top bar and terminal title identify **REMOTE laptop**. F4 detaches
from the remote workspace and returns to the unchanged local workspace.

Alternatively launch directly from a Linux terminal:

```bash
harbor remote open laptop
harbor remote open laptop --repo owner/project
harbor remote open laptop --project project
harbor remote open laptop --project project --repo git@github.com:owner/project.git
```

An explicit project launch opens/reuses an unused remote Project work session.
The repository is cloned **on the destination** only when absent. Existing
matching repositories, including dirty work, are reused without pulling,
resetting, or changing branches. A destination with a different/missing origin
is rejected when `--repo` is supplied. Local paths, file/ext Git transports,
credential-bearing URLs and project path traversal are not accepted. No client
project directories are automatically synchronized. Uncommitted client work
must be committed/pushed or transferred in a separately authorized operation.

Inside a remote conversation, ask for project implementation normally. The
agent is told to locate the repository under the remote projects root, clone
it there if necessary for authorized project work, read AGENTS.md, and use the
remote tools for development and tests. It should ask for the URL if the project
is ambiguous. Merely discussing a project does not authorize cloning or edits.
This instruction guides the agent; it is not an unattended natural-language
repository resolver or a change to native tool approvals.

## Reconnect, failure and boundaries

Reopen the same host to reattach to its stable remote-owned instance; remote
panes and saved conversations remain there. A lost client connection never
falls back to local execution. Remote jobs can continue in tmux while the SSH
terminal is disconnected, provided the laptop remains awake, WSL remains
running, and the remote process itself has not failed. Reconnect and inspect
status before retrying a command to avoid duplicate work. An explicit
`--instance NAME` selects a different named remote workspace (1–16 letters,
digits, hyphens or underscores). `--detached` starts/checks plumbing without
attaching, useful for diagnostics; it does not submit a task.

Existing local conversations stay local. This feature does **not** relocate the
current chat, import history between machines, forward local app integrations,
or make client-only attachments/files available remotely. Open a remote session
before sending tasks intended for the laptop. Both machines retain their own
Codex approval settings, model profiles, histories and sign-ins. Native approvals
are not bypassed. Remote applications also need explicit SSH port forwarding or
a separate viewer to display a web/GUI app here; this feature does not publish
ports or expose services automatically. .NET remains Windows-only and needs a
separately authorized Windows workflow.

```bash
harbor remote remove laptop
```

This removes only the client profile. It never deletes remote code, sessions,
Tailscale devices or credentials. Offline/unreachable hosts, missing tools,
unknown profiles, incompatible Harbor versions, denied access and clone failures
are errors, not reasons to run anything locally. Update the installed Harbor
copy as well as the checkout; active conversation panes are never restarted
silently by installation.
