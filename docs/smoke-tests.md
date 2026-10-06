# Smoke Tests

Use a private test channel, two human test members, and one moderator with Manage Messages in that channel. Run terminal commands from the project directory. Stop the bot with Ctrl+C before CLI setup changes, and restart afterward; slash-command changes apply immediately. None of these commands requires sudo. Live checks require a bot token and Discord access; automated test results do not count as live verification.

## Quick live check — bot already online (about 2 minutes)

Run these in **#twitter-cap**, provided this is the configured channel. Use slash commands selected from Discord's command picker; a plain @Twitter Cap mention does not run a command. To register missing commands, use the mention command below. Replace @you by selecting your own member profile. You need Manage Messages or Administrator for changes.

1. Action: /cap_help
   Expected: A private command guide appears. If the command is missing, use the troubleshooting steps below.
2. Action: /cap_status
   Expected: A private status reply identifies this channel and your current cap. Note any existing personal override so you can restore it afterward.
3. Action: /cap_user user:@you limit:3
   Expected: Private confirmation says your effective cap is now 3. Other members' caps are unchanged.
4. Action: /cap_reset user:@you
   Expected: A private prompt names only you. Click **Reset counters** within 30 seconds. Your accounting starts at zero; earlier messages stay and are excluded from this test's count/deletion pool.
5. Action: Send three separate normal messages: test 1, test 2, test 3. Wait five seconds.
   Expected: All three new messages remain. The sticky scoreboard shows `🐦 3 tweets sent · 📥 3 retained · 🎯 cap 3 · since reset`, without a date, timezone, or account name/ID.
6. Action: Send a fourth normal message: test 4. Wait five seconds.
   Expected: Exactly one of these four new test messages disappears, possibly test 4. Three remain. The scoreboard shows `🐦 4 tweets sent · 📥 3 retained · 🎯 cap 3`. Earlier pre-reset messages stay untouched.
7. Action: /cap_status
   Expected: Private status agrees: 4 sent, 3 retained, 0 remaining. A remaining allowance of zero means random replacement on each further message.
8. Action: /cap_reset user:@you
   Expected: Click **Cancel** this time. Status remains 4 sent and 3 retained.
9. Action: /cap_clear user:@you
   Expected: Your personal test override is removed and you become exempt from all caps. You disappear from the scoreboard; users without explicit personal caps are not listed. If you had a personal override before this test, restore that original limit with /cap_user instead.

Pass means the private commands respond, the sticky scoreboard refreshes, and the fourth new message causes exactly one same-user deletion. Online presence alone does not prove these behaviors. This walkthrough has not yet been marked live-passed; record the actual Discord outcome.

### Register commands from Discord

- Action: After updating the code, restart once with Ctrl+C and `./scripts/run.sh`. As a member with Manage Server or Administrator, send `@Twitter Cap slash sync` in #twitter-cap, selecting the actual bot mention from Discord’s picker.
  Expected: A public “Syncing slash commands…” reply changes to “Registered 9 slash commands” with their names, including `/cap_reader` and `/cap_source`. No ping occurs, the request does not increase your quota counters, and `/cap_help` becomes available. Message Content intent remains disabled.
- Action: Immediately send `@Twitter Cap sync`.
  Expected: A reply asks you to wait 30 seconds. No second registration occurs.
- Action: Send the sync command as a member without Manage Server or Administrator.
  Expected: The reply explains the required permission; commands and counters remain unchanged.

## Direct jump and restart recovery

Use two human accounts and SaucyBot: one human posting account and one reader. Select the posting source with `/cap_source`; only that account’s posts are eligible. Select the reader with Discord's native member picker; selecting the posting account would intentionally exclude that account's own messages.

- Action: ./scripts/run.sh
  Expected: After stopping the previous process with Ctrl+C, the updated bot starts, restores saved counts, reader and source selections, and refreshes the sticky summary. No sudo is required.
- Action: /cap_reader user:@reader
  Expected: As a moderator in the configured channel, receive a private confirmation. The bottom summary gains a jump button once a source is also set; this reader selection is shared by everyone viewing that summary. A non-moderator or bot target is rejected.
- Action: /cap_source user:@SaucyBot
  Expected: A moderator receives private confirmation. The jump searches only SaucyBot posts; human messages (including your own) and other bots are skipped.
- Action: Generate three SaucyBot posts today with older human messages still present; react to the oldest as the selected reader, then wait for the summary refresh and tap Jump to unreacted.
  Expected: Discord opens the second message directly, with no intermediate bot reply. Someone else's reaction does not skip a message; any normal or super reaction by the reader does.
