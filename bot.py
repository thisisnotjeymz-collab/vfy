import os
import json
import logging
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DEFAULT_CONFIG = {
    "approval_channel_id": None,
    "logs_channel_id": None,
    "verify_channel_id": None,
    "approved_role_id": None,
    "kick_on_decline": True,
    "panel_message_id": None,
    "embeds": {
        "panel": {
            "title": "Verification Panel",
            "description": "Click the button below to request access.",
            "color": "5865F2",
            "footer": "Staff will review your request.",
            "image_url": "",
            "thumbnail_url": ""
        },
        "approval": {
            "title": "Verification Request",
            "description": "{user_mention} requested verification.\n\n**Roblox:** {roblox_username}\n**Notes:** {notes}",
            "color": "FEE75C",
            "footer": "Use the buttons below.",
            "image_url": "",
            "thumbnail_url": ""
        },
        "approved_dm": {
            "title": "Approved",
            "description": "You have been approved in **{guild_name}**.",
            "color": "57F287",
            "footer": "Welcome.",
            "image_url": "",
            "thumbnail_url": ""
        },
        "declined_dm": {
            "title": "Declined",
            "description": "Your verification request in **{guild_name}** was declined.",
            "color": "ED4245",
            "footer": "You may contact staff if needed.",
            "image_url": "",
            "thumbnail_url": ""
        }
    }
}


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config(data)

    for k, v in DEFAULT_CONFIG.items():
        if k not in data:
            data[k] = v

    if "embeds" not in data:
        data["embeds"] = json.loads(json.dumps(DEFAULT_CONFIG["embeds"]))

    for embed_name, embed_defaults in DEFAULT_CONFIG["embeds"].items():
        if embed_name not in data["embeds"]:
            data["embeds"][embed_name] = embed_defaults.copy()
        else:
            for k, v in embed_defaults.items():
                if k not in data["embeds"][embed_name]:
                    data["embeds"][embed_name][k] = v

    return data


config = load_config()


def parse_color(value: str) -> discord.Color:
    value = (value or "5865F2").strip().replace("#", "")
    try:
        return discord.Color(int(value, 16))
    except Exception:
        return discord.Color.blurple()


