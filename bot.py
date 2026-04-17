import os
import json
import logging
from pathlib import Path
from typing import Optional

import aiohttp
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
            "title": "New Verification Request",
            "description": "{user_mention} requested roles in **{guild_name}**.",
            "color": "FEE75C",
            "footer": "Use the buttons below to approve or decline.",
            "image_url": "",
            "thumbnail_url": ""
        },
        "approved_dm": {
            "title": "You were approved",
            "description": "Hello {user_mention}, your verification in **{guild_name}** was approved by {staff_mention}. You received the **{role_name}** role.",
            "color": "57F287",
            "footer": "Welcome to the server.",
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


def deep_copy(data):
    return json.loads(json.dumps(data))


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_config():
    if not CONFIG_FILE.exists():
        data = deep_copy(DEFAULT_CONFIG)
        save_config(data)
        return data

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = deep_copy(DEFAULT_CONFIG)
        save_config(data)
        return data

    for key, value in DEFAULT_CONFIG.items():
        if key not in data:
            data[key] = value

    if "embeds" not in data:
        data["embeds"] = deep_copy(DEFAULT_CONFIG["embeds"])

    for embed_name, embed_defaults in DEFAULT_CONFIG["embeds"].items():
        if embed_name not in data["embeds"]:
            data["embeds"][embed_name] = deep_copy(embed_defaults)
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
    notes: Optional[str] = None,
    staff_mention: Optional[str] = None,
    role_name: Optional[str] = None,
):
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
    text = text.replace("{staff_mention}", staff_mention or "Staff")
    text = text.replace("{role_name}", role_name or "Verified")

    return text


def build_embed(
    kind: str,
    guild: Optional[discord.Guild] = None,
    user: Optional[discord.Member] = None,
    roblox_username: Optional[str] = None,
    notes: Optional[str] = None,
    staff_mention: Optional[str] = None,
    role_name: Optional[str] = None,
) -> discord.Embed:
    data = config["embeds"][kind]

    embed = discord.Embed(
        title=apply_placeholders(
            data["title"], guild, user, roblox_username, notes, staff_mention, role_name
        ),
        description=apply_placeholders(
            data["description"], guild, user, roblox_username, notes, staff_mention, role_name
        ),
        color=parse_color(data["color"])
    )

    footer = apply_placeholders(
        data.get("footer", ""), guild, user, roblox_username, notes, staff_mention, role_name
    )
    if footer:
        embed.set_footer(text=footer)

    image_url = data.get("image_url", "").strip()
    thumb_url = data.get("thumbnail_url", "").strip()

    if image_url:
        embed.set_image(url=image_url)

    if thumb_url:
        embed.set_thumbnail(url=thumb_url)

    return embed


def setup_is_ready():
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
    channel_id = config.get("logs_channel_id")
    if not channel_id:
        return

    channel = guild.get_channel(channel_id)
    if channel and isinstance(channel, discord.TextChannel):
        try:
            await channel.send(content=content, embed=embed)
        except Exception:
            pass


async def roblox_lookup(username: str):
    username = (username or "").strip()
    if not username or username.upper() == "N/A":
        return None

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "https://users.roblox.com/v1/usernames/users",
                json={
                    "usernames": [username],
                    "excludeBannedUsers": False
                }
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            results = data.get("data", [])
            if not results:
                return None

            user = results[0]
            user_id = user.get("id")
            real_username = user.get("name")
            display_name = user.get("displayName", real_username)

            if not user_id:
                return None

            avatar_url = ""
            async with session.get(
                f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false"
            ) as resp:
                if resp.status == 200:
                    thumb_data = await resp.json()
                    thumb_items = thumb_data.get("data", [])
                    if thumb_items:
                        avatar_url = thumb_items[0].get("imageUrl", "")

            return {
                "user_id": user_id,
                "username": real_username,
                "display_name": display_name,
                "profile_url": f"https://www.roblox.com/users/{user_id}/profile",
                "avatar_url": avatar_url
            }
        except Exception:
            return None


