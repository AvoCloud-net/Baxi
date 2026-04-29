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

## Dashboard Integration Rules

When adding or modifying any bot system that has dashboard settings:

1. **New system → add a card** in `assets/dash/web/dash.html` (card HTML + JS init block + JS save handler).
2. **New system → add save endpoint** in `assets/dash/dash.py` under the `elif system == "..."` chain.
3. **New system → add to the `order` list** in `dash.html` (the JS array around line ~2788 that controls which sections are rendered and in what order). If a system is missing from this list its card will be detached from the DOM and never shown.
4. **New system → add nav item** in the sidebar of `dash.html`.
5. **Modified system** → keep the dashboard card, save endpoint, and JS init in sync with any new config keys.

## Key Patterns

- **Interaction responses**: Always `await interaction.response.defer()` before async work, then `await interaction.followup.send(...)`.
- **Guild data access**: `datasys.load_data(guild_id, "all")` or specific sys string. Save with `datasys.save_data(guild_id, key, value)`.
- **Language strings**: `lang = datasys.load_lang_file(guild_id)` then index into nested dict.
- **Colors**: Use `config.Discord.color` (purple), `.danger_color` (red), `.warn_color` (amber), `.success_color` (green), `.info_color` (blue) for embeds.
- **Icons**: Custom Discord emoji strings in `config.Icons`.