- Action: Remove the reader's last reaction from the first message, wait for the next summary edit, and tap the summary button again.
  Expected: The first message is the destination again. Deleting that target advances to the next eligible surviving message. A quota reset does not hide older posts from this jump.
- Action: React as the reader to every eligible message from today.
  Expected: The summary shows a disabled All caught up today button. Yesterday's posts, the reader's own posts, all authors except the selected source, webhooks and system messages are not jump targets.
- Action: Note /cap_status sent and retained values, stop the bot, send two posts, delete one previously counted post, and restart with ./scripts/run.sh.
  Expected: Recovery adds the two surviving offline posts exactly once, preserves previously saved sent totals, subtracts the deleted post from retained only, and makes no retroactive cap deletions. The reader and source settings persist and the jump reflects live reactions. Restart again: neither sent nor retained doubles. Messages created and deleted entirely during downtime cannot be recovered.
- Action: Repeat restart after /cap_reset, and run the same checks in a second configured server.
  Expected: Recovery respects the since-reset window; previous posts are not counted again. Each server retains its own reader, source and daily counts. The jump still considers all eligible posts from today, including those before a counter reset.
- Action: Temporarily deny Read Message History, trigger a reader reaction change, then restore permission.
  Expected: A live reader addition can still use the warm cache without history permission. On the next periodic reconciliation (or after restarting), the jump becomes unavailable rather than falsely caught up; saved counts remain intact on failed recovery. Lookups recover after permission is restored (reader retry on the next refresh; startup recovery retry within 30 seconds).
- Action: In a test channel, create 49 reacted source posts followed by one unreacted source post; leave reactions unchanged while the summary scans.
  Expected: The scan tolerates rate-limit waits up to its two-minute budget and links to the 50th post. If that budget is exceeded, timeout warnings identify TimeoutError and an increasing completed-check count across retries; the jump eventually reaches the unreacted post when individual requests finish within the budget. Counts and new messages continue updating during the scan, and another server remains responsive; cold history and reaction checks run independently. Removing a reader reaction while recovery is in progress makes that older post eligible again. After midnight yesterday's unreacted posts leave the today-only search.
- Action: After the jump has hydrated, react to its current target as the selected reader; send another source post and inspect the summary during ongoing activity.
  Expected: The jump advances from cached order on the next healthy worker tick (normally about one second), counts update by edits, and the summary moves down at most once every five seconds. Reaction-only updates keep the same summary message. Discord rate-limit waits can extend timing.
- Action: Put both a normal and super reaction (or two emoji) on the same eligible post, then remove just one as the reader.
  Expected: The post stays seen while any reader reaction remains. Removing the final one makes it eligible again; other readers' reactions do not mark it seen.
- Action: Stop the bot, remove the selected reader's reaction from an older post and add another person's reaction so the total stays unchanged; restart.
  Expected: Saved counts appear while recovery runs. The jump stays temporarily unavailable until reconciled and then returns to the older post. Aggregate reaction counts do not substitute for reader membership.
- Action: .venv/bin/python scripts/benchmark_updates.py
  Expected: The synthetic fixture reaches the independently expected targets. The working tree makes zero history, fetch and membership reads for warm refresh and reader-add; the baseline comparison names its Git revision. No token, live API or sudo is required. Use --baseline REV for an older implementation after committing.
- Action: /cap_source without a user, then re-select SaucyBot and restart.
  Expected: Clearing the source hides the button while keeping the reader. Re-selecting and restarting restores the SaucyBot-only jump.
- Action: /cap_reader
  Expected: As a moderator, remove the jump button without changing counts or caps.

### If a step fails

- **No slash commands:** use `@Twitter Cap slash sync` as described above. If there is no response, confirm the updated bot was restarted and you selected its real mention in the configured channel. If sync fails, use the reply’s invite link to re-authorize application commands and retry after 30 seconds. If sync succeeds but commands are hidden, reopen the command picker, allow Use Application Commands, and check server integration settings.
- **Configured channel unavailable:** the bot stays online. Enter a replacement ID at its terminal prompt, or press Enter and send `@Twitter Cap channel here` in #twitter-cap as a member with Manage Server or Administrator. Expect a saved-channel confirmation and slash registration. Use `/cap_channel channel:#channel` to move a working server channel too.
- **No sticky scoreboard:** check the terminal for counter errors and allow View Channel and Send Messages in this channel.
- **Fourth new message stays and none disappear:** check Manage Messages permission and the terminal's deletion errors. Check /cap_status confirms personal cap 3 and that the user reset succeeded.

## Configure once and start

