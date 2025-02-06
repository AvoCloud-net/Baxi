class Help:
    title = "Hilfe"

    class Description:
        class Prefix:
            title = "Präfix"
            content = "Alle Befehle beginnen mit dem Präfix „/“."

        class About:
            title = "Über dieses Projekt"
            content = "Dieser Bot wurde von Avocloud.net erstellt. Weitere Informationen findest du auf unserer Website."

        class Icons:
            title = "Icons"
            content = "Die von Baxi verwendeten Icons findet ihr hier: [Icons](https://discord.gg/aPvvhefmt3)"

        class Bugs:
            title = "Bugs"
            content = "Wenn du auf Fehler stößt, würden wir dich bitten, diese mit dem Befehl </report:1227394011715735582> zu melden. Dies hilft uns sehr bei der Entwicklung und Fehlerbehebung. Vielen Dank für deine Unterstützung!"

        footer = "Baxi Bot - Avocloud.net"


class Chatfilter:
    title = "Chatfilter"

    class Description:
        text = (
            "Diese Nachricht wurde gelöscht da sie potenziell schädlich sein könnte.\n"
            "Solltest du diese jedoch trotzen lesen wollen, kannst du sie mithilfe des unteren links einsehen.\n\n"
            "**Benutzer:** {user}\n"
            "**ID:** {id}\n"
            "**Info:** {link}\n\n"
            "-# Sollte dies ein Fehler sein, kontaktiere bitte den Support via Discord oder per Email."
        )

    footer = "Baxi Security"


class Globalchat:
    title = "Globalchat"

    class Error:
        file_not_image = "Diese Datei ist kein Bild und kann daher nicht im globalen Chat versendet werden."
        to_many_files = "Du kannst maximal ein Bild anhängen und versenden."
        message_to_long = "Deine Nachricht ist zu lang. Beachte, dass die maximale Länge 1000 Zeichen beträgt."
        baned = "Du bist aus dem globalen Chat ausgeschlossen. Folgender Grund ist angegeben: {reason}"


class Ai:
    title = "AI"

    class Waiting:
        content = "Baxi AI arbeitet an einer Antwort..."

    class Error:
        unknown = "Ein unbekannter Fehler ist aufgetreten. Bitte versuche es später noch einmal."
        id_not_found = "Die ConversationID deiner Unterhaltung wurde nicht gefunden. Bitte starte einen neuen chat mithilfe des `/ai` Befehls."
        model_unable_to_chat = "Mit diesem Model kannst du leider nicht chatten. Bitte versuche es mit dem anderen Model."


class Events:
    class on_guild_join:
        title = "Halloooo!"
        content = (
            "Hallo zusammen! Ich bin Baxi, ein Discord Bot wie für dich gemacht. Mein Ziel ist es, deine Community sicher und beschäftigt zu halten.\n"
            "Um Einstellungen vorzunehmen, musst du das Baxi Dash öffnen. https://baxi.avocloud.net\n\n"
            "-# {saved_data}"
        )

        class saved_data:
            new_data = "Standardmäßig sind alle Systeme deaktiviert. Du kannst nun über das Dashboard bestimmte Systeme aktivieren und einstellen."
            existing_data = "Da wir bereits Einstellungen von diesem Server abgespeichert haben, wurden diese wiederhergestellt. Überprüfe bitte im Dashboard ob diese Einstellungen korrekt sind."


