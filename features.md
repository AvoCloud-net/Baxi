# Baxi - Features

Complete documentation of all features available in the Baxi Discord bot.  
Each feature can be enabled/disabled and configured per-server via the dashboard at https://baxi.avocloud.net or via slash commands.

---

## Moderation

**Commands:** `/ban`, `/kick`, `/unban`, `/mute`, `/clear`, `/warn`, `/unwarn`, `/warnings`

Ban, kick, mute and warn members with optional temporary durations, auto-escalation and DM notifications. All actions are logged and confirmed via button prompts before execution.

### What it does
- **Ban/Kick/Unban** – Remove or restore users with confirmation dialogs and automatic DM notifications containing reason, moderator and (for bans) expiration date
- **Mute (Timeout)** – Temporarily silence users (max 28 days, Discord limit) with DM notification
- **Clear** – Bulk-delete messages from a text channel with confirmation
- **Warn System** – Issue formal warnings that auto-escalate to mute → kick → ban at configurable thresholds (default: 3 warns = mute, 5 = kick, 7 = ban)
- **Warnings Log** – View and remove individual warnings by ID

### Customization
- Warn escalation thresholds (`mute_at`, `kick_at`, `ban_at`) configurable per guild
- Mute duration after auto-escalation configurable (`mute_duration`)
- All text and embeds support i18n (German + English via `lang/lang.json`)
- Permission-gated: requires `ban_members`, `kick_members`, `moderate_members`, `manage_messages` respectively

---

## Chat Filter

Three-layer message filtering that inspects every message sent on the server.

### What it does
1. **SafeText** – Keyword and regex-based pattern matching against known bad words/phrases
2. **AI Content Moderation** – Sends flagged messages to an external AI API (OwUI/Qwen) for classification into 5 categories: NSFW, Insults, Hate Speech, Doxxing, Self-Harm
3. **Phishing URL Detection** – Real-time check against a continuously updated blocklist of scam/phishing domains (sourced from Discord-AntiScam)

Messages that violate any layer are automatically deleted. Users receive a DM-style embed explaining the deletion reason with a link to appeal.

### Customization
- Enable/disable entire filter or individual layers (`phishing_filter`, `ai_categories`)
- AI categories can be toggled individually (1–5 correspond to the five offense types above)
- Fully localized error messages and explanations
- Integrates with Prism trust scoring – violations lower the user's trust score

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

Members earn XP for every message they send, scaling with message length, and level up automatically.

### What it does
- XP awarded per message based on content length:
  - < 20 chars: 8 XP
  - < 100 chars: 20 XP
  - < 300 chars: 35 XP
  - ≥ 300 chars: 50 XP
- Level formula: `level * (level + 1) * 50` cumulative XP (e.g. level 1 = 100 XP, level 2 = 300 XP)
- Level-up announcements with configurable destination
- Role rewards: automatically assign roles when milestones are reached
- Per-server, per-user tracking stored in `data/<guild_id>/leveling_users.json`

### Customization
- Enable/disable per guild
- Announcement mode: `"same_channel"`, dedicated `"channel"`, or `"off"`
- `announcement_channel` for dedicated mode
- `role_rewards`: list of `{level, role_id}` pairs for automatic role assignment
- Localized level-up embed text

---

## Donations

Integrated donation system supporting Stripe and PayPal payment providers.

### What it does
- Configurable donation page text and success message
- Supports Stripe and PayPal payment processing
- Encrypted storage of payment provider secrets using Fernet (AES-128-CBC)
- Optional logging of donations to a dedicated channel
- Tiered donation rewards

### Customization
- `provider`: `"stripe"` or `"paypal"`
- Encrypted API keys via `crypto.py` (master key in `config/auth.py`)
- Custom `page_text` for the donation button/panel
- Custom `success_text` shown after payment
- `log_enabled` + `log_channel` for donation tracking
- Configurable donation `tiers`

---

## Admin & Utility

### User Scan (`/scan_users`)
- Scans all members of the current server against the global flagged-user database
- Displays Prism trust scores, flag sources (auto vs manual), event counts and entry dates
- Recommendations for moderators based on scan results

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
| **GCDH Sync** | 15s | Syncs global chat message data to disk |
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
- Default: 4 shards, configurable via `config.py`

### Web Dashboard (Quart)
- CORS-enabled Quart web server running alongside the bot
- Template rendering with custom Jinja filters (e.g. `highlight_word`)
- "Starting" page displayed while bot is not ready
- OAuth2 integration for guild management

### Data Storage
- Per-guild JSON files in `data/<guild_id>/`
- Separate files for: config, tickets, transcripts, users, stats, activity, mod events, filter events, temp actions, leveling, Prism trust, global chat
- Automatic directory creation on guild join

### Encryption
- Fernet symmetric encryption for sensitive data (donation API keys, etc.)
- Master key stored in `config/auth.py`
- Legacy plaintext values auto-upgraded to encrypted on next save

### Logging
- `reds_simple_logger` for structured logging with levels (info, debug, success, warning, error)
- Admin log channel for internal event tracking
- Per-task status reporting

---

## Configuration

All features are configured via:
1. **Web Dashboard** at https://baxi.avocloud.net (recommended)
2. **JSON config files** in `data/<guild_id>/conf.json`
3. **Hardcoded defaults** in `config/config.py` → `datasys.default_data`

Global settings (shard count, API URLs, colors, version) are in `config/config.py` and `config/auth.py`.
