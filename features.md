# Baxi - Features

Complete documentation of all features available in the Baxi Discord bot.  
Each feature can be enabled/disabled and configured per-server via the dashboard at https://baxi.avocloud.net or via slash commands.

---

## Moderation

**Commands:** `/ban`, `/kick`, `/unban`, `/mute`, `/unmute`, `/clear`, `/warn`, `/unwarn`, `/warnings`, `/case`, `/note`

Ban, kick, mute and warn members with optional temporary durations, auto-escalation and DM notifications. All actions are logged and confirmed via button prompts before execution.

### What it does
- **Ban/Kick/Unban** – Remove or restore users with confirmation dialogs and automatic DM notifications containing reason, moderator and (for bans) expiration date
- **Mute (Timeout)** – Temporarily silence users (max 28 days, Discord limit) with DM notification
- **Clear** – Bulk-delete messages from a text channel with confirmation
- **Warn System** – Issue formal warnings that auto-escalate to mute → kick → ban at configurable thresholds (default: 3 warns = mute, 5 = kick, 7 = ban)
- **Warnings Log** – View and remove individual warnings by ID
- **Cases** – Every action against a person is a numbered case (#123, per server, never reused). The user gets exactly one DM with what happened, why, how long, the case number and an **Appeal** button
- **Case file** – `/case <member>` shows a member's full history (staff only); `/note add|remove` keeps private staff notes
- **Appeals** – Users appeal a case from the DM button or the web page `/appeal/` (own cases only, one per case, within 14 days). Appeals land in the review queue for the team
- **Retention** – Cases and notes are kept one year, closed review items 30 days

### Customization
- Warn escalation thresholds (`mute_at`, `kick_at`, `ban_at`) configurable per guild
- Mute duration after auto-escalation configurable (`mute_duration`)
- All text and embeds support i18n (German + English via `lang/lang.json`)
- Permission-gated: requires `ban_members`, `kick_members`, `moderate_members`, `manage_messages` respectively

---

## Chat Filter

Local, multi-stage message filtering that inspects every message sent on the server (no external API).

### What it does
1. **SafeText lexicons** – Text normalisation (obfuscated spellings, l33t, spacing) plus German/English word lists for slurs, threats, self-harm phrases and personal data
2. **Local toxicity model** – `textdetox/xlmr-large-toxicity-classifier` runs in its own process, started on the first message that needs a score and stopped after it was unused for a while
3. **Phishing URL Detection** – Real-time check against a continuously updated blocklist of scam/phishing domains
4. **Sensitivity** – 3-step slider (with a live description) per server; borderline messages go to the review queue instead of being removed

Messages that violate any layer are automatically deleted. Users receive a DM-style embed explaining the deletion reason with a link to appeal.

### Customization
- Enable/disable entire filter or individual layers (`phishing_filter`, `ai_categories`)
- AI categories can be toggled individually (1–5 correspond to the five offense types above)
- Fully localized error messages and explanations
- Integrates with Prism trust scoring – violations lower the user's trust score

---

## Language Gate

Keeps a server (or parts of it) to German and/or English. Messages in any other language are removed, like the chat filter does.

### What it does
- Runs right after the Chat Filter, also on edited messages; a removed message earns no level XP and triggers no custom command
- Detects the language locally, without an external service: non-Latin scripts (Cyrillic, Arabic, Korean, Japanese/Chinese) by their characters, Latin-script languages (German, English, French, Spanish, Italian, Portuguese, Dutch, Turkish, Polish) by typical function words
- Cautious on purpose: texts under 12 letters or 4 words, dialect, slang, abbreviations and mixed-language chat are left alone; a message is only removed when a foreign language clearly outweighs the allowed ones
- Deletes the message and posts a short notice that disappears after 10 seconds (at most once per 20 seconds per member); no warning, no case, no DM
- Never applies to bots, DMs, ticket channels, the global chat or attachment-only messages

### Customization
- Allowed languages: German, English or both
- Exempt members who can manage messages (on by default)
- Free channels where any language is fine
- Requires the `manage_messages` permission in the channel

---

## Anti-Spam

Detects and acts on message floods, repeated content and mention spam in real time.

### What it does
- Tracks message frequency per user within a sliding time window
- Detects duplicate messages sent in rapid succession
- Configurable whitelist for channels and roles (e.g. mod channels exempt)
- Automatic actions: warn or mute the offending user
- Integrates with Prism – spam events lower trust scores

### Customization
- `max_messages` – messages allowed within the interval before triggering
- `interval` – time window in seconds for the message count
- `max_duplicates` – how many identical messages trigger the filter
- `action` – `"mute"` or `"warn"`
- `whitelisted_channels` / `whitelisted_roles` – bypass lists

---

## Welcomer

Sends custom join and leave messages with optional generated banner images.

### What it does
- Posts a welcome embed when a member joins, with customizable text template
- Posts a farewell embed when a member leaves
- Supports variables: `{user}` (mention), `{username}`, `{displayname}`, `{server}`, `{membercount}`
- Optional image generation: renders a PNG card with the user's avatar, server name and member count using Pillow
- Custom background images can be uploaded per-guild

### Customization
- Separate channels for welcome and leave messages
- Custom message templates
- Custom embed colors (`color`, `leave_color`)
- `image_mode`: `"none"` or `"generate"` (generates the welcome card)
- `card_color` for the generated banner background
- Upload custom background images to override the default gradient

---

## Live Stats Channels

Dedicated voice channels that automatically display live server statistics.

### What it does
Renames voice channels every 10 minutes to show real-time counts for:
- Total members
- Humans (non-bot members)
- Bots
- Text/Voice channels
- Roles

### Customization
- Enable/disable individual stat types
- Custom name templates per stat (e.g. `"Members: {count}"`)
- Only updates the channel name when the value actually changes (respects Discord rate limits)
- Runs on a 10-minute polling interval

---

## Livestream Tracker

Polls Twitch, YouTube and TikTok for go-live events and posts Discord embed notifications.

### What it does
- **Twitch** – Batched API calls every 60 seconds, round-robin queue (max 20 checks/min)
- **YouTube** – Uses yt-dlp (no API key/quota required) to detect live streams every 5 minutes
- **TikTok** – Scrapes `/live` pages for live status every 5 minutes
- Automatically renames the configured Discord channel to show 🔴/⚫ status
- Posts rich embeds with title, game/category, viewer count, start time and thumbnail
- Optional role ping when a streamer goes live
- Caches profile images for display in embeds

### Customization
- Per-streamer platform selection (Twitch, YouTube, TikTok)
- Custom Discord channel per streamer
- Optional `ping_role` for notifications
- Localized embed text (German + English)
- Automatically handles embed deletion and re-sends if the message is removed

---

## Global Chat

Cross-server chat rooms that relay messages between participating guilds.

### What it does
- Messages sent in a designated channel are relayed to all other guilds participating in the same global chat network
- Messages are reformatted into embeds showing sender name, avatar, guild name and icon
- Supports image attachments, GIFs (Tenor), Imgur, Reddit media
- Optional watermarking on images (`--watermark` flag in message)
- Reply threading is preserved across servers
- Shared flagged-user database – globally flagged users are blocked from participating
- Automated moderation via Chat Filter and Anti-Spam

### Customization
- Per-guild channel configuration
- Baxi-hosted attachment storage with unique message IDs
- Automatic bans for flagged users (shared across all participating guilds)
- Message length limit: 1000 characters

---

## Temp Voice Channels

On-demand private voice channels created when a user joins a designated trigger channel.

### What it does
- When a member joins the configured "create" channel, Baxi instantly creates a new voice channel
- The member is automatically moved into their private channel
- Channel is named using a configurable template (default: `"{user}'s Channel"`)
- Automatically deleted when the last member leaves
- Empty channel cleanup runs regardless of feature state

### Customization
- `create_channel_id` – the trigger channel users must join
- `category_id` – optional category for new channels (falls back to trigger channel's category)
- `name_template` – supports `{user}` variable for the member's display name

---

## Support Tickets

Full member support workflow with configurable categories, staff roles and automatic transcripts.

### What it does
- Persistent panel message with configurable buttons (one per ticket type, e.g. "Support", "Report", "Feedback")
- Clicking a button creates a private ticket channel in a configured category
- Only the ticket creator and configured staff roles can access the channel
- Staff can "claim" tickets to indicate they are handling it
- Ticket closure requires typing "confirm" in the channel as a safety measure
- Automatic transcript generation and DM to the user upon closure
- Transcript panel message auto-resends if deleted

### Customization
- Custom ticket panel message and embed color
- Fully configurable buttons: each with custom `id`, `label`, `emoji`, and `style` (primary/secondary/success/danger)
- Configurable transcript channel
- Configurable staff role with access permissions
- Configurable ticket category
- Localized messages for all interactions

---

## Prism – Trust Scoring

Network-wide behavior analysis that assigns every user a trust score (0–100) based on violations across all Baxi servers.

### What it does
- Tracks moderation events (bans, kicks, warnings, chatfilter violations, spam, phishing) across all participating guilds
- Calculates a rolling trust score with severity-based penalties:
  - **Critical** (−30 / −25): Phishing, Bans
  - **Severe** (−20): Hate Speech
  - **High** (−15): Content Violations
  - **Medium** (−12): Kicks
  - **Low** (−8): Spam
  - **Minor** (−6): Warnings
  - **Minimal** (−4): Mild Violations
- Time-based decay: events older than 90 days count at half weight
- Recovery: score gradually increases during clean periods, rate depends on worst offense tier
- Velocity penalties: burst violations within 24h/7d incur extra penalties
- Account age ramp: new accounts (< 90 days) start with a reduced score
- Auto-flags users at score ≤ 30, auto-unflags at ≥ 50
- Risk signal detection: new account age, velocity bursts, multi-server violations
- Optional LLM-generated risk summaries via OpenWebUI
- User-facing `/my_trust` command for transparency
- Opt-out support via `/prism_optout`

### Customization
- Per-guild enable/disable (`prism_enabled`)
- Individual users can opt out of scoring
- Notification channel for staff alerts on critical/severe events
- Near-flag warnings when score approaches threshold (≤ 45)
- Event and profile data pruned automatically (90-day retention)

---

## Minigames

Two built-in community games with leaderboards and configurable settings.

### Counting Game
- Members take turns counting upward by sending the next number in sequence
- Only one user can count at a time (configurable: no double-counting)
- Reactions for correct/incorrect answers (configurable)
- Tracks high scores per guild
- Configurable dedicated channel

### Flag Quiz
- Baxi posts a flag image and members guess the country
- Hints appear after a configurable number of wrong attempts
- Points-based scoring with per-user leaderboards
- Configurable delay between questions
- Points can be enabled or disabled

### Customization
- Both games run in dedicated, configurable channels
- Enable/disable independently
- Quiz: `hint_after_attempts`, `next_delay`, `points_enabled`
- Counting: `no_double_count`, `react_correct`, `react_wrong`

---

## Giveaway

**Command:** `/giveaway`

Start a giveaway in any text channel. Members enter via button (live participant count shown on button). When the duration expires, winners are drawn randomly, announced in the channel via embed, and notified by DM. Supports custom winner message, configurable winner count (1–20) and optional image attachment.

---

## Suggestions

Members submit ideas to a dedicated channel; Baxi converts each into a formatted embed with voting and staff review.

### What it does
- Suggestions posted in designated channels are automatically reformatted as embeds with upvote/downvote buttons
- Public voting with live vote counts on the buttons
- Private discussion thread auto-created for each suggestion
- Staff buttons: Accept, Decline, Comment – all open modals for optional reasoning
- Decisions are recorded on the embed with reviewer name and timestamp
- Optional auto-forward: suggestions exceeding a configurable upvote threshold are forwarded to a designated channel
- Log channel for tracking all staff decisions
- Staff can join the discussion thread via button

### Customization
- Multiple suggestion channels, each with independent `votes_enabled` toggle
- Configurable staff role (or `manage_guild` permission) for review actions
- `auto_forward_enabled` with configurable `auto_forward_threshold`
- Dedicated log channel for decision tracking
- Localized button labels, modal text and embed fields

---

## Reaction & Button Roles

Self-assignable roles triggered by clicking buttons on panel messages.

### What it does
- Configurable role panels with one button per role
- Clicking a button toggles the associated role on the user
- Per-panel `max_roles` limit: clicking a new role automatically removes the oldest one if the limit is exceeded
- Persistent buttons survive bot restarts via Discord's custom_id system
- Dynamic item registration for template-based role IDs (`rr:<role_id>`)

### Customization
- Multiple panels per guild, each with custom `title`, `description` and `color`
- Per-entry: `role_id`, `label`, `emoji` (standard or custom Discord emojis)
- `max_roles` per panel (0 = unlimited, N = mutual-exclusion group of size N)
- Localized response messages (role applied, removed, group limit exceeded)

---

## Auto-Roles

Automatically assigns configured roles to every new member on join.

### What it does
- When a member joins, Baxi assigns all roles configured in the auto-roles list
- Runs immediately on `on_member_join`
- Silent failures on missing permissions (logged for admin review)

### Customization
- Enable/disable per guild
- Configurable list of role IDs
- Integrates with member join event (runs alongside Welcomer)

---

## Custom Commands

Create server-specific text or embed responses triggered by any message content.

### What it does
- Admin-configured trigger words/phrases that auto-reply with a predefined response
- Responses can be plain text or rich embeds with custom titles, descriptions, colors and fields
- Supports user variables in response templates

### Customization
- Per-guild command definitions stored in `custom_commands`
- Configured entirely via the dashboard
- No prefix required – matches raw message content

---

## Warnings & Auto-Slowmode

### Warnings
- Issue formal warnings to members with `/warn` (requires `moderate_members`)
- Warnings are logged with unique IDs, reasons and moderator attribution
- DM notifications sent to the warned user
- Remove warnings by ID with `/unwarn`
- View all warnings for a user with `/warnings`

### Auto-Slowmode
- Monitors message activity in text channels
- Automatically applies a slowmode delay when message frequency exceeds a threshold
- Configurable threshold, interval, slowmode delay and duration
- Passive check – does not block message processing

### Customization
- **Slowmode:**
  - `threshold` – messages per interval to trigger slowmode
  - `interval` – time window in seconds
  - `slowmode_delay` – slowmode duration to apply
  - `duration` – how long the slowmode lasts

---

## Verification

Button-based member verification panel that grants a configured role on click.

### What it does
- Persistent panel message with a "Verify" button
- Three verification modes:
  0. **Instant** – click button, get role immediately
  1. **CAPTCHA** – user must solve a 5-character alphanumeric CAPTCHA modal
  2. **Password** – user must enter a server-defined password via modal
- Panel message auto-resends if deleted
- Requires guild to have accepted terms of service

### Customization
- `verify_option`: 0 (instant), 1 (CAPTCHA), 2 (password)
- Configurable role ID (`rid`)
- Custom panel `title`, `description` and `color`
- Password stored in config for password mode
- Localized success/error messages

---

## Sticky Messages

Pins a message to the bottom of a channel by automatically re-posting it whenever newer messages push it out of view.

### What it does
- Configured message is automatically posted in designated channels
- Whenever a new message is posted and a debounce window (4 seconds) passes without further activity, the sticky is deleted and re-posted at the bottom
- Debounce prevents excessive re-posting during active conversations
- Per-channel configuration

### Customization
- Per-channel sticky message content
- Automatic footer: "📌 Sticky Message · Baxi"
- Embed color matches server theme

---

## YouTube Video Alerts

Monitors configured YouTube channels and posts embeds when new videos are uploaded.

### What it does
- Polls YouTube RSS feeds every 10 minutes for new uploads (no API key required)
- Posts an embed with video title, thumbnail, publish date and link
- Optional role ping to notify subscribers
- Dedicated log channel for tracking posted videos

### Customization
- Per-guild list of monitored YouTube channels (handle or channel ID)
- Configurable alert channel for embeds
- Optional `ping_role` for notifications
- Enable/disable per guild

---

## Leveling System

Members earn XP from chatting and from time in voice channels; one level is derived from both.

### What it does
- **Text XP** – Once per 60 seconds per member, only for messages that passed anti-spam and the chat filter
- **Voice XP** – 5 XP per full minute, only while not deafened, with another non-deafened human present, not in the AFK channel
- Level-up announcements with configurable destination
- Role rewards: automatically assign roles when milestones are reached
- `/rank [member]` shows a rank card, `/leaderboard` the top members

### Customization
- Enable/disable per guild
- Announcement mode: `"same_channel"`, dedicated `"channel"`, or `"off"`
- `role_rewards`: list of `{level, role_id}` pairs for automatic role assignment

---

## Honeypot

A trap channel that catches spam bots.

### What it does
- Admins pick one channel; a notice in it tells people not to write there. Setup can create the channel automatically
- Whoever writes there is removed through the normal case flow (case number, one DM, audit-log reason) and the message is deleted
- Action is `ban`, `kick` or `mute` (24 h). A ban also deletes the member's messages of the last N hours in all channels
- Staff (Manage Messages / Manage Server / Administrator) and bots are ignored

---

## Pulse, Insights & Wrapped

- **Pulse** (`/pulse server|me|recap`) – When and how the community is active, best time to post, personal streak and rank, plus a weekly recap post
- **Insights** (`/insights`) – Server statistics derived from the activity data, including voice time
- **Wrapped** – A yearly personal summary card with a button

---

## Community Extras

- **Starboard** – Messages with enough star reactions are copied to a board channel; `/starboard random`, weekly throwbacks
- **Quote Book** (`/quote add|show|list|remove`) – Save and look up memorable messages, quote reactions
- **Time Capsule** (`/capsule send|list|cancel`) – Seal a message that is delivered later
- **Polls** (`/poll`, `/pollstatus`) – Up to 10 options, staff overview of running polls
- **Birthdays** (`/birthday set|remove|hide|show|upcoming`)
- **Invite tracking** (`/invites top|user`) – Optional, off by default
- **One Word Story** – Minigame next to counting and the flag quiz

---

## Embed Art (Dither)

- Every embed with a title or fields gets a small animated, transparent dither picture as thumbnail (avocloud brand: Bayer 4x4, rust tones)
- The shape follows the slash command (shield for bans, bars for music and stats, spiral for help, ...); red embeds show a "!", green ones a check mark
- Slash command replies, errors and moderation embeds (including the honeypot) always have it; for everything else (tickets, suggestions, welcome ...) it can be switched off per server under **General → Dither graphics**
- The images are rendered by the bot and served from `/dither/<shape>.gif` of the web server

---

## Staff Roles

One shared **staff roles** setting (General) used by tickets and suggestions; the notification channel doubles as the staff channel for open items.

---

## Admin & Utility

### User Scan (`/scan_users`)
- Scans all members of the current server against the global flagged-user database
- Displays Prism trust scores, flag sources (auto vs manual), event counts and entry dates
- Recommendations for moderators based on scan results

### Bot owner (`/owner`)
- Owner-only command (checked with `bot.is_owner`, team aware) that posts a "verified bot owner" embed with server count, shards and latency; everyone else gets a private refusal

### Dashboard (`/dashboard`)
- Returns the link to the Baxi web dashboard for server configuration

### Help (`/help`)
- Displays information about bot prefix, about section, icon sources and bug reporting

### User Management (Dashboard)
- Flag/unflag users globally with reason tracking
- Manual flag status overrides Prism auto-flagging
- User list viewable and editable via the dashboard

---

## Background Tasks

Baxi runs several automated background tasks to maintain system health:

| Task | Interval | Purpose |
|------|----------|---------|
| **GCDH Sync** | 15s | Syncs global chat message data (only when something changed) |
| **Backup** | 12h | SQLite snapshot, gzip, upload to the backup server |
| **Rest mode** | idle | After 10 min without activity: stops the chat filter model, frees memory, idle presence |
| **Voice activity** | 5min | Books voice time and voice XP |
| **Starboard / Time Capsule** | 30min / 5min | Throwbacks, delivery of sealed capsules |
| **Update Stats** | 10min | Counts guilds and unique users, posts to TopGG |
| **Livestream (Twitch)** | 60s | Polls Twitch for streamer go-live/offline events |
| **Livestream (YT/TikTok)** | 5min | Polls YouTube and TikTok for live status |
| **Stats Channels** | 10min | Updates voice channel names with server stats |
| **Temp Actions** | Periodic | Processes timed bans and timeout expirations |
| **Phishing List** | Periodic | Fetches updated phishing domain blocklist |
| **Prism Recalculation** | Periodic | Recalculates trust scores for all users with time-based decay |
| **Garbage Collector** | Periodic | Prunes old activity and moderation events (90-day retention) |
| **YouTube Videos** | 10min | Checks for new video uploads on monitored channels |

---

## Technical Infrastructure

### Multi-Language Support
- German (`de`) and English (`en`) via `lang/lang.json`
- Per-guild language selection stored in guild config
- All user-facing strings externalized for translation

### Sharding
- Auto-sharded bot supporting large-scale deployments
- Shard count via `SHARD_COUNT` in `.env`

### Web Dashboard (Quart)
- CORS-enabled Quart web server running alongside the bot
- Template rendering with custom Jinja filters (e.g. `highlight_word`)
- "Starting" page displayed while bot is not ready
- OAuth2 integration for guild management

### Data Storage
- SQLite database (`baxi_data.db`); per-guild config, tickets, transcripts, users, stats, activity, cases, leveling, Prism trust and global chat live in tables
- Settings without their own table fall back to a generic `guild_misc` store
- Automatic backups every 12 h

### Logging
- `reds_simple_logger` for structured logging with levels (info, debug, success, warning, error)
- Admin log channel for internal event tracking
- Per-task status reporting

---

## Configuration

All features are configured via:
1. **Web Dashboard** at https://baxi.avocloud.net (recommended)
2. **The SQLite database** (per-guild config)
3. **Hardcoded defaults** in `config/config.py` → `datasys.default_data`

Global settings (shard count, API URLs, colors, version) are in `config/config.py` and `config/auth.py`.
