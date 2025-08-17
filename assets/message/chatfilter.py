import aiohttp
import asyncio
from typing import Dict, Any
from assets.translate import translate_api
import config.config as config
import config.auth as auth
import assets.data as datasys


class Chatfilter:
    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=10)

    async def check(self, message: str, gid: int, cid: int) -> Dict[str, Any]:
        chatfilter_data: dict = dict(datasys.load_data(gid, "chatfilter"))
        preferred_system = chatfilter_data.get("system", "SafeText").lower()

        safetext_task = asyncio.create_task(
            self._try_safetext_check(message, gid, cid, chatfilter_data)
        )
        ai_task = asyncio.create_task(self._try_ai_check(message))

        try:
            async with asyncio.timeout(10):
                safetext_result, ai_result = await asyncio.gather(
                    safetext_task, ai_task
                )
        except asyncio.TimeoutError:
            safetext_result = safetext_task.result() if safetext_task.done() else None
            ai_result = ai_task.result() if ai_task.done() else None

        
        if safetext_result and safetext_result.get("reason") == "custom":
            return safetext_result
        if ai_result and ai_result.get("reason") == "S11":
            return ai_result

        
        if preferred_system == "safetext":
            if safetext_result is not None:
                print("Default: SafeText; Used: SafeText")
                return safetext_result
            if ai_result is not None:
                print("Default: SafeText; Used: AI")
                return ai_result
        else:
            if ai_result is not None:
                print("Default: AI; Used: AI")
                return ai_result
            if safetext_result is not None:
                print("Default: AI; Used: SafeText")
                return safetext_result

        return {
            "code": "safe",
            "flagged": False,
            "distance": None,
            "reason": "no_issues_detected",
            "json": {},
        }

    async def _try_safetext_check(
        self, message: str, gid: int, cid: int, chatfilter_data: dict
    ) -> Dict[str, Any] | None:
        json_data = {
            "message": message,
            "gid": gid,
            "cid": cid,
            "c_badwords": chatfilter_data.get("c_badwords"),
            "c_goodwords": chatfilter_data.get("c_goodwords"),
            "key": auth.Chatfilter.api_key,
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    config.Chatfilter.chatfilter_url, json=json_data
                ) as response:
                    if response.status == 200:
                        data = await response.json()

                        if not data:
                            return {
                                "code": "safe",
                                "flagged": False,
                                "distance": None,
                                "reason": None,
                                "json": {},
                            }

                        return {
                            "code": "safetext-filter",
                            "flagged": True,
                            "distance": str(data.get("distance", "0")),
                            "reason": f"{data.get('code')}",
                            "json": data,
                        }

        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError) as e:
            print(f"SafeText check failed: {str(e)}")
            return None

    async def _try_ai_check(self, message: str) -> Dict[str, Any] | None:
        try:
            translated_message = await translate_api(message)
            payload = {
                "model": "hf.co/jquirion/Llama-Guard-3-1B-Q4_K_M:latest",
                "messages": [{"role": "user", "content": translated_message}],
                "temperature": 0.2,
                "max_tokens": 512,
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth.Chatfilter.ai_key}",
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    config.Chatfilter.ai_url, json=payload, headers=headers
                ) as ai_response_raw:
                    ai_response_json = await ai_response_raw.json()

            content = ai_response_json["choices"][0]["message"]["content"]
            lines = content.strip().split("\n")
            flagged_categories = {"S3", "S4", "S5", "S10", "S11", "S12"}
            status = lines[0].lower()
            category = lines[1] if len(lines) > 1 else None

            return {
                "code": (
                    "flagged"
                    if status == "unsafe" and category in flagged_categories
                    else "safe"
                ),
                "flagged": status == "unsafe" and category in flagged_categories,
                "distance": None,
                "reason": category,
                "json": {"status": status, "category": category},
            }
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError) as e:
            print(f"AI check failed: {str(e)}")
            return None
