# MSFS Discord Auto-Channel Hook

This bot seamlessly hooks into Microsoft Flight Simulator via SimConnect and automatically manages your Discord Voice Channel location based on your nearest physical airport and tuned COM1 radio frequency.

## Requirements

1. **Python 3.10+**: Make sure Python is installed on the same computer running Microsoft Flight Simulator. You can download Python from the Microsoft Store or [python.org](https://www.python.org/downloads/).
2. **Microsoft Flight Simulator**: The PC running this script must be the one running MSFS (or have SimConnect local network proxy configured), as it requires `SimConnect.dll`.

## Setup

1. Open PowerShell or Command Prompt in this folder (`c:\Users\tiny-\Documents\antigravity\fs_discord_bot`).
2. Run `pip install -r requirements.txt` to install `discord.py`.
3. Create a Discord Bot in the [Discord Developer Portal](https://discord.com/developers/applications):
   - Navigate to the **Bot** tab.
   - Enable **Privileged Gateway Intents**: Turn on **Message Content Intent**, **Server Members Intent**, and **Presence Intent**.
   - Copy your **Bot Token**.
4. Invite the bot to your Discord Server via the OAuth2 URL Generator. Give it the following permissions:
   - `Manage Channels`
   - `Move Members`
   - `View Channels`
   - `Connect` / `Speak` (Voice permissions)

## Running the Bot

Set your bot token as an environment variable and run the Python script.
In Command Prompt:
```cmd
set DISCORD_BOT_TOKEN=your_token_here
python bot.py
```

In PowerShell:
```powershell
$env:DISCORD_BOT_TOKEN="your_token_here"
python bot.py
```

## How to use

1. Start up MSFS and load into a flight.
2. Join *any* Voice Channel in your Discord Server.
3. In a text channel, type `!link`.
4. The bot will acknowledge and start polling your flight sim data locally.
5. When your COM1 frequency or closest airport changes, it checks if a Voice Channel named `FREQ(ICAO)` exists (e.g. `122.8(EHAM)`). All modern Discord voice channels created via API now use the new DAVE E2EE protocol automatically.
6. If the channel does not exist, the bot creates it.
7. The bot will automatically move you to that channel.
8. Use `!unlink` to stop the auto-tracking feature.
