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
    return int(value.strip().replace("#", ""), 16)


def safe_hex(value: str, fallback: str = "5865F2") -> str:
    try:
        parse_color(value)
        return value.replace("#", "")
    except Exception:
        return fallback


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
        "color": "5865F2",
        "footer": "Staff approval required",
        "image_url": "",
        "thumbnail_url": ""
    },
    "approval_embed": {
        "title": "New Verification Request",
        "description": "{user_mention} requested roles in **{guild}**.",
        "color": "F1C40F",
        "footer": "Use the buttons below to approve or decline.",
        "image_url": "",
        "thumbnail_url": ""
    },
    "approved_dm": {
        "title": "You were approved",
        "description": "Hello {user_mention}, your verification in **{guild}** was approved by **{moderator}**. You received the **{role}** role.",
        "color": "57F287",
        "footer": "Welcome to the server.",
        "image_url": "",
        "thumbnail_url": ""
    },
    "declined_dm": {
        "title": "Your verification was declined",
        "description": "Hello {user_mention}, your verification in **{guild}** was declined by **{moderator}**.",
        "color": "ED4245",
        "footer": "You may contact the staff team if you believe this was a mistake.",
        "image_url": "",
        "thumbnail_url": ""
    },
    "log_messages": {
        "approved": "✅ {user_tag} was approved by {moderator_tag} and received role: {role}",
        "declined": "❌ {user_tag} was declined by {moderator_tag}",
    },
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
        "role": role.name if role else "No role set",
    }
    try:
        return template.format(**values)
    except Exception:
        return template


def build_embed(data: Dict[str, str], member: discord.Member, guild: discord.Guild, moderator: discord.Member | discord.User | None = None, role: discord.Role | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=fmt(data.get("title", "Message"), member, guild, moderator, role),
        description=fmt(data.get("description", ""), member, guild, moderator, role),
        color=parse_color(data.get("color", "5865F2")),
    )
    footer = fmt(data.get("footer", ""), member, guild, moderator, role)
    if footer:
        embed.set_footer(text=footer)
    image_url = data.get("image_url", "").strip()
    thumb = data.get("thumbnail_url", "").strip()
    if image_url:
        embed.set_image(url=image_url)
    if thumb:
        embed.set_thumbnail(url=thumb)
    return embed


def build_preview_embed(section_name: str, section: Dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=section.get("title") or section_name,
        description=section.get("description") or "No description set.",
        color=parse_color(section.get("color", "5865F2")),
    )
    footer = section.get("footer", "")
    if footer:
        embed.set_footer(text=footer)
    image_url = section.get("image_url", "")
    thumb = section.get("thumbnail_url", "")
    if image_url:
        embed.set_image(url=image_url)
    if thumb:
        embed.set_thumbnail(url=thumb)
    return embed


async def ensure_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this inside your server.", ephemeral=True)
        return False
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need Administrator to use this.", ephemeral=True)
        return False
    return True


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
            await interaction.response.send_message("Approved role is not set yet. Run /setup first.", ephemeral=True)
            return

        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message("The approved role no longer exists. Set it again in /setup.", ephemeral=True)
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
                await logs_channel.send(fmt(guild_cfg["log_messages"]["approved"], requester, interaction.guild, interaction.user, role))

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
                await logs_channel.send(fmt(guild_cfg["log_messages"]["declined"], requester, interaction.guild, interaction.user, None))

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
        button = discord.ui.Button(label=(button_label or "Get Roles")[:80], style=discord.ButtonStyle.primary, custom_id="verification:get_roles")
        button.callback = self.get_roles
        self.add_item(button)

    async def get_roles(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This button only works inside a server.", ephemeral=True)
            return

        guild_cfg = config.guild(interaction.guild.id)
        approval_channel_id = guild_cfg.get("approval_channel_id")
        if not approval_channel_id:
            await interaction.response.send_message("Approval channel is not set yet. Ask an admin to run /setup.", ephemeral=True)
            return

        approval_channel = interaction.guild.get_channel(approval_channel_id)
        if approval_channel is None:
            await interaction.response.send_message("Approval channel was not found. Ask an admin to set it again in /setup.", ephemeral=True)
            return

        embed = build_embed(guild_cfg["approval_embed"], interaction.user, interaction.guild)
        embed.add_field(name="User ID", value=str(interaction.user.id), inline=True)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(interaction.user.created_at, style="F"), inline=False)
        if not guild_cfg["approval_embed"].get("thumbnail_url"):
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await approval_channel.send(embed=embed, view=DecisionView(interaction.user.id))
        await interaction.response.send_message("Your request was sent to the staff team for approval.", ephemeral=True)