class VerificationRequestModal(discord.ui.Modal, title="Verification Request"):
    def __init__(self):
        super().__init__(timeout=300)

        self.roblox_input = discord.ui.TextInput(
            label="Roblox Username (Optional)",
            placeholder="Enter username or N/A",
            required=False,
            max_length=50
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

        roblox_value = str(self.roblox_input.value).strip() or "N/A"
        notes = str(self.notes_input.value).strip() or "N/A"
        roblox_data = await roblox_lookup(roblox_value)

        embed = build_embed(
            "approval",
            guild=interaction.guild,
            user=interaction.user,
            roblox_username=roblox_value,
            notes=notes
        )

        embed.clear_fields()
        embed.add_field(name="User ID", value=str(interaction.user.id), inline=False)
        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(interaction.user.created_at, style="F"),
            inline=False
        )
        embed.add_field(name="Status", value="Pending review by staff", inline=False)

        if roblox_data:
            embed.add_field(
                name="Roblox Account",
                value=(
                    f"**Username:** {roblox_data['username']}\n"
                    f"**Display Name:** {roblox_data['display_name']}\n"
                    f"**User ID:** {roblox_data['user_id']}\n"
                    f"**Profile:** {roblox_data['profile_url']}"
                ),
                inline=False
            )
            if roblox_data["avatar_url"]:
                embed.set_thumbnail(url=roblox_data["avatar_url"])
        else:
            if roblox_value.upper() != "N/A":
                embed.add_field(name="Roblox Account", value=roblox_value, inline=False)

        if notes.upper() != "N/A":
            embed.add_field(name="Notes", value=notes, inline=False)

        content = None
        if roblox_data:
            content = f"Roblox profile to review: {roblox_data['profile_url']}"

        await approval_channel.send(
            content=content,
            embed=embed,
            view=ApprovalView(
                interaction.user.id,
                roblox_value,
                notes,
                roblox_data["profile_url"] if roblox_data else None
            )
        )

        await interaction.response.send_message("Your request has been sent to staff for review.", ephemeral=True)


