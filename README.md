# Discord Verification Bot for Railway

Clean version with a small command set:
- `/setup` - opens the setup UI
- `/customize` - opens embed customization UI
- `/panel` - sends or refreshes the verification panel
- `/settings` - shows current config

## Main flow
1. Admin runs `/setup`
2. Choose:
   - verify panel channel
   - approval channel
   - logs channel
   - approved role
   - kick on decline on/off
3. Edit panel text
4. Run `Send / Refresh Panel`
5. Users click **Get Roles**
6. Staff approve or decline
7. Approved users get the role and a DM
8. Declined users get a DM and can be auto-kicked

## Features
- Button-based verification panel
- Staff approval buttons
- Approved role is selectable in setup UI
- Custom embeds with title, description, color, footer, image URL, GIF URL, and thumbnail URL
- Per-guild saved config in `./data/config.json`
- Railway-ready

## Railway variables
Required:
- `DISCORD_TOKEN`

Recommended:
- `GUILD_ID` = your server ID for faster slash command sync

Optional:
- `DATA_DIR=/data`

## Railway notes
Use a Railway Volume if you want your saved config to stay after redeploys.
Mount the volume to `/data` and set:
- `DATA_DIR=/data`

## Required Discord bot permissions
- Manage Roles
- Kick Members
- Send Messages
- Embed Links
- Use Slash Commands

Also enable in Discord Developer Portal:
- Server Members Intent
- Message Content Intent is optional here, but safe to enable

## Install
`requirements.txt`:
- `discord.py>=2.4.0`

Start command:
```bash
python bot.py
```