- Action: ./scripts/setup.sh --cap 3
  Expected: Prompts accept a dedicated test bot token, test channel ID, cap default 3, and America/Toronto. Dependencies install into .venv; token input is hidden; config.json is saved without printing the token; no Red installation is needed.
- Action: ./scripts/run.sh --invite
  Expected: A server invite URL is printed for the configured bot with bot/application-command scopes and View Channel, Send Messages, Read Message History, and Manage Messages permissions. The token is not printed, no quota database is opened, and no message tracking starts. Open the link and authorize the bot in the target server.
- Action: .venv/bin/python bot.py --check
  Expected: The offline check reports the configured channel, cap, and timezone without the token.
- Action: ./scripts/run.sh
  Expected: Startup connects to Discord, creates a scoreboard in the configured channel, and logs the result of server slash-command registration.
- Action: Stop the bot with Ctrl+C.
  Expected: The process exits cleanly.
- Action: .venv/bin/python bot.py --setup
  Expected: Pressing Enter at existing-value prompts preserves settings and message state.
- Action: ./scripts/run.sh
  Expected: Normal startup does not request the token again.

## Repair an inaccessible channel

- Action: With a dedicated test config, save an inaccessible channel ID and run `./scripts/run.sh`. Enter a valid replacement ID when prompted.
  Expected: The bot stays online, validates permissions, saves the replacement, starts its scoreboard and registers slash commands without a token prompt or restart. Invalid input prompts again.
- Action: Repeat with an inaccessible channel, press Enter at the prompt, then as a server manager send `@Twitter Cap channel here` using a real bot mention in the desired text channel.
  Expected: Public confirmation identifies the saved channel. `/cap_help` works; setup messages do not consume allowance. A second request for the same channel reports it is already configured; a different valid channel changes only this server.
- Action: Attempt setup as an ordinary member, or target a channel in another server or one missing Manage Messages permission.
  Expected: An actionable rejection; saved configuration remains unchanged.
- Action: While the terminal prompt is waiting, complete setup in Discord, or stop with Ctrl+C.
  Expected: The pending prompt is cancelled; Discord setup works immediately and shutdown does not hang waiting for terminal input.
- Action: Restart after successful recovery and send one normal message in the new channel.
  Expected: No replacement prompt; the saved channel's scoreboard counts the message. The previous channel does not count.

## Slash discovery and private feedback

- Action: Invite/re-authorize the bot with the bot and applications.commands scopes; allow View Channel, Send Messages, Read Message History, and Manage Messages. Start the bot and type `/cap` in the configured text channel.
  Expected: `/cap_channel`, `/cap_user`, `/cap_default`, `/cap_clear`, `/cap_status`, `/cap_reset`, and `/cap_help` are registered for the server. Moderator command visibility follows Discord permissions. Message Content intent is not required.
- Action: As an ordinary member with Use Application Commands, run `/cap_help`, `/cap_status`, and `/cap_status user:@Alice` using the member picker.
  Expected: Private replies show concise help or the chosen member's status, effective cap/source, sent/retained counts, remaining allowance, channel, accounting window, timezone, and next midnight reset. Replies cause no mentions or public channel clutter.
- Action: Run `/cap_status` in another server text channel; inspect command availability in a DM.
  Expected: The other channel receives a private actionable response pointing to the configured channel. The server commands are unavailable in DMs and cannot execute there.
- Action: Deny an ordinary member Manage Messages in the monitored channel. Try a moderator command; if server integration settings expose it, invoke it directly. Then grant Manage Messages and try again.
  Expected: Unauthorized changes are unavailable or privately rejected without changing state. The authorized invocation succeeds. Role-level permission does not override a channel denial unless the user is Administrator.
- Action: Try `/cap_user` with a zero/negative limit or Twitter Cap itself.
  Expected: Discord or the bot rejects the invalid value/target clearly; stored caps and counts remain unchanged.
- Action: Briefly disconnect/reconnect the running bot, then inspect its log and scoreboard.
  Expected: Slash registration is not repeated on reconnect and one scoreboard worker remains active. A registration failure, if encountered, is logged without claiming commands are ready.

## Cap commands and persistence

- Action: With default 3 and no personal override, run `/cap_user user:@Alice limit:2`, then `/cap_status user:@Alice`.
  Expected: The private confirmation shows old/new effective caps and the channel. Status identifies a personal cap of 2; existing counts/messages are unchanged and the scoreboard refreshes within the throttle.
- Action: Run `/cap_default limit:4`, then inspect Alice and a member without an override.
  Expected: Alice remains capped at 2. The other member inherits default 4 immediately. Lowering any cap does not delete messages immediately; the next over-cap send causes exactly one eligible same-user deletion.
