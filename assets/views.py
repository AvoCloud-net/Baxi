import assets.data as datasys
import discord

from discord import Interaction, ui


class Verify_Captcha_Modal(ui.Modal):
    def __init__(
        self,
        user: discord.abc.User,
        captcha: str,
        guild: discord.Guild,
        role: discord.Role,
    ):
        super().__init__(timeout=60, title="SYS // VERIFY CAPTCHA")
        self.user: discord.abc.User = user
        self.guild: discord.Guild = guild
        self.role: discord.Role = role
        self.captcha: str = captcha

        self.code_input = ui.TextInput(
            placeholder=self.captcha, min_length=5, max_length=5, label="Captcha Code"
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: Interaction):
        try:
            lang = datasys.load_lang_file(self.guild.id)
            member = await self.guild.fetch_member(int(self.user.id))
        except Exception:
            await interaction.response.send_message(
                "An error occurred. Please try again.", ephemeral=True
            )
            return

        if self.code_input.value == self.captcha:
            try:
                await member.add_roles(self.role, reason="Baxi Verify")
            except discord.Forbidden:
                await interaction.response.send_message(
                    "Verification failed: the bot lacks permission to assign that role. Please contact an administrator.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as e:
                await interaction.response.send_message(
                    f"Verification failed: {e}", ephemeral=True
                )
                return
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["description_success"],
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["captcha"]["description_wrong_code"],
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class Verify_Password_Modal(ui.Modal):
    def __init__(
        self,
        user: discord.abc.User,
        captcha: str,
        guild: discord.Guild,
        role: discord.Role,
    ):
        super().__init__(timeout=60, title="SYS // VERIFY PASSWORD")
        self.user: discord.abc.User = user
        self.guild: discord.Guild = guild
        self.role: discord.Role = role
        self.captcha: str = captcha

        self.code_input = ui.TextInput(
            placeholder="Enter the server password",
            min_length=1,
            max_length=max(int(len(captcha)) + 1, 2),
            label="Password",
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: Interaction):
        try:
            lang = datasys.load_lang_file(self.guild.id)
            member = await self.guild.fetch_member(int(self.user.id))
        except Exception:
            await interaction.response.send_message(
                "An error occurred. Please try again.", ephemeral=True
            )
            return

        if self.code_input.value == self.captcha:
            try:
                await member.add_roles(self.role, reason="Baxi Verify")
            except discord.Forbidden:
                await interaction.response.send_message(
                    "Verification failed: the bot lacks permission to assign that role. Please contact an administrator.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as e:
                await interaction.response.send_message(
                    f"Verification failed: {e}", ephemeral=True
                )
                return
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["description_success"],
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title=lang["systems"]["verify"]["title"],
                description=lang["systems"]["verify"]["password"][
                    "description_wrong_password"
                ],
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


