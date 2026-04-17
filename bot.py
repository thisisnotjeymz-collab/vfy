import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

import discord
from discord import app_commands
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.json"

BOT_TOKEN = os.getenv("DISCORD_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable.")


def parse_color(value: str) -> int:
    value = value.strip().replace("#", "")
    return int(value, 16)


DEFAULT_GUILD_CONFIG: Dict[str, Any] = {
    "approval_channel_id": None,
    "logs_channel_id": None,
    "approved_role_id": None,
    "kick_on_decline": True,
    "panel": {
        "channel_id": None,
        "message_id": None,
        "title": "Verification",
        "description": "Click the button below to request your roles.",
        "button_label": "Get Roles",
        "embed_color": "5865F2",
        "footer": "Staff approval required"
    },
    "approval_embed": {
        "title": "New Verification Request",
        "description": "{user_mention} requested roles in **{guild}**.",
        "color": "F1C40F",
        "footer": "Use the buttons below to approve or decline."
    },
    "approved_dm": {
        "title": "You were approved",
        "description": "Hello {user_mention}, your verification in **{guild}** was approved by **{moderator}**. You received the **{role}** role.",
        "color": "57F287",
        "footer": "Welcome to the server."
    },
    "declined_dm": {
        "title": "Your verification was declined",
        "description": "Hello {user_mention}, your verification in **{guild}** was declined by **{moderator}**.",
        "color": "ED4245",
        "footer": "You may contact the staff team if you believe this was a mistake."
    },
    "log_messages": {
        "approved": "✅ {user_tag} was approved by {moderator_tag} and received role: {role}",
        "declined": "❌ {user_tag} was declined by {moderator_tag}",
        "already_processed": "⚠️ This request was already handled by {moderator_tag}."
    }
}


def deep_copy(data: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(data))


class ConfigManager:
    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, Any] = {"guilds": {}}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.save()

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def guild(self, guild_id: int) -> Dict[str, Any]:
        gid = str(guild_id)
        if gid not in self.data["guilds"]:
            self.data["guilds"][gid] = deep_copy(DEFAULT_GUILD_CONFIG)
            self.save()
        return self.data["guilds"][gid]

    def update_guild(self, guild_id: int, cfg: Dict[str, Any]) -> None:
        self.data["guilds"][str(guild_id)] = cfg
        self.save()


config = ConfigManager(CONFIG_PATH)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def fmt(template: str, member: discord.Member, guild: discord.Guild, moderator: discord.Member | discord.User | None = None, role: discord.Role | None = None) -> str:
    values = {
        "user": member.display_name,
        "user_name": member.name,
        "user_tag": str(member),
        "user_mention": member.mention,
        "guild": guild.name,
        "moderator": getattr(moderator, "display_name", "Unknown Moderator") if moderator else "Unknown Moderator",
        "moderator_tag": str(moderator) if moderator else "Unknown Moderator",
        "role": role.name if role else "No role set"
    }
    try:
        return template.format(**values)
    except Exception:
        return template


def build_embed(data: Dict[str, str], member: discord.Member, guild: discord.Guild, moderator: discord.Member | discord.User | None = None, role: discord.Role | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=fmt(data.get("title", "Message"), member, guild, moderator, role),
        description=fmt(data.get("description", ""), member, guild, moderator, role),
        color=parse_color(data.get("color", "5865F2"))
    )
    footer = fmt(data.get("footer", ""), member, guild, moderator, role)
    if footer:
        embed.set_footer(text=footer)
    return embed


