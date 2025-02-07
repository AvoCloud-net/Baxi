import asyncio
from deep_translator import GoogleTranslator
import asyncio

def translate(language, text_obj):
    if language == "en":
        parent_obj = text_obj.__parent__
        attr_name = text_obj.__name__
        if hasattr(parent_obj, "en"):
            en_obj = getattr(parent_obj, "en")
            if hasattr(en_obj, attr_name):
                return getattr(en_obj, attr_name)
    return text_obj

async def baxi_translate(language, text_obj):
    async def task():
        if language == "en":
            return translate(language, text_obj)
        try:
            translated = GoogleTranslator(source="auto", target=language).translate(str(text_obj))
            return translated
        except Exception as e:
            return f"An error occurred: {str(e)}"

    translated = await asyncio.create_task(task(), name="baxi_translate")
    return str(translated)