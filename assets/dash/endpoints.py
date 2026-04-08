import quart
from quart import request, jsonify
from discord.ext import commands
import discord
import config.auth as auth
from reds_simple_logger import Logger

logger = Logger()


def dash_auth_endpoint(app: quart.Quart, bot: commands.AutoShardedBot):
    @app.route("/dash/auth/callback")
    async def auth():
        return "Not implemented yet"


def topgg_vote_endpoint(app: quart.Quart, bot: commands.AutoShardedBot):
    @app.route("/webhooks/topgg/vote", methods=["POST"])
    async def topgg_vote():
        # Verify the webhook authorization
        auth_header = request.headers.get("Authorization", "")
        expected = auth.TopGG.webhook_secret
        if not expected or expected == "YOUR-TOPGG-WEBHOOK-SECRET":
            logger.warning("[TopGG Vote] Webhook secret not configured, rejecting request.")
            return jsonify({"error": "Not configured"}), 503
        if auth_header != expected:
            logger.warning("[TopGG Vote] Unauthorized vote webhook request.")
            return jsonify({"error": "Unauthorized"}), 401

        data = await request.get_json()
        if not data:
            return jsonify({"error": "Bad request"}), 400

        voter_id: int = int(data.get("user", 0))
        guild_id: int = int(data.get("guild", 0)) if data.get("guild") else 0
        vote_type: str = data.get("type", "upvote")  # "upvote" or "test"

        if not voter_id:
            return jsonify({"error": "Missing user"}), 400

        avocloud_guild_id = auth.TopGG.avocloud_guild_id
        vote_channel_id = auth.TopGG.vote_channel_id

        if not avocloud_guild_id or not vote_channel_id:
            logger.warning("[TopGG Vote] avocloud_guild_id or vote_channel_id not configured.")
            return jsonify({"ok": True}), 200

        # Check if voter is a member of the avocloud.net Discord server
        avocloud_guild: discord.Guild | None = bot.get_guild(avocloud_guild_id)
        if avocloud_guild is None:
            logger.warning("[TopGG Vote] Bot is not in avocloud guild.")
            return jsonify({"ok": True}), 200

        try:
            voter_member = avocloud_guild.get_member(voter_id)
            if voter_member is None:
                voter_member = await avocloud_guild.fetch_member(voter_id)
        except discord.NotFound:
            voter_member = None
        except Exception as e:
            logger.error(f"[TopGG Vote] Error fetching member {voter_id}: {e}")
            voter_member = None

        if voter_member is None:
            # Voter is not on the avocloud.net server — skip announcement
            logger.debug.info(f"[TopGG Vote] User {voter_id} voted but is not on avocloud server.")
            return jsonify({"ok": True}), 200

        # Find the guild that was voted for
        voted_guild: discord.Guild | None = bot.get_guild(guild_id) if guild_id else None

        vote_channel: discord.TextChannel | None = bot.get_channel(vote_channel_id)  # type: ignore
        if vote_channel is None:
            logger.warning(f"[TopGG Vote] Vote channel {vote_channel_id} not found.")
            return jsonify({"ok": True}), 200

        # Build the announcement embed
        embed = discord.Embed(
            title="New Top.gg Vote!",
            color=discord.Color.from_rgb(255, 84, 84),  # top.gg red
        )
        embed.set_footer(text="top.gg • Baxi", icon_url="https://top.gg/favicon.ico")

        if voted_guild:
            embed.description = (
                f"**{voter_member.mention}** voted for Baxi and boosted **{voted_guild.name}**'s reach!\n\n"
                f"Want your server featured here too?\n"
                f"[Vote for Baxi on Top.gg](https://top.gg/bot/{bot.user.id}/vote) — it's free and takes 2 seconds."
            )
            if voted_guild.icon:
                embed.set_thumbnail(url=voted_guild.icon.url)
            embed.add_field(name="Server", value=voted_guild.name, inline=True)
            embed.add_field(name="Members", value=str(voted_guild.member_count), inline=True)
        else:
            embed.description = (
                f"**{voter_member.mention}** just voted for Baxi on Top.gg!\n\n"
                f"[Vote too →](https://top.gg/bot/{bot.user.id}/vote)"
            )

        try:
            await vote_channel.send(embed=embed)
            logger.debug.success(f"[TopGG Vote] Announced vote by {voter_member} in channel {vote_channel_id}.")
        except Exception as e:
            logger.error(f"[TopGG Vote] Failed to send announcement: {e}")

        return jsonify({"ok": True}), 200
