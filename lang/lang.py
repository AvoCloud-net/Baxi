class Help:
    title = "Hilfe"

    class en:
        title = "Help"

    class Description:
        class Prefix:
            title = "Präfix"
            content = "Alle Befehle beginnen mit dem Präfix „/“."

            class en:
                title = "Prefix"
                content = "All commands start with the prefix „/“."

        class About:
            title = "Über dieses Projekt"
            content = "Dieser Bot wurde von Avocloud.net erstellt. Weitere Informationen findest du auf unserer Website."

            class en:
                title = "About this project"
                content = "This bot was created by Avocloud.net. You can find more information on our website."

        class Icons:
            title = "Icons"
            content = "Die von Baxi verwendeten Icons findet ihr hier: [Icons](https://discord.gg/aPvvhefmt3)"

            class en:
                title = "Icons"
                content = "The icons used by Baxi can be found here: [Icons](https://discord.gg/aPvvhefmt3)"

        class Bugs:
            title = "Bugs"
            content = "Wenn du auf Fehler stößt, würden wir dich bitten, diese mit dem Befehl </report:1227394011715735582> zu melden. Dies hilft uns sehr bei der Entwicklung und Fehlerbehebung. Vielen Dank für deine Unterstützung!"

            class en:
                title = "Bugs"
                content = "If you encounter any bugs, we would be grateful if you could report them with the command </report:1227394011715735582>. This helps us a lot with development and bug fixing. Thank you for your support!"

        footer = "Baxi Bot - Avocloud.net"

        class en:
            footer = "Baxi Bot - Avocloud.net"


class Chatfilter:
    title = "Chatfilter"

    class en:
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

        class en:
            text = (
                "This message has been deleted because it could potentially be harmful.\n"
                "If you still want to read it, you can view it using the link below.\n\n"
                "**User:** {user}\n"
                "**ID:** {id}\n"
                "**Info:** {link}\n\n"
                "-# If this is an error, please contact support via Discord or email."
            )

    footer = "Baxi Security"

    class en:
        footer = "Baxi Security"


class Globalchat:
    title = "Globalchat"

    class en:
        title = "Globalchat"

    class Error:
        file_not_image = "Diese Datei ist kein Bild und kann daher nicht im globalen Chat versendet werden."
        to_many_files = "Du kannst maximal ein Bild anhängen und versenden."
        message_to_long = "Deine Nachricht ist zu lang. Beachte, dass die maximale Länge 1000 Zeichen beträgt."
        baned = "Du bist aus dem globalen Chat ausgeschlossen. Folgender Grund ist angegeben: {reason}"

        class en:
            file_not_image = (
                "This file is not an image and cannot be sent in the global chat."
            )
            to_many_files = "You can attach and send a maximum of one image."
            message_to_long = "Your message is too long. Note that the maximum length is 1000 characters."
            baned = "You are banned from the global chat. The following reason is given: {reason}"


class Ai:
    title = "AI"

    class en:
        title = "AI"

    class Waiting:
        content = "Baxi AI arbeitet an einer Antwort..."

        class en:
            content = "Baxi AI is working on an answer..."

    class Error:
        unknown = "Ein unbekannter Fehler ist aufgetreten. Bitte versuche es später noch einmal."
        id_not_found = "Die ConversationID deiner Unterhaltung wurde nicht gefunden. Bitte starte einen neuen chat mithilfe des `/ai` Befehls."
        model_unable_to_chat = "Mit diesem Model kannst du leider nicht chatten. Bitte versuche es mit dem anderen Model."

        class en:
            unknown = "An unknown error has occurred. Please try again later."
            id_not_found = "The ConversationID of your conversation was not found. Please start a new chat using the `/ai` command."
            model_unable_to_chat = "Unfortunately, you cannot chat with this model. Please try the other model."


class Events:
    class on_guild_join:
        title = "Halloooo!"
        content = (
            "Hallo zusammen! Ich bin Baxi, ein Discord Bot wie für dich gemacht. Mein Ziel ist es, deine Community sicher und beschäftigt zu halten.\n"
            "Um Einstellungen vorzunehmen, musst du das Baxi Dash öffnen. https://baxi.avocloud.net\n\n"
            "-# {saved_data}"
        )

        class en:
            title = "Helloooo!"
            content = (
                "Hello everyone! I'm Baxi, a Discord bot made just for you. My goal is to keep your community safe and entertained.\n"
                "To make settings, you have to open the Baxi Dash. https://baxi.avocloud.net\n\n"
                "-# {saved_data}"
            )

        class saved_data:
            new_data = "Standardmäßig sind alle Systeme deaktiviert. Du kannst nun über das Dashboard bestimmte Systeme aktivieren und einstellen."
            existing_data = "Da wir bereits Einstellungen von diesem Server abgespeichert haben, wurden diese wiederhergestellt. Überprüfe bitte im Dashboard ob diese Einstellungen korrekt sind."

            class en:
                new_data = "By default, all systems are disabled. You can now enable and configure certain systems through the dashboard."
                existing_data = "Since we have already saved settings from this server, they have been restored. Please check in the dashboard if these settings are correct."