class DecisionView(discord.ui.View):
    def __init__(self, requester_id: int):
        super().__init__(timeout=None)
        self.requester_id = requester_id
        self.processed = False

    async def _require_staff(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This can only be used inside a server.", ephemeral=True)
            return False
        perms = interaction.user.guild_permissions
        if not (perms.manage_roles or perms.kick_members or perms.administrator):
            await interaction.response.send_message("You need Manage Roles, Kick Members, or Administrator to do this.", ephemeral=True)
            return False
        return True

    async def _get_requester(self, interaction: discord.Interaction) -> discord.Member | None:
        if not interaction.guild:
            return None
        member = interaction.guild.get_member(self.requester_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(self.requester_id)
            except discord.NotFound:
                return None
        return member

    async def _disable_buttons(self, interaction: discord.Interaction, label_suffix: str) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed(title="Verification Request")
        embed.add_field(name="Status", value=label_suffix, inline=False)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="verification:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_staff(interaction):
            return
        if self.processed:
            await interaction.response.send_message("This request was already handled.", ephemeral=True)
            return

        requester = await self._get_requester(interaction)
        if requester is None or interaction.guild is None:
            await interaction.response.send_message("I could not find that member anymore.", ephemeral=True)
            return

        guild_cfg = config.guild(interaction.guild.id)
        role_id = guild_cfg.get("approved_role_id")
        if not role_id:
            await interaction.response.send_message("Approved role is not set yet. Use /set_approved_role first.", ephemeral=True)
            return

        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message("The approved role no longer exists. Set it again with /set_approved_role.", ephemeral=True)
            return

        self.processed = True
        await requester.add_roles(role, reason=f"Approved by {interaction.user}")

        try:
            await requester.send(embed=build_embed(guild_cfg["approved_dm"], requester, interaction.guild, interaction.user, role))
        except discord.Forbidden:
            pass

        logs_channel_id = guild_cfg.get("logs_channel_id")
        if logs_channel_id:
            logs_channel = interaction.guild.get_channel(logs_channel_id)
            if logs_channel:
                msg = fmt(guild_cfg["log_messages"]["approved"], requester, interaction.guild, interaction.user, role)
                await logs_channel.send(msg)

        await interaction.response.send_message(f"Approved {requester.mention} and gave {role.mention}.", ephemeral=True)
        await self._disable_buttons(interaction, f"Approved by {interaction.user.mention}")

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="verification:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_staff(interaction):
            return
        if self.processed:
            await interaction.response.send_message("This request was already handled.", ephemeral=True)
            return

        requester = await self._get_requester(interaction)
        if requester is None or interaction.guild is None:
            await interaction.response.send_message("I could not find that member anymore.", ephemeral=True)
            return

        guild_cfg = config.guild(interaction.guild.id)
        self.processed = True

        try:
            await requester.send(embed=build_embed(guild_cfg["declined_dm"], requester, interaction.guild, interaction.user, None))
        except discord.Forbidden:
            pass

        logs_channel_id = guild_cfg.get("logs_channel_id")
        if logs_channel_id:
            logs_channel = interaction.guild.get_channel(logs_channel_id)
            if logs_channel:
                msg = fmt(guild_cfg["log_messages"]["declined"], requester, interaction.guild, interaction.user, None)
                await logs_channel.send(msg)

        if guild_cfg.get("kick_on_decline", True):
            try:
                await requester.kick(reason=f"Verification declined by {interaction.user}")
            except discord.Forbidden:
                await interaction.response.send_message("Declined, but I could not kick the user. Check my role position and Kick Members permission.", ephemeral=True)
                await self._disable_buttons(interaction, f"Declined by {interaction.user.mention}")
                return

        await interaction.response.send_message(f"Declined {requester.mention}.", ephemeral=True)
        await self._disable_buttons(interaction, f"Declined by {interaction.user.mention}")


class RequestView(discord.ui.View):
    def __init__(self, button_label: str = "Get Roles"):
        super().__init__(timeout=None)
        self.button_label = button_label[:80] if button_label else "Get Roles"
        button = discord.ui.Button(
            label=self.button_label,
            style=discord.ButtonStyle.primary,
            custom_id="verification:get_roles"
        )
        button.callback = self.get_roles
        self.add_item(button)

    async def get_roles(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This button only works inside a server.", ephemeral=True)
            return

        guild_cfg = config.guild(interaction.guild.id)
        approval_channel_id = guild_cfg.get("approval_channel_id")
        if not approval_channel_id:
            await interaction.response.send_message("Approval channel is not set yet. Ask an admin to run /set_approval_channel.", ephemeral=True)
            return

        approval_channel = interaction.guild.get_channel(approval_channel_id)
        if approval_channel is None:
            await interaction.response.send_message("Approval channel was not found. Ask an admin to set it again.", ephemeral=True)
            return

        embed = build_embed(guild_cfg["approval_embed"], interaction.user, interaction.guild, None, None)
        embed.add_field(name="User ID", value=str(interaction.user.id), inline=True)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(interaction.user.created_at, style="F"), inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await approval_channel.send(embed=embed, view=DecisionView(interaction.user.id))
        await interaction.response.send_message("Your request was sent to the staff team for approval.", ephemeral=True)


@bot.event
async def on_ready():
    bot.add_view(RequestView())
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    try:
        synced = await bot.tree.sync()
        logging.info("Synced %s slash commands.", len(synced))
    except Exception as exc:
        logging.exception("Failed to sync commands: %s", exc)


async def upsert_panel(guild: discord.Guild) -> str:
    guild_cfg = config.guild(guild.id)
    panel_cfg = guild_cfg["panel"]
    channel_id = panel_cfg.get("channel_id")
    if not channel_id:
        return "Panel channel is not set. Use /setup_panel first."

    channel = guild.get_channel(channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return "Panel channel was not found. Set it again with /setup_panel."

    embed = discord.Embed(
        title=panel_cfg["title"],
        description=panel_cfg["description"],
        color=parse_color(panel_cfg["embed_color"])
    )
    embed.set_footer(text=panel_cfg.get("footer", ""))

    view = RequestView(panel_cfg.get("button_label", "Get Roles"))
    message_id = panel_cfg.get("message_id")
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed, view=view)
            return f"Updated the panel in {channel.mention}."
        except discord.NotFound:
            pass

    message = await channel.send(embed=embed, view=view)
    panel_cfg["message_id"] = message.id
    config.update_guild(guild.id, guild_cfg)
    return f"Created the panel in {channel.mention}."


@bot.tree.command(name="setup_panel", description="Create or update the Get Roles panel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction, channel: discord.TextChannel, title: str = "Verification", description: str = "Click the button below to request your roles.", button_label: str = "Get Roles"):
    if interaction.guild is None:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    cfg = config.guild(interaction.guild.id)
    cfg["panel"]["channel_id"] = channel.id
    cfg["panel"]["title"] = title
    cfg["panel"]["description"] = description
    cfg["panel"]["button_label"] = button_label[:80]
    config.update_guild(interaction.guild.id, cfg)
    result = await upsert_panel(interaction.guild)
    await interaction.response.send_message(result, ephemeral=True)


@bot.tree.command(name="refresh_panel", description="Refresh the existing Get Roles panel.")
@app_commands.checks.has_permissions(administrator=True)
async def refresh_panel(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    result = await upsert_panel(interaction.guild)
    await interaction.response.send_message(result, ephemeral=True)


@bot.tree.command(name="set_approval_channel", description="Set the staff approval channel.")
@app_commands.checks.has_permissions(administrator=True)
async def set_approval_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = config.guild(interaction.guild.id)
    cfg["approval_channel_id"] = channel.id
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message(f"Approval channel set to {channel.mention}.", ephemeral=True)


@bot.tree.command(name="set_logs_channel", description="Set the logs channel.")
@app_commands.checks.has_permissions(administrator=True)
async def set_logs_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg = config.guild(interaction.guild.id)
    cfg["logs_channel_id"] = channel.id
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message(f"Logs channel set to {channel.mention}.", ephemeral=True)


@bot.tree.command(name="set_approved_role", description="Set the role given on approval.")
@app_commands.checks.has_permissions(administrator=True)
async def set_approved_role(interaction: discord.Interaction, role: discord.Role):
    cfg = config.guild(interaction.guild.id)
    cfg["approved_role_id"] = role.id
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message(f"Approved role set to {role.mention}.", ephemeral=True)


@bot.tree.command(name="set_kick_on_decline", description="Choose whether declined users get kicked automatically.")
@app_commands.checks.has_permissions(administrator=True)
async def set_kick_on_decline(interaction: discord.Interaction, enabled: bool):
    cfg = config.guild(interaction.guild.id)
    cfg["kick_on_decline"] = enabled
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message(f"Kick on decline set to **{enabled}**.", ephemeral=True)


@bot.tree.command(name="set_panel_style", description="Customize the panel embed style.")
@app_commands.checks.has_permissions(administrator=True)
async def set_panel_style(interaction: discord.Interaction, color_hex: str, footer: str = "Staff approval required"):
    cfg = config.guild(interaction.guild.id)
    try:
        parse_color(color_hex)
    except Exception:
        await interaction.response.send_message("Use a valid hex color like `5865F2` or `#5865F2`.", ephemeral=True)
        return
    cfg["panel"]["embed_color"] = color_hex.replace("#", "")
    cfg["panel"]["footer"] = footer
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message("Panel style updated. Use /refresh_panel to apply it to the panel message.", ephemeral=True)


@bot.tree.command(name="set_approve_message", description="Customize the DM embed sent when a user is approved.")
@app_commands.checks.has_permissions(administrator=True)
async def set_approve_message(interaction: discord.Interaction, title: str, description: str, color_hex: str = "57F287", footer: str = "Welcome to the server."):
    cfg = config.guild(interaction.guild.id)
    cfg["approved_dm"] = {"title": title, "description": description, "color": color_hex.replace("#", ""), "footer": footer}
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message("Approved DM message updated.", ephemeral=True)


@bot.tree.command(name="set_decline_message", description="Customize the DM embed sent when a user is declined.")
@app_commands.checks.has_permissions(administrator=True)
async def set_decline_message(interaction: discord.Interaction, title: str, description: str, color_hex: str = "ED4245", footer: str = "You may contact the staff team if you believe this was a mistake."):
    cfg = config.guild(interaction.guild.id)
    cfg["declined_dm"] = {"title": title, "description": description, "color": color_hex.replace("#", ""), "footer": footer}
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message("Declined DM message updated.", ephemeral=True)


@bot.tree.command(name="set_approval_message", description="Customize the embed staff sees for new requests.")
@app_commands.checks.has_permissions(administrator=True)
async def set_approval_message(interaction: discord.Interaction, title: str, description: str, color_hex: str = "F1C40F", footer: str = "Use the buttons below to approve or decline."):
    cfg = config.guild(interaction.guild.id)
    cfg["approval_embed"] = {"title": title, "description": description, "color": color_hex.replace("#", ""), "footer": footer}
    config.update_guild(interaction.guild.id, cfg)
    await interaction.response.send_message("Approval request embed updated.", ephemeral=True)


@bot.tree.command(name="show_verification_settings", description="Show the current verification settings.")
@app_commands.checks.has_permissions(administrator=True)
async def show_verification_settings(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    cfg = config.guild(interaction.guild.id)
    role = interaction.guild.get_role(cfg.get("approved_role_id")) if cfg.get("approved_role_id") else None
    approval_channel = interaction.guild.get_channel(cfg.get("approval_channel_id")) if cfg.get("approval_channel_id") else None
    logs_channel = interaction.guild.get_channel(cfg.get("logs_channel_id")) if cfg.get("logs_channel_id") else None
    panel_channel = interaction.guild.get_channel(cfg["panel"].get("channel_id")) if cfg["panel"].get("channel_id") else None

    embed = discord.Embed(title="Verification Settings", color=discord.Color.blurple())
    embed.add_field(name="Approved Role", value=role.mention if role else "Not set", inline=False)
    embed.add_field(name="Approval Channel", value=approval_channel.mention if approval_channel else "Not set", inline=False)
    embed.add_field(name="Logs Channel", value=logs_channel.mention if logs_channel else "Not set", inline=False)
    embed.add_field(name="Panel Channel", value=panel_channel.mention if panel_channel else "Not set", inline=False)
    embed.add_field(name="Kick on Decline", value=str(cfg.get("kick_on_decline", True)), inline=False)
    embed.add_field(name="Placeholders", value="`{user}` `{user_mention}` `{guild}` `{moderator}` `{role}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@setup_panel.error
@refresh_panel.error
@set_approval_channel.error
@set_logs_channel.error
@set_approved_role.error
@set_kick_on_decline.error
@set_panel_style.error
@set_approve_message.error
@set_decline_message.error
@set_approval_message.error
@show_verification_settings.error
async def admin_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("You need Administrator to use this command.", ephemeral=True)
        return
    logging.exception("Command error: %s", error)
    if interaction.response.is_done():
        await interaction.followup.send(f"Something went wrong: {error}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Something went wrong: {error}", ephemeral=True)


bot.run(BOT_TOKEN)
