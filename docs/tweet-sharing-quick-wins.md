# Tweet Sharing Feature Ideas and Implementation Prompts

This repository review identifies small ways to make posting tweets in Discord more satisfying and make them easier for a partner to read, react to, and revisit. Start with personal star favorites: they give each person a simple, private collection without requiring account setup. The recommendations and three independent, paste-ready implementation prompts below are based on the current Python, discord.py, and per-server SQLite implementation.

## Repository findings

The bot tracks per-server daily message counts and random replacements, keeps a scoreboard, and already offers private slash-command responses. It does not store message bodies or run with Discord's Message Content intent. SaucyBot replies can remove the human-authored message they reference, so a useful reading list should include surviving SaucyBot replies as well as human posts.

Daily quota data is not a durable archive: rollover clears the daily message index, and moderator resets make messages ineligible for future cap deletions even while those messages remain visible in Discord. Favorites and reading checkpoints must use their own persistent records or query Discord history; they cannot safely treat the cap tracker as a list of extant posts. A reaction also does not establish that its author read a message.

The implementation and tests support the findings: [SQLite quota store](../bot.py), [daily rollover and reset](../bot.py), [SaucyBot reply cleanup](../bot.py), [per-server gateway and command routing](../guild_bot.py), and [regression tests](../tests/).

## Ranked feature ideas

| Rank | Idea and experience | Smallest useful version and evidence | Effort, dependencies, and one-session confidence |
|---|---|---|---|
| **1. Quick win: Personal favorites** | You or your wife adds ⭐ to a post; `/favorites` privately returns saved jump links for that person. | Save a message ID when a human adds a normal Unicode ⭐ and remove that person's save when they unstar. Show ten saved links per page; allow human posts and eligible SaucyBot replies. Existing SQLite supports durable metadata, but favorites need a table separate from daily quota state. | **Medium.** Requires normal reaction intent at the gateway, raw event routing, an independent table, and migration. **High confidence** if offline-star reconciliation and cap changes stay out of scope. |
| **2. Quick win: Recent-post catch-up** | Your wife opens `/catchup` to see recent surviving tweets without scrolling back through the channel. | Read a bounded Discord history window on demand; return ten jump links per page, oldest first within the snapshot. Include human posts and eligible SaucyBot replies. Existing channel setup already requires Read Message History. | **Small.** No new storage, message-body archive, or reaction handling. **Very high confidence** for a bounded history query. |
| **3. Quick win: Reaction roundup** | You revisit recent posts that attracted the most emoji reactions. | `/reactions` privately lists up to five recent posts with total and per-emoji counts and jump links. Use fresh history and reaction metadata; the current gateway has no reaction handlers. | **Small.** No new persistence or reaction events. Counts may include bots, multiple emoji from one person, and super reactions. **Very high confidence.** |
| **4. Quick win: Last-post receipt** | `/last_tweet` explains whether your latest observed post remains, was replaced by the cap, or was later removed through the SaucyBot workflow. | Keep a small per-author receipt with the observed outcome and any surviving link. The existing `/cap_status` already reports aggregate sent, retained, remaining, and reset values, so the receipt must describe an individual post. | **Medium.** Requires durable outcome metadata and hooks around processing and deletion. A successfully counted message might itself be deleted; **medium-high confidence** if the receipt says only what the bot verified. |
| **5. Next step: Resume catch-up** | Your wife reads the next batch and explicitly selects “Mark this batch caught up.” | Keep a checkpoint per reader and channel. Listing posts or reacting never advances it; only the explicit action advances past the displayed batch. Midnight and quota resets leave it alone. | **Medium to large.** Naturally follows idea 2 and requires independent persistent state. **Medium-high confidence** with a fixed scan limit and no scheduled alerts. |
| **6. Next step: Favorites that follow SaucyBot replies** | A ⭐ saved on a human post follows its verified SaucyBot reply when the original is deleted. | Record the source-to-reply relationship and transfer a personal favorite only for the existing reply-cleanup workflow. The cleanup currently recognizes reply references but does not persist the relationship. | **Medium to large.** Builds on idea 1 or includes it. Must handle deletion ordering and event gaps honestly. **Medium confidence** for a bounded follow-up. |

