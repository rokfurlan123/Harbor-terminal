from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import workspace as app


class TemporarySessionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(app, 'DATA', Path(temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rpc = object.__new__(app.Rpc)
        self.rpc.call = Mock(return_value={'data': [], 'nextCursor': None})
        self.cwd = str(Path.home())

    def new(self, live_ids=()):
        return self.rpc.create_or_reuse('New session', self.cwd, 'auto', set(live_ids))

    def test_repeated_new_reuses_open_blank_without_saving_it(self):
        first = self.new()
        second = self.new([first['id']])
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.rpc.threads(), [])
        self.assertTrue(second['temporary'])

    def test_closed_or_restarted_blank_disappears(self):
        first = self.new()
        self.assertEqual(self.rpc.threads(live_ids=set()), [])
        with app.drafts() as db:
            self.assertIsNone(db.execute('SELECT id FROM drafts WHERE id=?', (first['id'],)).fetchone())
        self.assertNotEqual(first['id'], self.new()['id'])

    def test_catalog_snapshot_during_native_id_handoff_keeps_blank(self):
        first = self.new()
        native = {**first, 'id': 'native-id', 'workspaceDraftId': first['id']}
        with app.drafts() as db:
            db.execute('UPDATE drafts SET id=?,data=? WHERE id=?',
                       (native['id'], json.dumps(native), first['id']))
        items = self.rpc.threads(live_ids={first['id']})
        self.assertEqual(items[0]['id'], native['id'])
        self.assertEqual(self.new([native['id']])['id'], native['id'])

    def test_first_message_history_is_preserved_and_new_creates_another(self):
        first = self.new()
        recorded = {'id': first['id'], 'cwd': self.cwd, 'preview': 'My first message', 'name': 'Real chat'}
        self.rpc.call.return_value = {'data': [recorded], 'nextCursor': None}
        saved = self.rpc.threads(live_ids=set())
        self.assertEqual(saved[0]['id'], first['id'])
        self.assertFalse(saved[0].get('temporary'))
        self.assertNotEqual(self.new([first['id']])['id'], first['id'])
        self.assertEqual(app.session_mode(first['id']), 'auto')

    def test_old_blank_is_reused_but_named_saved_chat_is_not(self):
        legacy = self.rpc.create('New session', self.cwd)
        self.assertEqual(self.new([legacy['id']])['id'], legacy['id'])
        self.rpc.call.return_value = {'data': [{'id': legacy['id'], 'name': 'New session',
            'cwd': self.cwd, 'preview': 'Already started'}], 'nextCursor': None}
        self.assertNotEqual(self.new([legacy['id']])['id'], legacy['id'])

    def test_reopening_temporary_does_not_duplicate_sidebar_row(self):
        side = app.Sidebar(Mock())
        self.addCleanup(side.pool.shutdown)
        side.workspace = Mock()
        thread = self.new()
        side.open_created(thread)
        side.open_created(thread)
        self.assertEqual([t['id'] for t in side.items], [thread['id']])
