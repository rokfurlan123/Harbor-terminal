import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('wsl_setup', Path(__file__).resolve().parents[1] / 'scripts/setup_wsl_tailscale.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class StartupConfigTests(unittest.TestCase):
    def test_preserves_existing_sections_and_comments(self):
        original = '# keep this\n[user]\ndefault=rokdbest\n'
        updated = setup.boot_config(original)
        self.assertTrue(updated.startswith(original))
        self.assertIn('[boot]\ncommand=' + str(setup.HELPER), updated)
        self.assertEqual(updated, setup.boot_config(updated))

    def test_boot_before_other_sections(self):
        original = '[boot]\n# keep\n[user]\ndefault=rokdbest'
        updated = setup.boot_config(original)
        self.assertIn('# keep\ncommand=' + str(setup.HELPER) + '\n[user]', updated)
        self.assertTrue(updated.endswith('default=rokdbest\n'))

    def test_empty_command_and_no_final_newline(self):
        updated = setup.boot_config('[boot]\ncommand=')
        self.assertEqual(updated.count('command='), 1)
        self.assertEqual(updated, setup.boot_config(updated))

    def test_refuses_existing_hook(self):
        with self.assertRaisesRegex(ValueError, 'preserved'):
            setup.boot_config('[boot]\ncommand=service docker start\n')

    def test_refuses_systemd_machine(self):
        with self.assertRaisesRegex(ValueError, 'systemctl'):
            setup.boot_config('[boot]\nsystemd=true\n')

    def test_atomic_write_permissions(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'helper'
            setup.atomic_write(path, setup.STARTER, 0o755)
            self.assertEqual(path.read_text(), setup.STARTER)
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(Path(directory).iterdir()), [path])
