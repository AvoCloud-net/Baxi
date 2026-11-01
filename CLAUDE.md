# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current

## Running the Bot

```bash
pip install -r requirements.txt
python main.py
```

The bot runs in `asyncio.gather` -  both the Discord bot (`discord.py`) and the Quart web server start concurrently. Web server listens on port `1637` by default.

## Configuration

- `.env` (project root, git-ignored; template `.env.example`) -  everything server-specific: secrets, channel/guild ids, URLs, port. Loaded by `config/env.py`, real env vars win. This keeps `config/` copyable to the server without touching secrets.
- `config/auth.py` -  reads the secrets from `.env` via `get(...)`. **Never write real values into it.**
- `config/config.py` -  settings (shard count, colors, API URLs, check intervals, default guild data schema).

## Architecture

### Entry Point (`main.py`)
Creates `PersistentViewBot` (subclass of `commands.AutoShardedBot`) and a Quart `web` app. `setup_hook` registers persistent Views (buttons that survive bot restarts). Bot and web server run concurrently via `asyncio.gather`.

### Data Layer (`assets/data.py`, `assets/share.py`)
- Per-guild config stored as `data/<guild_id>/conf.json`. Default schema defined in `config.config.datasys.default_data`.
- Additional per-guild files: `tickets.json`, `transcripts.json`, `users.json`, `chatfilter_log.json`, `stats.json`, `globalchat_message_data.json`.
- `data/1001/conf.json` is a special global config file (global chat, PRISM network data).
- `assets/share.py` holds in-memory globals: `globalchat_message_data`, `phishing_url_list`, `temp_voice_channels`, `task_status`, `admin_log_buffer`.

### Commands (`assets/commands.py`)
All slash commands are defined as `bot.tree.command(...)` grouped into three registration functions called from `main.py`: `base_commands`, `utility_commands`, `bot_admin_commands`.

### Events (`assets/events.py`)
Single `events(bot, web)` function that registers all `@bot.event` handlers. Handles `on_message` (chat filter → global chat → anti-spam → auto-slowmode → counting game → flag quiz → custom commands), `on_member_join/remove` (welcomer, auto-roles, PRISM), `on_voice_state_update` (temp voice), etc.

### Background Tasks (`assets/tasks.py`)
Classes using `discord.ext.tasks` loops: `GCDH_Task` (global chat data sync, 15s), `UpdateStatsTask` (guild stats, 10m), `LivestreamTask` (Twitch/YouTube/TikTok polling), `StatsChannelsTask` (voice channel stats, 10m), temp-action expiry (60s), `BackupTask` in `assets/backup.py` (SQLite snapshot → gzip → self-hosted backup server every 12h via `assets/backup_client.py`; credentials only via env `BACKUP_URL`/`BACKUP_PROJECT`/`BACKUP_KEY` → `config.auth.Backup`; the server handles retention/mirroring), PRISM trust score recalc (1h), phishing list refresh (12h), garbage collector (daily).

### Rest mode (`assets/idle.py`)
Keeps idle cost near zero. `idle.guilds_with(bot, sys, key="enabled")` returns only the guilds with a feature on (cached per config key, invalidated by `datasys.save_data`, 10-min safety TTL): **background tasks loop over that, never over `bot.guilds` with a `load_data` per guild**, and return early when there is nothing to do (no `set_task_status` either, it writes to the admin log). Due-work tasks query the due rows directly (`temp_action_guild_ids`, `due_giveaway_guild_ids`, `due_poll_guild_ids`); GCDH saves only when `share.globalchat_dirty` is set (set it after every write to `globalchat_message_data`). After `BAXI_REST_AFTER` s (default 600) without user messages/interactions/voice changes, `RestModeTask` stops the chatfilter model process, runs `gc.collect()` + `malloc_trim`, and sets the presence to idle; the next activity wakes it.