class Utility:
    user = "Benutzer:"
    mod = "Moderator:"
    reason = "Grund:"
    amount = "Anzahl der Nachrichten:"
    channel = "Kanal:"

    class en:
        user = "User:"
        mod = "Moderator:"
        reason = "Reason:"
        amount = "Amount of messages:"
        channel = "Channel:"

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

        class en:
            title = "Ban"
            confirmation = (
                "Do you really want to ban the user with the following reason?"
            )
            missing_perms = (
                "You do not have the necessary permissions to ban this user."
            )
            bot_missing_perms = (
                "I do not have the necessary permissions to ban this user."
            )
            success = "The user has been successfully banned with the following reason:"
            audit_reason = "Banned by {moderator}: {reason}"
            error = "An error occurred: {error}"
            abort = "The ban process has been aborted."

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

        class en:
            title = "Unban"
            confirmation = "Do you really want to unban the user?"
            missing_perms = (
                "You do not have the necessary permissions to unban this user."
            )
            bot_missing_perms = (
                "I do not have the necessary permissions to unban this user."
            )
            success = "The user has been successfully unbanned."
            audit_reason = "Unbanned by {moderator}"
            error = "An error occurred: {error}"
            abort = "The unban process has been aborted."

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

        class en:
            title = "Kick"
            confirmation = (
                "Do you really want to kick the user with the following reason?"
            )
            missing_perms = (
                "You do not have the necessary permissions to kick this user."
            )
            bot_missing_perms = (
                "I do not have the necessary permissions to kick this user."
            )
            success = "The user has been successfully kicked with the following reason:"
            audit_reason = "Kicked by {moderator}: {reason}"
            error = "An error occurred: {error}"
            abort = "The kick process has been aborted."

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

        class en:
            title = "Clear messages"
            confirmation = "Do you really want to delete the messages?"
            missing_perms = (
                "You do not have the necessary permissions to delete messages."
            )
            bot_missing_perms = (
                "I do not have the necessary permissions to delete messages."
            )
            success = "The messages have been successfully deleted."
            error = "An error occurred: {error}"
            abort = "The process has been aborted."


class Minigames:
    class Counting:
        title = "Zählspiel"
        description_wrong_number = "{user}, die Zahl die du gesendet hast ist nicht die richtige. Wir beginnen wieder bei 1."
        description_same_user = "{user}, du darfst nicht zweimal hintereinander eine Zahl senden. Ihr müsst abwechselnd zählen."

        class en:
            title = "Counting game"
            description_wrong_number = (
                "{user}, the number you sent is not the right one. We start again at 1."
            )
            description_same_user = "{user}, you are not allowed to send a number twice in a row. You have to count alternately."

    class Guessing:
        title = "Raten"
        description_correct = "{user}, du hast die Zahl richtig geraten!\nWir beginnen mit einer neuen Zahl, diese wurde zwischen 1 und {max_value} generiert.\nViel Erfolg!"

        class en:
            title = "Guessing"
            description_correct = "{user}, you guessed the number correctly!\nWe start with a new number, this was generated between 1 and {max_value}.\nGood luck!"


class Verify:
    title = "Verifizierung"
    description_not_enabeld = "Die Verifizierung ist auf diesem Server nicht aktiviert. Bitte kontaktiere einen Administrator."
    description_success = (
        "Die Verifizierung war erfolgreich. Willkommen auf dem Server!"
    )

    class en:
        title = "Verification"
        description_not_enabeld = "Verification is not enabled on this server. Please contact an administrator."
        description_success = "Verification was successful. Welcome to the server!"

    class Captcha:
        description_wrong_code = (
            "Der eingegebene Code ist falsch. Bitte versuche es erneut."
        )

        class en:
            description_wrong_code = "The entered code is incorrect. Please try again."

    class Password:
        description_wrong_password = (
            "Das eingegebene Passwort ist falsch. Bitte versuche es erneut."
        )

        class en:
            description_wrong_password = (
                "The entered password is incorrect. Please try again."
            )


class Ticket:
    title = "Support Ticket"
    channel_name = "support-{user}"
    description_creation_successfull = "Das Ticket wurde erfolgreich erstellt. Ein Teammitglied wird sich in Kürze bei dir melden.\nDein Ticket: {channel}"
    description_already_open = "Du hast bereits ein offenes Ticket. Bitte warte bis ein Teammitglied antwortet.\nDein Ticket: {channel}"
    description_no_permission_delete = (
        "Du hast keine Berechtigung dieses Ticket zu löschen."
    )
    description_no_permission_claim = (
        "Du hast keine Berechtigung dieses Ticket zu übernehmen."
    )
    description_claimed = "Der Supporter {user} übernimmt nun dieses Ticket."

    class en:
        title = "Support Ticket"
        channel_name = "support-{user}"
        description_creation_successfull = "The ticket has been successfully created. A team member will contact you shortly.\nYour ticket: {channel}"
        description_already_open = "You already have an open ticket. Please wait until a team member responds.\nYour ticket: {channel}"
        description_no_permission_delete = (
            "You do not have permission to delete this ticket."
        )
        description_no_permission_claim = (
            "You do not have permission to take over this ticket."
        )
        description_claimed = "The supporter {user} is now taking over this ticket."
