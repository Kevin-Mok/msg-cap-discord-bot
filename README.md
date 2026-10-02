# Discord Message Cap

A small standalone Discord bot for channel moderators who want a shared daily message budget. It counts each person's messages, keeps a sticky scoreboard near the bottom of one channel per server, and randomly replaces messages after the daily cap. The project demonstrates persistent event accounting, native slash-command controls, bounded background work, and deterministic tests with two Python runtime modules and one Discord connection.

## Tech Stack And Why Chosen

- **Python 3.11+**: standard-library configuration, timezones, SQLite, and asynchronous coordination keep the runtime small.
- **discord.py**: the only third-party runtime dependency; handles Discord events, API requests, reconnects, and rate limits.
- **SQLite**: durable counters, personal cap overrides, reset windows, and message IDs without a database service.
- **Bash wrappers**: project-local virtual environment and configure-once startup.
- **unittest**: automated checks without another test dependency.

Browse: [Setup](#setup) · [Slash commands](#discord-slash-commands) · [Smoke tests](docs/smoke-tests.md) · [Implementation plans](plans/)

## Server isolation

Invite the same bot to multiple servers. In **each server**, run `/cap_channel channel:#your-channel` as a member with **Manage Server** or **Administrator**. If the slash command is missing, select the bot’s actual mention and send `@Twitter Cap channel here` in the desired channel. This creates or changes only that server’s monitored channel.

Each server has separate daily counts, default caps, personal overrides, reset windows, and scoreboard messages—even when the same user is present in several servers. `/cap_default` changes only the invoking server. Channel setup rejects targets from another server. Changing channels starts a fresh daily scope for that server and leaves the old channel’s messages untouched.

## Daily behavior

The default cap is **50** in **America/Toronto**; moderators can set personal overrides with `/cap_user`. `/cap_clear` exempts the selected member from all caps until a moderator assigns a new personal cap. Each member message (including other bot accounts) in the configured channel increases that user's daily sent count. Messages up to the effective cap are allowed. Each further message triggers one uniformly random deletion among that user's tracked messages from today, including the new message. Other users and yesterday's messages are never deletion candidates.

The scoreboard shows only users with an explicit personal cap, with sent and retained counts such as `Alice: 53 sent · 50 retained · cap 50`. Users with only the channel default and users cleared from caps are omitted. Deletions reduce retained count, not sent count. Edits, this bot’s own messages, webhooks, direct messages, and other channels do not count. Other bot accounts can be selected in `/cap_user`, `/cap_status`, `/cap_reset`, and `/cap_clear` and follow the same cap rules.

In the configured SaucyBot workflow, its direct reply removes the referenced human-authored message after the response arrives. This cleanup is limited to SaucyBot and the monitored channel.

The bot replaces its status batch after activity, at most once every five seconds. This returns the scoreboard near the bottom; Discord cannot permanently anchor a message there. Large scoreboards use multiple messages. At local midnight, tracking and the displayed day reset without deleting yesterday's human messages.

## Setup

Requirements: Python 3.11+ with venv support, internet access for dependency installation, and permission to invite a bot to the server. The supplied scripts require Bash. No sudo is required by these scripts.

Clone the project and enter its directory:

```bash
git clone https://github.com/Kevin-Mok/msg-cap-discord-bot.git
cd msg-cap-discord-bot
```

1. Open the [Discord Developer Portal](https://discord.com/developers/applications), create an application, and open its **Bot** page. Obtain its bot token; treat it like a password.
2. Leave **Message Content**, **Server Members**, and **Presence** privileged intents off. Counting uses guild/message events and does not need message bodies; see the [discord.py intents documentation](https://discordpy.readthedocs.io/en/stable/intents.html).
3. In **OAuth2 → URL Generator**, select the **bot** and **applications.commands** scopes and permissions **View Channel**, **Send Messages**, **Read Message History**, and **Manage Messages**. Use the resulting URL to invite it to your server. Ensure channel overrides allow those permissions; Administrator is unnecessary. Discord documents message deletion permissions in its [Message API](https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx).
4. Enable Discord's **User Settings → Advanced → Developer Mode**, then right-click the target text channel and choose **Copy Channel ID**.
5. From this project directory, run:

```bash
./scripts/setup.sh
```

Setup creates `.venv`, installs `requirements.txt`, and asks for the token with hidden input, channel ID, cap, and timezone. Press Enter to accept the cap/timezone defaults. It stores `config.json` with owner-only permissions and uses `data.sqlite3` for message state. Both are ignored by Git. The initial channel is a legacy/bootstrap setting; configure additional servers inside Discord. Keep this directory on a private local filesystem and do not share the config file.

Invite the bot using your saved token (this prints a URL and exits without tracking messages):

```bash
./scripts/run.sh --invite
```

Open the printed link, choose the server containing your configured channel, and authorize the requested permissions. The link includes the bot and application-command scopes. If startup cannot access the channel, the bot stays online and prompts for a replacement channel ID. Press Enter to skip the terminal prompt and configure it in Discord as described below. The replacement is checked and saved without re-entering your token. Optional PyNaCl/davey voice warnings do not prevent this text bot from working.

Subsequent starts need no token entry:

```bash
./scripts/run.sh
```

Stop with Ctrl+C. Keep one process running for this bot token; that process handles all configured servers. Both wrappers forward options to the Python CLI. Setup adds `--setup` automatically; for example, `./scripts/setup.sh --cap 3` selects a test-cap prompt default. Run supports options such as `./scripts/run.sh --check`.

## Set or repair a server’s channel

Run `/cap_channel channel:#your-channel` in that server. You can change a working channel or repair an unavailable one without restarting. If slash commands are missing, select the actual bot mention and send:

```text
@Twitter Cap channel here
```

`@Twitter Cap channel #your-channel` (a real channel mention) or a numeric channel ID also works. Requires **Manage Server** or **Administrator**. The target must be in the same server. The bot checks View Channel, Send Messages, Read Message History, and Manage Messages before saving. It starts counting and registers all seven slash commands automatically; then try `/cap_help`. Setup messages do not consume allowance.

If the initial channel is inaccessible and no server is configured, an interactive terminal offers a replacement ID; press Enter to configure in Discord. The bot stays online. Other servers continue working if one server’s channel is unavailable.

## Register slash commands inside Discord

After updating, restart once with Ctrl+C and `./scripts/run.sh`. In the configured channel, select the bot’s real mention and send:

```text
@Twitter Cap slash sync
```

You need **Manage Server** or **Administrator**. The bot replies publicly with the registered command names; then run `/cap_help`. `@Twitter Cap sync` also works. Sync requests do not consume your message allowance, are limited to once per 30 seconds, and do not require Message Content intent. A plain mention still counts as a normal message. Startup also registers commands automatically.

If registration fails, the reply includes a re-authorization link with `applications.commands`. Authorize it and retry. If registration succeeds but commands remain hidden, reopen the command picker and check **Use Application Commands** and server integration permissions.

## Discord slash commands

Use cap/status/reset commands in **this server’s configured text channel**. `/cap_channel` is also available elsewhere in the same server. Select members from Discord's native picker; do not type a user ID. All replies are private to the requester, and the public scoreboard refreshes through its normal five-second throttle.

| Command | Who can use it | Effect |
| --- | --- | --- |
| `/cap_channel channel:#channel` | Manage Server / Administrator | Set or change this server’s monitored channel; can run elsewhere in the same server. |
| `/cap_status` | Everyone | Show your effective cap, sent/retained counts, remaining allowance, accounting window, channel, timezone, and next reset. |
| `/cap_status user:@Alice` | Everyone | Inspect another member’s status privately, including bots. |
| `/cap_help` | Everyone | Show command examples and explain random replacement and reset. |
| `/cap_user user:@Alice limit:25` | Moderators | Save a personal cap; report the previous and new effective limits. |
| `/cap_default limit:50` | Moderators | Change and save the channel default immediately; personal overrides remain. |
| `/cap_clear user:@Alice` | Moderators | Remove Alice's personal cap and exempt her from all caps until `/cap_user` assigns one. |
| `/cap_reset user:@Alice` | Moderators | Ask for confirmation to start Alice's accounting again. |
| `/cap_reset` | Moderators | Ask for confirmation to start accounting again for everyone in the monitored channel. |

Moderators need **Manage Messages in this channel** or **Administrator**. Runtime checks enforce this even if server command settings allow broader command visibility. Other channels receive a private response directing the requester to the configured channel; DMs are unsupported. Caps must be positive integers. Other bot accounts can be selected; this bot itself is excluded to protect its scoreboard and replies.

A personal cap takes priority over the channel default and survives midnight/restarts until cleared. `/cap_clear` exempts the member from cap enforcement and persists across restarts. Changing a cap preserves counts and never immediately deletes messages. A remaining allowance of zero means each additional message triggers one random replacement; it does not block sending. Lowering a cap does not bulk-delete earlier messages.

Reset confirmations explain their exact scope and offer **Reset counters** and **Cancel** for 30 seconds. Only the requester can confirm, permissions are checked again, and expired or already-used confirmations cannot execute. A reset leaves existing Discord messages in place and excludes them from subsequent random deletions. The new window displays **since reset**, survives restart, and returns to normal daily accounting at local midnight. Reset never changes caps or personal overrides.

Each joined server receives `/cap_channel`; configured servers also receive the cap/status/reset commands. Commands register at startup, server join, and channel setup, or through manual sync. After upgrading, stop the old process and run `./scripts/run.sh` again. If commands are missing, check the startup log for registration errors, confirm the bot was invited with **applications.commands**, and check server/channel **Use Application Commands** permission and application integration settings. Reconnects do not repeatedly sync commands. Message Content intent remains unnecessary.

## Configuration and checks

Run these commands from the project directory:

```bash
.venv/bin/python bot.py --setup
.venv/bin/python bot.py --check
.venv/bin/python bot.py --help
.venv/bin/python -m unittest discover -s tests -v
```

- `--setup` creates or edits configuration; blank input keeps existing values. It preserves message data.
- `--cap N` selects the cap prompt default during setup (press Enter to accept); for example `.venv/bin/python bot.py --setup --cap 3` prepares a short live smoke test.
- `--config PATH` selects another config file; `data.sqlite3` and `guild_data/` live beside it. Use a separate directory for isolated setup checks.
- `--check` validates the global and saved per-server configurations/databases and reports initial defaults plus the number of saved servers without logging in or printing the token. It does not verify Discord permissions or token validity.
- `--invite` authenticates using the saved token and prints this bot’s server invite URL. It does not connect the Gateway, start moderation, or open the quota database.
- `--help` lists supported CLI options.

CLI setup changes require a restart and supply login/initial defaults. Existing servers keep their own settings: use `/cap_channel` and `/cap_default` in Discord to change them. A server channel change resets only its current daily quota scope. Lowering the cap does not bulk-delete existing messages; each further over-cap send still triggers one deletion. A channel change leaves the old status batch for manual cleanup in the old channel. Follow [the live smoke checklist](docs/smoke-tests.md), then restore the default with `/cap_default limit:50` and assign test members' intended cap with `/cap_user` after using `/cap_clear`. CLI setup remains available while the bot is stopped.

## Reliability and limits

Each server stores owner-only `config.json` and `data.sqlite3` under `guild_data/<guild-id>/`, ignored by Git. These configs contain credentials; keep the whole directory private. SQLite preserves observed sent counts, retained message IDs, status IDs, personal overrides, and reset windows across restarts. On first upgrade, the legacy database is copied only to the verified server owning the original channel; existing per-server databases are never overwritten. The original database is retained as a backup. Back up the global config and entire guild_data directory while stopped. Existing version-1 databases migrate automatically without resetting counts or status IDs; keep a stopped-process backup before upgrading. Do not replace the database to enable commands. Message bodies are not stored. Already-deleted candidates are removed and selection retries. Transient transport failures are logged and the counter retries on a later refresh; local database failures stop tracking rather than silently losing accounting. Permission/API failures are logged and failed deletions are not reported as successful; fix channel permissions before relying on cap enforcement.

Only messages observed while the bot is running are tracked. Messages sent offline are not backfilled. Offline/manual deletions can temporarily make retained counts stale until candidates are checked. Discord API actions and SQLite writes cannot form one atomic transaction, so a crash at that boundary can also leave state needing reconciliation. This is an MVP for one process and one channel per server, not a strict moderation guarantee during outages.

Automated checks exercise offline behavior. A real token and test channel are needed to validate invitation, permissions, deletion, and sticky display. See [the slash-command plan](plans/discord-cap-slash-commands.md) for current verification and [the original implementation plan](plans/discord-message-cap-mvp.md) for baseline acceptance and [the accepted slash-command prompt](prompts/discord-cap-slash-commands.md) for the command implementation contract. Offline checks do not verify live slash-command registration or Discord interaction behavior.
