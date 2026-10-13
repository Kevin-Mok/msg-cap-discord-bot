"""Cap cleanup pairing regressions using real SQLite and tracker accounting."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import bot

PISTOL = 142822767497052161
SAUCY = 647368715742216193


class PairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = bot.Store(Path(self.tmp.name) / 'pairs.sqlite3')
        self.addCleanup(lambda: self.store.close())
        self.now = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)
        self.deleted = []
        self.failed_ids = set()
        self.missing = set()
        self.tracker = self.reopen()

    def reopen(self):
        return bot.Tracker(self.store, 123, 2, 'America/Toronto',
                           now=lambda: self.now, choose=lambda ids: ids[0], delete=self.delete)

    async def delete(self, mid):
        if mid in self.failed_ids:
            raise bot.DeleteFailed('permission denied')
        if mid in self.missing:
            raise bot.MissingMessage()
        self.deleted.append(mid)

    async def send(self, mid, uid, source=None):
        if source is None:
            return await self.tracker.process(mid, uid, str(uid), self.now)
        return await self.tracker.process(mid, uid, str(uid), self.now, reply_to=source)

    async def seed(self):
        await self.send(1, PISTOL)
        await self.send(10, SAUCY, 1)
        await self.send(2, PISTOL)
        await self.send(11, SAUCY, 2)

    async def test_pistol_over_cap_prefers_unmatched_original(self):
        await self.seed()
        await self.send(3, PISTOL)
        self.assertEqual(self.deleted, [3])
        self.assertEqual(dict((uid, (sent, retained)) for uid, _, sent, retained in self.tracker.rows()),
                         {PISTOL: (3, 2), SAUCY: (2, 2)})

    async def test_saucy_over_cap_deletes_matching_original(self):
        await self.seed()
        await self.send(12, SAUCY, 1)
        self.assertEqual(self.deleted, [10, 1])

    async def test_pairs_survive_tracker_restart(self):
        await self.seed()
        self.store.close()
        self.store = bot.Store(Path(self.tmp.name) / 'pairs.sqlite3')
        self.tracker = self.reopen()
        await self.send(12, SAUCY, 1)
        self.assertEqual(self.deleted, [10, 1])

    async def test_exempt_counterpart_falls_back_to_single(self):
        await self.seed()
        await self.tracker.clear_user_cap(PISTOL)
        await self.send(12, SAUCY, 1)
        self.assertEqual(self.deleted, [10])
        self.assertIn(1, self.tracker.owners)

    async def test_reset_counterpart_is_not_deleted(self):
        await self.seed()
        await self.tracker.reset(SAUCY)
        await self.send(3, PISTOL)
        self.assertEqual(self.deleted, [1])

    async def test_other_authors_are_never_paired(self):
        await self.send(1, 7)
        await self.send(10, SAUCY, 1)
        await self.send(11, SAUCY)
        await self.send(12, SAUCY)
        self.assertEqual(self.deleted, [10])
        self.assertIn(1, self.tracker.owners)

    async def test_failed_first_delete_preserves_both(self):
        await self.seed()
        self.failed_ids.add(10)
        with self.assertLogs('messagecap', level='ERROR'):
            await self.send(12, SAUCY, 1)
        self.assertEqual(self.deleted, [])
        self.assertIn(1, self.tracker.owners)

    async def test_failed_counterpart_keeps_honest_retained_counts(self):
        await self.seed()
        self.failed_ids.add(1)
        with self.assertLogs('messagecap', level='ERROR'):
            await self.send(12, SAUCY, 1)
        self.assertEqual(self.deleted, [10])
        self.assertIn(1, self.tracker.owners)
        self.assertNotIn(10, self.tracker.owners)

    async def test_missing_counterpart_is_reconciled(self):
        await self.seed()
        self.missing.add(1)
        await self.send(12, SAUCY, 1)
        self.assertEqual(self.deleted, [10])
        self.assertNotIn(1, self.tracker.owners)

    async def test_old_unmatched_original_precedes_complete_pair(self):
        await self.send(1, PISTOL)
        await self.send(2, PISTOL)
        await self.send(10, SAUCY, 2)
        await self.send(3, PISTOL)
        self.assertEqual(self.deleted, [1])
        self.assertIn(2, self.tracker.owners)
        self.assertIn(10, self.tracker.owners)

    async def test_unmatched_saucy_preserves_complete_pairs(self):
        await self.seed()
        await self.send(12, SAUCY)
        self.assertEqual(self.deleted, [12])
        self.assertIn(1, self.tracker.owners)
        self.assertIn(10, self.tracker.owners)

    async def test_deleted_reply_makes_original_unmatched(self):
        await self.seed()
        await self.tracker.removed([10])
        await self.send(3, PISTOL)
        self.assertEqual(self.deleted, [1])
        self.assertIn(2, self.tracker.owners)
        self.assertIn(11, self.tracker.owners)

    async def test_midnight_clears_pair_links(self):
        await self.seed()
        self.now += timedelta(days=1)
        await self.tracker.rollover()
        self.assertEqual(self.store.connection.execute('SELECT * FROM tweet_pairs').fetchall(), [])
        await self.send(20, PISTOL)
        await self.send(21, PISTOL)
        await self.send(22, PISTOL)
        self.assertEqual(self.deleted, [20])

    async def test_live_adapter_records_same_channel_reply_only(self):
        client = bot.create_client(bot.Settings('unused', 123, 2), self.store)
        await client._async_setup_hook()
        self.addAsyncCleanup(client.close)
        client.tracker = self.tracker
        client.channel = SimpleNamespace(id=123)
        def message(mid, uid, source=None, source_channel=123):
            return SimpleNamespace(id=mid, channel=client.channel, guild=SimpleNamespace(id=456),
                author=SimpleNamespace(id=uid, display_name=str(uid), bot=uid == SAUCY),
                webhook_id=None, content='', created_at=self.now,
                reference=None if source is None else SimpleNamespace(message_id=source, channel_id=source_channel))
        for post in (message(1, PISTOL), message(10, SAUCY, 1), message(2, PISTOL),
                     message(11, SAUCY, 2), message(12, SAUCY, 1, 999)):
            await client.process_message(post)
        self.assertEqual(self.deleted, [12])
        self.assertEqual(self.store.connection.execute('SELECT * FROM tweet_pairs ORDER BY reply_id').fetchall(),
                         [(10, 1), (11, 2)])

    async def test_history_recovers_pairs_without_retroactive_deletion(self):
        from restart_recovery import RestartRecovery
        def message(mid, uid, source=None):
            return SimpleNamespace(id=mid, channel=SimpleNamespace(id=123), guild=SimpleNamespace(id=456),
                author=SimpleNamespace(id=uid, display_name=str(uid), bot=uid == SAUCY),
                webhook_id=None, content='', created_at=self.now - timedelta(minutes=1),
                reference=None if source is None else SimpleNamespace(message_id=source, channel_id=123))
        async def history(**kwargs):
            for post in (message(1, PISTOL), message(10, SAUCY, 1),
                         message(2, PISTOL), message(11, SAUCY, 2)):
                yield post
        self.assertTrue(await RestartRecovery(self.tracker).refresh(SimpleNamespace(history=history), 999))
        self.assertEqual(self.deleted, [])
        await self.send(12, SAUCY, 1)
        self.assertEqual(self.deleted, [10, 1])
