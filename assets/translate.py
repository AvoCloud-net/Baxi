from deep_translator import GoogleTranslator
from deep_translator import DeeplTranslator
from deep_translator.exceptions import NotValidPayload
import asyncio


async def baxi_translate(message, language):

    async def task():
        if language == "de":
            return message
        try:
            translated = GoogleTranslator(source="auto", target=language).translate(
                message
            )
            return translated  # , translation_time
        except NotValidPayload:
            return "Translation error: Invalid payload.", None
        except Exception as e:
            return f"An error occurred: {str(e)}", None

    translated = await asyncio.create_task(task(), name="baxi_translate")
    return str(translated)