### Web Dashboard (`assets/dash/`)
- `dash.py` -  main Quart route registrations for the dashboard UI
- `endpoints.py` -  API endpoints (TopGG vote webhook, etc.)
- `log.py` -  admin log utilities
- `web/` -  Jinja2 HTML templates
- `static/` -  CSS/JS/image assets

### Message Processing (`assets/message/`)
Feature modules: `chatfilter.py` (entry point for the local SafeText pipeline in `safetext/`: normalisation, phishing, doxxing, DE/EN lexicons + `textdetox/xlmr-large-toxicity-classifier`, which runs in its own process `safetext/model_worker.py`: started on the first message that needs a score, stopped after `SAFETEXT_IDLE_UNLOAD` s unused, so the bot process never imports torch), `globalchat.py`, `welcomer.py`, `antispam.py`, `auto_slowmode.py`, `reactionroles.py`, `warnings.py`, `customcmd.py`.

### Pulse (`assets/pulse.py`, `pulse_card.py`, `pulse_commands.py`)
Community activity analytics derived from the BaxiInsights `activity` blob (no own tracking). Note the tracker files messages under the **UTC date with the Vienna hour**; `pulse._local_slot` undoes that. Voice time is the one thing Pulse/Insights track themselves: `assets/voice_activity.py` (hook in `on_voice_state_update`, 5-min reconcile `VoiceActivityTask`) credits seconds into `activity.voice_by_day` (per user / channel; bots and the AFK channel excluded). `PulseTask` posts the weekly recap (config key `pulse`, stored via the `guild_misc` catch-all).

### Leveling (`assets/leveling.py`, `rank_card.py`)
One level from `text_xp + voice_xp` (`leveling_users.xp` is that total, indexed for the leaderboard; every write keeps the invariant, the start-up data migration in `db._DATA_MIGRATIONS` books pre-split XP as text). Single-row reads/UPSERTs only (`repo.entities.add_leveling_xp`, `leveling_leaderboard`, `leveling_rank`), never `load_data("leveling_users")` on a hot path. Text XP: once per 60 s per user (in memory), only after anti-spam passed; the chat filter hands its verdict over (`events.ChatfilterVerdict`) and `leveling.earns_xp` decides (removed: none, borderline: `BORDERLINE_EARNS_XP`). Voice XP: 5 per full minute, own monotonic clock per member in `voice_activity.py` (not deafened, another non-deafened human present, not AFK, no bots; only guilds with leveling on), banked in the 5-min reconcile with leftover seconds carried. `/rank [member]` shows the card (`rank_card.render_rank`, graphics only).

### Starboard / Quotes / Time Capsule (`assets/starboard.py`, `quotes.py`, `capsule.py`)
Each owns its commands and (where needed) a task (`StarboardTask` 30 min, `CapsuleTask` 5 min), started in `events.py`. Tables: `starboard_entries` (IDs only), `quotes`, `time_capsules`; config keys `starboard`/`quotes`/`capsule` live in `guild_misc`. Starboard uses `bot.add_listener` (not `@bot.event`) for raw reaction/delete events so it doesn't replace handlers in `events.py`. Anything Baxi publishes later or on someone's behalf goes through `chatfilter.text_is_clean`.

