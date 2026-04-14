import discord
from discord.ext import commands
import os
import json

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Trying to find a way to hook into speaking events
@bot.event
async def on_socket_raw_receive(msg):
    # This might print raw gateway messages, but voice gateway is separate
    pass

bot.run("MOCK_TOKEN")
