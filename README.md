# Vaultcord Manual Review Verification Bot

Simple Discord verification bot for this flow:

1. User clicks the website verify button.
2. User finishes website verification outside Discord.
3. User clicks `Done / Skip Roblox`.
4. Bot sends the request to a mod logs channel.
5. Staff clicks `Approve` or `Decline / Kick`.
6. Approve gives the verified role and removes unverified.
7. Decline kicks the member.

## Features

- Auto unverified role on member join
- Mod review buttons in logs channel
- Approve = verified role
- Decline = kick
- Custom verify URL
- Custom panel title, description, and button labels
- Per-server settings stored in SQLite
- No Roblox connector inside this bot

## Railway Variables

Use these in Railway:

- `DISCORD_TOKEN`
- `DATABASE_PATH` (optional, default `bot.db`)
- `DEFAULT_VERIFY_URL` (optional)
- `DEFAULT_PANEL_TITLE` (optional)
- `DEFAULT_PANEL_DESCRIPTION` (optional)
- `DEFAULT_WEBSITE_BUTTON` (optional)
- `DEFAULT_DONE_BUTTON` (optional)
- `DEFAULT_UNVERIFIED_ROLE_NAME` (optional)
- `DEFAULT_VERIFIED_ROLE_NAME` (optional)

## Required Bot Permissions

Give the bot these permissions:

- Manage Roles
- Kick Members
- Send Messages
- View Channels
- Read Message History

Also enable **Server Members Intent** in the Discord Developer Portal.

## Slash Commands

- `/roles` → set unverified and verified roles
- `/set_logs` → set staff logs channel
- `/set_verify_channel` → set panel channel
- `/set_verify_url` → set your verify website URL
- `/set_message` → change panel title, description, button labels
- `/setup_panel` → send the verify panel
- `/config` → show current config

## Recommended Setup Order

1. Invite the bot
2. Run `/roles`
3. Run `/set_logs`
4. Run `/set_verify_channel`
5. Run `/set_verify_url`
6. Run `/set_message`
7. Run `/setup_panel`

## Start Command

```bash
python bot.py
```
