"""Compact, per-conversation configuration for Ollama clients."""
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parent


def enabled(model):
    return bool(model and (model.get('provider') == 'ollama' or model.get('backend') == 'ollama'))


def web_enabled():
    return os.environ.get('HARBOR_OLLAMA_WEB', '1').lower() not in ('0', 'false', 'off')


def overrides(model):
    if not enabled(model):
        return {}
    config = {
        'web_search': 'disabled',
        'model_instructions_file': str(ROOT / 'policies/ollama.md'),
        'model_context_window': 8192,
        'model_auto_compact_token_limit': 6000,
        'features.goals': False,
        'features.apps': False,
        'features.tool_suggest': False,
        'features.multi_agent': False,
        'features.view_image': False,
        'features.image_generation': False,
    }
    if web_enabled():
        config['mcp_servers.harbor_web'] = {
            'command': sys.executable, 'args': [str(ROOT / 'web_tools.py')],
            'enabled': True, 'enabled_tools': ['search', 'fetch'],
            'startup_timeout_sec': 10, 'tool_timeout_sec': 45,
        }
    else:
        config['mcp_servers.harbor_web.enabled'] = False
    return config


def facts(model):
    if not enabled(model):
        return ''
    data = {
        'model': model['model'],
        'inference': model.get('inference', 'Ollama on ' + socket.gethostname()),
        'interface': 'Harbor text interface using the native Codex client',
        'tools_run_on': socket.gethostname(),
        'public_web_tools': web_enabled(),
    }
    return ('\n\n[Verified local runtime facts]\n' + json.dumps(data, ensure_ascii=True) +
            '\nUse these deployment facts when asked how we communicate or where you run. '
            'For SSH, inference runs on the named remote destination; tools_run_on is the client computer, not the model host. '
            'Do not confuse the model developer Alibaba with the inference host. '
            'Web tools access public websites, not an Alibaba/Ollama cloud inference service. '
            'Queries and fetched URLs are sent to external websites; do not include secrets.')


def toml(value):
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + '=' + toml(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(toml(v) for v in value) + ']'
    return json.dumps(value)
