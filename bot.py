import os
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

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
    "approved_role_ids": [],
    "staff_mention_role_id": None,
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
            "description": "{notify_staff}\n{user_mention} requested roles in **{guild_name}**.",
            "color": "FEE75C",
            "footer": "Use the buttons below to approve or decline.",
            "image_url": "",
            "thumbnail_url": ""
        },
        "approved_dm": {
            "title": "You were approved",
            "description": "Hello {user_mention}, your verification in **{guild_name}** was approved by {staff_mention}. You received: **{role_names}**.",
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

    if "approved_role_ids" not in data:
        old_role = data.get("approved_role_id")
        data["approved_role_ids"] = [old_role] if old_role else []

    if "staff_mention_role_id" not in data:
        data["staff_mention_role_id"] = None

    if "embeds" not in data:
        data["embeds"] = deep_copy(DEFAULT_CONFIG["embeds"])

    for embed_name, defaults in DEFAULT_CONFIG["embeds"].items():
        if embed_name not in data["embeds"]:
            data["embeds"][embed_name] = deep_copy(defaults)
        else:
            for key, value in defaults.items():
                if key not in data["embeds"][embed_name]:
                    data["embeds"][embed_name][key] = value

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
    role_names: Optional[str] = None,
    notify_staff: Optional[str] = None,
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
    text = text.replace("{role_names}", role_names or "Verified")
    text = text.replace("{notify_staff}", notify_staff or "")

    return text


def build_embed(
    kind: str,
    guild: Optional[discord.Guild] = None,
    user: Optional[discord.Member] = None,
    roblox_username: Optional[str] = None,
    notes: Optional[str] = None,
    staff_mention: Optional[str] = None,
    role_names: Optional[str] = None,
    notify_staff: Optional[str] = None,
) -> discord.Embed:
    data = config["embeds"][kind]

    embed = discord.Embed(
        title=apply_placeholders(
            data["title"], guild, user, roblox_username, notes, staff_mention, role_names, notify_staff
        ),
        description=apply_placeholders(
            data["description"], guild, user, roblox_username, notes, staff_mention, role_names, notify_staff
        ),
        color=parse_color(data["color"])
    )

    footer = apply_placeholders(
        data.get("footer", ""), guild, user, roblox_username, notes, staff_mention, role_names, notify_staff
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
    if not config.get("approved_role_ids"):
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


async def roblox_lookup(username: str) -> Optional[Dict[str, Any]]:
    username = (username or "").strip()
    if not username:
        return None

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "https://users.roblox.com/v1/usernames/users",
                json={"usernames": [username], "excludeBannedUsers": False}
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
                f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png&isCircular=false"
            ) as resp:
                if resp.status == 200:
                    thumb_data = await resp.json()
                    thumb_items = thumb_data.get("data", [])
                    if thumb_items:
                        avatar_url = thumb_items[0].get("imageUrl", "")

            groups: List[Dict[str, Any]] = []
            try:
                async with session.get(
                    f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
                ) as resp:
                    if resp.status == 200:
                        groups_data = await resp.json()
                        raw_groups = groups_data.get("data", [])
                        for item in raw_groups[:25]:
                            group = item.get("group", {})
                            role = item.get("role", {})
                            gid = group.get("id")
                            gname = group.get("name", "Unknown Group")
                            role_name = role.get("name", "Member")
                            if gid:
                                groups.append({
                                    "id": gid,
                                    "name": gname,
                                    "role_name": role_name,
                                    "url": f"https://www.roblox.com/communities/{gid}/group"
                                })
            except Exception:
                groups = []

            return {
                "user_id": user_id,
                "username": real_username,
                "display_name": display_name,
                "profile_url": f"https://www.roblox.com/users/{user_id}/profile",
                "avatar_url": avatar_url,
                "groups": groups
            }
        except Exception:
            return None


class GroupSelect(discord.ui.Select):
    def __init__(self, groups: List[Dict[str, Any]]):
        options = []
        for group in groups[:25]:
            options.append(
                discord.SelectOption(
                    label=group["name"][:100],
                    description=f"Role: {group['role_name']}"[:100],
                    value=str(group["id"])
                )
            )

        super().__init__(
            placeholder="View Roblox communities",
            min_values=1,
            max_values=1,
            options=options,
            row=1
        )
        self.groups = {str(g["id"]): g for g in groups[:25]}

    async def callback(self, interaction: discord.Interaction):
        group = self.groups.get(self.values[0])
        if not group:
            return await interaction.response.send_message("Group not found.", ephemeral=True)

        embed = discord.Embed(
            title=group["name"],
            description=f"**Role:** {group['role_name']}\n**Link:** {group['url']}",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ApprovalView(discord.ui.View):
    def __init__(
        self,
        target_user_id: int,
        roblox_username: str,
        notes: str = "N/A",
        roblox_profile_url: Optional[str] = None,
        discord_profile_url: Optional[str] = None,
        roblox_groups: Optional[List[Dict[str, Any]]] = None
    ):
        super().__init__(timeout=604800)
        self.target_user_id = target_user_id
        self.roblox_username = roblox_username
        self.notes = notes
        self.roblox_profile_url = roblox_profile_url
        self.discord_profile_url = discord_profile_url
        self.roblox_groups = roblox_groups or []

        if self.roblox_profile_url:
            self.add_item(
                discord.ui.Button(
                    label="Roblox Profile",
                    style=discord.ButtonStyle.link,
                    url=self.roblox_profile_url,
                    row=0
                )
            )

        if self.discord_profile_url:
            self.add_item(
                discord.ui.Button(
                    label="Discord Profile",
                    style=discord.ButtonStyle.link,
                    url=self.discord_profile_url,
                    row=0
                )
            )

        if self.roblox_groups:
            self.add_item(GroupSelect(self.roblox_groups))

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="verify_approve", row=2)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("You need Manage Roles.", ephemeral=True)

        member = interaction.guild.get_member(self.target_user_id)
        if not member:
            return await interaction.response.send_message("User not found.", ephemeral=True)

        role_ids = config.get("approved_role_ids", [])[:10]
        roles = []
        for rid in role_ids:
            role = interaction.guild.get_role(rid)
            if role:
                roles.append(role)

        if not roles:
            return await interaction.response.send_message("No approved roles configured.", ephemeral=True)

        me = interaction.guild.me
        if me is None:
            return await interaction.response.send_message("Bot member not found.", ephemeral=True)

        for role in roles:
            if me.top_role <= role:
                return await interaction.response.send_message(
                    f"My bot role must be higher than {role.mention}.",
                    ephemeral=True
                )

        try:
            await member.add_roles(*roles, reason=f"Approved by {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I can't assign one of the roles. Check permissions and role order.",
                ephemeral=True
            )

        role_names = ", ".join(role.name for role in roles)

        dm_embed = build_embed(
            "approved_dm",
            guild=interaction.guild,
            user=member,
            roblox_username=self.roblox_username,
            notes=self.notes,
            staff_mention=interaction.user.mention,
            role_names=role_names
        )

        try:
            await member.send(embed=dm_embed)
        except Exception:
            pass

        for child in self.children:
            child.disabled = True

        try:
            if interaction.message.embeds:
                old_embed = interaction.message.embeds[0].copy()
                kept_fields = []
                for field in old_embed.fields:
                    if field.name.lower() == "status":
                        continue
                    kept_fields.append(field)

                old_embed.clear_fields()
                for field in kept_fields:
                    old_embed.add_field(name=field.name, value=field.value, inline=field.inline)
                old_embed.add_field(name="Status", value=f"Approved by {interaction.user.mention}", inline=False)
                await interaction.message.edit(embed=old_embed, view=self)
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

        await interaction.response.send_message(f"Approved {member.mention}.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="verify_decline", row=2)
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

        for child in self.children:
            child.disabled = True

        try:
            if interaction.message.embeds:
                old_embed = interaction.message.embeds[0].copy()
                kept_fields = []
                for field in old_embed.fields:
                    if field.name.lower() == "status":
                        continue
                    kept_fields.append(field)

                old_embed.clear_fields()
                for field in kept_fields:
                    old_embed.add_field(name=field.name, value=field.value, inline=field.inline)
                old_embed.add_field(name="Status", value=f"Declined by {interaction.user.mention}", inline=False)
                await interaction.message.edit(embed=old_embed, view=self)
        except Exception:
            pass

        log_embed = discord.Embed(
            title="Declined",
            description=f"{member.mention} was declined by {interaction.user.mention}.\nKick executed: **{kicked}**",
            color=discord.Color.red()
        )
        if self.roblox_profile_url:
            log_embed.add_field(name="Roblox Profile", value=self.roblox_profile_url, inline=False)
        await send_log(interaction.guild, embed=log_embed)

        await interaction.response.send_message(f"Declined {member.mention}. Kick: {kicked}", ephemeral=True)


class VerificationRequestModal(discord.ui.Modal, title="Verification Request"):
    def __init__(self):
        super().__init__(timeout=300)

        self.roblox_input = discord.ui.TextInput(
            label="Roblox Username",
            placeholder="Enter your Roblox username",
            required=True,
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

        roblox_value = str(self.roblox_input.value).strip()
        notes = str(self.notes_input.value).strip() or "N/A"

        if not roblox_value:
            return await interaction.response.send_message("Roblox username is required.", ephemeral=True)

        roblox_data = await roblox_lookup(roblox_value)
        if not roblox_data:
            return await interaction.response.send_message("Roblox account not found. Check the username and try again.", ephemeral=True)

        notify_staff = ""
        notify_role_id = config.get("staff_mention_role_id")
        if notify_role_id:
            notify_role = interaction.guild.get_role(notify_role_id)
            if notify_role:
                notify_staff = notify_role.mention

        embed = build_embed(
            "approval",
            guild=interaction.guild,
            user=interaction.user,
            roblox_username=roblox_value,
            notes=notes,
            notify_staff=notify_staff
        )

        embed.clear_fields()
        embed.add_field(name="User ID", value=str(interaction.user.id), inline=False)
        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(interaction.user.created_at, style="F"),
            inline=False
        )
        embed.add_field(name="Status", value="Pending review by staff", inline=False)
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

        if notes.upper() != "N/A":
            embed.add_field(name="Notes", value=notes, inline=False)

        if interaction.user.display_avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)

        if roblox_data["avatar_url"]:
            embed.set_image(url=roblox_data["avatar_url"])
        else:
            custom_img = config["embeds"]["approval"].get("image_url", "").strip()
            if custom_img:
                embed.set_image(url=custom_img)

        view = ApprovalView(
            target_user_id=interaction.user.id,
            roblox_username=roblox_value,
            notes=notes,
            roblox_profile_url=roblox_data["profile_url"],
            discord_profile_url=f"https://discord.com/users/{interaction.user.id}",
            roblox_groups=roblox_data.get("groups", [])
        )

        await approval_channel.send(content=notify_staff or None, embed=embed, view=view)
        await interaction.response.send_message("Your request has been sent to staff for review.", ephemeral=True)


class GetRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get Roles", style=discord.ButtonStyle.success, custom_id="get_roles_button")
    async def get_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)
        await interaction.response.send_modal(VerificationRequestModal())


