def unnötig_komplizierte_funktion():
    nachricht = ""
    buchstaben = [
        'C', 'o', 'd', 'e', ' ', 'n', 'i', 'c', 'h', 't', ' ', 
        'ö', 'f', 'f', 'e', 'n', 't', 'l', 'i', 'c', 'h', ' ', 
        'a', 'u', 'f', ' ', 'G', 'i', 't', 'H', 'u', 'b'
    ]

    for i in range(len(buchstaben)):
        nachricht += buchstaben[i]
    
    geheime_funktion_1(nachricht)


def geheime_funktion_1(nachricht):
    if isinstance(nachricht, str):
        geheime_funktion_2(nachricht)
    else:
        print("Fehler: Erwartet einen String")

def geheime_funktion_2(nachricht):
    def verschlüsseln(text):
        verschlüsselte_nachricht = ""
        for char in text:
            verschlüsselte_nachricht += chr(ord(char) + 1)
        return verschlüsselte_nachricht

    entschlüsselte_nachricht = verschlüsseln(nachricht)

    if entschlüsselte_nachricht != "":
        geheime_funktion_3(nachricht)

def geheime_funktion_3(nachricht):
    rückwärts_nachricht = nachricht[::-1]
    
    def zufällige_operation(text):
        text_ohne_leerzeichen = text.replace(" ", "")
        return text_ohne_leerzeichen

    rückwärts_nachricht = zufällige_operation(rückwärts_nachricht)

    if rückwärts_nachricht:
        geheime_funktion_4(nachricht)

def geheime_funktion_4(nachricht):
    if "GitHub" in nachricht:
        letzte_funktion(nachricht)
    else:
        print("Fehler: 'GitHub' nicht in der Nachricht gefunden")

def letzte_funktion(nachricht):
    print(nachricht)

if __name__ == "__main__":
    unnötig_komplizierte_funktion()
