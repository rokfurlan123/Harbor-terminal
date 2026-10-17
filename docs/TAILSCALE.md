# Tailscale model connection recipe

Harbor remembers the steps of a working Tailscale SSH connection in its connector
and this guide. Connection profiles supply the machine-specific values. This
first guided transport targets an Ollama server; it supports any model installed
there. Adding other API formats or transports is separate work.

## What the user enters

In the sidebar press **C**, then **s Setup Tailscale**:

| Value | Example | Meaning |
| --- | --- | --- |
| Connection name | laptop | A name used in Harbor’s model picker |
| Computer | strawberry-laptop-linux | Tailscale name, full DNS name, or IP |
| Linux username | rokdbest | Account on the model computer |
| Remote port | 11434 | Model API on that computer’s loopback interface |
| Model (optional) | local-qwen | Select for new sessions after verification |

A blank username uses the current Linux account; a blank port uses 11434. A blank
model leaves the current default unchanged. Cancel before submission saves
nothing. An existing connection needs explicit replacement confirmation.

The terminal supports the same operation:

```bash
harbor connections devices
harbor connections setup
# Or provide the fields directly:
harbor connections setup laptop --host strawberry-laptop-linux --user rokdbest --model local-qwen
harbor connections test laptop
harbor models list --connection laptop
```

Use `--remote-port` for a different Ollama port and `--replace` for an existing
connection. Setup does not submit an AI prompt, download weights, install a
remote daemon, or change running conversations. It verifies discovery and access.
A real reply is a separate inference check when the user requests one.

## What Harbor does

1. Find the Linux Tailscale CLI. Normal PATH and common Linux user install
   locations are supported; `HARBOR_TAILSCALE` explicitly selects an executable.
2. Read the authenticated local daemon’s device map. A normal system daemon is
   tried first. A running userspace daemon belonging to the same Linux user can
   be detected from its declared socket. `HARBOR_TAILSCALE_SOCKET`, or the
   per-connection `--tailscale-socket`, selects a custom socket explicitly.
3. Match exactly one online peer by name, DNS name, or Tailscale IPv4 address.
   A short ambiguous name needs a full name/IP. Public DNS is not used as a
   fallback; an unknown device is an error.
4. Use `tailscale ssh` with OpenSSH BatchMode and strict host-key verification.
   Tailscale checks the host key against the coordination server and supplies
   its userspace ProxyCommand. Harbor does not accept unverified host keys.
5. Forward an automatically chosen local **127.0.0.1** port to the model host’s
   **127.0.0.1:remote-port**. No Ollama listener is exposed to the network.
6. Read Ollama’s `/api/tags`. If a model was supplied, verify its canonical name
   (including an implicit `:latest` tag). Save only after these checks pass.
7. Persist the profile privately in Harbor’s base `connections.json` (0600).
   Store the optional selected model in this instance’s normal preferences.
   No passwords, API keys, or Tailscale identity files are copied.
8. Open a fresh owned tunnel for each model operation or conversation and close
   it when that operation/conversation exits. Reopening resolves the peer and
   reconnects. No fixed tunnel process, shell alias, or manual port reservation
   is required. Existing native approvals and conversation history stay intact.

## Prerequisites and recovery

Both Linux environments need Tailscale installed and signed into the same
permitted tailnet. The model computer must be awake with Ollama running and
Tailscale SSH enabled. Administrative first-time setup can still be required:
Harbor cannot grant itself network/SSH permissions without an administrator.

| Symptom | What to do |
| --- | --- |
| CLI/daemon missing | Start/install Linux Tailscale or configure its executable/socket |
| Not connected | Sign in to Tailscale in that Linux/WSL environment |
| Device missing | Check the name, tailnet, and device visibility; list devices |
| Device offline | Wake it and start its Linux Tailscale client |
| Connection refused | Enable Tailscale SSH on the destination: `sudo tailscale set --ssh` |
| SSH policy blocks access | Permit this source → that destination as the entered Linux username |
| SSH host key cannot be verified | Confirm the destination is running Tailscale SSH; use the regular SSH connector for ordinary OpenSSH with separately verified keys |
| SSH login denied | Check the Linux account and permitted SSH usernames |
| Ollama API unavailable | Start Ollama on the destination and verify its loopback port |
| Model missing | Choose an installed model or explicitly install one on the model computer |

SSH rules are directional. An allow rule for **PC → laptop** does not permit
**laptop → PC**. Our verified PC → laptop rule uses the existing tags
`tag:strawberry-ssh-client` → `tag:local-ai-ssh`, user `rokdbest`. The reverse rule
was added separately. Those names describe the current devices; future devices
need their own approved identity/rule. Keep existing unrelated policy entries.
A Tailscale SSH permission rule and network permission for TCP 22 are both needed.

Harbor reports which stage failed and leaves an existing saved connection
unchanged on setup failure. It never silently falls back to a cloud model,
opens a public listener, edits tailnet policy, or disables host-key checking.

## Verify from the computer that will use the model

Run setup/test/model listing **on the source PC**, not just on the destination.
For an authorized inference test use an isolated Harbor home/data/tmux socket,
select the saved connection, send a short disposable prompt, and verify the
saved reply and reopen behavior. Do not copy real sign-in data or use live
conversations as test fixtures. Preserve running conversation panes during app
updates; a new workspace or a support-sidebar reload exposes the new wizard.

The known deployment is **strawberry (100.89.111.39) →
strawberry-laptop-linux (100.124.226.26) → loopback Ollama 11434**. This workflow
also works for another permitted Linux Tailscale peer and any model its Ollama
catalog reports. It does not require the separate chat website or its access key.