class ApprovalView(discord.ui.View):
    def __init__(
        self,
        target_user_id: int,
        roblox_username: str = "N/A",
        notes: str = "N/A",
        roblox_profile_url: Optional[str] = None
    ):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        self.roblox_username = roblox_username
        self.notes = notes
        self.roblox_profile_url = roblox_profile_url

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

        me = interaction.guild.me
        if me is None or me.top_role <= role:
            return await interaction.response.send_message(
                "My bot role must be higher than the approved role.",
                ephemeral=True
            )

        try:
            await member.add_roles(role, reason=f"Approved by {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I can't assign that role. Check permissions and role order.",
                ephemeral=True
            )

        dm_embed = build_embed(
            "approved_dm",
            guild=interaction.guild,
            user=member,
            roblox_username=self.roblox_username,
            notes=self.notes,
            staff_mention=interaction.user.mention,
            role_name=role.name
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

        if self.roblox_profile_url:
            log_embed.add_field(name="Roblox Profile", value=self.roblox_profile_url, inline=False)

        await send_log(interaction.guild, embed=log_embed)

        for child in self.children:
            child.disabled = True

        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

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
            notes=self.notes,
            staff_mention=interaction.user.mention
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

        if self.roblox_profile_url:
            log_embed.add_field(name="Roblox Profile", value=self.roblox_profile_url, inline=False)

        await send_log(interaction.guild, embed=log_embed)

        for child in self.children:
            child.disabled = True

        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.response.send_message(f"Declined {member.mention}. Kick: {kicked}", ephemeral=True)


class GetRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get Roles", style=discord.ButtonStyle.success, custom_id="get_roles_button")
    async def get_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        await interaction.response.send_modal(VerificationRequestModal())


class SetupModal(discord.ui.Modal, title="Setup Configuration"):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

        self.verify_channel_input = discord.ui.TextInput(
            label="Verify Channel ID",
            default=str(config["verify_channel_id"]) if config.get("verify_channel_id") else "",
            placeholder="Paste channel ID",
            required=True,
            max_length=30
        )
        self.approval_channel_input = discord.ui.TextInput(
            label="Approval Channel ID",
            default=str(config["approval_channel_id"]) if config.get("approval_channel_id") else "",
            placeholder="Paste channel ID",
            required=True,
            max_length=30
        )
        self.logs_channel_input = discord.ui.TextInput(
            label="Logs Channel ID",
            default=str(config["logs_channel_id"]) if config.get("logs_channel_id") else "",
            placeholder="Paste channel ID",
            required=True,
            max_length=30
        )
        self.role_input = discord.ui.TextInput(
            label="Approved Role ID",
            default=str(config["approved_role_id"]) if config.get("approved_role_id") else "",
            placeholder="Paste role ID",
            required=True,
            max_length=30
        )
        self.kick_input = discord.ui.TextInput(
            label="Kick on Decline (true/false)",
            default=str(config.get("kick_on_decline", True)).lower(),
            placeholder="true or false",
            required=True,
            max_length=10
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


class EditEmbedMainModal(discord.ui.Modal):
    def __init__(self, kind: str):
        super().__init__(title=f"Edit {kind} Embed", timeout=300)
        self.kind = kind
        current = config["embeds"][kind]

        self.title_input = discord.ui.TextInput(
            label="Title",
            default=current.get("title", "")[:100],
            max_length=100,
            required=True
        )
        self.desc_input = discord.ui.TextInput(
            label="Description",
            default=current.get("description", "")[:4000],
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True
        )
        self.color_input = discord.ui.TextInput(
            label="Color Hex",
            default=current.get("color", "5865F2")[:20],
            placeholder="5865F2",
            max_length=20,
            required=False
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer",
            default=current.get("footer", "")[:200],
            max_length=200,
            required=False
        )
        self.image_input = discord.ui.TextInput(
            label="Image / GIF URL",
            default=current.get("image_url", "")[:400],
            placeholder="https://example.com/image.gif",
            max_length=400,
            required=False
        )

        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.color_input)
        self.add_item(self.footer_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        saved_data = {
            "title": str(self.title_input.value),
            "description": str(self.desc_input.value),
            "color": str(self.color_input.value or "5865F2").replace("#", ""),
            "footer": str(self.footer_input.value),
            "image_url": str(self.image_input.value).strip()
        }
        await interaction.response.send_modal(EditEmbedThumbnailModal(self.kind, saved_data))


class EditEmbedThumbnailModal(discord.ui.Modal):
    def __init__(self, kind: str, saved_data: dict):
        super().__init__(title=f"{kind} Thumbnail", timeout=300)
        self.kind = kind
        self.saved_data = saved_data

        self.thumb_input = discord.ui.TextInput(
            label="Thumbnail URL",
            default=config["embeds"][kind].get("thumbnail_url", "")[:400],
            placeholder="https://example.com/thumb.png",
            max_length=400,
            required=False
        )
        self.add_item(self.thumb_input)

    async def on_submit(self, interaction: discord.Interaction):
        data = config["embeds"][self.kind]
        data["title"] = self.saved_data["title"]
        data["description"] = self.saved_data["description"]
        data["color"] = self.saved_data["color"]
        data["footer"] = self.saved_data["footer"]
        data["image_url"] = self.saved_data["image_url"]
        data["thumbnail_url"] = str(self.thumb_input.value).strip()
        save_config(config)

        preview = build_embed(
            self.kind,
            guild=interaction.guild,
            user=interaction.user if isinstance(interaction.user, discord.Member) else None,
            roblox_username="N/A",
            notes="N/A"
        )

        await interaction.response.send_message(
            f"Updated **{self.kind}** embed.",
            embed=preview,
            ephemeral=True
        )


class EditSelect(discord.ui.Select):
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
        await interaction.response.send_modal(EditEmbedMainModal(self.values[0]))


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


class EditHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(EditSelect())

    @discord.ui.button(label="Preview Current Embeds", style=discord.ButtonStyle.secondary)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        embeds = [
            build_embed("panel", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None),
            build_embed("approval", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None, roblox_username="ExampleUser", notes="Example note"),
            build_embed("approved_dm", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None, staff_mention=interaction.user.mention, role_name="Verified"),
            build_embed("declined_dm", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None),
        ]
        await interaction.response.send_message("Current embed previews:", embeds=embeds, ephemeral=True)

    @discord.ui.button(label="Send / Refresh Panel", style=discord.ButtonStyle.success)
    async def panel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await send_or_refresh_panel(interaction)


@bot.tree.command(name="setup", description="Setup channels, role, and kick settings.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_command(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Guild only.", ephemeral=True)

    await interaction.response.send_modal(SetupModal(interaction.guild))


@bot.tree.command(name="edit", description="Edit embeds and refresh panel.")
@app_commands.checks.has_permissions(administrator=True)
async def edit_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Pick what you want to edit.",
        view=EditHomeView(),
        ephemeral=True
    )


@setup_command.error
@edit_command.error
async def command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        if interaction.response.is_done():
            await interaction.followup.send("You need Administrator permission.", ephemeral=True)
        else:
            await interaction.response.send_message("You need Administrator permission.", ephemeral=True)
        return

    logging.exception("Command error: %s", error)
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
