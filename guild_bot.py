"""One Discord connection with isolated channel controllers for each guild."""
import asyncio
from contextlib import AsyncExitStack, suppress
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys

import aiohttp
import discord
from discord import app_commands

from bot import (LOG, Settings, Store, channel_input, create_client, load_config,
                 save_config)

NETWORK_ERRORS = (discord.HTTPException, OSError, aiohttp.ClientError, app_commands.AppCommandError)


def check_guild_data(config_path: Path) -> int:
    """Validate saved guild configs and databases without connecting to Discord."""
    count = 0
    for path in (config_path.resolve().parent / 'guild_data').glob('*/config.json'):
        if not path.parent.name.isdecimal() or not 0 < int(path.parent.name) < 2**64:
            raise ValueError('Invalid saved server directory; restore guild_data from backup.')
        load_config(path)
        store = Store(path.parent / 'data.sqlite3')
        store.close()
        count += 1
    return count


def create_guild_client(defaults: Settings, legacy: Store, *, config_path: Path):
    root = config_path.resolve().parent / 'guild_data'

    class GuildTree(app_commands.CommandTree):
        async def on_error(self, interaction, error):
            original = getattr(error, 'original', error)
            text = str(original) if isinstance(original, ValueError) else 'Command failed. Check bot logs and try /cap_status before retrying.'
            LOG.error('Guild command failed (%s).', type(original).__name__)
            send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    class GuildClient(discord.Client):
        def __init__(self):
            intents = discord.Intents.none()
            intents.guilds = True
            intents.guild_messages = True
            intents.guild_reactions = True
            super().__init__(intents=intents, max_messages=None, allowed_mentions=discord.AllowedMentions.none())
            self.tree = GuildTree(self)
            self.controllers = {}
            self.stores: dict[int, Store] = {}
            self.locks: dict[int, asyncio.Lock] = {}
            self.synced: set[int] = set()
            self.worker = None
            self.prompt = None
            self.startup_error = None

            @self.tree.command(name='cap_channel', description='Set this server’s message-cap channel.')
            @app_commands.guild_only()
            @app_commands.default_permissions(manage_guild=True)
            @app_commands.describe(channel='Text channel to monitor in this server')
            async def cap_channel(interaction: discord.Interaction, channel: discord.TextChannel):
                await interaction.response.defer(ephemeral=True)
                text = await self.configure_guild(interaction.guild_id, channel, interaction.user)
                await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        def lock_for(self, guild_id: int):
            return self.locks.setdefault(guild_id, asyncio.Lock())

        def config_for(self, guild_id: int) -> Path:
            return root / str(guild_id) / 'config.json'

        def validate_channel(self, guild_id, channel, actor=None):
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild_id:
                raise ValueError('Choose a text channel in the same server as this command.')
            if actor is not None:
                if not isinstance(actor, discord.Member):
                    raise ValueError('Use this command as a server member.')
                permissions = channel.permissions_for(actor)
                if not (permissions.manage_guild or permissions.administrator):
                    raise ValueError('You need Manage Server or Administrator to set this server’s channel.')
            permissions = channel.permissions_for(channel.guild.me)
            missing = [name for name in ('view_channel', 'send_messages', 'read_message_history', 'manage_messages')
                       if not getattr(permissions, name)]
            if missing:
                raise ValueError('Missing bot permissions: ' + ', '.join(missing))

        async def sync_guild(self, guild_id: int):
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            controller = self.controllers.get(guild_id)
            if controller is not None:
                for command in controller.tree.get_commands():
                    self.tree.add_command(command, guild=guild, override=True)
            commands = await self.tree.sync(guild=guild)
            self.synced.add(guild_id)
            if controller is not None:
                controller.commands_synced = True
            return commands

        async def configure_guild(self, guild_id, channel, actor=None):
            self.validate_channel(guild_id, channel, actor)
            async with self.lock_for(guild_id):
                current = self.controllers.get(guild_id)
                if current is not None and current.channel is not None and current.channel.id == channel.id:
                    return f'Already tracking <#{channel.id}> in this server. Use /cap_help.'
                path = self.config_for(guild_id)
                settings = load_config(path) if path.exists() else defaults
                updated = replace(settings, token=defaults.token, channel_id=channel.id)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                store = self.stores.get(guild_id)
                opened = store is None
                database = path.parent / 'data.sqlite3'
                existing = database.exists()
                snapshot = sqlite3.connect(':memory:')
                snapshot_ready = False
                try:
                    if store is None:
                        store = Store(database)
                        migrated = legacy.connection.execute("SELECT value FROM meta WHERE key='guild_migrated'").fetchone()
                        if not existing and channel.id == defaults.channel_id and migrated is None:
                            legacy.connection.backup(store.connection)
                    async with AsyncExitStack() as stack:
                        if current is not None:
                            await stack.enter_async_context(current.tracker.lock)
                        store.connection.backup(snapshot)
                        snapshot_ready = True
                        # Build and persist before retiring any working controller.
                        controller = create_client(updated, store, config_path=path, gateway=self)
                        save_config(path, updated)
                        if current is not None:
                            current.tracker.retired = True
                            current.channel = None
                except (OSError, ValueError, sqlite3.Error):
                    if store is not None:
                        if snapshot_ready:
                            snapshot.backup(store.connection)
                        if opened:
                            store.close()
                    if opened and not existing:
                        database.unlink(missing_ok=True)
                    raise
                finally:
                    snapshot.close()
                controller.channel = channel
                controller.recovery.request()
                controller.get_channel = self.get_channel
                controller.fetch_channel = self.fetch_channel
                async def sync_commands(guild_id: int):
                    return await self.sync_guild(guild_id)
                async def close_controller():
                    controller.channel = None
                    controller.tracker.retired = True
                    LOG.error('Tracking paused for guild %s; repair it with /cap_channel.', guild_id)
                controller.sync_commands = sync_commands
                controller.close = close_controller
                self.controllers[guild_id] = controller
                self.stores[guild_id] = store
                if channel.id == defaults.channel_id:
                    with legacy.connection:
                        legacy.connection.execute("INSERT OR IGNORE INTO meta VALUES ('guild_migrated', ?)", (str(guild_id),))
                if self.prompt is not None and self.prompt is not asyncio.current_task():
                    self.prompt.cancel()
                try:
                    await self.sync_guild(guild_id)
                    suffix = 'Slash commands ready: /cap_help.'
                except NETWORK_ERRORS:
                    LOG.error('Slash sync failed for guild %s; counting remains active.', guild_id)
                    suffix = 'Counting is active. Use @bot slash sync to retry command registration.'
                return f'Now tracking <#{channel.id}> for this server. Saved for restarts. {suffix}'

        async def load_guild(self, guild):
            if guild.id in self.controllers:
                return
            path = self.config_for(guild.id)
            try:
                if path.exists():
                    channel_id = load_config(path).channel_id
                    channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
                    await self.configure_guild(guild.id, channel)
            except (ValueError, sqlite3.Error, *NETWORK_ERRORS):
                LOG.error('Guild %s channel unavailable; use /cap_channel or @bot channel here.', guild.id)
            if guild.id not in self.synced:
                try:
                    await self.sync_guild(guild.id)
                except NETWORK_ERRORS:
                    LOG.error('Setup command registration failed for guild %s; use @bot channel here.', guild.id)

        async def on_ready(self):
            for guild in self.guilds:
                await self.load_guild(guild)
                async with self.lock_for(guild.id):
                    controller = self.controllers.get(guild.id)
                    if controller is not None and controller.channel is not None:
                        controller.recovery.request()
            migrated = legacy.connection.execute("SELECT value FROM meta WHERE key='guild_migrated'").fetchone()
            if migrated is None:
                try:
                    channel = self.get_channel(defaults.channel_id) or await self.fetch_channel(defaults.channel_id)
                    if isinstance(channel, discord.TextChannel) and channel.guild.id not in self.controllers:
                        await self.configure_guild(channel.guild.id, channel)
                except (ValueError, sqlite3.Error, *NETWORK_ERRORS):
                    LOG.warning('Initial channel unavailable. Each server can use /cap_channel or @bot channel here.')
                    if not self.controllers and sys.stdin.isatty() and (self.prompt is None or self.prompt.done()):
                        self.prompt = asyncio.create_task(self.prompt_channel())
            LOG.info('Ready: %s configured server(s).', len(self.controllers))

        async def on_guild_join(self, guild):
            await self.load_guild(guild)

        async def on_guild_remove(self, guild):
            async with self.lock_for(guild.id):
                controller = self.controllers.pop(guild.id, None)
                if controller is not None:
                    async with controller.tracker.lock:
                        controller.tracker.retired = True
                        controller.channel = None
                self.synced.discard(guild.id)

        async def prompt_channel(self):
            while not self.controllers:
                answer = await channel_input()
                if not answer:
                    return
                try:
                    cid = int(answer)
                    channel = self.get_channel(cid) or await self.fetch_channel(cid)
                    if not isinstance(channel, discord.TextChannel):
                        raise ValueError('Choose a text channel.')
                    LOG.info('%s', await self.configure_guild(channel.guild.id, channel))
                except (ValueError, sqlite3.Error, *NETWORK_ERRORS):
                    LOG.warning('Channel not saved. Check the ID/permissions or press Enter for Discord setup.')

        async def on_message(self, message):
            if message.guild is None or message.webhook_id is not None:
                return
            gid = message.guild.id
            words = message.content.lower().split() if not message.author.bot else []
            mention = self.user is not None and words and words[0] in (f'<@{self.user.id}>', f'<@!{self.user.id}>')
            if mention and len(words) >= 2 and words[1] == 'channel':
                try:
                    if len(words) != 3:
                        raise ValueError('Use @bot channel here or /cap_channel channel:#channel.')
                    if words[2] == 'here':
                        channel = message.channel
                    else:
                        cid = int(words[2].removeprefix('<#').removesuffix('>'))
                        channel = self.get_channel(cid) or await self.fetch_channel(cid)
                    text = await self.configure_guild(gid, channel, message.author)
                except ValueError:
                    text = 'Setup rejected. Use a channel in this server, with Manage Server permission and all required bot permissions.'
                except (sqlite3.Error, *NETWORK_ERRORS):
                    text = 'Could not save channel setup. Check permissions, connection and storage; then retry.'
                with suppress(*NETWORK_ERRORS):
                    await message.reply(text, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                return
            async with self.lock_for(gid):
                controller = self.controllers.get(gid)
                if controller is not None:
                    await controller.on_message(message)

        async def on_raw_message_delete(self, payload):
            await self.removed(payload.channel_id, [payload.message_id])

        async def on_raw_bulk_message_delete(self, payload):
            await self.removed(payload.channel_id, list(payload.message_ids))

        async def route_reaction(self, name, payload):
            for gid, controller in list(self.controllers.items()):
                async with self.lock_for(gid):
                    if controller.channel is not None and controller.channel.id == payload.channel_id:
                        await getattr(controller, name)(payload)

        async def on_raw_reaction_add(self, payload):
            await self.route_reaction('on_raw_reaction_add', payload)

        async def on_raw_reaction_remove(self, payload):
            await self.route_reaction('on_raw_reaction_remove', payload)

        async def on_raw_reaction_clear(self, payload):
            await self.route_reaction('on_raw_reaction_clear', payload)

        async def on_raw_reaction_clear_emoji(self, payload):
            await self.route_reaction('on_raw_reaction_clear_emoji', payload)

        async def removed(self, channel_id, ids):
            for gid, controller in list(self.controllers.items()):
                async with self.lock_for(gid):
                    if controller.channel is not None and controller.channel.id == channel_id:
                        await controller.handle_removed(ids)

        async def setup_hook(self):
            self.worker = asyncio.create_task(self.refresh_loop(), name='guild-counters')

        async def refresh_loop(self):
            await self.wait_until_ready()
            while not self.is_closed():
                for gid in list(self.controllers):
                    async with self.lock_for(gid):
                        controller = self.controllers.get(gid)
                        if controller is None or controller.channel is None:
                            continue
                        try:
                            if self.user is not None:
                                await controller.recovery.refresh(controller.channel, self.user.id)
                            await controller.dashboard.refresh()
                        except sqlite3.Error:
                            await controller.close()
                await asyncio.sleep(1)

        async def close(self):
            for task in (self.prompt, self.worker):
                if task is not None and task is not asyncio.current_task():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            await super().close()
            for store in self.stores.values():
                store.close()
            self.stores.clear()

    return GuildClient()
