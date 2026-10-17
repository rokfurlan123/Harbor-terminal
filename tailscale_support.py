"""Tailscale device discovery and authenticated SSH, without machine-specific recipes."""
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess


def executable():
    configured = os.environ.get('HARBOR_TAILSCALE')
    if configured:
        found = shutil.which(configured)
        if not found:
            raise RuntimeError('HARBOR_TAILSCALE does not point to an executable Tailscale CLI.')
        return found
    for candidate in ('tailscale', str(Path.home()/'.local/bin/tailscale'),
                      str(Path.home()/'bin/tailscale'), str(Path.home()/'tools/tailscale/tailscale')):
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError('Tailscale CLI not found. Install Tailscale in Linux/WSL and sign in, or set HARBOR_TAILSCALE to its executable.')


def user_sockets():
    """Find sockets advertised by this user's running Linux tailscaled processes."""
    found = set()
    try:
        processes = Path('/proc').iterdir()
        for path in processes:
            if not path.name.isdigit():
                continue
            try:
                if path.stat().st_uid != os.getuid():
                    continue
                args = (path/'cmdline').read_bytes().decode(errors='replace').split('\0')
                if not args or Path(args[0]).name != 'tailscaled':
                    continue
                for i, arg in enumerate(args):
                    value = arg.split('=', 1)[1] if arg.startswith('--socket=') else (args[i+1] if arg == '--socket' and i+1<len(args) else None)
                    if value and Path(value).is_absolute():
                        found.add(value)
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return sorted(found)


def status(socket_path=None):
    binary = executable()
    explicit = socket_path or os.environ.get('HARBOR_TAILSCALE_SOCKET')
    candidates = [explicit] if explicit else [None, *user_sockets()]
    disconnected = False
    for candidate in candidates:
        command = [binary] + (['--socket='+candidate] if candidate else [])
        try:
            result = subprocess.run(command+['status', '--json'], capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            continue
        if result.returncode:
            continue
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                continue
        except (ValueError, TypeError):
            continue
        if value.get('BackendState') != 'Running':
            disconnected = True
            continue
        peers = value.get('Peer') or {}
        if not isinstance(peers, dict) or not all(isinstance(p, dict) for p in peers.values()):
            raise RuntimeError('Tailscale returned an invalid device list.')
        return command, value
    if disconnected:
        raise RuntimeError('Tailscale is not connected. Sign in to Tailscale in this Linux/WSL environment, then retry.')
    raise RuntimeError('Cannot reach the Linux Tailscale daemon. Start Tailscale, or set HARBOR_TAILSCALE_SOCKET to its userspace daemon socket.')


def devices(socket_path=None):
    _, state = status(socket_path)
    return sorted([{'name': p.get('DNSName', '').rstrip('.') or p.get('HostName', ''),
                    'hostname': p.get('HostName', ''), 'addresses': p.get('TailscaleIPs', []),
                    'online': bool(p.get('Online')), 'os': p.get('OS', '')}
                   for p in (state.get('Peer') or {}).values()], key=lambda p: p['name'].lower())


def prepare(profile):
    """Resolve only a device in the authenticated tailnet; never use public DNS."""
    command, state = status(profile.get('tailscale_socket'))
    username, host = profile['ssh'].split('@', 1)
    name = host.rstrip('.').lower()
    peers = list((state.get('Peer') or {}).values())
    matches = [p for p in peers if name in {
        str(p.get('HostName', '')).lower(), str(p.get('DNSName', '')).rstrip('.').lower(),
        str(p.get('DNSName', '')).split('.')[0].lower(),
        *[str(ip).lower() for ip in p.get('TailscaleIPs', [])]}]
    if len(matches) != 1:
        raise RuntimeError('Tailscale device not found or name is ambiguous: '+host+'. Use a full device DNS name or Tailscale IP; run harbor connections devices.')
    peer = matches[0]
    if not peer.get('Online'):
        raise RuntimeError(host+' is offline in Tailscale. Wake that computer and connect its Linux Tailscale client, then retry.')
    addresses = peer.get('TailscaleIPs') or []
    ipv4 = []
    for address in addresses:
        try:
            if ipaddress.ip_address(address).version == 4:
                ipv4.append(address)
        except ValueError:
            continue
    if not ipv4:
        raise RuntimeError('The Tailscale device has no IPv4 address. Use a device with a Tailscale IPv4 address for this connector.')
    # The supported Tailscale wrapper supplies userspace routing and verifies
    # SSH host keys against the coordination server, including on first use.
    return command+['ssh', username+'@'+ipv4[0]]


def failure(profile, stderr):
    target = profile['ssh']
    username = target.split('@', 1)[0]
    lower = stderr.lower()
    if 'tailnet policy does not permit' in lower or 'access denied' in lower:
        return 'Tailscale SSH policy blocks '+target+'. In Tailscale Access controls, allow this source device to SSH to that destination as '+username+'. The reverse direction is a separate rule.'
    if 'host key' in lower or 'known_hosts' in lower:
        return 'Tailscale could not verify the SSH host key for '+target+'. Enable Tailscale SSH on the destination (sudo tailscale set --ssh), then retry. Harbor did not bypass host-key checks.'
    if 'refused' in lower:
        return 'SSH is not listening on '+target+'. On that computer, enable Tailscale SSH with sudo tailscale set --ssh, then check its SSH policy.'
    if 'permission denied' in lower:
        return 'SSH login denied for '+target+'. Check that the Linux username exists and the Tailscale SSH rule permits that username.'
    return 'Tailscale SSH connection failed for '+target+'. Check device connectivity, the destination SSH service, username, and Tailscale SSH access rules.'
