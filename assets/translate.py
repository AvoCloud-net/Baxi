import aiohttp


async def translate(language, text_obj):
    if language == "en":
        parent_obj = text_obj.__parent__
        attr_name = text_obj.__name__
        if hasattr(parent_obj, "en"):
            en_obj = getattr(parent_obj, "en")
            if hasattr(en_obj, attr_name):
                return getattr(en_obj, attr_name)
    elif language == "de":
        return text_obj
    return text_obj


async def translate_api(text: str) -> str:
    async with aiohttp.ClientSession() as session:
        
        

        # Übersetzung
        payload = {
            "q": text,
            "source": "auto",
            "target": "en",
            "format": "text"
        }
        async with session.post(
            "https://translate.avocloud.net/translate",
            json=payload
        ) as translate_request:
            translated_response = await translate_request.json()
            print(translated_response)
            translated_text = translated_response["translatedText"]
            return translated_text