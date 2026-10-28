# Harbor hub: machines × backends × models

Harbor is a hub, not an Ollama-only client. Choose an **execution host**, then a
**backend**, then a discovered **model**. Host count, connection count and model
count are data-driven; do not add machine/model-specific UI branches.

## Use

```bash
harbor hub hosts
harbor hub models --host laptop
harbor hub models --all
harbor hub open --host laptop --backend codex
# Optionally --model EXACT_ID from the catalog, --project EXISTING_FOLDER,
# --repo owner/repo, --instance NAME (16 characters maximum), or --detached.
harbor hub open --host local --backend connection:laptop --model local-qwen:latest
```

In a fresh sidebar press **H**: host → backend → model → confirmation. Selecting
this computer changes only its new-session default. Selecting a remote computer
opens its workspace in a full-size terminal popup. F4 detaches without stopping
remote work; H reconnects. Existing native conversation panes are never restarted
or switched. An explicit CLI local launch uses the stable `hub-local` instance
unless `--instance` is supplied. Remote launches reuse the existing stable remote
instance unless explicitly named. Use the same host/instance to reconnect.

**Execution and inference are different.** Remote Codex runs its shell, tools,
projects, approvals and history on that Linux host. It calls the provider using
that host's sign-in; this does not mean OpenAI's model weights run on the laptop.
A `connection:laptop` Ollama backend instead supplies remote inference while
execution stays on the chosen workspace host. API endpoints similarly provide
inference, not a remote filesystem. Nothing silently falls back locally.

## Install / add another machine

Follow [INSTALLATION.md](INSTALLATION.md) on both machines. All toolchains stay
in Linux/WSL. Build/install Harbor, Codex, Python 3.10+, tmux and Git on the
execution host. Discover its Linux Tailscale device and use its full DNS name:

```bash
harbor connections devices
harbor remote setup laptop --host FULL_DEVICE_DNS --user LINUX_USER
# Add --replace only to intentionally change an existing profile.
harbor remote test laptop
harbor hub models --host laptop
```

Codex sign-in belongs to that host: run `codex login` there in an interactive SSH
terminal (or `codex login --device-auth` where supported), following current
[official authentication guidance](https://learn.chatgpt.com/docs/auth).
Do not copy auth.json, API keys, SSH private keys, session databases or the local
environment to make a remote host work. Native Codex handles authentication and
approvals. Tailscale transport verifies the device and SSH host key; do not turn
off host-key checking or broaden ACLs to repair a connection.

## Providers and subscriptions

Codex is a native agent adapter using its authenticated app-server protocol.
`connection:NAME` adapters use existing `connections.json` profiles; execution
hosts use `development-hosts.json`. No duplicate credential/backend registry is
needed. Each host discovers its own connections and Codex catalog.

```bash
harbor connections add studio --kind responses --url https://provider.example/v1 \
  --key-env PROVIDER_KEY --models exact-model-id
harbor hub models --host local
```

Only set environment variable **names** in profiles. Set actual keys outside
Harbor on the execution host before starting its service. Responses providers
must support Codex's Responses/tools/streaming protocol, not just Chat
Completions. Configured IDs and model catalogs do not prove inference access.
The hub labels this distinction; a successful inference turn is needed to verify
actual account/model access. Discovery never sends a prompt.

A future vendor subscription is **not automatically an API entitlement**. Use
that vendor's supported login and native integration. Add an adapter to `hub.py`
with catalog, capability/auth status and selection behavior; update worker
protocol/capabilities if its launch contract differs from Codex. Do not extract
subscription cookies/tokens, convert a subscription into an unofficial API, or
pretend every backend speaks the same protocol. Current adapters cover native
Codex, Ollama (direct/SSH/Tailscale), and Responses-compatible endpoints only.

## Maintain and diagnose

1. Test **from the source**: `harbor remote test NAME`, then
   `harbor hub models --host NAME`. These check reachability, installation,
   sign-in status and catalogs, not inference.
2. If offline/ambiguous, run `harbor connections devices`; wake the host, restore
   its Linux Tailscale daemon, or deliberately replace its stale DNS profile.
   [TAILSCALE.md](TAILSCALE.md) covers userspace/non-systemd daemon recovery.
3. If sign-in expires, log in on that host. Never auto-change provider/account.
4. For old worker protocol or unknown flags, update Harbor on both ends. Build a
   wheel and `pipx install --force PATH_TO_WHEEL`; pulling Git alone does not
   update installed code. Preserve active panes; reopen sidebar/support UI only
   when safe, and reopen individual conversation terminals at user convenience.
5. Validate catalogs and an isolated workspace on the source after updates. Use
   temporary CODEX_HOME, DATA/BASE_DATA, SOCKET and projects paths for tests.
   Never delete real history or use real sessions as test fixtures. Record exact
   versions, host direction, test limits, and reconnect command in WORKLOG.md.

Codex uses the default stdio app-server for read-only discovery (not obsolete
`--stdio`) and native TUI/Unix-socket transport for interactive sessions. See
[official app-server documentation](https://learn.chatgpt.com/docs/app-server).
No public Codex/Ollama listener is introduced.

### Existing pip-less application venvs

Inspect the launcher's shebang before updating: not every host uses pipx. The
current laptop uses `~/.local/share/harbor-app/venv/bin/python` without pip or
ensurepip. Keep that dedicated environment and launcher; do not install into
system Python. An official temporary pip zipapp can install the wheel there:

```bash
# Run on that Linux host; use a new temporary directory for these artifacts.
work=$(mktemp -d)
curl --fail --location https://bootstrap.pypa.io/pip/pip.pyz -o "$work/pip.pyz"
# First securely transfer the built Harbor wheel to this host.
~/.local/share/harbor-app/venv/bin/python "$work/pip.pyz" --version
~/.local/share/harbor-app/venv/bin/python "$work/pip.pyz" install \
  --no-deps --force-reinstall /path/to/harbor-0.4.0-py3-none-any.whl
```

This is a fallback for an **existing dedicated venv**, not a substitute for the
normal pipx installation. Verify the wheel contents and installed package version;
keep installer version/path in the work log. Use `python -m build` (sdist then
wheel in a clean build tree), not a wheel-only build over stale renamed-package
build directories. An old build cache can accidentally include legacy modules.
The execution-host ID `local` is reserved; use another ID for remote machines.