Discord's current [message documentation](https://docs.discord.com/developers/resources/message#message-object) distinguishes message metadata, reaction counts, and content fields. Content-based previews or digests need a separate permissions and storage decision. For event-based favorite tracking, discord.py's [raw reaction events](https://discordpy.readthedocs.io/en/stable/api.html#discord.on_raw_reaction_add) work when messages are absent from its internal cache; the configured production gateway and its per-server routing need to receive and route those events.

## Tradeoffs and proposed defaults

- **Reacting and reading are different signals.** A favorite marks a post to save. A reaction count describes reactions visible when read; neither proves a post was read.
- **A jump link does not preserve a post.** Discord links can break after cap deletion, manual deletion, or SaucyBot cleanup. Removing saved links for confirmed deletions cannot undo a deletion or recover the content.
- **Protecting ⭐ posts would change cap behavior.** None of the three implementation prompts below exempts starred posts. Decide separately whether that cap change is worth making.
- **Catch-up shows what survives.** A fresh history query can include posts sent while the bot was offline, but it cannot restore a deleted original. A 100-message scan must disclose when older results might exist.
- **Favorite tracking initially observes events only while online.** The bounded MVP documents stars added or removed during downtime as a reconciliation limitation rather than promising an accurate historical collection.
- **The proposed default is per-person ownership.** Each person sees their own favorites; neither favorites nor reaction counts imply shared ownership or who has read a post.

## Implementation prompt 1: Personal favorites

Paste the following prompt into Cursor or Codex with this repository open. It is self-contained and does not rely on the other prompts.

```text
Implement personal Unicode ⭐ favorites in /home/kevin/coding/twitter-cap-bot.

Purpose: two people share a Discord channel where one posts tweets and
the other reacts. Let each human save and privately revisit their own
favorite posts without configuration for either person's Discord ID.

Before editing, read applicable AGENTS instructions, README.md,
tasks/lessons.md, relevant plans, bot.py, guild_bot.py, and tests.
Capture git status --short and preserve existing dirty work. Use
synthetic Discord fixtures and temporary databases only. Never read
credentials, live messages, or runtime databases. Do not create a
worktree, commit, push, deploy, or start the live bot. Create
plans/tweet-favorites.md using the applicable plan contract.

Build this bounded MVP:
1. A human's normal Unicode ⭐ saves a message for that reactor;
   removing that person's ⭐ removes only their save. Ignore super
   reactions, other emoji, bots, DMs, and unrelated channels.
2. Support human posts and replies from the existing
   REPLY_CLEANUP_BOT_ID. Exclude this bot, other bots, and webhooks.
   Validate message metadata without treating daily quota rows as an
   archive or inferring the human author of a SaucyBot reply.
3. Add /favorites page:1. Privately list the caller's ten most
   recently saved links per page, with safe author and timestamp
   labels. Do not allow looking up another member's collection.
   Check channel and message-history permissions. Defer before network
   requests; suppress mentions and link previews; bound output size.
4. Add an independent, validated persistent favorites table to each
   server database. Use channel/message/reactor identity, deterministic
   ordering, uniqueness, and transactional migration from every schema
   version currently supported by this checkout. Preserve quota data
   and roll back data and schema on migration failure. Favorites
   survive restart, midnight, cap resets, and channel switches; all
   queries are limited to the configured channel.
5. Add guild reaction intent at the production GuildClient and route
   raw add, remove, clear-all, and clear-one-emoji events to only the
   matching active controller under existing per-guild locking. Do not
   turn on Message Content, Members, or Presence intents. Reaction
   removal works when payload.member and the message cache are absent.
6. Handle cap, manual, SaucyBot, single, and bulk deletions. Clear a
   favorite only after confirmed deletion or NotFound, idempotently.
   Keep saves on Forbidden or transport failures and report that
   validation failed. Check only the selected page; do not scan without
   a limit. A saved link cannot recover deleted content.
7. After awaits, verify the channel's controller is still active; a
   channel replacement cannot accept stale favorite writes. Do not
   reacquire Tracker.lock from deletion code already holding that lock.
8. Integrate ordinary-member slash-command registration and /cap_help.
   Update exact command and intent assertions without weakening current
   permission, migration, quota, or sync checks. Keep new behavior in a
   cohesive module; bot.py is already over 1,000 lines.

Non-goals: import historic reactions, reconcile reactions missed
while offline, mark posts read, store post content, recover deleted
posts, protect favorites from cap cleanup, change SaucyBot behavior,
or add dependencies or public messages. Explain the offline-event
limitation in README and smoke documentation.

Write focused defining tests first and observe RED. Then implement
minimal GREEN behavior and refactor if useful. Cover duplicate event
replay; two users saving the same message; add/remove without cached
member/message; clear-all and clear-one; human and Saucy eligibility;
bot, webhook, DM, wrong-guild/channel, emoji, and super-reaction
rejections; offline-message limitations; restart, Toronto midnight,
reset, channel switching, and per-server isolation; confirmed, missing,
and failed deletion; queued writes after controller retirement;
migration preservation/rollback; output bounds, private access,
pagination, and real command registration. Assert existing cap behavior
is unchanged.

Exact root-level verification commands:
.venv/bin/python -B -m unittest discover -s tests -p test_tweet_favorites.py -v
.venv/bin/python -B -m unittest discover -s tests -v
UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx pyright *.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python
git diff --check

Update README.md, /cap_help, docs/smoke-tests.md with grouped Action
and Expected steps, and plans/tweet-favorites.md in the same change.
Document migration/rollback, restart/sync, stale or deleted links, and
missed reactions during downtime. Do not claim live Discord verification
without actually observing it.

Done means focused and full tests, type checks, and whitespace check
pass; migration, permissions, and command sync remain intact; matching
plan and usage docs are accurate; live checks are marked pending.
Report changed files and exact verification results. Suggested future
commit subject: feat: add personal tweet favorites
```

## Implementation prompt 2: Recent-post catch-up

Paste this prompt independently; it needs no favorite or reaction-roundup feature.

```text
Implement bounded /catchup in /home/kevin/coding/twitter-cap-bot.

Let a channel member browse recent surviving tweets using a private list
of Discord jump links. Include eligible replies from the existing
REPLY_CLEANUP_BOT_ID: its replies can survive cleanup of human originals.

Before editing, read applicable AGENTS instructions, README.md,
tasks/lessons.md, relevant plans, bot.py, guild_bot.py, and tests.
Capture git status --short and preserve existing dirty work. Use
synthetic Discord responses and temporary fixtures; never read
credentials, live messages, or runtime databases. Do not create a
worktree, commit, push, deploy, or start the live bot. Create
plans/tweet-catchup.md using the applicable plan contract.

Bounded MVP:
1. Register /catchup hours:24 page:1, privately available to ordinary
   members in the configured channel. Restrict hours to 1–168 and page
   to 1–10. Verify caller and bot can view channel history; acknowledge
   before fetching, and recheck the active controller after awaits.
2. Take one UTC snapshot. Fetch at most the latest 100 channel
   messages at or before the snapshot, stopping when the rolling-hour
   window begins. Filter to human messages and replies from the known
   SaucyBot ID; exclude this bot, other bots, webhooks, and system
   messages. Deduplicate by message ID. Never inspect or store body text.
3. Sort eligible messages oldest first and return ten per page, each
   with author, timestamp, and jump link. State the chosen time window,
   page number, and scan coverage. If the scan reaches 100, state that
   older eligible posts might be missing. Each invocation takes a fresh
   snapshot; no stable-unread claim.
4. Give empty and unavailable pages useful private responses. Escape
   labels, suppress mentions and previews, bound the response, and
   distinguish permission/network errors from an empty result.
5. Read Discord channel history, never Store.events, retained flags, or
   quota owner maps: midnight clears daily records and a manual reset
   hides quota records without removing visible Discord messages.
   History may include messages sent while this bot was offline; it
   does not alter quota accounting.
6. Do not persist posts, checkpoints, or message bodies. Deleted posts
   disappear on a later fetch; a jump link can become unavailable after
   the response. Reading, reactions, restart, and quota resets do not
   record a read state. Do not introduce privileged intents.
7. Add cohesive code in a suitable module; integrate ordinary-member
   command routing, per-guild sync, /cap_help, and accurate command
   assertions. No dependency on other proposed features.

Non-goals: unread state, catch-up checkpoints, content previews or
digests, archival storage, scheduled messages, push alerts, and quota
changes.

Start with a focused RED test, then implement GREEN. Cover eligible
human/Saucy versus ignored sources, repeated IDs, exact time boundary,
ordering, pagination, invalid values, 100-message limit, empty and
failed history, denied permissions, wrong guild/channel/DM, ordinary
member access, and channel replacement during fetch. Cover timestamps
across Toronto midnight and DST. Verify offline posts are listable and
the command never changes cap counts, reset windows, or deletions.

Exact root-level verification commands:
.venv/bin/python -B -m unittest discover -s tests -p test_tweet_catchup.py -v
.venv/bin/python -B -m unittest discover -s tests -v
UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx pyright *.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python
git diff --check

Update README.md, /cap_help, docs/smoke-tests.md with grouped Action
and Expected checks, and plans/tweet-catchup.md in the same change.
Document scan limits, fresh-snapshot pages, permission needs, and the
difference between a jump link and preserved message content. Mark
live Discord checks pending unless actually performed.

Manual checklist to add, not run against a live bot: create human posts
and SaucyBot replies in a test channel; as an ordinary member run
/catchup hours:24 page:1 and follow links; delete a listed message and
refresh; exercise the next page, denied history, another channel, and
an empty window. Use synthetic tests for downtime, rollover, and the
100-message cutoff.

Done means focused/full tests and type checking pass, existing
moderation behavior is unchanged, docs and plan match implementation,
and live verification is marked pending. Report changed files and exact
verification. Suggested future commit subject:
feat: add recent tweet catch-up links
```

## Implementation prompt 3: Reaction roundups

Paste this prompt independently; it needs no favorites or catch-up feature.

```text
Implement a private, bounded /reactions roundup in
/home/kevin/coding/twitter-cap-bot.

Let a channel member find recent posts that currently display the most
reactions. Describe counts as visible emoji reactions, never as unique
readers or proof that a particular person read a post.

Before editing, read applicable AGENTS instructions, README.md,
tasks/lessons.md, relevant plans, bot.py, guild_bot.py, and tests.
Capture git status --short and preserve existing dirty work. Use
synthetic message metadata and temporary fixtures; do not read
credentials, live messages, or runtime databases. Do not create a
worktree, commit, push, deploy, or start the live bot. Create
plans/tweet-reaction-roundup.md using the applicable plan contract.

Bounded MVP:
1. Register /reactions hours:24 (integer 1–168), private to an
   ordinary member in the configured channel. Check that caller and bot
   can view channel history; acknowledge before fetching, and recheck
   the active controller afterward.
2. Capture one UTC time and examine at most 100 newest messages at or
   before it, stopping at the rolling lookback boundary. Include human
   posts and replies by the existing REPLY_CLEANUP_BOT_ID; exclude this
   bot, other bots, webhooks, system messages, and duplicate IDs.
3. Compute each post's score from Discord's reported message-reaction
   counts. Return the five highest-scoring posts with per-emoji counts,
   author, timestamp, and jump links; break ties by newest message ID.
   Bound emoji output and state if some emoji counts were omitted.
4. Explain that the window filters post creation time, not when
   reactions were added. Counts can include bots, multiple reactions
   from one member, and super reactions. Do not call any count “wife
   reactions” or “readers.” Re-fetch on each command; do not accumulate
   persistent totals or enable reaction-event handlers or intents.
5. Clearly disclose the 100-message coverage cutoff. Empty results,
   permission failure, and transport failure must have distinct useful
   responses. Escape labels, suppress mentions/previews, and bound output.
6. Deleted posts disappear on the next snapshot; existing jump links
   may later expire. Restart, midnight, and cap reset require no new
   stored data. Do not change the cap or SaucyBot behavior.
7. Keep code cohesive, integrate ordinary-member command registration,
   guild sync, /cap_help, and exact command expectations. Do not depend
   on the other feature proposals or add a library.

Non-goals: identify which person reacted, infer that anyone read a post,
calculate lifetime or reaction-event totals, archive content, generate
digests, schedule notifications, protect posts, change quota, or add
reaction listeners and persistent reaction records.

Write tests/test_tweet_reactions.py first and observe RED. Cover mixed
eligible/ineligible sources; multiple and repeated emoji; deterministic
ties and top-five/output limits; zero reactions; bot, webhook, and
super-reaction counts as Discord reports them; removal, clearing, and
deletion reflected in the next fresh snapshot; rolling window boundaries
across Toronto midnight and DST; restart/reset; scan cutoff; wrong
guild/channel/DM; ordinary-member access; denied history and network
errors; and controller replacement during the fetch. Verify no message
content is read or stored, no DB state accumulates between calls, and
daily quota/deletion behavior stays unchanged.

Exact root-level verification commands:
.venv/bin/python -B -m unittest discover -s tests -p test_tweet_reactions.py -v
.venv/bin/python -B -m unittest discover -s tests -v
UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx pyright *.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python
git diff --check

Update README.md, /cap_help, docs/smoke-tests.md with grouped Action
and Expected entries, and plans/tweet-reaction-roundup.md in the same
change. Explain exactly what the counts measure, the scan cutoff, the
lack of reader attribution, and broken-link behavior. Do not claim a
live Discord check without performing it.

Manual checklist to add, not execute against a live bot: create human
posts and eligible SaucyBot replies, add multiple emoji, and compare
/reactions hours:24 to Discord. Remove and clear reactions, delete a
post, and rerun. Verify ordinary-member access and another-channel
rejection. Use synthetic tests for paging limits and service failures.

Done means focused/full tests, type checking, and whitespace check pass;
existing permission and moderation behavior remains intact; docs and
plan match; live checks are marked pending. Report changed files and
exact evidence. Suggested future commit subject:
feat: add recent tweet reaction roundups
```

## Verification and suggested first task

The offline regression baseline on 2026-10-03 was 102 passing tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests -v
```

This checks the existing offline suite, not live Discord permissions, event delivery, slash-command visibility, or actual reaction history. The implementation prompts specify separate focused tests, the full offline regression, type checks, documentation work, and manual checks to add.

Start with **personal favorites**. Your wife will be able to save an appealing surviving post with one familiar reaction and jump back to it privately. Each of you will keep a separate list that persists through midnight and cap resets without changing what the cap can remove.