async def upsert_panel(guild: discord.Guild) -> str:
    guild_cfg = config.guild(guild.id)
    panel_cfg = guild_cfg["panel"]
    channel_id = panel_cfg.get("channel_id")
    if not channel_id:
        return "Panel channel is not set yet. Open /setup and choose your verify channel."

    channel = guild.get_channel(channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return "Panel channel was not found. Set it again in /setup."

    dummy_member = guild.me or next((m for m in guild.members if m.bot), None)
    embed = discord.Embed(
        title=panel_cfg["title"],
        description=panel_cfg["description"],
        color=parse_color(panel_cfg["color"]),
    )
    if panel_cfg.get("footer"):
        embed.set_footer(text=panel_cfg["footer"])
    if panel_cfg.get("image_url"):
        embed.set_image(url=panel_cfg["image_url"])
    if panel_cfg.get("thumbnail_url"):
        embed.set_thumbnail(url=panel_cfg["thumbnail_url"])

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


class ChannelSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(VerifyChannelSelect())
        self.add_item(ApprovalChannelSelect())
        self.add_item(LogsChannelSelect())
        self.add_item(ApprovedRoleSelect())
        self.add_item(KickToggleButton())
        self.add_item(SendPanelButton())


class VerifyChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(channel_types=[discord.ChannelType.text], placeholder="Choose verify panel channel", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        cfg["panel"]["channel_id"] = self.values[0].id
        config.update_guild(interaction.guild.id, cfg)
        await interaction.response.send_message(f"Verify panel channel set to {self.values[0].mention}.", ephemeral=True)


class ApprovalChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(channel_types=[discord.ChannelType.text], placeholder="Choose approval channel", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        cfg["approval_channel_id"] = self.values[0].id
        config.update_guild(interaction.guild.id, cfg)
        await interaction.response.send_message(f"Approval channel set to {self.values[0].mention}.", ephemeral=True)


class LogsChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(channel_types=[discord.ChannelType.text], placeholder="Choose logs channel", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        cfg["logs_channel_id"] = self.values[0].id
        config.update_guild(interaction.guild.id, cfg)
        await interaction.response.send_message(f"Logs channel set to {self.values[0].mention}.", ephemeral=True)


class ApprovedRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Choose approved role", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        cfg["approved_role_id"] = self.values[0].id
        config.update_guild(interaction.guild.id, cfg)
        await interaction.response.send_message(f"Approved role set to {self.values[0].mention}.", ephemeral=True)


class KickToggleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Toggle Kick On Decline", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        cfg["kick_on_decline"] = not cfg.get("kick_on_decline", True)
        config.update_guild(interaction.guild.id, cfg)
        await interaction.response.send_message(f"Kick on decline is now **{cfg['kick_on_decline']}**.", ephemeral=True)


class SendPanelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Send / Refresh Panel", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        result = await upsert_panel(interaction.guild)
        await interaction.response.send_message(result, ephemeral=True)


class EmbedTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Panel Embed", value="panel"),
            discord.SelectOption(label="Approval Embed", value="approval_embed"),
            discord.SelectOption(label="Approved DM Embed", value="approved_dm"),
            discord.SelectOption(label="Declined DM Embed", value="declined_dm"),
        ]
        super().__init__(placeholder="Choose what to customize", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EmbedCustomizeModal(self.values[0]))


class CustomizeHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(EmbedTypeSelect())
        self.add_item(PreviewButton())
        self.add_item(SendPanelButton())


class PreviewButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Preview Current Embeds", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        embeds = [
            build_preview_embed("Panel Embed", cfg["panel"]),
            build_preview_embed("Approval Embed", cfg["approval_embed"]),
            build_preview_embed("Approved DM Embed", cfg["approved_dm"]),
            build_preview_embed("Declined DM Embed", cfg["declined_dm"]),
        ]
        await interaction.response.send_message(embeds=embeds, ephemeral=True)


class EmbedCustomizeModal(discord.ui.Modal):
    def __init__(self, section_key: str):
        self.section_key = section_key
        labels = {
            "panel": "Panel Embed",
            "approval_embed": "Approval Embed",
            "approved_dm": "Approved DM Embed",
            "declined_dm": "Declined DM Embed",
        }
        super().__init__(title=f"Customize {labels.get(section_key, section_key)}")

        self.title_input = discord.ui.TextInput(label="Title", required=False, max_length=256)
        self.description_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False, max_length=4000)
        self.color_input = discord.ui.TextInput(label="Hex Color", required=False, placeholder="#5865F2")
        self.footer_input = discord.ui.TextInput(label="Footer", required=False, max_length=2048)
        self.image_input = discord.ui.TextInput(label="Image / GIF URL", required=False, max_length=1000)
        self.thumb_input = discord.ui.TextInput(label="Thumbnail URL", required=False, max_length=1000)

        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)
        self.add_item(self.footer_input)
        self.add_item(self.image_input)
        self.add_item(self.thumb_input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        section = cfg[self.section_key]

        if self.title_input.value:
            section["title"] = self.title_input.value
        if self.description_input.value:
            section["description"] = self.description_input.value
        if self.color_input.value:
            section["color"] = safe_hex(self.color_input.value, section.get("color", "5865F2"))
        if self.footer_input.value:
            section["footer"] = self.footer_input.value
        if self.image_input.value is not None:
            section["image_url"] = self.image_input.value.strip()
        if self.thumb_input.value is not None:
            section["thumbnail_url"] = self.thumb_input.value.strip()

        if self.section_key == "panel" and "button_label" not in section:
            section["button_label"] = "Get Roles"

        config.update_guild(interaction.guild.id, cfg)
        preview = build_preview_embed(self.section_key.replace("_", " ").title(), section)
        await interaction.response.send_message("Saved. Here is your updated preview.", embed=preview, ephemeral=True)


class SetupHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ChannelRoleButton())
        self.add_item(PanelTextButton())
        self.add_item(CustomizeOpenButton())
        self.add_item(SendPanelButton())
        self.add_item(CurrentSettingsButton())


class ChannelRoleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Channels / Role", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Set your verify channel, approval channel, logs channel, approved role, and kick option below.",
            view=ChannelSelectView(),
            ephemeral=True,
        )


class PanelTextButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Panel Text", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PanelTextModal())


class CustomizeOpenButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Customize Embeds", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Choose which embed you want to edit.", view=CustomizeHomeView(), ephemeral=True)


class CurrentSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="View Current Settings", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        role = interaction.guild.get_role(cfg.get("approved_role_id")) if cfg.get("approved_role_id") else None
        approval_channel = interaction.guild.get_channel(cfg.get("approval_channel_id")) if cfg.get("approval_channel_id") else None
        logs_channel = interaction.guild.get_channel(cfg.get("logs_channel_id")) if cfg.get("logs_channel_id") else None
        panel_channel = interaction.guild.get_channel(cfg["panel"].get("channel_id")) if cfg["panel"].get("channel_id") else None

        embed = discord.Embed(title="Verification Settings", color=discord.Color.blurple())
        embed.add_field(name="Approved Role", value=role.mention if role else "Not set", inline=False)
        embed.add_field(name="Approval Channel", value=approval_channel.mention if approval_channel else "Not set", inline=False)
        embed.add_field(name="Logs Channel", value=logs_channel.mention if logs_channel else "Not set", inline=False)
        embed.add_field(name="Verify Channel", value=panel_channel.mention if panel_channel else "Not set", inline=False)
        embed.add_field(name="Kick on Decline", value=str(cfg.get("kick_on_decline", True)), inline=False)
        embed.add_field(name="Placeholders", value="`{user}` `{user_mention}` `{guild}` `{moderator}` `{role}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PanelTextModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Panel Text")
        self.title_input = discord.ui.TextInput(label="Panel Title", required=False, max_length=256)
        self.description_input = discord.ui.TextInput(label="Panel Description", style=discord.TextStyle.paragraph, required=False, max_length=4000)
        self.button_input = discord.ui.TextInput(label="Button Label", required=False, max_length=80)
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.button_input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = config.guild(interaction.guild.id)
        if self.title_input.value:
            cfg["panel"]["title"] = self.title_input.value
        if self.description_input.value:
            cfg["panel"]["description"] = self.description_input.value
        if self.button_input.value:
            cfg["panel"]["button_label"] = self.button_input.value[:80]
        config.update_guild(interaction.guild.id, cfg)
        await interaction.response.send_message("Panel text saved. Press Send / Refresh Panel in /setup or /customize.", ephemeral=True)


