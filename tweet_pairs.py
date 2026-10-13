"""Persist exact reply links and select eligible Pistol/Saucy cleanup pairs."""
from __future__ import annotations

import sqlite3
from typing import Mapping

PISTOL_ID = 142822767497052161
SAUCY_ID = 647368715742216193


def reply_source(message: object, channel_id: int) -> int | None:
    """Ignore absent and cross-channel references without fetching Discord data."""
    reference = getattr(message, 'reference', None)
    if reference is None or getattr(reference, 'channel_id', None) != channel_id:
        return None
    source = getattr(reference, 'message_id', None)
    return source if type(source) is int and source > 0 else None


class TweetPairs:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        connection.execute('''CREATE TABLE IF NOT EXISTS tweet_pairs (
            reply_id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL)''')
        columns = [row[1] for row in connection.execute('PRAGMA table_info(tweet_pairs)')]
        if columns != ['reply_id', 'source_id']:
            raise ValueError('Invalid tweet pair schema; restore a database backup.')
        invalid = connection.execute('''SELECT 1 FROM tweet_pairs WHERE
            typeof(reply_id) != 'integer' OR reply_id <= 0 OR
            typeof(source_id) != 'integer' OR source_id <= 0 OR reply_id=source_id LIMIT 1''').fetchone()
        if invalid:
            raise ValueError('Invalid persisted tweet reply IDs; restore a database backup.')

    def remember(self, reply_id: int, source_id: int | None, owners: Mapping[int, int]) -> None:
        if (type(source_id) is int and source_id > 0 and source_id != reply_id
                and owners.get(reply_id) == SAUCY_ID and owners.get(source_id) == PISTOL_ID):
            self.connection.execute('INSERT OR IGNORE INTO tweet_pairs VALUES (?, ?)', (reply_id, source_id))

    def candidates(self, user_id: int, owners: Mapping[int, int]) -> dict[int, int]:
        if user_id not in (PISTOL_ID, SAUCY_ID):
            return {}
        pairs = {}
        for reply, source in self.connection.execute('SELECT reply_id, source_id FROM tweet_pairs ORDER BY reply_id'):
            if owners.get(reply) == SAUCY_ID and owners.get(source) == PISTOL_ID:
                candidate, partner = (source, reply) if user_id == PISTOL_ID else (reply, source)
                pairs.setdefault(candidate, partner)
        return pairs
