"""Local SafeText pipeline: phishing, custom words, doxxing, suicide, NSFW, toxic/hate."""
from assets.message.safetext.pipeline import check as check
from assets.message.safetext.models import preload as preload
