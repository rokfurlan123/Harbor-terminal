import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('qwen_install', Path(__file__).resolve().parents[1] / 'scripts/install_local_qwen.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class QwenLauncherTests(unittest.TestCase):
    def test_prompt_literal_arguments_and_interactive(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary = home / '.local/bin/ollama'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            binary.chmod(0o700)
            launcher = installer.install(home)
            self.assertEqual(installer.install(home), launcher)
            import json
            env = dict(os.environ, HOME=str(home))
            def call(*args):
                return json.loads(subprocess.check_output([str(launcher), *args], env=env, text=True))
            self.assertEqual(call(), ['run', 'local-qwen', '--think=false'])
            self.assertEqual(call('hello', '$(touch injected); "world"'),
                             ['run', 'local-qwen', '--think=false', 'hello $(touch injected); "world"'])

    def test_missing_ollama_and_existing_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'Ollama'):
                installer.install(home)
            binary = home / '.local/bin/ollama'
            binary.parent.mkdir(parents=True)
            binary.touch(mode=0o700)
            launcher = binary.with_name('qwen')
            launcher.write_text('unrelated')
            with self.assertRaisesRegex(RuntimeError, 'overwrite'):
                installer.install(home)
            self.assertEqual(launcher.read_text(), 'unrelated')
            launcher.unlink()
            launcher.symlink_to(binary)
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                installer.install(home)
