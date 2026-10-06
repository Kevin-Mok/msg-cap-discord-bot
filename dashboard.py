"""Coalesced status edits with separately throttled sticky relocation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Awaitable, Callable, Sequence

if TYPE_CHECKING:
    from bot import Delete, Store, Tracker

LOG = logging.getLogger('messagecap')


class Dashboard:
    def __init__(self, store: Store, tracker: Tracker,
                 send: Callable[[str], Awaitable[int]], delete: Delete,
                 *, monotonic: Callable[[], float] = time.monotonic,
                 prepare: Callable[[], Awaitable[None]] | None = None,
                 edit: Callable[[int, str], Awaitable[None]] | None = None,
                 signature: Callable[[], object] | None = None):
        self.store, self.tracker = store, tracker
        self.send, self.delete, self.edit = send, delete, edit
        self.monotonic, self.prepare, self.signature = monotonic, prepare, signature
        self.last_attempt = float('-inf')
        self.published = -1  # Persisted batches are replaced after restart.
        self.lock = asyncio.Lock()
        self._contents: list[str] | None = None
        self._signature: object = None
        self._batch_ids: list[tuple[int, int]] = []
        self._last_relocation = float('-inf')
        self._activity = 0
        self._published_activity = 0

    def note_activity(self) -> None:
        """Request relocation after a post, without delaying ordinary edits."""
        self._activity += 1

    async def refresh(self) -> None:
        # Imports stay local so bot can expose this class without a cycle.
        from bot import DeleteFailed, render_dashboard

        async with self.lock:
            if self.tracker.retired:
                return
            await self.tracker.rollover()
            if self.tracker.retired:
                return
            if self.prepare is not None:
                await self.prepare()
            if self.tracker.retired:
                return
            async with self.tracker.lock:
                if self.tracker.retired:
                    return
                revision = self.tracker.revision
                contents = render_dashboard(self.tracker)
                signature = self.signature() if self.signature is not None else None
            now = self.monotonic()
            statuses = self.store.status_ids()
            activity = self._activity
            fast = self.edit is not None
            relocate = (fast and activity != self._published_activity
                        and now - self._last_relocation >= 5)
            replace = (not fast or self.published == -1 or self._contents is None
                       or statuses != self._batch_ids or len(contents) != len(statuses)
                       or relocate)
            unchanged = (contents == self._contents and signature == self._signature)
            if fast and unchanged and not replace:
                # A revision may change fields omitted from the rendered summary.
                self.published = revision
                return
            if not fast and self.published == revision:
                return
            if now - self.last_attempt < (1 if fast else 5):
                return
            self.last_attempt = now
            try:
                if not replace:
                    replace = not await self._edit(statuses, contents)
                if self.tracker.retired:
                    return
                if replace:
                    if not await self._replace(contents):
                        return
                    self._last_relocation = now
                    self._published_activity = activity
                if self.tracker.retired:
                    return
                # An external deletion during the last await invalidates the batch.
                if self.store.status_ids() != self._batch_ids:
                    self.published = -1
                    return
                self._contents = contents
                self._signature = signature
                self.published = revision
            except DeleteFailed:
                LOG.error('Counter refresh failed in channel %s; check channel permissions and connectivity.',
                          self.tracker.channel_id)

    async def _edit(self, statuses: list[tuple[int, int]], contents: list[str]) -> bool:
        from bot import MissingMessage

        assert self.edit is not None
        for (message_id, _channel_id), text in zip(statuses, contents):
            if self.tracker.retired:
                return False
            try:
                await self.edit(message_id, text)
            except MissingMessage:
                if self.tracker.retired:
                    return False
                self.store.forget_status(message_id)
                self.published = -1
                return False
            if self.tracker.retired:
                return False
        return True

    async def _replace(self, contents: list[str]) -> bool:
        from bot import MissingMessage

        self.published = -1
        for message_id, channel_id in self.store.status_ids():
            if self.tracker.retired:
                return False
            if channel_id != self.tracker.channel_id:
                LOG.warning('Forgetting old counter %s in previous channel %s; remove it manually.',
                            message_id, channel_id)
            else:
                try:
                    await self.delete(message_id)
                except MissingMessage:
                    pass
            if self.tracker.retired:
                return False
            self.store.forget_status(message_id)
        batch = []
        for text in contents:
            if self.tracker.retired:
                return False
            message_id = await self.send(text)
            if self.tracker.retired:
                return False
            self.store.remember_status(message_id, self.tracker.channel_id)
            batch.append((message_id, self.tracker.channel_id))
        self._batch_ids = batch
        return True

    def removed(self, message_ids: Sequence[int]) -> None:
        if self.tracker.retired:
            return
        stored = {mid for mid, _ in self.store.status_ids()}
        for message_id in message_ids:
            if message_id in stored:
                self.store.forget_status(message_id)
                self.published = -1