class SetupState:
    def __init__(self):
        self.verify_channel_id = config.get("verify_channel_id")
        self.approval_channel_id = config.get("approval_channel_id")
        self.logs_channel_id = config.get("logs_channel_id")
        self.approved_role_ids = config.get("approved_role_ids", [])[:10]
        self.staff_mention_role_id = config.get("staff_mention_role_id")
        self.kick_on_decline = config.get("kick_on_decline", True)


class VerifyChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select verify channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, SetupView):
            self.view.state.verify_channel_id = self.values[0].id
            await interaction.response.edit_message(embed=self.view.build_summary_embed(), view=self.view)


class ApprovalChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select approval channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, SetupView):
            self.view.state.approval_channel_id = self.values[0].id
            await interaction.response.edit_message(embed=self.view.build_summary_embed(), view=self.view)


class LogsChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select logs channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, SetupView):
            self.view.state.logs_channel_id = self.values[0].id
            await interaction.response.edit_message(embed=self.view.build_summary_embed(), view=self.view)


class ApprovedRolesSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select approved roles",
            min_values=1,
            max_values=10
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, SetupView):
            self.view.state.approved_role_ids = [role.id for role in self.values[:10]]
            await interaction.response.edit_message(embed=self.view.build_summary_embed(), view=self.view)


class StaffMentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select staff notify role",
            min_values=0,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, SetupView):
            self.view.state.staff_mention_role_id = self.values[0].id if self.values else None
            await interaction.response.edit_message(embed=self.view.build_summary_embed(), view=self.view)


class SetupView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=900)
        self.guild = guild
        self.state = SetupState()

        self.add_item(VerifyChannelSelect())
        self.add_item(ApprovalChannelSelect())
        self.add_item(LogsChannelSelect())
        self.add_item(ApprovedRolesSelect())
        self.add_item(StaffMentionRoleSelect())

    def build_summary_embed(self):
        verify_channel = self.guild.get_channel(self.state.verify_channel_id) if self.state.verify_channel_id else None
        approval_channel = self.guild.get_channel(self.state.approval_channel_id) if self.state.approval_channel_id else None
        logs_channel = self.guild.get_channel(self.state.logs_channel_id) if self.state.logs_channel_id else None
        notify_role = self.guild.get_role(self.state.staff_mention_role_id) if self.state.staff_mention_role_id else None

        role_mentions = []
        for rid in self.state.approved_role_ids:
            role = self.guild.get_role(rid)
            if role:
                role_mentions.append(role.mention)

        embed = discord.Embed(
            title="Setup Configuration",
            description="Choose the channels and roles below, then save.",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Verify Channel", value=verify_channel.mention if verify_channel else "Not set", inline=False)
        embed.add_field(name="Approval Channel", value=approval_channel.mention if approval_channel else "Not set", inline=False)
        embed.add_field(name="Logs Channel", value=logs_channel.mention if logs_channel else "Not set", inline=False)
        embed.add_field(name="Approved Roles", value=", ".join(role_mentions) if role_mentions else "Not set", inline=False)
        embed.add_field(name="Staff Notify Role", value=notify_role.mention if notify_role else "Not set", inline=False)
        embed.add_field(name="Kick on Decline", value=str(self.state.kick_on_decline), inline=False)
        return embed

    @discord.ui.button(label="Toggle Kick On Decline", style=discord.ButtonStyle.secondary, row=4)
    async def toggle_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.kick_on_decline = not self.state.kick_on_decline
        await interaction.response.edit_message(embed=self.build_summary_embed(), view=self)

    @discord.ui.button(label="Save Setup", style=discord.ButtonStyle.success, row=4)
    async def save_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.state.verify_channel_id:
            return await interaction.response.send_message("Please select a verify channel.", ephemeral=True)
        if not self.state.approval_channel_id:
            return await interaction.response.send_message("Please select an approval channel.", ephemeral=True)
        if not self.state.logs_channel_id:
            return await interaction.response.send_message("Please select a logs channel.", ephemeral=True)
        if not self.state.approved_role_ids:
            return await interaction.response.send_message("Please select at least 1 approved role.", ephemeral=True)

        config["verify_channel_id"] = self.state.verify_channel_id
        config["approval_channel_id"] = self.state.approval_channel_id
        config["logs_channel_id"] = self.state.logs_channel_id
        config["approved_role_ids"] = self.state.approved_role_ids[:10]
        config["staff_mention_role_id"] = self.state.staff_mention_role_id
        config["kick_on_decline"] = self.state.kick_on_decline
        save_config(config)

        await interaction.response.edit_message(content="Setup saved.", embed=self.build_summary_embed(), view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=4)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Setup panel closed.", embed=self.build_summary_embed(), view=self)


class EditTextModal(discord.ui.Modal):
    def __init__(self, kind: str):
        super().__init__(title=f"Edit {kind} Text", timeout=300)
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

        preview = build_embed(
            self.kind,
            guild=interaction.guild,
            user=interaction.user if isinstance(interaction.user, discord.Member) else None,
            roblox_username="ExampleUser",
            notes="Example note",
            staff_mention=interaction.user.mention if interaction.user else "Staff",
            role_names="Role 1, Role 2",
            notify_staff="@Staff"
        )
        await interaction.response.send_message(
            f"Updated **{self.kind}** text settings.",
            embed=preview,
            ephemeral=True
        )


class EditMediaModal(discord.ui.Modal):
    def __init__(self, kind: str):
        super().__init__(title=f"Edit {kind} Media", timeout=300)
        self.kind = kind
        current = config["embeds"][kind]

        self.image_input = discord.ui.TextInput(
            label="Image / GIF URL",
            default=current.get("image_url", "")[:400],
            placeholder="https://example.com/image.gif",
            max_length=400,
            required=False
        )
        self.thumb_input = discord.ui.TextInput(
            label="Thumbnail URL",
            default=current.get("thumbnail_url", "")[:400],
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
            user=interaction.user if isinstance(interaction.user, discord.Member) else None,
            roblox_username="ExampleUser",
            notes="Example note",
            staff_mention=interaction.user.mention if interaction.user else "Staff",
            role_names="Role 1, Role 2",
            notify_staff="@Staff"
        )
        await interaction.response.send_message(
            f"Updated **{self.kind}** media settings.",
            embed=preview,
            ephemeral=True
        )


class EditEmbedTargetSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Panel Embed", value="panel"),
            discord.SelectOption(label="Approval Embed", value="approval"),
            discord.SelectOption(label="Approved DM Embed", value="approved_dm"),
            discord.SelectOption(label="Declined DM Embed", value="declined_dm"),
        ]
        super().__init__(
            placeholder="Choose embed",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, EditHomeView):
            self.view.current_kind = self.values[0]
            await interaction.response.edit_message(
                content=f"Selected: **{self.values[0]}**",
                view=self.view
            )


class EditHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.current_kind = "panel"
        self.add_item(EditEmbedTargetSelect())

    @discord.ui.button(label="Edit Text", style=discord.ButtonStyle.primary, row=1)
    async def edit_text_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditTextModal(self.current_kind))

    @discord.ui.button(label="Edit Image / Thumbnail", style=discord.ButtonStyle.secondary, row=1)
    async def edit_media_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditMediaModal(self.current_kind))

    @discord.ui.button(label="Preview Current Embeds", style=discord.ButtonStyle.secondary, row=2)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Guild only.", ephemeral=True)

        embeds = [
            build_embed("panel", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None),
            build_embed("approval", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None, roblox_username="ExampleUser", notes="Example note", notify_staff="@Staff"),
            build_embed("approved_dm", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None, staff_mention=interaction.user.mention, role_names="Role 1, Role 2"),
            build_embed("declined_dm", guild=interaction.guild, user=interaction.user if isinstance(interaction.user, discord.Member) else None),
        ]
        await interaction.response.send_message("Current embed previews:", embeds=embeds, ephemeral=True)

    @discord.ui.button(label="Send / Refresh Panel", style=discord.ButtonStyle.success, row=2)
    async def panel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await send_or_refresh_panel(interaction)


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


@bot.tree.command(name="setup", description="Setup channels, roles, and kick settings.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_command(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Guild only.", ephemeral=True)

    view = SetupView(interaction.guild)
    await interaction.response.send_message(
        content="Pick your channels and roles below.",
        embed=view.build_summary_embed(),
        view=view,
        ephemeral=True
    )


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
