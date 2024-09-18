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

import discord

class GuidelinesButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Guidelines", url="https://pyropixle.com/gtc/"))


class DiscordButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Discord", url="https://link.pyropixle.com/discord/"))


class InviteButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Add me", url="https://link.pyropixle.com/baxi/"))


class InviteUndWebButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Add me", url="https://link.pyropixle.com/baxi/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Website", url="https://pyropixle.com/"))


class InviteUndWebUndDiscordButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Add me", url="https://link.pyropixle.com/baxi/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Website", url="https://pyropixle.com/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Discord", url="https://link.pyropixle.com/discord/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Privacy", url="https://pyropixle.com/privacy/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="GTC", url="https://pyropixle.com/gtc/"))


# noinspection SpellCheckingInspection
class InviteUndWebUndDiscordundDocsButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Add me", url="https://link.pyropixle.com/baxi/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Website", url="https://pyropixle.com/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Discord", url="https://link.pyropixle.com/discord/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Docs", url="https://docs.pyropixle.com/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="Privacy", url="https://pyropixle.com/privacy/"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.url,
                                        label="GTC", url="https://pyropixle.com/gtc/"))
