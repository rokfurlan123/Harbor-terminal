---
name: harbor-hub
description: Install, extend, connect, or maintain Harbor execution hosts and Codex, Ollama, or provider backends. Use for Harbor hub routing and connection repair, not generic Codex configuration or unrelated SSH administration.
---

# Harbor hub

Find the actual Harbor checkout and read its AGENTS.md and docs/HUB.md. This
machine's maintained checkout is /home/rokdbest/codex-workspace (the empty
harbor-ide directory is not the application source). For another machine, locate
its checkout rather than assuming this absolute path. Installed pipx packages
are copies, not the source of truth.

Preserve the principle: **execution host × backend × model**. Discover hosts and
catalogs, support arbitrary profile counts, and extend adapters rather than
hardcoding machines, model IDs or provider-specific branches into the UI.
Remote Codex executes on the selected host; remote inference alone does not
move files or tools. Tell users which machine executes and where inference goes.

For installation/update read docs/INSTALLATION.md; for Tailscale recovery read
docs/TAILSCALE.md. Use `harbor hub hosts`, `harbor remote test NAME`, and
`harbor hub models --host NAME` from the source. Discovery sends no model prompts
and proves neither paid entitlement nor inference compatibility. Use an isolated
inference smoke test only when authorized and report exactly what was verified.

Use supported native authentication on each execution host. Never copy secrets,
API-key values, auth caches, user history or credentials between hosts. A vendor
subscription needs an official supported adapter/login, not an assumed API key
or token extraction. Profiles may store environment-variable names only. Keep
SSH/Tailscale authentication, host-key verification and approvals intact. Fail
closed on unknown/offline hosts, missing models and expired login; no implicit
local/provider/account fallback.

Installation is Linux/WSL only. Build/test/package in the maintained checkout,
install the resulting wheel on both ends, verify source-to-destination behavior,
and record versions/paths and reconnection instructions. Do not overwrite dirty
remote source or restart active conversation panes. Follow the project's
workflow for isolated tests, scoped commits and push. Keep docs/HUB.md and these
instructions current as adapter contracts evolve; distinguish current support
from future plans.
