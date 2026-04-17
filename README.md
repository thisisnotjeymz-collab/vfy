# Discord Verification Approval Bot for Railway

A Discord bot with a **Get Roles** button.

Flow:
1. User clicks **Get Roles**
2. Bot sends the request to your **approval channel**
3. Staff clicks **Approve** or **Decline**
4. If approved, the bot gives the configured role and sends a DM embed
5. If declined, the bot sends a DM embed and can automatically kick the user
6. The bot also sends a log message in your logs channel

## Features
- Button-based verification panel
- Staff approval / decline buttons
- Auto-role on approve
- Optional auto-kick on decline
- Customizable DM embeds for approve and decline
- Customizable staff request embed
- Logs channel support
- Easy setup with slash commands
- Works on Railway

## Important Discord Permissions
Your bot should have these enabled in the Discord Developer Portal and server:
- **Server Members Intent** enabled in the bot page
- **Manage Roles** permission
- **Kick Members** permission
- **Send Messages**
- **Embed Links**
- **Use Slash Commands**
- **Read Message History**

Also make sure the bot's role is **higher than the role you want to give**.

## Railway Setup

### 1. Upload to GitHub
Create a new GitHub repo and upload these files.

### 2. Deploy on Railway
Create a new Railway project and deploy from your GitHub repo.

### 3. Add Variables
In Railway, add this variable:

- `DISCORD_TOKEN` = your bot token

### 4. Persistent Storage
This project stores its settings in `./data/config.json`.
If you want your settings to survive redeploys and restarts, attach a Railway **Volume** and mount it to:

`/app/data`

Railway says volumes provide persistent data for services, and mounting to the app path is the right way when your app writes to a relative folder like `./data`. citeturn674678search0turn674678search1

### 5. Start Command
Railway should detect the `Procfile`, but if needed use:

`python bot.py`

## Slash Commands
Run these in your Discord server:

### Basic setup
- `/set_approval_channel`
- `/set_logs_channel`
- `/set_approved_role`
- `/setup_panel`

### Optional setup
- `/set_kick_on_decline`
- `/set_panel_style`
- `/set_approve_message`
- `/set_decline_message`
- `/set_approval_message`
- `/refresh_panel`
- `/show_verification_settings`

## Example Setup Order
1. `/set_approval_channel #approval-queue`
2. `/set_logs_channel #verification-logs`
3. `/set_approved_role @Verified`
4. `/setup_panel #verify title:Verification description:Click below to request access button_label:Get Roles`

## Message Placeholders
You can use these inside your custom messages:
- `{user}`
- `{user_mention}`
- `{guild}`
- `{moderator}`
- `{role}`
- `{user_tag}`
- `{moderator_tag}`

## Example Approve DM
Title:
`Verification Approved`

Description:
`Hello {user_mention}, you were approved by {moderator} in {guild}. You now have the {role} role.`

## Notes
- This is made for **one approval role per server**.
- If you want, you can expand it later to support multiple panels and multiple role outputs.
- This bot uses Discord UI components and slash commands from `discord.py`. Discord.py documents UI components under `discord.ui`, application commands under `discord.app_commands`, and supports persistent views in 2.x. citeturn242432search0turn242432search8turn242432search6
