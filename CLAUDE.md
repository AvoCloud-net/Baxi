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

- `config/auth.py` -  secrets (bot token, OAuth client secret, API keys). **Never commit real values.**
- `config/config.py` -  non-secret settings (shard count, colors, API URLs, check intervals, default guild data schema).

To generate the Fernet master key for donation credential encryption:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

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
Classes using `discord.ext.tasks` loops: `GCDH_Task` (global chat data sync, 15s), `UpdateStatsTask` (guild stats, 10m), `LivestreamTask` (Twitch/YouTube/TikTok polling), `StatsChannelsTask` (voice channel stats, 10m), temp-action expiry (60s), PRISM trust score recalc (1h), phishing list refresh (12h), garbage collector (daily).

### Web Dashboard (`assets/dash/`)
- `dash.py` -  main Quart route registrations for the dashboard UI
- `endpoints.py` -  API endpoints (TopGG vote webhook, etc.)
- `log.py` -  admin log utilities
- `web/` -  Jinja2 HTML templates
- `static/` -  CSS/JS/image assets

### Message Processing (`assets/message/`)
Feature modules: `chatfilter.py` (SafeText + Llama Guard AI + phishing), `globalchat.py`, `welcomer.py`, `antispam.py`, `auto_slowmode.py`, `reactionroles.py`, `warnings.py`, `customcmd.py`.

### Games (`assets/games/`)
`counting.py` -  counting game logic. `quiz.py` -  flag quiz logic.

### Localisation (`lang/lang.json`)
All user-facing strings. Loaded per-guild via `datasys.load_lang_file(guild_id)` based on the guild's `lang` setting.

### PRISM / Trust System (`assets/trust.py`)
Network-wide user behavior scoring. Only fully functional on the official hosted network.

## Dashboard Design Rules

- **Toggles (`role="switch"`)**: only for enable/disable of an entire system or feature (e.g. "Enable Music", "Enable Welcomer"). One per card header area.
- **Checkboxes**: everything else that is boolean — source selection, permission flags, optional sub-features, multi-select options. Never use `role="switch"` for these.
- **Channel/item cards in lists**: always use `<div class="card">` with `<header class="flex items-center justify-between">`. Channel name as `<h3 class="text-base font-semibold">`. Optional subtitle as `<p class="text-muted text-xs">`. Remove button: `<button class="btn-outline" style="color:#ef4444;border-color:#ef4444;">` with trash SVG + `<span class="btn-label">Remove</span>`. Never use raw `div` with inline `style.cssText` or bare X-icon buttons for list items.
- **Add-area (input + add button)**: wrap all add-form sections in `<div class="add-area mt-3">` (or `mt-4`). This applies the custom SVG dashed border with wider dash gaps (6px dash / 12px gap) and rounded corners. The class is defined in the `<style>` block. Always use `class="btn-primary"` for add buttons — never `btn-secondary`.
- **Empty states**: use `<div class="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-6 text-center hidden">` with icon box (`bg-muted size-10 rounded-lg`), `<h3 class="text-base font-semibold tracking-tight">`, and `<p class="text-muted text-sm">`. For full-width sections add `md:p-10`.

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