def apply_placeholders(
    text: str,
    guild: Optional[discord.Guild] = None,
    user: Optional[discord.Member] = None,
    roblox_username: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    text = text or ""
    if guild:
        text = text.replace("{guild_name}", guild.name)
    if user:
        text = text.replace("{user_mention}", user.mention)
        text = text.replace("{user_name}", user.display_name)
        text = text.replace("{user_tag}", str(user))
        text = text.replace("{user_id}", str(user.id))
    text = text.replace("{roblox_username}", roblox_username or "N/A")
    text = text.replace("{notes}", notes or "N/A")
    return text


def build_embed(
    kind: str,
    guild: Optional[discord.Guild] = None,
    user: Optional[discord.Member] = None,
    roblox_username: Optional[str] = None,
    notes: Optional[str] = None
) -> discord.Embed:
    data = config["embeds"][kind]

    embed = discord.Embed(
        title=apply_placeholders(data["title"], guild, user, roblox_username, notes),
        description=apply_placeholders(data["description"], guild, user, roblox_username, notes),
        color=parse_color(data["color"])
    )

    footer = apply_placeholders(data["footer"], guild, user, roblox_username, notes)
    if footer:
        embed.set_footer(text=footer)

    image_url = data.get("image_url", "").strip()
    thumb_url = data.get("thumbnail_url", "").strip()

    if image_url:
        embed.set_image(url=image_url)

    if thumb_url:
        embed.set_thumbnail(url=thumb_url)

    return embed


def setup_is_ready() -> tuple[bool, str]:
    if not config.get("verify_channel_id"):
        return False, "Verify channel is not set."
    if not config.get("approval_channel_id"):
        return False, "Approval channel is not set."
    if not config.get("logs_channel_id"):
        return False, "Logs channel is not set."
    if not config.get("approved_role_id"):
        return False, "Approved role is not set."
    return True, "Ready."


async def send_log(guild: discord.Guild, embed: Optional[discord.Embed] = None, content: Optional[str] = None):
    logs_channel_id = config.get("logs_channel_id")
    if not logs_channel_id:
        return
    channel = guild.get_channel(logs_channel_id)
    if channel and isinstance(channel, discord.TextChannel):
        try:
            await channel.send(content=content, embed=embed)
        except Exception:
            pass


class VerificationRequestModal(discord.ui.Modal, title="Verification Request"):
    def __init__(self):
        super().__init__(timeout=300)

        self.roblox_input = discord.ui.TextInput(
            label="Roblox Account (Optional)",
            placeholder="Username / profile link / N/A",
            required=False,
            max_length=100
        )
        self.notes_input = discord.ui.TextInput(
            label="Extra Notes (Optional)",
            placeholder="Leave empty if none",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=500
        )

        self.add_item(self.roblox_input)
        self.add_item(self.notes_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        ready, msg = setup_is_ready()
        if not ready:
            return await interaction.response.send_message(f"Setup incomplete: {msg}", ephemeral=True)

        approval_channel = interaction.guild.get_channel(config["approval_channel_id"])
        if not approval_channel or not isinstance(approval_channel, discord.TextChannel):
            return await interaction.response.send_message("Approval channel is invalid.", ephemeral=True)

        roblox_username = str(self.roblox_input.value).strip() or "N/A"
        notes = str(self.notes_input.value).strip() or "N/A"

        embed = build_embed(
            "approval",
            guild=interaction.guild,
            user=interaction.user,
            roblox_username=roblox_username,
            notes=notes
        )
        embed.add_field(name="User", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=False)
        embed.add_field(name="Roblox Account", value=roblox_username, inline=False)
        embed.add_field(name="Notes", value=notes, inline=False)

        await approval_channel.send(embed=embed, view=ApprovalView(interaction.user.id, roblox_username, notes))
        await interaction.response.send_message("Your request has been sent to staff for review.", ephemeral=True)


class ApprovalView(discord.ui.View):
    def __init__(self, target_user_id: int, roblox_username: str = "N/A", notes: str = "N/A"):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        self.roblox_username = roblox_username
        self.notes = notes

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="verify_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("You need Manage Roles.", ephemeral=True)

        role_id = config.get("approved_role_id")
        if not role_id:
            return await interaction.response.send_message("Approved role is not set.", ephemeral=True)

        member = interaction.guild.get_member(self.target_user_id)
        role = interaction.guild.get_role(role_id)

        if not member:
            return await interaction.response.send_message("User not found.", ephemeral=True)
        if not role:
            return await interaction.response.send_message("Role not found.", ephemeral=True)
        if interaction.guild.me.top_role <= role:
            return await interaction.response.send_message("My bot role must be higher than the approved role.", ephemeral=True)

        try:
            await member.add_roles(role, reason=f"Approved by {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message("I can't assign that role. Check permissions and role order.", ephemeral=True)

        dm_embed = build_embed(
            "approved_dm",
            guild=interaction.guild,
            user=member,
            roblox_username=self.roblox_username,
            notes=self.notes
        )
        try:
            await member.send(embed=dm_embed)
        except Exception:
            pass

        log_embed = discord.Embed(
            title="Approved",
            description=f"{member.mention} was approved by {interaction.user.mention}.",
            color=discord.Color.green()
        )
        await send_log(interaction.guild, embed=log_embed)

        for child in self.children:
            child.disabled = True

        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"Approved {member.mention}.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="verify_decline")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        if not interaction.user.guild_permissions.kick_members:
            return await interaction.response.send_message("You need Kick Members.", ephemeral=True)

        member = interaction.guild.get_member(self.target_user_id)
        if not member:
            return await interaction.response.send_message("User not found.", ephemeral=True)

        dm_embed = build_embed(
            "declined_dm",
            guild=interaction.guild,
            user=member,
            roblox_username=self.roblox_username,
            notes=self.notes
        )
        try:
            await member.send(embed=dm_embed)
        except Exception:
            pass

        kicked = False
        if config.get("kick_on_decline", True):
            try:
                await member.kick(reason=f"Declined by {interaction.user}")
                kicked = True
            except discord.Forbidden:
                kicked = False

        log_embed = discord.Embed(
            title="Declined",
            description=f"{member.mention} was declined by {interaction.user.mention}.\nKick executed: **{kicked}**",
            color=discord.Color.red()
        )
        await send_log(interaction.guild, embed=log_embed)

        for child in self.children:
            child.disabled = True

        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"Declined {member.mention}. Kick: {kicked}", ephemeral=True)


class GetRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get Roles", style=discord.ButtonStyle.success, custom_id="get_roles_button")
    async def get_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        await interaction.response.send_modal(VerificationRequestModal())


class ConfigModal(discord.ui.Modal, title="Setup Configuration"):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

        self.verify_channel_input = discord.ui.TextInput(
            label="Verify Channel ID",
            default=str(config["verify_channel_id"]) if config.get("verify_channel_id") else "",
            placeholder="Paste channel ID",
            max_length=30,
            required=True
        )
        self.approval_channel_input = discord.ui.TextInput(
            label="Approval Channel ID",
            default=str(config["approval_channel_id"]) if config.get("approval_channel_id") else "",
            placeholder="Paste channel ID",
            max_length=30,
            required=True
        )
        self.logs_channel_input = discord.ui.TextInput(
            label="Logs Channel ID",
            default=str(config["logs_channel_id"]) if config.get("logs_channel_id") else "",
            placeholder="Paste channel ID",
            max_length=30,
            required=True
        )
        self.role_input = discord.ui.TextInput(
            label="Approved Role ID",
            default=str(config["approved_role_id"]) if config.get("approved_role_id") else "",
            placeholder="Paste role ID",
            max_length=30,
            required=True
        )
        self.kick_input = discord.ui.TextInput(
            label="Kick on Decline (true/false)",
            default=str(config.get("kick_on_decline", True)).lower(),
            placeholder="true or false",
            max_length=10,
            required=True
        )

        self.add_item(self.verify_channel_input)
        self.add_item(self.approval_channel_input)
        self.add_item(self.logs_channel_input)
        self.add_item(self.role_input)
        self.add_item(self.kick_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            verify_channel_id = int(str(self.verify_channel_input.value).strip())
            approval_channel_id = int(str(self.approval_channel_input.value).strip())
            logs_channel_id = int(str(self.logs_channel_input.value).strip())
            role_id = int(str(self.role_input.value).strip())
            kick_on_decline = str(self.kick_input.value).strip().lower() in ("true", "yes", "1", "on")
        except ValueError:
            return await interaction.response.send_message("Invalid ID input.", ephemeral=True)

        verify_channel = self.guild.get_channel(verify_channel_id)
        approval_channel = self.guild.get_channel(approval_channel_id)
        logs_channel = self.guild.get_channel(logs_channel_id)
        role = self.guild.get_role(role_id)

        if not verify_channel or not isinstance(verify_channel, discord.TextChannel):
            return await interaction.response.send_message("Verify channel ID is invalid.", ephemeral=True)
        if not approval_channel or not isinstance(approval_channel, discord.TextChannel):
            return await interaction.response.send_message("Approval channel ID is invalid.", ephemeral=True)
        if not logs_channel or not isinstance(logs_channel, discord.TextChannel):
            return await interaction.response.send_message("Logs channel ID is invalid.", ephemeral=True)
        if not role:
            return await interaction.response.send_message("Approved role ID is invalid.", ephemeral=True)

        config["verify_channel_id"] = verify_channel_id
        config["approval_channel_id"] = approval_channel_id
        config["logs_channel_id"] = logs_channel_id
        config["approved_role_id"] = role_id
        config["kick_on_decline"] = kick_on_decline
        save_config(config)

        embed = discord.Embed(
            title="Setup Saved",
            description=(
                f"**Verify Channel:** {verify_channel.mention}\n"
                f"**Approval Channel:** {approval_channel.mention}\n"
                f"**Logs Channel:** {logs_channel.mention}\n"
                f"**Approved Role:** {role.mention}\n"
                f"**Kick on Decline:** `{kick_on_decline}`"
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EmbedMainModal(discord.ui.Modal, title="Edit Embed (Part 1/2)"):
    def __init__(self, kind: str):
        super().__init__(timeout=300)
        self.kind = kind
        current = config["embeds"][kind]

        self.title_input = discord.ui.TextInput(
            label="Title",
            default=current["title"][:100],
            max_length=100,
            required=True
        )
        self.desc_input = discord.ui.TextInput(
            label="Description",
            default=current["description"][:4000],
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True
        )
        self.color_input = discord.ui.TextInput(
            label="Color Hex",
            default=current["color"][:20],
            placeholder="5865F2",
            max_length=20,
            required=False
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer",
            default=current["footer"][:200],
            max_length=200,
            required=False
        )

        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.color_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        data = config["embeds"][self.kind]
        data["title"] = str(self.title_input.value)
        data["description"] = str(self.desc_input.value)
        data["color"] = str(self.color_input.value or "5865F2").replace("#", "")
        data["footer"] = str(self.footer_input.value)
        save_config(config)

        await interaction.response.send_modal(EmbedAssetsModal(self.kind))


class EmbedAssetsModal(discord.ui.Modal, title="Edit Embed (Part 2/2)"):
    def __init__(self, kind: str):
        super().__init__(timeout=300)
        self.kind = kind
        current = config["embeds"][kind]

        self.image_input = discord.ui.TextInput(
            label="Image / GIF URL",
            default=current["image_url"][:400] if current["image_url"] else "",
            placeholder="https://example.com/image.gif",
            max_length=400,
            required=False
        )
        self.thumb_input = discord.ui.TextInput(
            label="Thumbnail URL",
            default=current["thumbnail_url"][:400] if current["thumbnail_url"] else "",
            placeholder="https://example.com/thumb.png",
            max_length=400,
            required=False
        )

        self.add_item(self.image_input)
        self.add_item(self.thumb_input)

    async def on_submit(self, interaction: discord.Interaction):
        data = config["embeds"][self.kind]
        data["image_url"] = str(self.image_input.value).strip()
        data["thumbnail_url"] = str(self.thumb_input.value).strip()
        save_config(config)

        preview = build_embed(
            self.kind,
            guild=interaction.guild,
            user=interaction.user if isinstance(interaction.user, discord.Member) else None
        )
        await interaction.response.send_message(f"Updated **{self.kind}** embed.", embed=preview, ephemeral=True)


class EmbedSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Panel Embed", value="panel"),
            discord.SelectOption(label="Approval Embed", value="approval"),
            discord.SelectOption(label="Approved DM Embed", value="approved_dm"),
            discord.SelectOption(label="Declined DM Embed", value="declined_dm"),
        ]
        super().__init__(
            placeholder="Choose what to edit",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EmbedMainModal(self.values[0]))


async def send_or_refresh_panel(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Guild only.", ephemeral=True)

    verify_channel_id = config.get("verify_channel_id")
    if not verify_channel_id:
        return await interaction.response.send_message("Verify channel is not set.", ephemeral=True)

    verify_channel = interaction.guild.get_channel(verify_channel_id)
    if not verify_channel or not isinstance(verify_channel, discord.TextChannel):
        return await interaction.response.send_message("Verify channel is invalid.", ephemeral=True)

    embed = build_embed(
        "panel",
        guild=interaction.guild,
        user=interaction.user if isinstance(interaction.user, discord.Member) else None
    )
    view = GetRolesView()

    old_message_id = config.get("panel_message_id")
    if old_message_id:
        try:
            old_msg = await verify_channel.fetch_message(old_message_id)
            await old_msg.edit(embed=embed, view=view)
            return await interaction.response.send_message("Panel refreshed.", ephemeral=True)
        except Exception:
            pass

    msg = await verify_channel.send(embed=embed, view=view)
    config["panel_message_id"] = msg.id
    save_config(config)
    await interaction.response.send_message("Panel sent.", ephemeral=True)


class SetupHomeView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=600)
        self.guild = guild
        self.add_item(EmbedSelect())

    @discord.ui.button(label="Setup Channels / Role", style=discord.ButtonStyle.primary)
    async def setup_config_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ConfigModal(self.guild))

    @discord.ui.button(label="Preview Current Embeds", style=discord.ButtonStyle.secondary)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        embeds = [
            build_embed("panel", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None),
            build_embed("approval", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None, roblox_username="N/A", notes="N/A"),
            build_embed("approved_dm", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None),
            build_embed("declined_dm", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None),
        ]
        await interaction.response.send_message("Current embed previews:", embeds=embeds, ephemeral=True)

    @discord.ui.button(label="Send / Refresh Panel", style=discord.ButtonStyle.success)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await send_or_refresh_panel(interaction)

    @discord.ui.button(label="View Settings", style=discord.ButtonStyle.secondary)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        verify_channel = guild.get_channel(config["verify_channel_id"]) if config.get("verify_channel_id") else None
        approval_channel = guild.get_channel(config["approval_channel_id"]) if config.get("approval_channel_id") else None
        logs_channel = guild.get_channel(config["logs_channel_id"]) if config.get("logs_channel_id") else None
        approved_role = guild.get_role(config["approved_role_id"]) if config.get("approved_role_id") else None

        embed = discord.Embed(title="Current Settings", color=discord.Color.blurple())
        embed.add_field(name="Verify Channel", value=verify_channel.mention if verify_channel else "Not set", inline=False)
        embed.add_field(name="Approval Channel", value=approval_channel.mention if approval_channel else "Not set", inline=False)
        embed.add_field(name="Logs Channel", value=logs_channel.mention if logs_channel else "Not set", inline=False)
        embed.add_field(name="Approved Role", value=approved_role.mention if approved_role else "Not set", inline=False)
        embed.add_field(name="Kick on Decline", value=str(config.get("kick_on_decline", True)), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setup", description="Open the setup panel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_command(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Guild only.", ephemeral=True)

    await interaction.response.send_message(
        "Pick what you want to manage.",
        view=SetupHomeView(interaction.guild),
        ephemeral=True
    )


@setup_command.error
async def setup_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        if interaction.response.is_done():
            await interaction.followup.send("You need Administrator permission.", ephemeral=True)
        else:
            await interaction.response.send_message("You need Administrator permission.", ephemeral=True)
        return

    logging.exception("Setup command error: %s", error)
    if interaction.response.is_done():
        await interaction.followup.send(f"Error: `{error}`", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: `{error}`", ephemeral=True)


@bot.event
async def on_ready():
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id)

    bot.add_view(GetRolesView())

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            synced = await bot.tree.sync(guild=guild_obj)
            logging.info("Synced %s guild slash commands to %s", len(synced), GUILD_ID)
        else:
            synced = await bot.tree.sync()
            logging.info("Synced %s global slash commands", len(synced))
    except Exception as e:
        logging.exception("Sync failed: %s", e)


bot.run(TOKEN)
