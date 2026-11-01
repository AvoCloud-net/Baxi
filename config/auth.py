import os

from config.env import get, get_int  # reads .env in the project root

class Bot:
    token: str = get("BOT_TOKEN") 
    client_secret: str = get("BOT_CLIENT_SECRET")
    callback_url: str = get("BOT_CALLBACK_URL")

class Web:
    secret_key: str = get("WEB_SECRET_KEY")

class Assistant:
    # Optional bearer token for the Ollama endpoint (config.config.Assistant.ollama_url).
    # Plain local Ollama needs NO auth — leave empty. Only set this if your Ollama sits
    # behind a reverse proxy that requires Authorization: Bearer <token>.
    api_key: str = get("ASSISTANT_API_KEY")

class Twitch:
    client_id: str = get("TWITCH_CLIENT_ID")
    client_secret: str = get("TWITCH_CLIENT_SECRET")


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
    auth_token: str = get("TWITTER_AUTH_TOKEN")
    ct0: str = get("TWITTER_CT0")
    # Discord channel the bot posts to when the cookies above stop working (and when they
    # start working again). Leave 0 to only write the alert to the admin log.
    alert_channel_id: int = get_int("TWITTER_ALERT_CHANNEL_ID")


class TopGG:
    token: str = get("TOPGG_TOKEN")
    webhook_secret: str = get("TOPGG_WEBHOOK_SECRET")
    vote_channel_id: int = get_int("TOPGG_VOTE_CHANNEL_ID")           # Channel on avocloud.net Discord to post vote announcements
    avocloud_guild_id: int = get_int("TOPGG_AVOCLOUD_GUILD_ID")         # avocloud.net Discord server ID

class Meta:
    # Meta (Facebook/Instagram) app credentials.
    # Create app at developers.facebook.com → Add product: Instagram
    # Use case: "Manage messaging & content on Instagram"
    # Add OAuth redirect URI: https://baxi.avocloud.net/oauth/instagram/callback
    app_id: str = get("META_APP_ID")
    app_secret: str = get("META_APP_SECRET")
    redirect_uri: str = get("META_REDIRECT_URI")


class Translate:
    api_key: str = get("TRANSLATE_API_KEY") #NOT NEEDED


class Backup:
    # Self-hosted backup server (see backup-server/docs/INTEGRATION.md). The real values come
    # from the environment (BACKUP_URL / BACKUP_PROJECT / BACKUP_KEY) so they never land in git;
    # leave the placeholders here. Without real values the DB backup task stays idle.
    url: str        = get("BACKUP_URL", "http://BACKUP-SERVER:PORT")
    project_id: str = get("BACKUP_PROJECT", "prj_XXXXXXXXXX")
    key: str        = get("BACKUP_KEY", "bks_YOUR-PROJECT-KEY")
