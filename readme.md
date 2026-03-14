# Baxi — Privacy-Focused Discord Bot

> Your all-in-one solution for a safer, smarter Discord community

Baxi is a modern, privacy-focused Discord bot designed to make server management **safer, smarter, and easier**.
It combines powerful moderation tools, an AI-powered chat filter, cross-server global chat, and much more —
all configurable through an easy-to-use **web dashboard**.

Baxi is part of the **[AvoCloud](https://avocloud.net)** project, focused on creating modern, privacy-friendly tools for Discord communities.
Everything is open source under the **MIT license** — self-host it, audit it, contribute to it.

---

## ✨ Features

- 🛡️ **Moderation** — ban, kick, mute, warn, temp actions with auto-expiry, auto-escalation on warning thresholds, DM notifications
- 🚫 **Anti-Spam** — detects message spam, mention floods & repeated content in real time
- 🤖 **AI Chat Filter** — multi-tier filtering: SafeText (bad-word detection) + Llama Guard AI (context-aware) + phishing link scanner
- 🌐 **Global Chat** — cross-server chatroom connecting all Baxi servers, always AI-filtered *(official hosted bot only)*
- 🎫 **Ticket System** — modal-based tickets, staff can claim, close & archive as transcripts
- 👋 **Welcome & Leave** — customizable messages with variables + optional welcome image with custom background
- ⚙️ **Custom Commands** — define your own commands with dynamic variables (`{user}`, `{server}`, `{membercount}`) and embed support
- ✅ **Auto-Roles** — automatically assign one or more roles when a user joins
- 🔴 **Twitch Tracking** — auto-post live announcements with title, viewer count & role ping; channel name updates live
- 📊 **Stats Channels** — voice channels displaying live server stats, updated every 10 minutes
- 🎙️ **Temp Voice** — joining a creator channel auto-creates a private voice channel, deleted when empty
- 🚩 **Global User Flagging** — shared flagged-user database across the Baxi network; use `/scan_users` proactively *(official hosted bot only)*

---

## 🖥️ Web Dashboard

Configure **every** Baxi feature through a clean web interface — login with Discord OAuth2, no slash commands or config files needed.

- Manage moderation, welcome messages, custom commands, Twitch tracking, auto-roles & more
- Built-in **audit log** and feature adoption statistics
- Changes apply **instantly**

🔗 [baxi.avocloud.net](https://baxi.avocloud.net)

---

## 🚀 Getting Started

### Official Hosted Bot *(recommended)*

Get started in seconds — invite the bot and configure everything via the dashboard.

👉 [**Invite Baxi**](https://avocloud.net/baxi/invite/)

### Self-Hosting

```bash
git clone https://github.com/AvoCloud-net/Baxi.git
cd Baxi
pip install -r requirements.txt
```

1. Open `config/auth.py` and fill in your **Bot Token** and required values.
2. Start the bot:

```bash
python main.py
```

**Limitations when self-hosting:**

| Feature | Self-Hosted |
|---|---|
| 🌐 Global Chat | ❌ Not available (requires official network) |
| 🤖 AI Filter (Llama Guard) | ⚠️ Self-host with [Ollama](https://ollama.ai/) + Llama Guard 3 |
| 🔍 SafeText | ⚠️ Requires a Public API Key (request via support) |
| Everything else | ✅ Fully functional |

---

## 🔧 Commands

Baxi uses **Discord Slash Commands** (`/`).
Type `/` in your server to browse all available commands — each includes descriptions and options directly in Discord.

---

## 🔒 Privacy by Design

We believe **your data belongs to you**.
Baxi follows a strict **minimal data collection** principle — every feature is opt-in, and only data required for an active feature is ever stored.

**Stored (only if feature is enabled):**
- Chat filter logs — only for removed messages
- Server configuration — your dashboard settings
- Global chat images — for cross-server delivery

**Never stored:**
- Regular messages or chat history
- Personal data or user profiles
- Tracking or analytics data of any kind

*Privacy is not an afterthought — it's our foundation.*

---

## 💬 Support

- 🌐 [Discord Support Server](https://avocloud.net/discord/)
- 📧 [support@avocloud.net](mailto:support@avocloud.net)
- 🐛 [Open an Issue](https://github.com/AvoCloud-net/Baxi/issues)

---

## 📄 License

[MIT](LICENSE) — free to use, modify, and distribute.

---

*Made with ❤️ by [AvoCloud](https://avocloud.net)*
