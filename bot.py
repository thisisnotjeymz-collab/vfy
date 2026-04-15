import os
import json
import sqlite3
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


DB_PATH = os.getenv("DATABASE_PATH", "verification_bot.db")
BOT_PREFIX = os.getenv("BOT_PREFIX", "!")
DEFAULT_UNVERIFIED_ROLE_NAME = os.getenv("DEFAULT_UNVERIFIED_ROLE_NAME", "Unverified")
DEFAULT_VERIFIED_ROLE_NAME = os.getenv("DEFAULT_VERIFIED_ROLE_NAME", "Verified")
DEFAULT_VERIFICATION_CHANNEL_NAME = os.getenv("DEFAULT_VERIFICATION_CHANNEL_NAME", "verify")
DEFAULT_NICKNAME_SOURCE = os.getenv("DEFAULT_NICKNAME_SOURCE", "discord")
ROLE_PREFIX = os.getenv("GAME_ROLE_PREFIX", "Game")
AUTO_CREATE_GAME_ROLES = os.getenv("AUTO_CREATE_GAME_ROLES", "true").lower() == "true"
SYNC_ON_STARTUP = os.getenv("SYNC_ON_STARTUP", "true").lower() == "true"
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            verification_channel_id INTEGER,
            unverified_role_id INTEGER,
            verified_role_id INTEGER,
            default_nickname_source TEXT DEFAULT 'discord',
            auto_create_game_roles INTEGER DEFAULT 1,
            remove_unverified_on_verify INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS user_verifications (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            verified INTEGER DEFAULT 0,
            nickname_source TEXT,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS game_connections (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            external_id TEXT,
            display_name TEXT,
            extra_json TEXT,
            PRIMARY KEY (guild_id, user_id, game)
        );

        CREATE TABLE IF NOT EXISTS roblox_group_binds (
            guild_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            min_rank INTEGER NOT NULL DEFAULT 1,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, group_id, role_id)
        );
        """
    )
    conn.commit()
    conn.close()


init_db()

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)


@dataclass
class GameProfile:
    game: str
    external_id: str
    display_name: str
    extra: Dict[str, Any]


class Database:
    @staticmethod
    def ensure_guild(guild_id: int) -> None:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO guild_settings (guild_id, default_nickname_source, auto_create_game_roles)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO NOTHING
            """,
            (guild_id, DEFAULT_NICKNAME_SOURCE, 1 if AUTO_CREATE_GAME_ROLES else 0),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_guild_settings(guild_id: int) -> sqlite3.Row:
        Database.ensure_guild(guild_id)
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
        conn.close()
        return row

    @staticmethod
    def update_guild_setting(guild_id: int, field: str, value: Any) -> None:
        allowed = {
            "verification_channel_id",
            "unverified_role_id",
            "verified_role_id",
            "default_nickname_source",
            "auto_create_game_roles",
            "remove_unverified_on_verify",
        }
        if field not in allowed:
            raise ValueError("Invalid guild setting field")
        Database.ensure_guild(guild_id)
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(f"UPDATE guild_settings SET {field} = ? WHERE guild_id = ?", (value, guild_id))
        conn.commit()
        conn.close()

    @staticmethod
    def set_verified(guild_id: int, user_id: int, verified: bool) -> None:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_verifications (guild_id, user_id, verified)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET verified = excluded.verified
            """,
            (guild_id, user_id, 1 if verified else 0),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def set_nickname_source(guild_id: int, user_id: int, source: str) -> None:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_verifications (guild_id, user_id, verified, nickname_source)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET nickname_source = excluded.nickname_source
            """,
            (guild_id, user_id, source),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_user_verification(guild_id: int, user_id: int) -> Optional[sqlite3.Row]:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM user_verifications WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cur.fetchone()
        conn.close()
        return row

    @staticmethod
    def save_game_connection(guild_id: int, user_id: int, profile: GameProfile) -> None:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO game_connections (guild_id, user_id, game, external_id, display_name, extra_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, game)
            DO UPDATE SET external_id = excluded.external_id,
                          display_name = excluded.display_name,
                          extra_json = excluded.extra_json
            """,
            (
                guild_id,
                user_id,
                profile.game,
                profile.external_id,
                profile.display_name,
                json.dumps(profile.extra),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_game_connection(guild_id: int, user_id: int, game: str) -> Optional[sqlite3.Row]:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM game_connections WHERE guild_id = ? AND user_id = ? AND game = ?",
            (guild_id, user_id, game),
        )
        row = cur.fetchone()
        conn.close()
        return row

    @staticmethod
    def get_user_connections(guild_id: int, user_id: int) -> List[sqlite3.Row]:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM game_connections WHERE guild_id = ? AND user_id = ? ORDER BY game ASC",
            (guild_id, user_id),
        )
        rows = cur.fetchall()
        conn.close()
        return rows

    @staticmethod
    def delete_game_connection(guild_id: int, user_id: int, game: str) -> None:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM game_connections WHERE guild_id = ? AND user_id = ? AND game = ?",
            (guild_id, user_id, game),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def add_roblox_group_bind(guild_id: int, group_id: int, min_rank: int, role_id: int) -> None:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO roblox_group_binds (guild_id, group_id, min_rank, role_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, group_id, role_id)
            DO UPDATE SET min_rank = excluded.min_rank
            """,
            (guild_id, group_id, min_rank, role_id),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_roblox_group_binds(guild_id: int) -> List[sqlite3.Row]:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM roblox_group_binds WHERE guild_id = ?", (guild_id,))
        rows = cur.fetchall()
        conn.close()
        return rows