### Cases, case file, notes, appeals (`assets/moderation/cases.py`, `casefile.py`, `appeals.py`, `assets/repo/cases.py`)
Every action against a person is a **case**: a `mod_events` row whose `pos` is the case number (#123; per-guild counter `mod_case_counter`, never reused; starts at 1). Write one with `cases.record(...)` BEFORE the Discord action (DM and audit-log reason carry the number), `cases.notify(...)` is the ONE DM a user gets (what, why, how long, case number, Appeal button), `cases.discard(...)` when the action failed. Never write a second DM. Extra case data (warn id, duration, log id, appeal state) lives in `extra_json`; Insights only counts warn/mute/kick/ban. Appeals are `mod_review_queue` items of kind `appeal`; the DM button is the persistent `AppealButton` (custom_id `baxi:appeal:<guild>:<case>`, no guild context in DMs), the web page is `/appeal/` (own cases only, user id from the login session). `repo/cases.submit_appeal` enforces one-per-case / 14 days / own case atomically. Retention: cases and notes one year (daily prune in `BorderlineExpiryTask`), closed queue items 30 days. The dashboard section `mod_cases` shows case files and the team overview (never ranked).

### Games (`assets/games/`)
`counting.py` -  counting game logic. `quiz.py` -  flag quiz logic.

### Localisation (`lang/lang.json`)
All user-facing strings. Loaded per-guild via `datasys.load_lang_file(guild_id)` based on the guild's `lang` setting.

### PRISM / Trust System (`assets/trust.py`)
Network-wide user behavior scoring. Only fully functional on the official hosted network.

## Dashboard Design Rules

- **Toggles (`role="switch"`)**: only for enable/disable of an entire system or feature (e.g. "Enable Music", "Enable Welcomer"). One per card header area.
- **Checkboxes**: everything else that is boolean — source selection, permission flags, optional sub-features, multi-select options. Never use `role="switch"` for these.
- **Channel/item cards in lists**: always use `<div class="card">` with `<header class="flex items-center justify-between">`. Channel name as `<h3 class="text-base font-semibold">`. Optional subtitle as `<p class="text-muted text-xs">`. Remove button: `<button class="btn" data-variant="outline" data-size="default" style="color:var(--avo-error);border-color:var(--avo-error);">` with trash SVG + `<span class="btn-label">Remove</span>`. Never use raw `div` with inline `style.cssText` or bare X-icon buttons for list items.
- **Add-area (input + add button)**: wrap all add-form sections in `<div class="add-area mt-3">` (or `mt-4`). This applies the custom SVG dashed border with wider dash gaps (6px dash / 12px gap) and rounded corners. The class is defined in the `<style>` block. Always use `data-variant="primary"` for add buttons — never `secondary`. **Known divergence from BRANDING §3** ("one coral block per view"): a settings page has one such button per card, so a view can show several. Kept by decision; the brand-correct fix would make only the screen's main action primary and the rest `outline`.
- **Empty states**: `<div class="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-6 text-center hidden">` with `<h3 class="text-base font-semibold tracking-tight">` and `<p class="text-muted text-sm">`. **No icon box, no illustration** (brand v5, `UI.md` "Leer"): one sentence of what would be here, and the action. The earlier icon-box exception was dropped when moving to v5.

## Basecoat / CDN / UI theme

- Third-party and brand assets come from `https://cdn.avocloud.net`, pinned in **one** place: `config/cdn.json` (read by `assets/dash/cdn.py`, exposed to every template as `{{ cdn.fonts_css }}`, `{{ cdn.basecoat_css }}`, `{{ cdn.basecoat_js }}`, `{{ cdn.ui_base_css }}`, `{{ cdn.favicon }}`). Never `latest`, never `@5`. Bump a version = edit that file, then look at the pages. A new kit version is a new URL: read `brand/CHANGELOG.md` and `brand/AGENTS.md` first.
- **The dashboard runs avocloud UI v5 (kit `avocloud-ui@5.0.1`)**, source of truth `~/Nextcloud/avocloud/brand/` (`AGENTS.md`, `BRANDING.md`, `UI.md`, prototype `docs/dashboard-next.html`). Every template loads, in this order: Basecoat → `{{ cdn.ui_base_css }}` → `main.css`. v5 in short: anthracite canvas `#111215`, flat surfaces with a 1px hairline (no glass, no shadow), soft shapes (12 fields, 20 cards, 28 sheets and popups, **pill** buttons/chips/switch), **Space Grotesk for text, IBM Plex Mono for figures** (`.num`, stat values, timestamps, IDs), Syne only for the wordmark, sentence case, controls 44px (36 compact), one coral block per view, status = dot + word, no corner marks, no `//` kickers, no `[ ]` glyphs, no uppercase tracking, no colour transitions (hover is a cut).
- **Light theme**: `scripts/theme.js` sets `html.dark` (our own selectors, Tailwind) **and** `html.avo-light` (the kit). Dark is the kit default.
- **`main.css` carries no tokens.** Use `--avo-*` (`--avo-primary`, `--avo-surface`, `--avo-line`, `--avo-radius` 12px / `--avo-radius-lg` 20px / `--avo-radius-xl` 28px / `--avo-radius-pill`, `--avo-ui-control-h` 44px …). A hex, a radius or a font written into a template or `main.css` is a second source of truth: report it as a kit problem (`brand/AGENTS.md`, "Reporting a kit problem"), do not patch the kit here. `--avo-accent-text` is coral *as text*; use `--avo-primary` for fills and marks.
- **Retargeted in `main.css` on purpose**: the kit styles `.input[type=checkbox]` and `[role=switch]`, but the dashboard uses bare native inputs, so `main.css` carries the same v5 shapes (22px box with 6px radius, round radio, pill switch, coral on) for bare `input[type=checkbox|radio]`. Same for bare text inputs (12px, 44px).
- **Rules the templates follow** (check them when you add UI): never transition a colour property; radii only 12/20/28/pill (50% for avatars and round icon buttons); floating surfaces (popups, menus, the save bar, tooltips) are opaque; text on a coral fill is black; coral is brand, never status; one coral block per view; no entrance animation on data; charts: coral is series 1 then `--avo-series-*`, bars are plain bars with a 4px corner, no area fills, no doughnuts (`insights.html` resolves the tokens for canvas). Section titles (`.section-label`) are 15px headings in sentence case: write them that way in the markup.
- Basecoat is **1.0.x**: a button is `class="btn"` plus `data-variant="primary|secondary|outline|ghost|destructive|link"` and `data-size="default|sm|lg|icon…"`. Switching a button's variant in JS = `el.dataset.variant = '…'`.
- Toasts: `document.getElementById('toaster').toast({category, title, description, cancel})`.
- Loading: the kit's tick ring, `<span class="spinner avo-spinner sm hidden">` inside a button (the `.spinner` class is what the save handlers toggle).
- `.dash-nav` is rendered but permanently hidden: the Home hub replaced the rail, and the section router still reads its items. Below 900px the account plate becomes the floating pill bar at the bottom.
- Previewing without the bot: the templates render with lenient Jinja stubs (`jinja2.ChainableUndefined`) plus `/static` served from `assets/dash/static`; there is no committed harness.

## Dashboard Integration Rules

When adding or modifying any bot system that has dashboard settings:

1. **New system → add a card** in `assets/dash/web/dash.html` (card HTML + JS init block + JS save handler).
2. **New system → add save endpoint** in `assets/dash/dash.py` under the `elif system == "..."` chain.
3. **New system → add to the `order` list** in `dash.html` (the JS array around line ~2788 that controls which sections are rendered and in what order). If a system is missing from this list its card will be detached from the DOM and never shown.
4. **New system → add nav item** in the sidebar of `dash.html`.
5. **Modified system** → keep the dashboard card, save endpoint, and JS init in sync with any new config keys.

## Card Image Design Pattern (Pillow + cairosvg)

Reference implementation: `assets/mc_link_card.py` (+ `assets/mc_link_view.py`, `assets/commands.py:mc_link_cmd`). Reuse this pattern for any new "card-style" interactive flow (link confirmations, profile cards, large stat panels, etc.).

### Split text and graphics
- **All copy lives in the Discord embed** (`embed.title`, `embed.description`, `embed.set_footer`). Never bake user-facing text into the PNG — Discord renders it crisper, themes adapt, copy is localizable via `lang/lang.json`, and screen readers work.
- **PNG holds only graphic content** that cannot be expressed in an embed: avatars, icons, decorative connectors, identifiers that must be visually prominent (e.g. MC username next to Discord username).

### Canvas + chrome
- Default canvas: `640 × 320` (`CONFIRM_CANVAS`, `STATE_CANVAS`). Aspect ~2:1 keeps the embed compact on mobile.
- Background `#18181b` matches Discord dark embed surface. Card border: `_CARD_BORDER` (`#3c3c41`) at 2px, rounded `radius=24`, inset 16px from canvas edge.
- Palette constants live at top of `mc_link_card.py`: `_BG`, `_TEXT`, `_MUTED`, `_PRIMARY` (`#6F83AA`, brand), `_SUCCESS`, `_DANGER`, `_LINE`. Reuse these — do not introduce ad-hoc hex.

### Icons → SVG via cairosvg
- Rasterize **Lucide** icons (https://lucide.dev) at runtime with `cairosvg.svg2png`. Inline the path data into a format string with `{stroke}` placeholder so color can be themed per call. See `_LINK_SVG` + `_render_link_icon()`.
- Do **not** approximate SVG icons with `ImageDraw` primitives — `stroke-linecap="round"` and joins are wrong, looks amateur.
- `cairosvg` is in `requirements.txt`. System deps: cairo + pango (Fedora: `cairo pango`).

### Anti-aliasing trick
- For state icons (check, X, etc.) drawn with PIL primitives: render at **4× supersample** then `Image.LANCZOS` downsample. See `_render_state()` — `ss = 4`, draw on `icon_big_size = r * 2 * ss` canvas, resize at end. Pillow's native line drawing has jagged diagonals; supersampling fixes it without external libs.

### Avatars
- Discord user: `interaction.user.display_avatar.url` → `_fetch_image()` (aiohttp, 6s timeout) → `_circle_crop()`. Always provide `_placeholder()` fallback if fetch returns `None` — never crash the render on a flaky CDN.
- Minecraft head: `https://mc-heads.net/avatar/{uuid}/128` → `_round_crop()` with `Image.NEAREST` resize (keeps pixelated MC look) + rounded mask `radius=16`.

### Discord `View` state machine
- `assets/mc_link_view.py` is the template: subclass `discord.ui.View`, store `bot`, `token`, `author_id`, `kind` on the view, set `timeout=600` (10 min, matching session TTL).
- Guard with `interaction_check()` so only the original invoker can click.
- Button callbacks: `await interaction.response.defer()` → mutate backend → render new PNG → `await interaction.edit_original_response(attachments=[file], embed=new_embed, view=self)`. Atomic swap, no message churn.
- After action: walk `self.children` and disable each `discord.ui.Button` before the final `edit_original_response`. Set `self.stop()` is optional — the disabled state is the visual contract.
- `on_timeout`: drop any backend session, disable buttons (best-effort, no message ref).

### Resilience
- Wrap every renderer call in `try/except` with a text-only fallback (`_fallback_text()` in `mc_link_view.py`). PNG rendering must never block the interaction response — Discord's 15-min followup window is the only hard constraint.
- Renderers return `io.BytesIO` (not `discord.File`) so they're reusable from any context. Wrap in `discord.File(buf, filename=...)` at the send site.
- Filename matters: `embed.set_image(url=f"attachment://{filename}")` only resolves if the filename in the `discord.File` matches exactly.

### When to use this pattern vs plain embeds
- **Use card image**: when there's a visual identity to compare (avatars side-by-side), an icon worth showing big (status, achievement, badge), or marketing-grade polish is needed.
- **Stick to plain embeds**: for status checks, lists, errors, anything text-heavy. Don't generate a PNG just to display a name.

## Key Patterns

- **Interaction responses**: Always `await interaction.response.defer()` before async work, then `await interaction.followup.send(...)`.
- **Guild data access**: `datasys.load_data(guild_id, "all")` or specific sys string. Save with `datasys.save_data(guild_id, key, value)`.
- **Language strings**: `lang = datasys.load_lang_file(guild_id)` then index into nested dict.
- **Colors**: Use `config.Discord.color` (purple), `.danger_color` (red), `.warn_color` (amber), `.success_color` (green), `.info_color` (blue) for embeds.
- **Icons**: Custom Discord emoji strings in `config.Icons`.