- Action: Stop and restart with `./scripts/run.sh`, then inspect both statuses.
  Expected: The personal override and channel default persist. No token prompt occurs. The server’s saved config under guild_data retains default 4; global CLI defaults do not overwrite it.
- Action: Start the bot, run `/cap_clear user:@Alice` twice, and inspect Alice's status and scoreboard.
  Expected: The first invocation exempts Alice from all caps without resetting counts. Her status says unlimited and she disappears from the scoreboard. Users with only the default cap are also omitted from the scoreboard. The second reports that Alice is already exempt. `/cap_user` can assign her a cap again.

## Reset confirmation and isolation

- Action: With messages from Alice and Bob present, run `/cap_reset user:@Alice` and select Cancel.
  Expected: A private prompt names Alice and explains that existing messages remain. Cancel changes no counts, deletion eligibility, or caps.
- Action: Request another reset and wait more than 30 seconds before attempting Reset counters.
  Expected: The confirmation expires; it performs no reset and a fresh command is required.
- Action: .venv/bin/python -m unittest discover -s tests -p test_slash.py -v
  Expected: A different user's interaction is rejected, and a successful confirmation can execute only once. A private confirmation cannot normally be shared with a second live account.
- Action: Request Alice's reset as a moderator, revoke that moderator's Manage Messages before Reset counters, then confirm without Administrator permission.
  Expected: Confirmation rechecks permissions and rejects the reset; counts and messages remain unchanged. Restore permissions for further checks.
- Action: Run `/cap_reset user:@Alice`, select Reset counters, then inspect Alice and Bob and send new messages from Alice past her cap.
  Expected: Alice starts at zero sent/retained, labeled since reset. Bob is unchanged. All old human messages remain; only Alice's post-reset messages can be randomly deleted. Caps and overrides remain.
- Action: Restart the bot during Alice's reset window and inspect `/cap_status user:@Alice`.
  Expected: The reset window and new counts persist; old messages remain ineligible. Redelivered pre-reset events remain deduplicated in automated tests.
- Action: Run `/cap_reset` with no user and select Reset counters.
  Expected: The prompt explicitly names the entire monitored channel. All current accounts start fresh and display since reset; existing Discord messages, default cap, and personal overrides remain.

## Cap and user isolation

- Action: Set `/cap_default limit:3`, clear test overrides, confirm `/cap_reset`, then send three messages as user A and one as user B. Wait at least five seconds.
  Expected: A shows 3 sent and 3 retained; B shows 1 sent and 1 retained. All four human messages remain.
- Action: Send A's fourth message and wait for the scoreboard refresh.
  Expected: Exactly one of A's four messages is deleted; it may be the newest. A shows 4 sent and 3 retained. B's message remains.
- Action: Send A's fifth message, then edit one surviving A message and manually delete another surviving A message.
  Expected: The fifth message causes one additional A deletion. The edit does not increase sent count. The manual deletion decreases retained count but leaves sent count unchanged.
- Action: Send messages in another channel, send a webhook message, and allow Twitter Cap to refresh its scoreboard.
  Expected: These messages do not change any counters or trigger random cap deletions.
- Action: Run `/cap_user user:@OtherBot limit:3`, then `/cap_reset user:@OtherBot` and confirm. Have that bot send four new messages in this channel.
  Expected: The bot target is accepted. One of its four messages is deleted; `/cap_status user:@OtherBot` shows 4 sent and 3 retained. Twitter Cap’s own replies remain excluded. Run `/cap_clear user:@OtherBot` afterward, or restore its prior override.
- Action: Have any human member post an X status URL that causes SaucyBot to reply directly to the message.
  Expected: Below each account's cap, the original human message and its X/Twitter URL remain after SaucyBot replies. SaucyBot's response also remains. Reply arrival does not trigger source cleanup.
- Action: Set the human poster and SaucyBot to cap 2 with `/cap_user`, reset each with `/cap_reset`, then send three original posts and have SaucyBot send three replies.
  Expected: Each account shows 3 sent and 2 retained. One original and one SaucyBot post are deleted by their separate caps; SaucyBot replies do not delete the referenced original as an extra cleanup step. Restore both accounts' previous caps after checking.
- Action: Set a member's cap to 1, ensure their only tracked message is removed manually, then send another message as that member.
  Expected: Sent increases, and the new message remains as the only tracked message (`1 retained`). It is not selected for deletion when no older candidate remains.

## Sticky display and restart

- Action: Send a short burst of human messages and watch the scoreboard for at least ten seconds.
  Expected: A current status batch appears near the bottom, refreshes no more than once every five seconds, and does not trigger a bot-message loop. Old status messages are cleaned up; human messages follow cap behavior.
