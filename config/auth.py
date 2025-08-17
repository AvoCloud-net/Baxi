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

class Translate:
    api_key: str = "LIBRE-TRANSLATE-API-KEY" #NOT NEEDED
