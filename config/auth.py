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

class Ai:
    uri: str = "http://localhost:8080/api/chat/completions" #NOT NEEDED
    api_key: str = "OPENWEBUI-API-KEY" #NOT NEEDED

class Twitch:
    client_id: str = "YOUR-TWITCH-CLIENT-ID"
    client_secret: str = "YOUR-TWITCH-CLIENT-SECRET"


class TopGG:
    token: str = "YOUR-TOPGG-TOKEN"
    webhook_secret: str = "YOUR-TOPGG-WEBHOOK-SECRET"
    vote_channel_id: int = 0           # Channel on avocloud.net Discord to post vote announcements
    avocloud_guild_id: int = 0         # avocloud.net Discord server ID

class Translate:
    api_key: str = "LIBRE-TRANSLATE-API-KEY" #NOT NEEDED

class Donations:
    # Fernet master key used to encrypt donation provider credentials (Stripe/PayPal) at rest.
    # Generate once with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # NEVER change this after credentials have been saved — stored keys become unreadable.
    master_key: str = "GENERATE-A-FERNET-KEY"
