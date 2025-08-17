
# 🌟 Baxi – The Privacy-Focused Discord Bot

Welcome to **Baxi**, a modern and versatile Discord bot designed to make your server **safer, smarter, and easier to manage**.  
Baxi combines **powerful moderation tools**, a **customizable verification system**, and an **global chat**, all wrapped in an **easy-to-use web dashboard**.

One of Baxi’s core principles is **privacy**:  
➡️ We collect **as little data as possible** and store only what is strictly necessary for the bot’s functionality (see [Privacy](#-privacy-first)).  
You stay in full control at all times.

---

## ✨ Features

- 🤖 **AI-Powered Chat Filter (SafeText + AI)**  
  Baxi comes with **two powerful filtering systems** to keep your server safe:  
  - **SafeText** – our own lightweight bad-word detection system (open source: [SafeText on GitHub](https://github.com/AvoCloud-net/SafeText))  
  - **AI Filter** – a large language model (LLM) hosted on our own servers, designed to detect more complex or harmful content beyond simple keyword checks.  

- 🌍 **Global Chat**  
  Connect multiple servers together with an **inter-server chatroom**.  
  - Perfect for community networking or cross-server events.  
  - *(Note: This feature is only available when using the official hosted bot. Self-hosted bots cannot join the global chat network.)*

- ✅ **Flexible Verification System**  
  Secure your server with customizable onboarding methods:  
  - Button only  
  - Button + CAPTCHA  
  - Button + Password  

- 🎟️ **Ticket System**  
  Let your members easily create support tickets – ideal for help requests or moderation reports.  

- ⚙️ **Web Dashboard**  
  Every system and feature can be enabled, disabled, and fully configured via the dashboard.  
  No confusing commands – just point, click, and customize.  

*(Fun minigames are currently disabled, but may return in future updates.)*

---

## 🚀 Getting Started

### Invite the Official Bot  
The simplest way to get started:  
👉 [**Invite Baxi to your server**](https://avocloud.net/baxi/)

### Self-Hosting  
If you prefer to run Baxi yourself:  

```bash
git clone https://github.com/AvoCloud-net/Baxi.git
cd Baxi
pip install -r requirements.txt

```

1.  Open `config/auth.py` and add your **Bot Token** and other required values.
    
    -   Fields marked with `#NOT NEEDED` are optional.
        
2.  Start the bot:
    
    ```bash
    python main.py
    
    ```
    

⚠️ **Important for Self-Hosting:**  

When running Baxi yourself, there are some limitations compared to the official hosted version:  

- 🌍 **Global Chat**  
  Not available when self-hosting, since it requires access to the official Baxi network.  

- 🤖 **Chat Filter**  
  - **SafeText**: Supports public usage, but requires a **Public API Key**.  
    You can request one from us if you want to use SafeText in your own hosting environment.  
  - **AI Filter**: Needs to be hosted by you.  
    Recommended setup: [OpenWebUI](https://github.com/open-webui/open-webui) with [Ollama](https://ollama.ai/) running the **Llama-Guard 3** model.  

- ✅ **Other Features** (verification system, tickets, dashboard, etc.) work fully without restrictions.  


----------

## 🔧 Commands

Baxi uses **Discord Slash Commands** (`/`).  
Just type `/` in your server to explore all available commands.  
Each command includes helpful descriptions and options right inside Discord.

----------

## 💬 Support

Need help or want to suggest new features? We’re here for you:

-   🌐 [Join our Support Discord](https://avocloud.net/discord/)
    
-   📧 Email: [support@avocloud.net](mailto:support@avocloud.net)
    

----------

## 🔒 Privacy First

We believe **your data belongs to you**.  
Baxi is built around the principle of **minimizing data collection** and **maximizing transparency**.

The only information stored is:

-   📝 **Chat Filter Logs** – Only if the filter is enabled, and only for messages that get removed.
    
-   ⚙️ **Server Configuration** – Your dashboard settings so Baxi remembers your preferences.
    
-   🖼️ **Global Chat Images** – Images sent in the Global Chat, so they can be delivered across servers.
    

✅ **We do NOT log or store any other messages, personal data, or private information.**  
✅ **No tracking, no selling, no hidden data collection.**  
✅ **All systems are optional** – you decide what features to use, and what data (if any) is stored.

With Baxi, **privacy is not an afterthought – it’s our foundation.**

----------

## 💡 About

Baxi is part of the **AvoCloud** project, focused on creating modern, privacy-friendly tools for Discord communities.  
We’re always improving and adding features – so stay tuned for updates!

