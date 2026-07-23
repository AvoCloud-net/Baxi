class Bot:
    token: str = "YOUR.BOT.TOKEN" 
    client_secret: str = "YOUR-CLIENT-SECRET"
    callback_url: str = "http://localhost:1637/callback"

class Web:
    secret_key: str = "CUSTOM-GENERATED-SECRET-KEY"

class Chatfilter:
    api_key: str = "SAFE-TEXT-API-KEY"
    admin_key: str = "SAFE-TEXT-ADMIN-KEY"
    ai_key: str = "OPENWEBUI-API-KEY"

class Assistant:
    # Optional bearer token for the Ollama endpoint (config.config.Assistant.ollama_url).
    # Plain local Ollama needs NO auth — leave empty. Only set this if your Ollama sits
    # behind a reverse proxy that requires Authorization: Bearer <token>.
    api_key: str = ""

class Twitch:
    client_id: str = "YOUR-TWITCH-CLIENT-ID"
    client_secret: str = "YOUR-TWITCH-CLIENT-SECRET"


class Twitter:
    # X (Twitter) post tracking has no free official API. Without cookies the bot uses an
    # anonymous "guest token", which only works for large/popular accounts — X hides the
    # timelines of small or new accounts from guests. To track ANY public account, log in
    # to a (throwaway) X account in a browser and copy two cookies from DevTools
    # (Application → Cookies → https://x.com):
    #   auth_token  -> auth_token below
    #   ct0         -> ct0 below   (also used as the x-csrf-token header)
    # Leave both empty to stay in guest-only mode. Cookies expire periodically; refresh if
    # tracking stops working for smaller accounts.
    auth_token: str = ""
    ct0: str = ""


class TopGG:
    token: str = "YOUR-TOPGG-TOKEN"
    webhook_secret: str = "YOUR-TOPGG-WEBHOOK-SECRET"
    vote_channel_id: int = 0           # Channel on avocloud.net Discord to post vote announcements
    avocloud_guild_id: int = 0         # avocloud.net Discord server ID

class Meta:
    # Meta (Facebook/Instagram) app credentials.
    # Create app at developers.facebook.com → Add product: Instagram
    # Use case: "Manage messaging & content on Instagram"
    # Add OAuth redirect URI: https://baxi.avocloud.net/oauth/instagram/callback
    app_id: str = "YOUR-META-APP-ID"
    app_secret: str = "YOUR-META-APP-SECRET"
    redirect_uri: str = "https://baxi.avocloud.net/oauth/instagram/callback"


class Translate:
    api_key: str = "LIBRE-TRANSLATE-API-KEY" #NOT NEEDED

class Donations:
    # Fernet master key used to encrypt donation provider credentials (Stripe/PayPal) at rest.
    # Generate once with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # NEVER change this after credentials have been saved -  stored keys become unreadable.
    master_key: str = "GENERATE-A-FERNET-KEY"