- Action: Stop the bot with Ctrl+C without changing configuration.
  Expected: The process exits cleanly.
- Action: ./scripts/run.sh
  Expected: Today's counts persist and the stored old scoreboard batch is cleaned up when replaced. Startup does not ask for the token.
- Action: In a server with enough active test users to exceed one status message, inspect the scoreboard after refresh.
  Expected: Status is split into messages within Discord's limit, every active user appears, and replacing the batch removes the prior status batch.

## Midnight and failures

- Action: Keep the bot running through midnight in the configured timezone, with human messages from the previous day still present.
  Expected: The displayed date/counters reset even without new activity. Since-reset labels end and personal overrides persist. Previous-day human messages remain and are never selected for today's random deletions.
- Action: Request a reset shortly before local midnight and attempt Reset counters after the day changes, within its 30-second lifetime.
  Expected: The stale confirmation cannot reset the new day; a fresh request is required.
- Action: Temporarily deny the bot Manage Messages in the test channel, then send an over-cap message.
  Expected: Logs identify the permission/API failure without claiming successful deletion. Messages may remain above the cap until permissions are restored; the bot stays responsive.
- Action: Restore Manage Messages and send another over-cap message.
  Expected: A deletion attempt succeeds and status reflects actual tracked retained messages. One extra message causes one deletion; it does not retroactively guarantee removal of every message retained during the failure.

## Existing database upgrade

- Action: Before upgrading an existing installation, stop the process and back up its private configuration/database. Start the new bot using its existing version-1 database, then inspect status and the scoreboard.
  Expected: Migration preserves today's sent/retained counts and existing status IDs for cleanup. Commands work without deleting/recreating data, and no duplicate old scoreboard batch remains after refresh. The automated v1 migration regression is the reproducible fallback when no existing installation is available.

## Restore normal configuration

- Action: Run `/cap_default limit:50`, then `/cap_clear user:@Alice` and `/cap_clear user:@Bob` for any test overrides.
  Expected: Status reports unlimited for test members explicitly cleared earlier; other members use the channel default of 50. Counts remain until reset or midnight.
- Action: Stop the bot with Ctrl+C.
  Expected: The process exits cleanly.
- Action: .venv/bin/python bot.py --check
  Expected: The offline check reports cap 50.
- Action: ./scripts/run.sh
  Expected: Startup reuses the saved token and persisted state.
- Action: .venv/bin/python -m unittest discover -s tests -v
  Expected: All offline regression tests pass. Record live checks separately; an offline test pass does not verify Discord credentials, permissions, or command registration.


## Channel-access recovery

- Action: Start with a valid token but a text-channel ID the bot cannot access.
  Expected: Startup prints an invite/re-authorization URL plus channel-ID and permission-override guidance, keeps the Gateway online for /cap_channel or mention-based setup. Optional voice warnings are unrelated to channel access.
- Action: Use the invite link to authorize the correct bot in the correct server, allow the four channel permissions, and start again.
  Expected: Channel resolution succeeds when the ID and permissions are correct; the Ready message and slash-registration result appear.

## Multiple servers and channel setup

- Action: Invite the same bot to servers A and B. In each server, run `/cap_channel channel:#test` with Manage Server permission. If it is absent, send `@Twitter Cap channel here` with the real bot mention.
  Expected: Each server gets its own saved channel, scoreboard, and nine commands. Setup in B does not redirect A.
- Action: As the same human member in both servers, set your personal cap to 1 in A and 3 in B, reset your counters in both, then send two messages in each.
  Expected: A shows 2 sent / 1 retained; B shows 2 sent / 2 retained. No cross-server deletion occurs.
- Action: Run `/cap_default limit:8` and `/cap_reset` (confirm) in A; inspect `/cap_status` in B.
  Expected: B’s default, override and counters do not change. Restore prior caps after testing.
- Action: Run `/cap_channel` without Manage Server, or try a channel ID from another server through the mention command.
  Expected: Setup is rejected and both saved configurations remain unchanged.
- Action: Change A’s channel with `/cap_channel`, then restart the process.
  Expected: A rebuilds today's counts from surviving messages in its newly saved channel; B keeps its channel and counts. Old A messages stay untouched. Old reset confirmations cannot mutate the new scope. A's reader selection persists, with its jump now searching the new channel.
- Action: Upgrade a stopped single-server installation with a backup, start the new bot, and inspect its original server’s `/cap_status` before sending more messages.
  Expected: Existing daily counts and overrides import once into the owning server. Other servers start independently; restarting does not re-import stale legacy counts.
