##################################
# This is the original source code
# of the Discord Bot's Baxi.
#
# When using the code (copy, change)
# all policies and licenses must be adhered to.
#
# Developer: Red_Wolf2467
# Original App: Baxi
##################################


import datetime

from assets.general.get_saves import *


def load_language_model(server_id):
    language_settings = load_data("json/language.json")
    try:
        if str(server_id) not in language_settings:
            return load_data("language/en.json")

        elif language_settings[str(server_id)]["language"] == "en":
            return load_data("language/en.json")

        elif language_settings[str(server_id)]["language"] == "de":
            return load_data("language/de.json")

        elif language_settings[str(server_id)]["language"] == "fr":
            return load_data("language/fr.json")

        elif language_settings[str(server_id)]["language"] == "norsk":
            return load_data("language/norsk.json")

        else:
            return load_data("language/en.json")
    except:
        return load_data("language/en.json")


def handle_log_event(command, guild, username):
    log_folder = os.path.join("log", guild)
    log_file = os.path.join(log_folder, "log.txt")
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

    if not os.path.exists(log_folder):
        os.makedirs(log_folder)

    if not os.path.exists(log_file):
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("Log-Datei für den Server {} \n".format(guild))
        f.close()

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} - {command} - {username}\n")
    f.close()
