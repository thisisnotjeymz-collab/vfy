# Discord Game Verification Bot

A Discord bot starter for account verification and game connectors, built for Railway.

## What this bot does

- Global slash commands for all servers
- `/verify` to verify a Discord account per server
- `/setup channel` to set the verification channel
- `/setup roles` to set unverified and verified roles
- `/setup defaults` to set nickname source and role behavior without editing code
- `/setup_panel` to post a verification guide panel
- Auto role for new members
- Auto role for verified members
- Optional nickname change based on a saved game account
- Account connectors for:
  - Roblox
  - League of Legends
  - VALORANT
  - Mobile Legends
  - Call of Duty
- Roblox community role binding:
  - `/roblox community_connect`
  - `/roblox community_roles_bind`
- `/update` to refresh roles and nickname
- `/connections` to see saved accounts
- `/disconnect` to remove a saved account

## Important notes

- Roblox connection is real and resolves a username to a Roblox user ID.
- League and VALORANT connection use Riot's official account API and require `RIOT_API_KEY`.
- Mobile Legends and Call of Duty are saved as manual connectors in this starter. That keeps the bot usable even when official public account lookup options are limited or unstable.
- Per-server settings are stored in the bot database, so you do not need to keep editing GitHub for channel IDs or role IDs.

## Railway variables

Set these in Railway:

- `DISCORD_TOKEN` = your bot token
- `RIOT_API_KEY` = optional, for League and VALORANT
- `DATABASE_PATH` = optional, default is `verification_bot.db`
- `DEFAULT_UNVERIFIED_ROLE_NAME` = optional, default `Unverified`
- `DEFAULT_VERIFIED_ROLE_NAME` = optional, default `Verified`
- `DEFAULT_VERIFICATION_CHANNEL_NAME` = optional, default `verify`
- `DEFAULT_NICKNAME_SOURCE` = optional, default `discord`
- `GAME_ROLE_PREFIX` = optional, default `Game`
- `AUTO_CREATE_GAME_ROLES` = `true` or `false`
- `SYNC_ON_STARTUP` = `true` or `false`

## Railway deploy

1. Create a Discord application and bot in the Discord Developer Portal.
2. Enable these bot intents:
   - Server Members Intent
3. Invite the bot with these scopes:
   - `bot`
   - `applications.commands`
4. Permissions needed:
   - Manage Roles
   - Manage Nicknames
   - Send Messages
   - View Channels
   - Read Message History
5. Push this project to GitHub.
6. In Railway, create a new service from your GitHub repo.
7. Add the variables listed above.
8. Start command:
   - `python bot.py`

## Commands

### Main

- `/verify`
- `/update`
- `/connections`
- `/disconnect`
- `/nickname_source`
- `/setup_panel`

### Setup

- `/setup channel`
- `/setup roles`
- `/setup defaults`

### Connectors

- `/connect roblox username:<name>`
- `/connect league game_name:<name> tag_line:<tag> routing:<americas|asia|europe>`
- `/connect valorant game_name:<name> tag_line:<tag> routing:<americas|asia|europe>`
- `/connect mobile_legends player_id:<id> ign:<ign> server_id:<optional>`
- `/connect cod username:<name> platform:<platform>`

### Roblox helpers

- `/roblox community_connect`
- `/roblox community_roles_bind group_id:<id> min_rank:<rank> role:<role>`

## Clean role idea

This starter uses clean roles like:

- `Roblox | Connected`
- `LEAGUE | Connected`
- `VALORANT | Connected`
- `MOBILE_LEGENDS | Connected`
- `COD | Connected`

That is cleaner than creating one public role per exact player ID. The exact player ID is still saved privately in the database for connection data.

## Nickname behavior

Users can choose one source only:

- Discord
- Roblox
- League
- VALORANT
- Mobile Legends
- Call of Duty

They cannot type a custom nickname through the bot. They can only choose from already connected accounts.

## Recommended next upgrades

If you want this more like RoWifi premium style later, add:

- Web dashboard
- OAuth verification pages
- Screenshot proof flow
- Staff approval queue
- Better external game APIs where available
- MongoDB instead of SQLite
- Button UI and mod logs
