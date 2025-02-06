import assets.data as datasys
import config.auth as auth
import config.config as config
import requests


def check_message(message: str):
    request = requests.get(config.Chatfilter.chatfilter_url)


class Chatfilter:
    def __init__(self):
        pass

    class Message_check_answer:
        def __init__(self, data):
            result = bool(data)
            if result:
                chatfilter_data = datasys.load_data(int(data["gid"]), "chatfilter")
                if int(data["cid"]) in chatfilter_data["bypass"]:
                    self.flagged: bool = False
                    self.distance: str = None
                    self.match: str = None
                    self.original_word: str = None
                    self.json = data
                else:
                    self.flagged: bool = result
                    self.distance: str = data["distance"]
                    self.match: str = data["matched_badword"]
                    self.original_word: str = data["input_word"]
                    self.json = data
            else:
                self.flagged: bool = result
                self.distance: str = None
                self.match: str = None
                self.original_word: str = None
                self.json = data

    def check(self, message: str, gid: int, cid: int):
        json = {
            "message": message,
            "gid": gid,
            "cid": cid,
            "key": auth.Chatfilter.api_key,
        }
        request = requests.get(url=config.Chatfilter.chatfilter_url, json=json)
        if request.status_code != 200:
            return f"ERROR - {request.text}"

        data = request.json()
        return self.Message_check_answer(data=data)