class Utility:
    user = "Benutzer:"
    mod = "Moderator:"
    reason = "Grund:"
    amount = "Anzahl der Nachrichten:"
    channel = "Kanal:"

    class Ban:
        title = "Bann"
        confirmation = "Möchtest du den Benutzer wirklich mit folgendem Grund bannen?"
        missing_perms = (
            "Du hast nicht die nötigen Berechtigungen um diesen Benutzer zu bannen."
        )
        bot_missing_perms = (
            "Ich habe nicht die nötigen Berechtigungen um diesen Benutzer zu bannen."
        )
        success = "Der Benutzer wurde erfolgreich mit folgendem Grund gebannt:"
        audit_reason = "Gebannt von {moderator}: {reason}"
        error = "Ein Fehler ist aufgetreten: {error}"
        abort = "Der Bannvorgang wurde abgebrochen."

    class Unban:
        title = "Entbannung"
        confirmation = "Möchtest du den Benutzer wirklich entbannen?"
        missing_perms = (
            "Du hast nicht die nötigen Berechtigungen um diesen Benutzer zu entbannen."
        )
        bot_missing_perms = (
            "Ich habe nicht die nötigen Berechtigungen um diesen Benutzer zu entbannen."
        )
        success = "Der Benutzer wurde erfolgreich entbannt."
        audit_reason = "Entbannt von {moderator}"
        error = "Ein Fehler ist aufgetreten: {error}"
        abort = "Der Entbannungsvorgang wurde abgebrochen."

    class Kick:
        title = "Kick"
        confirmation = "Möchtest du den Benutzer wirklich mit folgendem Grund kicken?"
        missing_perms = (
            "Du hast nicht die nötigen Berechtigungen um diesen Benutzer zu kicken."
        )
        bot_missing_perms = (
            "Ich habe nicht die nötigen Berechtigungen um diesen Benutzer zu kicken."
        )
        success = "Der Benutzer wurde erfolgreich mit folgendem Grund gekickt:"
        audit_reason = "Gekickt von {moderator}: {reason}"
        error = "Ein Fehler ist aufgetreten: {error}"
        abort = "Der Kickvorgang wurde abgebrochen."

    class Clear:
        title = "Nachrichten löschen"
        confirmation = "Möchtest du die Nachrichten wirklich löschen?"
        missing_perms = (
            "Du hast nicht die nötigen Berechtigungen um Nachrichten zu löschen."
        )
        bot_missing_perms = (
            "Ich habe nicht die nötigen Berechtigungen um Nachrichten zu löschen."
        )
        success = "Die Nachrichten wurden erfolgreich gelöscht."
        error = "Ein Fehler ist aufgetreten: {error}"
        abort = "Der Vorgang wurde abgebrochen."


class Minigames:
    class Counting:
        title = "Zählspiel"
        description_wrong_number = "{user}, die Zahl die du gesendet hast ist nicht die richtige. Wir beginnen wieder bei 1."
        description_same_user = "{user}, du darfst nicht zweimal hintereinander eine Zahl senden. Ihr müsst abwechselnd zählen."

    class Guessing:
        title = "Raten"
        description_correct = "{user}, du hast die Zahl richtig geraten!\nWir beginnen mit einer neuen Zahl, diese wurde zwischen 1 und {max_value} generiert.\nViel Erfolg!"


class Verify:
    title = "Verifizierung"
    description_not_enabeld = "Die Verifizierung ist auf diesem Server nicht aktiviert. Bitte kontaktiere einen Administrator."
    description_success = (
        "Die Verifizierung war erfolgreich. Willkommen auf dem Server!"
    )

    class Captcha:
        description_wrong_code = (
            "Der eingegebene Code ist falsch. Bitte versuche es erneut."
        )

    class Password:
        description_wrong_password = (
            "Das eingegebene Passwort ist falsch. Bitte versuche es erneut."
        )

class Ticket:
    title = "Support Ticket"
    channel_name = "support-{user}"
    description_creation_successfull = "Das Ticket wurde erfolgreich erstellt. Ein Teammitglied wird sich in Kürze bei dir melden.\nDein Ticket: {channel}"
    description_already_open = "Du hast bereits ein offenes Ticket. Bitte warte bis ein Teammitglied antwortet.\nDein Ticket: {channel}"
    description_no_permission_delete = "Du hast keine Berechtigung dieses Ticket zu löschen."
    description_no_permission_claim = "Du hast keine Berechtigung dieses Ticket zu übernehmen."
    description_claimed = "Der Supporter {user} übernimmt nun dieses Ticket."