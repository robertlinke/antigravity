import discord
from discord.ext import commands, tasks
import json
import os
from simconnect_handler import MSFSClient

# Discord Setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# This dictionary stores linked Discord Unique IDs.
# Structure: { discord_user_id: {"guild_id": guild_id, "last_channel_name": None} }
linked_users = {}

# MSFS Client
msfs_client = MSFSClient()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    # Try connecting to MSFS SimConnect
    if msfs_client.start():
        print("Successfully hooked into MSFS SimConnect!")
    else:
        print("Failed to start SimConnect hook. Make sure MSFS is running.")
        
    polling_loop.start()

@bot.event
async def on_voice_state_update(member, before, after):
    # Check if a user left a voice channel
    if before.channel and before.channel != after.channel:
        # Check if the channel is under our SimRadio category
        if before.channel.category and before.channel.category.name == "SimRadio":
            # If the channel is now empty, delete it
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete()
                    print(f"Deleted auto-cleanup channel: {before.channel.name}")
                except Exception as e:
                    print(f"Failed to delete empty channel {before.channel.name}: {e}")

@bot.command()
async def link(ctx):
    """Links your Discord profile to the local MSFS SimConnect instance."""
    user_id = ctx.author.id
    linked_users[user_id] = {
        "guild_id": ctx.guild.id,
        "last_channel_name": None
    }
    await ctx.send(f"✅ Auto-switching linked to your MSFS SimConnect. I will now track your COM1 and proximity.")

@bot.command()
async def unlink(ctx):
    """Unlinks your Discord profile."""
    user_id = ctx.author.id
    if user_id in linked_users:
        del linked_users[user_id]
        await ctx.send(f"❌ Auto-switching disabled for you.")
    else:
        await ctx.send("You are not currently linked.")

@tasks.loop(seconds=5)
async def polling_loop():
    # Only process if we have linked users and SimConnect is giving us data
    if not linked_users or not msfs_client.connected:
        return
        
    status = msfs_client.get_status()
    # Wait until we have valid data from the sim
    # Determine target channel
    if status["closest_icao_4char"] is None:
        target_channel_name = "Main Menu"
    else:
        # Format: 121.5(EHAM)
        # Ensure human readable frequency
        freq_str = f"{status['com1']:.3f}".rstrip('0').rstrip('.') if '.' in f"{status['com1']}" else f"{status['com1']}"
        if freq_str.endswith(".0"):
            freq_str = freq_str[:-2]
        
        target_channel_name = f"{freq_str}({status['closest_icao_4char']})"

    # Go through all linked users and process channel moving
    for user_id, user_data in list(linked_users.items()):
        # If the channel name hasn't changed since last evaluation, skip
        if user_data["last_channel_name"] == target_channel_name:
            continue
            
        guild = bot.get_guild(user_data["guild_id"])
        if not guild:
            continue
            
        member = guild.get_member(user_id)
        if not member:
            continue

        # Check if user is currently inside a Voice Channel on this server
        if member.voice is None or member.voice.channel is None:
            # We don't force them into VC if they aren't even connected
            continue

        # Look for the target voice channel
        # Note: All recent discord voice channels use Dave E2EE implicitly
        target_channel = discord.utils.get(guild.voice_channels, name=target_channel_name)
        
        if not target_channel:
            try:
                # Find or create category
                category = discord.utils.get(guild.categories, name="SimRadio")
                if not category:
                    category = await guild.create_category("SimRadio")
                    
                # Create the channel inside category
                target_channel = await guild.create_voice_channel(name=target_channel_name, category=category)
                print(f"Created new voice channel: {target_channel_name}")
            except discord.Forbidden:
                print(f"Lacking manage_channels permission in guild: {guild.name}")
                continue
            except Exception as e:
                print(f"Error creating channel: {e}")
                continue

        # Move the user into the target channel if they aren't already there
        if member.voice.channel.id != target_channel.id:
            try:
                await member.move_to(target_channel)
                user_data["last_channel_name"] = target_channel_name
                print(f"Moved {member.display_name} to {target_channel_name}")
            except discord.Forbidden:
                print(f"Lacking move_members permission for user: {member.display_name}")
            except Exception as e:
                print(f"Failed to move user: {e}")

@bot.command()
async def state(ctx):
    """Debug command to show current sim var state."""
    await ctx.send(f"Current Sim State: {msfs_client.get_status()}")

# Retrieve Bot Token from Environment Variable
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Please set the DISCORD_BOT_TOKEN environment variable.")
    else:
        bot.run(BOT_TOKEN)
