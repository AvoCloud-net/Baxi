import configparser
import requests
import json

config = configparser.ConfigParser()
config.read("config/runtime.conf")

auth0 = configparser.ConfigParser()
auth0.read("config/auth0.conf")

class Check:
    def __init__(self):
        pass
    class User_check_answer:
        def __init__(self, data):
            self.id:int = data["id"]
            self.name:str = data["name"]
            self.reason:str = data["reason"]
            self.flagged:bool = data["flagged"]


    def check_user(self, id: int):
        json = {"id": id, "key": auth0["SEC"]["key"]}
        request = requests.get(url=config["SEC"]["user_uri"], json=json)
        if request.status_code != 200:
            return f"ERROR - {request.text}"
        
        data = request.json()
        return self.User_check_answer(data=data)
    


    class Message_check_answer:
        def __init__(self, data):
            result = bool(data)
            if result:
                self.flagged: bool = result
                self.distance: str = data["distance"]
                self.match: str = data["matched_badword"]
            else:
                self.flagged: bool = result
                self.distance: str = None
                self.match: str = None


    def check_message(self, message: str):
        json = {"message": message, "key": auth0["SEC"]["key"]}
        request = requests.get(url=config["SEC"]["message_uri"], json=json)
        if request.status_code != 200:
            return f"ERROR - {request.text}"
        
        data = request.json()
        print(data)
        return self.Message_check_answer(data=data)