class ExternalAPI:
    @staticmethod
    async def roblox_user_from_username(session: aiohttp.ClientSession, username: str) -> GameProfile:
        payload = {"usernames": [username], "excludeBannedUsers": False}
        async with session.post("https://users.roblox.com/v1/usernames/users", json=payload) as resp:
            data = await resp.json()
        users = data.get("data", [])
        if not users:
            raise ValueError("Roblox user not found.")
        user = users[0]
        return GameProfile(
            game="roblox",
            external_id=str(user["id"]),
            display_name=user.get("name", username),
            extra={"displayName": user.get("displayName"), "name": user.get("name")},
        )

    @staticmethod
    async def roblox_group_roles(session: aiohttp.ClientSession, user_id: str) -> List[Dict[str, Any]]:
        url = f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        return data.get("data", [])

    @staticmethod
    async def riot_account(session: aiohttp.ClientSession, game_name: str, tag_line: str, routing: str) -> GameProfile:
        if not RIOT_API_KEY:
            raise ValueError("RIOT_API_KEY is missing in Railway variables.")
        url = f"https://{routing}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        headers = {"X-Riot-Token": RIOT_API_KEY}
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                message = data.get("status", {}).get("message", "Riot account not found.")
                raise ValueError(message)
        puuid = data.get("puuid")
        return GameProfile(
            game="riot",
            external_id=puuid,
            display_name=f"{game_name}#{tag_line}",
            extra={"gameName": game_name, "tagLine": tag_line, "puuid": puuid, "routing": routing},
        )


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.user.guild_permissions.manage_guild)


async def ensure_role(guild: discord.Guild, role_name: str) -> discord.Role:
    existing = discord.utils.get(guild.roles, name=role_name)
    if existing:
        return existing
    return await guild.create_role(name=role_name, reason="Verification bot auto-created role")


async def apply_join_roles(member: discord.Member) -> None:
    settings = Database.get_guild_settings(member.guild.id)
    if settings["unverified_role_id"]:
        role = member.guild.get_role(settings["unverified_role_id"])
        if role and role not in member.roles:
            await member.add_roles(role, reason="Auto role for new member")