@bot.event
async def on_ready():
    bot.add_view(RequestView())
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    try:
        guild_id_raw = os.getenv("GUILD_ID", "").strip()
        if guild_id_raw:
            guild_obj = discord.Object(id=int(guild_id_raw))
            synced = await bot.tree.sync(guild=guild_obj)
            logging.info("Synced %s guild slash commands to %s.", len(synced), guild_id_raw)
        else:
            synced = await bot.tree.sync()
            logging.info("Synced %s global slash commands.", len(synced))
    except Exception as exc:
        logging.exception("Failed to sync commands: %s", exc)


@bot.tree.command(name="setup", description="Open the verification setup panel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    if not await ensure_admin(interaction):
        return
    await interaction.response.send_message(
        "Use the buttons below to set channels, role, panel text, and send the verification panel.",
        view=SetupHomeView(),
        ephemeral=True,
    )


@bot.tree.command(name="customize", description="Customize your verification embeds with a UI.")
@app_commands.checks.has_permissions(administrator=True)
async def customize(interaction: discord.Interaction):
    if not await ensure_admin(interaction):
        return
    await interaction.response.send_message("Pick what you want to customize.", view=CustomizeHomeView(), ephemeral=True)


@bot.tree.command(name="panel", description="Send or refresh the verification panel.")
@app_commands.checks.has_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    if not await ensure_admin(interaction):
        return
    result = await upsert_panel(interaction.guild)
    await interaction.response.send_message(result, ephemeral=True)


@bot.tree.command(name="settings", description="Show current verification settings.")
@app_commands.checks.has_permissions(administrator=True)
async def settings(interaction: discord.Interaction):
    if not await ensure_admin(interaction):
        return
    await CurrentSettingsButton().callback(interaction)


@setup.error
@customize.error
@panel.error
@settings.error
async def admin_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        if interaction.response.is_done():
            await interaction.followup.send("You need Administrator to use this command.", ephemeral=True)
        else:
            await interaction.response.send_message("You need Administrator to use this command.", ephemeral=True)
        return
    logging.exception("Command error: %s", error)
    if interaction.response.is_done():
        await interaction.followup.send(f"Something went wrong: {error}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Something went wrong: {error}", ephemeral=True)


bot.run(BOT_TOKEN)