async def get_preferred_nickname(member: discord.Member) -> Optional[str]:
    settings = Database.get_guild_settings(member.guild.id)
    verification = Database.get_user_verification(member.guild.id, member.id)
    source = settings["default_nickname_source"]
    if verification and verification["nickname_source"]:
        source = verification["nickname_source"]

    if source == "discord":
        return None

    row = Database.get_game_connection(member.guild.id, member.id, source)
    if row:
        display_name = row["display_name"]
        return display_name[:32]
    return None


async def refresh_member_roles_and_nickname(member: discord.Member) -> List[str]:
    notes: List[str] = []
    settings = Database.get_guild_settings(member.guild.id)
    verification = Database.get_user_verification(member.guild.id, member.id)

    if verification and verification["verified"]:
        verified_role_id = settings["verified_role_id"]
        if verified_role_id:
            verified_role = member.guild.get_role(verified_role_id)
            if verified_role and verified_role not in member.roles:
                await member.add_roles(verified_role, reason="User verified")
                notes.append(f"Added verified role: {verified_role.name}")

        if settings["remove_unverified_on_verify"] and settings["unverified_role_id"]:
            unverified_role = member.guild.get_role(settings["unverified_role_id"])
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="User verified")
                notes.append(f"Removed unverified role: {unverified_role.name}")

    connections = Database.get_user_connections(member.guild.id, member.id)
    for row in connections:
        game = row["game"]
        display_name = row["display_name"]
        clean_game = game.upper() if game != "roblox" else "Roblox"
        role_name = f"{ROLE_PREFIX} | {clean_game}"
        if game in {"mobile_legends", "cod", "roblox", "league", "valorant"}:
            role_name = f"{clean_game} | Connected"

        if settings["auto_create_game_roles"]:
            role = discord.utils.get(member.guild.roles, name=role_name)
            if role is None:
                role = await member.guild.create_role(name=role_name, reason="Game connector role")
                notes.append(f"Created role: {role.name}")
            if role not in member.roles:
                await member.add_roles(role, reason=f"Connected {game} account")
                notes.append(f"Added role: {role.name}")

    roblox_row = Database.get_game_connection(member.guild.id, member.id, "roblox")
    if roblox_row:
        try:
            async with aiohttp.ClientSession() as session:
                group_roles = await ExternalAPI.roblox_group_roles(session, roblox_row["external_id"])
            binds = Database.get_roblox_group_binds(member.guild.id)
            group_rank_map = {g["group"]["id"]: g["role"]["rank"] for g in group_roles if g.get("group") and g.get("role")}
            for bind in binds:
                if group_rank_map.get(bind["group_id"], 0) >= bind["min_rank"]:
                    role = member.guild.get_role(bind["role_id"])
                    if role and role not in member.roles:
                        await member.add_roles(role, reason="Roblox group bind matched")
                        notes.append(f"Added Roblox bind role: {role.name}")
        except Exception:
            pass

    nickname = await get_preferred_nickname(member)
    if nickname and member.nick != nickname:
        try:
            await member.edit(nick=nickname, reason="Nickname source preference")
            notes.append(f"Nickname updated to: {nickname}")
        except discord.Forbidden:
            notes.append("Could not change nickname due to role hierarchy or permissions.")
    return notes


class SetupGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="setup", description="Server setup commands for the verification bot")

    @app_commands.command(name="channel", description="Set the verification channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        Database.update_guild_setting(interaction.guild.id, "verification_channel_id", channel.id)
        await interaction.response.send_message(f"Verification channel set to {channel.mention}.", ephemeral=True)

    @app_commands.command(name="roles", description="Set the unverified and verified roles")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def roles(
        self,
        interaction: discord.Interaction,
        unverified_role: Optional[discord.Role] = None,
        verified_role: Optional[discord.Role] = None,
    ):
        guild = interaction.guild
        if unverified_role is None:
            unverified_role = await ensure_role(guild, DEFAULT_UNVERIFIED_ROLE_NAME)
        if verified_role is None:
            verified_role = await ensure_role(guild, DEFAULT_VERIFIED_ROLE_NAME)

        Database.update_guild_setting(guild.id, "unverified_role_id", unverified_role.id)
        Database.update_guild_setting(guild.id, "verified_role_id", verified_role.id)
        await interaction.response.send_message(
            f"Roles saved. Unverified: {unverified_role.mention} | Verified: {verified_role.mention}",
            ephemeral=True,
        )

    @app_commands.command(name="defaults", description="Set default bot behavior for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        nickname_source="Default nickname source for verified users",
        auto_create_game_roles="Automatically create game connection roles",
        remove_unverified_on_verify="Remove unverified role after /verify",
    )
    async def defaults(
        self,
        interaction: discord.Interaction,
        nickname_source: str,
        auto_create_game_roles: bool = True,
        remove_unverified_on_verify: bool = True,
    ):
        Database.update_guild_setting(interaction.guild.id, "default_nickname_source", nickname_source)
        Database.update_guild_setting(interaction.guild.id, "auto_create_game_roles", 1 if auto_create_game_roles else 0)
        Database.update_guild_setting(interaction.guild.id, "remove_unverified_on_verify", 1 if remove_unverified_on_verify else 0)
        await interaction.response.send_message("Default settings updated.", ephemeral=True)


setup_group = SetupGroup()


@setup_group.defaults.autocomplete("nickname_source")
async def nickname_source_autocomplete(interaction: discord.Interaction, current: str):
    values = ["discord", "roblox", "league", "valorant", "mobile_legends", "cod"]
    return [app_commands.Choice(name=v, value=v) for v in values if current.lower() in v.lower()][:25]


class ConnectGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="connect", description="Connect your game accounts")

    @app_commands.command(name="roblox", description="Connect a Roblox account by username")
    async def roblox(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with aiohttp.ClientSession() as session:
            profile = await ExternalAPI.roblox_user_from_username(session, username)
        Database.save_game_connection(interaction.guild.id, interaction.user.id, profile)
        notes = await refresh_member_roles_and_nickname(interaction.user)
        await interaction.followup.send(
            f"Roblox connected: **{profile.display_name}** (`{profile.external_id}`).\n" + ("\n".join(notes) if notes else "Done."),
            ephemeral=True,
        )

    @app_commands.command(name="league", description="Connect a League of Legends Riot ID")
    async def league(self, interaction: discord.Interaction, game_name: str, tag_line: str, routing: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with aiohttp.ClientSession() as session:
            riot_profile = await ExternalAPI.riot_account(session, game_name, tag_line, routing)
        riot_profile.game = "league"
        Database.save_game_connection(interaction.guild.id, interaction.user.id, riot_profile)
        notes = await refresh_member_roles_and_nickname(interaction.user)
        await interaction.followup.send(
            f"League connected: **{riot_profile.display_name}**.\n" + ("\n".join(notes) if notes else "Done."),
            ephemeral=True,
        )

    @app_commands.command(name="valorant", description="Connect a VALORANT Riot ID")
    async def valorant(self, interaction: discord.Interaction, game_name: str, tag_line: str, routing: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with aiohttp.ClientSession() as session:
            riot_profile = await ExternalAPI.riot_account(session, game_name, tag_line, routing)
        riot_profile.game = "valorant"
        Database.save_game_connection(interaction.guild.id, interaction.user.id, riot_profile)
        notes = await refresh_member_roles_and_nickname(interaction.user)
        await interaction.followup.send(
            f"VALORANT connected: **{riot_profile.display_name}**.\n" + ("\n".join(notes) if notes else "Done."),
            ephemeral=True,
        )

    @app_commands.command(name="mobile_legends", description="Save your Mobile Legends details")
    async def mobile_legends(
        self,
        interaction: discord.Interaction,
        player_id: str,
        ign: str,
        server_id: Optional[str] = None,
    ):
        profile = GameProfile(
            game="mobile_legends",
            external_id=player_id,
            display_name=ign,
            extra={"server_id": server_id, "ign": ign},
        )
        Database.save_game_connection(interaction.guild.id, interaction.user.id, profile)
        await interaction.response.defer(ephemeral=True, thinking=True)
        notes = await refresh_member_roles_and_nickname(interaction.user)
        await interaction.followup.send(
            f"Mobile Legends connected: **{ign}** (`{player_id}`).\n" + ("\n".join(notes) if notes else "Done."),
            ephemeral=True,
        )

    @app_commands.command(name="cod", description="Save your Call of Duty details")
    async def cod(self, interaction: discord.Interaction, username: str, platform: str):
        profile = GameProfile(
            game="cod",
            external_id=username,
            display_name=username,
            extra={"platform": platform},
        )
        Database.save_game_connection(interaction.guild.id, interaction.user.id, profile)
        await interaction.response.defer(ephemeral=True, thinking=True)
        notes = await refresh_member_roles_and_nickname(interaction.user)
        await interaction.followup.send(
            f"Call of Duty connected: **{username}** on **{platform}**.\n" + ("\n".join(notes) if notes else "Done."),
            ephemeral=True,
        )


connect_group = ConnectGroup()


@connect_group.league.autocomplete("routing")
@connect_group.valorant.autocomplete("routing")
async def riot_routing_autocomplete(interaction: discord.Interaction, current: str):
    values = ["americas", "asia", "europe"]
    return [app_commands.Choice(name=v, value=v) for v in values if current.lower() in v.lower()][:25]


class RobloxGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="roblox", description="Roblox-specific helper commands")

    @app_commands.command(name="community_connect", description="Refresh your Roblox community roles")
    async def community_connect(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        row = Database.get_game_connection(interaction.guild.id, interaction.user.id, "roblox")
        if not row:
            await interaction.followup.send("Connect your Roblox first with `/connect roblox`.", ephemeral=True)
            return
        notes = await refresh_member_roles_and_nickname(interaction.user)
        await interaction.followup.send("Roblox community sync done.\n" + ("\n".join(notes) if notes else "No changes."), ephemeral=True)

    @app_commands.command(name="community_roles_bind", description="Bind a Discord role to a Roblox group rank")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def community_roles_bind(
        self,
        interaction: discord.Interaction,
        group_id: int,
        min_rank: int,
        role: discord.Role,
    ):
        Database.add_roblox_group_bind(interaction.guild.id, group_id, min_rank, role.id)
        await interaction.response.send_message(
            f"Saved Roblox bind: group `{group_id}`, minimum rank `{min_rank}` -> {role.mention}",
            ephemeral=True,
        )


roblox_group = RobloxGroup()


@bot.tree.command(name="verify", description="Verify your Discord account in this server")
async def verify(interaction: discord.Interaction):
    Database.set_verified(interaction.guild.id, interaction.user.id, True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    notes = await refresh_member_roles_and_nickname(interaction.user)
    await interaction.followup.send(
        "You are now verified in this server.\n" + ("\n".join(notes) if notes else "Done."),
        ephemeral=True,
    )


@bot.tree.command(name="update", description="Refresh your roles and nickname from saved game connections")
async def update(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    notes = await refresh_member_roles_and_nickname(interaction.user)
    await interaction.followup.send("Refresh complete.\n" + ("\n".join(notes) if notes else "No changes."), ephemeral=True)


@bot.tree.command(name="nickname_source", description="Choose what account the bot should use for your nickname")
@app_commands.describe(source="Only saved account sources can be used")
async def nickname_source(interaction: discord.Interaction, source: str):
    if source != "discord":
        row = Database.get_game_connection(interaction.guild.id, interaction.user.id, source)
        if not row:
            await interaction.response.send_message(f"You have not connected **{source}** yet.", ephemeral=True)
            return
    Database.set_nickname_source(interaction.guild.id, interaction.user.id, source)
    await interaction.response.defer(ephemeral=True, thinking=True)
    notes = await refresh_member_roles_and_nickname(interaction.user)
    await interaction.followup.send("Nickname source saved.\n" + ("\n".join(notes) if notes else "Done."), ephemeral=True)


@nickname_source.autocomplete("source")
async def nickname_source_choice_autocomplete(interaction: discord.Interaction, current: str):
    values = ["discord", "roblox", "league", "valorant", "mobile_legends", "cod"]
    return [app_commands.Choice(name=v, value=v) for v in values if current.lower() in v.lower()][:25]


@bot.tree.command(name="connections", description="View your saved connected accounts")
async def connections(interaction: discord.Interaction):
    rows = Database.get_user_connections(interaction.guild.id, interaction.user.id)
    if not rows:
        await interaction.response.send_message("You do not have any saved connections yet.", ephemeral=True)
        return
    embed = discord.Embed(title="Your connected accounts")
    for row in rows:
        embed.add_field(name=row["game"], value=f"{row['display_name']}\nID: {row['external_id']}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="disconnect", description="Remove a saved game connection")
async def disconnect(interaction: discord.Interaction, game: str):
    Database.delete_game_connection(interaction.guild.id, interaction.user.id, game)
    await interaction.response.send_message(f"Removed saved connection for **{game}**.", ephemeral=True)


@disconnect.autocomplete("game")
async def disconnect_game_autocomplete(interaction: discord.Interaction, current: str):
    values = ["roblox", "league", "valorant", "mobile_legends", "cod"]
    return [app_commands.Choice(name=v, value=v) for v in values if current.lower() in v.lower()][:25]


@bot.tree.command(name="setup_panel", description="Post a verification guide panel in the chosen channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_panel(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    channel = channel or interaction.channel
    embed = discord.Embed(
        title="Verification Center",
        description=(
            "Use `/verify` to verify your Discord account.\n"
            "Use `/connect roblox`, `/connect league`, `/connect valorant`, `/connect mobile_legends`, or `/connect cod` to save your game account.\n"
            "Use `/nickname_source` if you want the bot to use one of your connected accounts as your nickname.\n"
            "Use `/update` anytime to refresh your roles and nickname."
        ),
        color=discord.Color.blurple(),
    )
    await channel.send(embed=embed)
    await interaction.response.send_message(f"Verification panel sent to {channel.mention}.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    try:
        if SYNC_ON_STARTUP:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global application commands.")
    except Exception as exc:
        print(f"Failed to sync commands: {exc}")


@bot.event
async def on_member_join(member: discord.Member):
    Database.ensure_guild(member.guild.id)
    try:
        await apply_join_roles(member)
    except Exception as exc:
        print(f"Failed to apply join roles for {member.id}: {exc}")


async def bootstrap_defaults(guild: discord.Guild):
    Database.ensure_guild(guild.id)
    settings = Database.get_guild_settings(guild.id)

    if not settings["unverified_role_id"]:
        role = await ensure_role(guild, DEFAULT_UNVERIFIED_ROLE_NAME)
        Database.update_guild_setting(guild.id, "unverified_role_id", role.id)

    if not settings["verified_role_id"]:
        role = await ensure_role(guild, DEFAULT_VERIFIED_ROLE_NAME)
        Database.update_guild_setting(guild.id, "verified_role_id", role.id)


@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        await bootstrap_defaults(guild)
        channel = discord.utils.get(guild.text_channels, name=DEFAULT_VERIFICATION_CHANNEL_NAME)
        if channel:
            Database.update_guild_setting(guild.id, "verification_channel_id", channel.id)
    except Exception as exc:
        print(f"Guild bootstrap failed for {guild.id}: {exc}")


async def main():
    async with bot:
        bot.tree.add_command(setup_group)
        bot.tree.add_command(connect_group)
        bot.tree.add_command(roblox_group)
        await bot.start(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    asyncio.run(main())
