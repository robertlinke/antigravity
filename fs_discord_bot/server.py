import discord
from discord.ext import commands, tasks
from aiohttp import web
import aiohttp
import json
import os
import random
import string
import sys
import re
import time
from datetime import datetime, timezone, timedelta
import pytz

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# Load Configuration
def find_config():
    search_paths = [
        os.path.join(get_base_path(), "server_config.json"),
        os.path.join(os.getcwd(), "server_config.json"),
        "server_config.json"
    ]
    for path in search_paths:
        if os.path.exists(path):
            return path
    return search_paths[0] # Default

CONFIG_FILE = find_config()
print(f"[*] Config search path selected: {CONFIG_FILE}")

try:
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
        print(f"✅ Config loaded. Token found: {'Yes' if config.get('discord_bot_token') else 'No'}")
except Exception as e:
    if os.path.exists(CONFIG_FILE):
        print(f"⚠️ Could not parse config file (JSON error?): {e}")
    else:
        print(f"⚠️ Config file not found at: {CONFIG_FILE}")
    
    config = {
        "bind_host": "0.0.0.0",
        "bind_port": 8080,
        "external_url": "127.0.0.1:8080",
        "discord_bot_token": "",
        "openaip_api_key": "f80b8d9dc9b6a58f20185d31d10103a1"
    }

# Discord Setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Persistent Users Config
USERS_FILE = os.path.join(get_base_path(), "linked_users.json")
linked_users = {}

def load_users():
    global linked_users
    try:
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
            # JSON keys are always strings, recreate int User IDs
            linked_users = {int(k): v for k, v in data.items()}
    except Exception:
        linked_users = {}

def save_users():
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(linked_users, f)
    except Exception as e:
        print(f"Failed to save users: {e}")

load_users()

# --- API SERVER ---
async def handle_update(request):
    try:
        data = await request.json()
        token = data.get("token")
        client_id = data.get("client_id")
        
        for uid, udata in linked_users.items():
            if udata["token"] == token:
                now = time.time()
                active_client_id = udata.get("active_client_id")
                last_update_time = udata.get("last_update_time", 0)
                
                # Check for conflicts (if a recent update < 10 sec is from another client)
                if active_client_id and client_id and active_client_id != client_id and (now - last_update_time < 10):
                    return web.json_response({"error": "Another client is actively broadcasting with this magic code. Please disconnect the other client first."}, status=409)
                
                udata["active_client_id"] = client_id
                udata["last_update_time"] = now
                udata["lat"] = data.get("lat")
                udata["lon"] = data.get("lon")
                udata["com1"] = data.get("com1")
                udata["closest_icao_4char"] = data.get("closest_icao_4char")
                return web.json_response({"status": "ok"})
                
        return web.json_response({"error": "Invalid token"}, status=401)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def setup_hook():
    app = web.Application()
    app.router.add_post('/update_state', handle_update)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.get("bind_host", "0.0.0.0"), config.get("bind_port", 8080))
    await site.start()
    print(f"Server configured. API listening on {config.get('bind_host')}:{config.get('bind_port')}")
    polling_loop.start()

bot.setup_hook = setup_hook

# --- DISCORD LOGIC ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel and before.channel != after.channel:
        if before.channel.category and before.channel.category.name == "SimRadio":
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete()
                    print(f"Deleted auto-cleanup channel: {before.channel.name}")
                except Exception as e:
                    print(f"Failed to delete empty channel {before.channel.name}: {e}")

def generate_random_token():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@bot.command()
async def link(ctx):
    """Links your Discord profile to a client connection code."""
    user_id = ctx.author.id
    token = generate_random_token()
    linked_users[user_id] = {
        "guild_id": ctx.guild.id,
        "last_channel_name": None,
        "token": token,
        "com1": 0.0,
        "closest_icao_4char": None,
        "lat": 0.0,
        "lon": 0.0
    }
    save_users()
    
    external_url = config.get("external_url", "127.0.0.1:8080")
    magic_code = f"http://{external_url}-{token}"
    
    await ctx.send(
        f"✅ Auto-switching linked to your profile.\n"
        f"Paste this exact Magic Code into your MSFS Client:\n"
        f"`{magic_code}`"
    )

@bot.command()
async def unlink(ctx):
    """Unlinks your Discord profile."""
    user_id = ctx.author.id
    if user_id in linked_users:
        del linked_users[user_id]
        save_users()
        await ctx.send(f"❌ Auto-switching disabled for you.")
    else:
        await ctx.send("You are not currently linked.")

@tasks.loop(seconds=5)
async def polling_loop():
    if not linked_users:
        return
        
    for user_id, user_data in list(linked_users.items()):
        # If client hasn't sent data recently (e.g. within 15 seconds), don't forcibly move the user
        if time.time() - user_data.get("last_update_time", 0) > 15:
            user_data["last_channel_name"] = None
            continue
            
        if user_data["closest_icao_4char"] is None:
            target_channel_name = "Main Menu"
        else:
            freq_str = f"{user_data['com1']:.3f}".rstrip('0').rstrip('.') if '.' in f"{user_data['com1']}" else f"{user_data['com1']}"
            if freq_str.endswith(".0"):
                freq_str = freq_str[:-2]
            target_channel_name = f"{freq_str}({user_data['closest_icao_4char']})"

        if user_data["last_channel_name"] == target_channel_name:
            continue
            
        guild = bot.get_guild(user_data["guild_id"])
        if not guild:
            continue
            
        member = guild.get_member(user_id)
        if not member:
            continue

        if member.voice is None or member.voice.channel is None:
            continue

        category = discord.utils.get(guild.categories, name="SimRadio")
        if not category:
            try:
                category = await guild.create_category("SimRadio")
            except:
                category = None
                
        target_channel = discord.utils.get(guild.voice_channels, name=target_channel_name)
        
        if not target_channel:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(use_voice_activation=False)
                }
                target_channel = await guild.create_voice_channel(name=target_channel_name, category=category, overwrites=overwrites)
                print(f"Created new voice channel: {target_channel_name}")
            except discord.Forbidden:
                print(f"Lacking manage_channels permission in guild: {guild.name}")
                continue
            except Exception as e:
                print(f"Error creating channel: {e}")
                continue

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
    user_id = ctx.author.id
    if user_id in linked_users:
        s = linked_users[user_id]
        await ctx.send(f"Current State: com1={s['com1']}, {s['lat']},{s['lon']}, icao={s['closest_icao_4char']}")
    else:
        await ctx.send("Not currently linked.")

# Flight category colours for the embed sidebar
FLTCAT_COLOURS = {
    "VFR":  discord.Colour.green(),
    "MVFR": discord.Colour.blue(),
    "IFR":  discord.Colour.red(),
    "LIFR": discord.Colour.from_rgb(148, 0, 211),  # purple
}

@bot.command()
async def metar(ctx, icao: str = None):
    """Fetches the latest METAR for an ICAO code. Usage: !metar EGLL"""
    if not icao:
        await ctx.send("Usage: `!metar <ICAO>` — e.g. `!metar EGLL`")
        return

    icao = icao.upper().strip()
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours=2"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 204 or resp.status == 404:
                    await ctx.send(f"❌ No METAR found for **{icao}**. Check the ICAO code spelling and try again.")
                    return
                elif resp.status != 200:
                    await ctx.send(f"⚠️ API error (HTTP {resp.status}). Try again later.")
                    return
                data = await resp.json()
        except Exception as e:
            await ctx.send(f"⚠️ Could not reach aviationweather.gov: `{e}`")
            return

    if not data:
        await ctx.send(f"❌ No METAR found for **{icao}**. Check the ICAO code and try again.")
        return

    m = data[0]  # Most recent report

    # --- Flight Category colour ---
    flt_cat = m.get("fltCat", "VFR")
    colour = FLTCAT_COLOURS.get(flt_cat, discord.Colour.greyple())

    # --- Wind ---
    wdir = m.get("wdir")
    wspd = m.get("wspd")
    wgst = m.get("wgst")
    if wdir == 0 and wspd == 0:
        wind_str = "Calm"
    elif wdir is not None and wspd is not None:
        gust_str = f" gusting {wgst}kt" if wgst else ""
        wind_str = f"{wdir:03d}° at {wspd}kt{gust_str}"
    else:
        wind_str = "N/A"

    # --- Visibility ---
    visib = m.get("visib", "N/A")
    vis_str = f"{visib} SM" if visib != "N/A" else "N/A"

    # --- Clouds ---
    clouds = m.get("clouds", [])
    if clouds:
        cloud_str = "  ".join(f"{c['cover']} @ {c['base']}ft" for c in clouds)
    else:
        cloud_str = m.get("cover", "CLR") or "CLR"

    # --- Temp / Dewpoint ---
    temp = m.get("temp")
    dewp = m.get("dewp")
    temp_str = f"{temp}°C / {dewp}°C" if temp is not None else "N/A"

    # --- Altimeter ---
    altim = m.get("altim")
    alt_str = f"{altim} hPa ({altim / 33.8639:.2f} inHg)" if altim else "N/A"

    # --- Observation Time ---
    obs_time = m.get("reportTime", "")
    try:
        dt = datetime.fromisoformat(obs_time.replace("Z", "+00:00"))
        time_str = dt.strftime("%d %b %Y %H:%MZ")
    except Exception:
        time_str = obs_time

    # --- Build Embed ---
    station_name = m.get("name", icao)
    raw_ob = m.get("rawOb", "")

    embed = discord.Embed(
        title=f"🌤️ METAR — {icao}",
        description=f"**{station_name}**\n```{raw_ob}```",
        colour=colour
    )
    embed.add_field(name="Flight Category", value=f"**{flt_cat}**", inline=True)
    embed.add_field(name="Observation Time", value=time_str, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
    embed.add_field(name="🌬️ Wind", value=wind_str, inline=True)
    embed.add_field(name="👁️ Visibility", value=vis_str, inline=True)
    embed.add_field(name="🌡️ Temp / Dewpoint", value=temp_str, inline=True)
    embed.add_field(name="☁️ Clouds", value=cloud_str, inline=True)
    embed.add_field(name="🔵 Altimeter", value=alt_str, inline=True)
    embed.set_footer(text="Source: aviationweather.gov")

    await ctx.send(embed=embed)


# ─── !convert ────────────────────────────────────────────────────────────────

# Maps every spelling variant to a canonical internal label
UNIT_ALIASES = {
    # Length / Altitude
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "ft": "ft", "foot": "ft", "feet": "ft",
    "km": "km", "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km",
    "nm": "nm", "nmi": "nm", "nauticalmile": "nm", "nauticalmiles": "nm",
    "mi": "mi", "mile": "mi", "miles": "mi",
    # Speed
    "kt": "kt", "kts": "kt", "knot": "kt", "knots": "kt",
    "km/h": "km/h", "kph": "km/h", "kmh": "km/h",
    "m/s": "m/s", "ms": "m/s",
    "mph": "mph",
    "fpm": "fpm", "ft/min": "fpm",
    # Weight
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "lbs": "lbs", "lb": "lbs", "pound": "lbs", "pounds": "lbs",
    # Pressure
    "hpa": "hpa", "mb": "hpa", "millibar": "hpa", "millibars": "hpa",
    "inhg": "inhg",
    "psi": "psi",
    # Temperature
    "c": "°c", "°c": "°c", "celsius": "°c",
    "f": "°f", "°f": "°f", "fahrenheit": "°f",
    "k": "k", "kelvin": "k",
    # Time Formats
    "12h": "12h", "12-hour": "12h", "12hr": "12h",
    "24h": "24h", "24-hour": "24h", "24hr": "24h",
    # Timezone Abbreviations (Mapped to Fixed Offsets)
    "utc": "UTC", "z": "UTC", "gmt": "UTC",
    "est": "EST", "edt": "EDT",
    "cst": "CST", "cdt": "CDT",
    "mst": "MST", "mdt": "MDT",
    "pst": "PST", "pdt": "PDT",
    "cet": "CET", "cest": "CEST",
    "bst": "BST", "jst": "JST",
}

# Explicit offsets for abbreviations to ensure Winter/Summer distinction
FIXED_TZ_OFFSETS = {
    "UTC":  timezone.utc,
    "EST":  timezone(timedelta(hours=-5)), "EDT":  timezone(timedelta(hours=-4)),  # US Eastern
    "CST":  timezone(timedelta(hours=-6)), "CDT":  timezone(timedelta(hours=-5)),  # US Central
    "MST":  timezone(timedelta(hours=-7)), "MDT":  timezone(timedelta(hours=-6)),  # US Mountain
    "PST":  timezone(timedelta(hours=-8)), "PDT":  timezone(timedelta(hours=-7)),  # US Pacific
    "CET":  timezone(timedelta(hours=1)),  "CEST": timezone(timedelta(hours=2)),  # Europe Central
    "BST":  timezone(timedelta(hours=1)),                                       # British Summer
    "JST":  timezone(timedelta(hours=9)),                                       # Japan Standard
}

def _parse_time(time_str: str):
    """Try parsing HH:MM or HH:MM AM/PM."""
    formats = ["%H:%M", "%I:%M %p", "%I:%M%p", "%H%M"]
    time_str = time_str.upper().strip()
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    return None

# Simple multiply-factor conversions
CONVERSIONS = {
    # Length
    ("m",  "ft"): 3.28084,  ("m",  "km"): 0.001,       ("m",  "nm"): 0.000539957, ("m",  "mi"): 0.000621371,
    ("ft", "m"):  0.3048,   ("ft", "km"): 0.0003048,    ("ft", "nm"): 0.000164579, ("ft", "mi"): 0.000189394,
    ("km", "m"):  1000,     ("km", "ft"): 3280.84,      ("km", "nm"): 0.539957,    ("km", "mi"): 0.621371,
    ("nm", "m"):  1852,     ("nm", "ft"): 6076.12,      ("nm", "km"): 1.852,       ("nm", "mi"): 1.15078,
    ("mi", "m"):  1609.34,  ("mi", "ft"): 5280,         ("mi", "km"): 1.60934,     ("mi", "nm"): 0.868976,
    # Speed
    ("kt",   "km/h"): 1.852,     ("kt",   "m/s"): 0.514444, ("kt",   "mph"): 1.15078,  ("kt",   "fpm"): 101.269,
    ("km/h", "kt"):   0.539957,  ("km/h", "m/s"): 0.277778, ("km/h", "mph"): 0.621371, ("km/h", "fpm"): 54.6807,
    ("m/s",  "kt"):   1.94384,   ("m/s",  "km/h"): 3.6,     ("m/s",  "mph"): 2.23694,  ("m/s",  "fpm"): 196.85,
    ("mph",  "kt"):   0.868976,  ("mph",  "km/h"): 1.60934, ("mph",  "m/s"): 0.44704,  ("mph",  "fpm"): 88,
    ("fpm",  "kt"):   0.00987473,("fpm",  "m/s"): 0.00508,  ("fpm",  "km/h"): 0.018288,("fpm",  "mph"): 0.0113636,
    # Weight
    ("kg",  "lbs"): 2.20462,
    ("lbs", "kg"):  0.453592,
    # Pressure
    ("hpa",  "inhg"): 0.02953,   ("hpa",  "psi"): 0.0145038,
    ("inhg", "hpa"):  33.8639,   ("inhg", "psi"): 0.491154,
    ("psi",  "hpa"):  68.9476,   ("psi",  "inhg"): 2.03602,
}

# Temperature needs offset formulas, not just a multiplier
TEMP_CONVERSIONS = {
    ("°c", "°f"): lambda v: v * 9/5 + 32,
    ("°f", "°c"): lambda v: (v - 32) * 5/9,
    ("°c", "k"):  lambda v: v + 273.15,
    ("k",  "°c"): lambda v: v - 273.15,
    ("°f", "k"):  lambda v: (v - 32) * 5/9 + 273.15,
    ("k",  "°f"): lambda v: (v - 273.15) * 9/5 + 32,
}

CONVERT_HELP = discord.Embed(
    title="🔢 !convert — Unit Converter",
    description="**Usage:** `!convert <value> <from> <to>`\n**Example:** `!convert 250 kt mph`",
    colour=discord.Colour.blurple()
)
CONVERT_HELP.add_field(name="📏 Distance / Altitude", value="`m` `ft` `km` `nm` `mi`", inline=False)
CONVERT_HELP.add_field(name="💨 Speed",               value="`kt` `km/h` `m/s` `mph` `fpm`", inline=False)
CONVERT_HELP.add_field(name="⚖️ Weight",              value="`kg` `lbs`", inline=False)
CONVERT_HELP.add_field(name="🌡️ Temperature",         value="`c` `f` `k`  (Celsius / Fahrenheit / Kelvin)", inline=False)
CONVERT_HELP.add_field(name="🔵 Pressure",            value="`hpa` `inhg` `psi`", inline=False)
CONVERT_HELP.add_field(name="🕙 Time",                value="`12h` `24h` or TZs (`UTC`, `EST`, `PST`, etc.)", inline=False)
CONVERT_HELP.add_field(name="📋 Time Examples",       value="`!convert 14:30 24h 12h`\n`!convert \"02:30 PM\" 12h 24h`\n`!convert 12:00 UTC EST`", inline=False)

@bot.command()
async def convert(ctx, *args):
    """Converts between aviation units. Usage: !convert <value> <from> <to>"""
    if not args or len(args) < 3:
        await ctx.send(embed=CONVERT_HELP)
        return

    # Filter out common connectors like 'to' or 'in'
    clean_args = [a for a in args if a.lower() not in ("to", "in")]
    if len(clean_args) < 3:
        await ctx.send(embed=CONVERT_HELP)
        return

    value, from_unit, to_unit = clean_args[0], clean_args[1], clean_args[2]

    try:
        num = float(value.replace(",", "."))
        is_numeric = True
    except ValueError:
        is_numeric = False

    from_canon = UNIT_ALIASES.get(from_unit.lower().replace(" ", ""), from_unit)
    to_canon   = UNIT_ALIASES.get(to_unit.lower().replace(" ", ""), to_unit)

    # ─── Time Logic ───
    is_time_format = ":" in value or value.upper().endswith(("AM", "PM")) or from_canon in ("12h", "24h")
    t_obj = _parse_time(value) if is_time_format else None

    if t_obj is not None:
        # Format/TZ conversion
        try:
            # 1. Format Swap (if units are 12h/24h)
            if from_canon in ("12h", "24h") and to_canon in ("12h", "24h"):
                res = t_obj.strftime("%I:%M %p") if to_canon == "12h" else t_obj.strftime("%H:%M")
                await ctx.send(f"🕙 **{value}** ({from_unit}) = **{res}**")
                return

            # 2. Timezone conversion
            f_tz = FIXED_TZ_OFFSETS.get(from_canon) or (pytz.timezone(from_canon) if from_canon in pytz.all_timezones else None)
            t_tz = FIXED_TZ_OFFSETS.get(to_canon) or (pytz.timezone(to_canon) if to_canon in pytz.all_timezones else None)
            
            if f_tz and t_tz:
                now = datetime.now()
                dt = datetime.combine(now.date(), t_obj)
                
                if isinstance(f_tz, pytz.BaseTzInfo): loc_dt = f_tz.localize(dt)
                else: loc_dt = dt.replace(tzinfo=f_tz)
                
                rem_dt = loc_dt.astimezone(t_tz)
                res = rem_dt.strftime("%H:%M")
                await ctx.send(f"🌍 **{value} {from_unit}** = **{res} {to_unit}**")
                return
            else:
                # Detect incompatibility (Time vs Physics)
                if from_canon in UNIT_ALIASES.values() and to_canon in UNIT_ALIASES.values():
                    await ctx.send(f"❌ Cannot convert **{from_unit}** → **{to_unit}**. These units are incompatible.")
                else:
                    missing = from_unit if not f_tz else to_unit
                    await ctx.send(f"❌ Unknown unit: `{missing}`.")
                return
        except Exception as e:
            await ctx.send(f"❌ Time conversion error: `{e}`")
            return

    if not is_numeric:
        if is_time_format:
            await ctx.send(f"❌ Unable to parse time string: `{value}`. Use `HH:MM` or `HH:MM AM/PM`.")
        else:
            await ctx.send(f"❌ `{value}` is not a valid number or time string.")
        return

    if from_canon == to_canon:
        await ctx.send(f"ℹ️ `{from_unit}` and `{to_unit}` are the same unit — result is **{num:g}**.")
        return

    # Temperature (offset-based)
    if (from_canon, to_canon) in TEMP_CONVERSIONS:
        result = TEMP_CONVERSIONS[(from_canon, to_canon)](num)
        await ctx.send(f"🌡️ **{num:g} {from_unit}** = **{result:.4g} {to_unit}**")
        return

    # Standard multiply conversion
    if (from_canon, to_canon) in CONVERSIONS:
        result = num * CONVERSIONS[(from_canon, to_canon)]
        await ctx.send(f"🔢 **{num:g} {from_unit}** = **{result:.6g} {to_unit}**")
        return

    # If we got here, it's a numeric conversion but unknown/incompatible units
    if from_canon not in UNIT_ALIASES.values():
        await ctx.send(f"❌ Unknown unit: `{from_unit}`.")
    elif to_canon not in UNIT_ALIASES.values():
        await ctx.send(f"❌ Unknown unit: `{to_unit}`.")
    else:
        await ctx.send(f"❌ Cannot convert **{from_unit}** → **{to_unit}**. These units are incompatible.")
        return

    # Temperature (offset-based)
    if (from_canon, to_canon) in TEMP_CONVERSIONS:
        result = TEMP_CONVERSIONS[(from_canon, to_canon)](num)
        await ctx.send(f"🌡️ **{num:g} {from_unit}** = **{result:.4g} {to_unit}**")
        return

    # Standard multiply conversion
    if (from_canon, to_canon) in CONVERSIONS:
        result = num * CONVERSIONS[(from_canon, to_canon)]
        await ctx.send(f"🔢 **{num:g} {from_unit}** = **{result:.6g} {to_unit}**")
        return

    await ctx.send(f"❌ Cannot convert `{from_unit}` → `{to_unit}`. These units are incompatible.\nRun `!convert` for a list of supported conversions.")


# ─── !notam ──────────────────────────────────────────────────────────────────

NOTAM_SEARCH_URL  = "https://notams.aim.faa.gov/notamSearch/search"
NOTAM_SESSION_URL = "https://notams.aim.faa.gov/notamSearch/nsapp.html"
NOTAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":     "application/json, text/plain, */*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin":    "https://notams.aim.faa.gov",
    "Referer":   "https://notams.aim.faa.gov/notamSearch/nsapp.html",
}
NOTAM_MAX_SHOW = 5  # Max NOTAMs per Discord response

def _fmt_notam(entry: dict) -> str:
    """Extract and return the cleanest human-readable NOTAM line."""
    notam = entry.get("notam", entry)  # handle both nested and flat shapes
    # Prefer the ICAO-format message, fall back to others
    msg = (notam.get("icaoMessage")
           or notam.get("traditionalMessage")
           or notam.get("plainLanguage")
           or str(notam))
    # Strip leading/trailing whitespace and collapse internal runs of spaces
    return " ".join(msg.split())

@bot.command()
async def notam(ctx, icao: str = None):
    """Fetches active NOTAMs for an ICAO. Usage: !notam EHAM"""
    if not icao:
        await ctx.send("Usage: `!notam <ICAO>` — e.g. `!notam EHAM`\nShows the latest active NOTAMs from notams.aim.faa.gov.")
        return

    icao = icao.upper().strip()
    await ctx.typing()

    form_data = {
        "searchType":           "0",
        "designatorsForLocation": icao,
        "radius":               "10",
        "sortColumns":          "5 false",
        "sortDirection":        "true",
        "latitudeDirection":    "N",
        "longitudeDirection":   "W",
        "flightPathBuffer":     "4",
        "flightPathIncludeNavaids": "true",
        "flightPathResultsType": "All NOTAMs",
        "offset":               "0",
        "notamsOnly":           "false",
        "recaptchaToken":       "",   # attempt without token; many backends skip validation
    }

    jar = aiohttp.CookieJar()
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(cookie_jar=jar, headers={"User-Agent": NOTAM_HEADERS["User-Agent"]}) as session:
        # 1. Hit the page first to grab a JSESSIONID and signal disclaimer acceptance
        try:
            async with session.get(NOTAM_SESSION_URL, timeout=timeout) as _:
                pass
            jar.update_cookies({"fnsDisclaimer": "agreed"}, response_url=None)
        except Exception:
            pass  # If this fails, try the POST anyway

        # 2. POST the actual search
        try:
            async with session.post(
                NOTAM_SEARCH_URL,
                data=form_data,
                headers=NOTAM_HEADERS,
                timeout=timeout
            ) as resp:
                if resp.status == 403:
                    await ctx.send(
                        f"⛔ The FAA NOTAM server rejected the request (reCAPTCHA enforcement).\n"
                        f"Browse NOTAMs manually: <https://notams.aim.faa.gov/notamSearch/>"
                    )
                    return
                if resp.status != 200:
                    await ctx.send(f"⚠️ FAA NOTAM API returned HTTP {resp.status}. Try again later.")
                    return
                data = await resp.json(content_type=None)
        except Exception as e:
            await ctx.send(f"⚠️ Could not reach notams.aim.faa.gov: `{e}`")
            return

    notam_list  = data.get("notamList", [])
    total_count = data.get("totalNotamCount", len(notam_list))

    if not notam_list:
        await ctx.send(f"✅ No active NOTAMs found for **{icao}**.")
        return

    showing = notam_list[:NOTAM_MAX_SHOW]
    more    = total_count - len(showing)

    embed = discord.Embed(
        title=f"📋 NOTAMs — {icao}",
        description=f"Showing {len(showing)} of **{total_count}** active NOTAM(s)",
        colour=discord.Colour.orange()
    )

    for i, entry in enumerate(showing, 1):
        msg = _fmt_notam(entry)
        # Discord field value cap is 1024 chars
        if len(msg) > 1020:
            msg = msg[:1020] + "…"
        embed.add_field(name=f"NOTAM {i}", value=f"```{msg}```", inline=False)

    if more > 0:
        embed.set_footer(text=f"{more} more NOTAM(s) not shown — visit notams.aim.faa.gov for the full list.")
    else:
        embed.set_footer(text="Source: notams.aim.faa.gov")

    await ctx.send(embed=embed)


# ─── !chart ──────────────────────────────────────────────────────────────────

OPENAIP_AIRPORTS_URL = "https://api.core.openaip.net/api/airports"

def _m_to_ft(m: float) -> int:
    return int(m * 3.28084)

@bot.command(name="chart", aliases=["airport", "apt"])
async def chart(ctx, icao: str = None):
    """Fetches high-fidelity airport data from openAIP. Usage: !chart EHAM"""
    if not icao:
        await ctx.send("Usage: `!chart <ICAO>` — e.g. `!chart EHAM` or `!airport KJFK`")
        return

    icao = icao.upper().strip()
    api_key = config.get("openaip_api_key")

    if not api_key:
        await ctx.send("❌ Error: openAIP API key not configured in `server_config.json`.")
        return

    await ctx.typing()

    params = {
        "search": icao,
        "apiKey": api_key,
        "limit": 10  # Search can return multiple, we look for exact ICAO
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(OPENAIP_AIRPORTS_URL, params=params, timeout=15) as resp:
                if resp.status != 200:
                    await ctx.send(f"⚠️ openAIP API returned HTTP {resp.status}. Try again later.")
                    return
                data = await resp.json()
    except Exception as e:
        await ctx.send(f"⚠️ Could not reach openAIP: `{e}`")
        return

    items = data.get("items", [])
    # Find exact match for ICAO code in the search results
    airport = next((i for i in items if i.get("icaoCode") == icao), None)

    if not airport:
        await ctx.send(f"✅ No airport found with ICAO code **{icao}** in openAIP.")
        return

    name = airport.get("name", "Unknown Airport")
    country = airport.get("country", "")
    elev_obj = airport.get("elevation", {})
    elev_val = elev_obj.get("value", 0)
    # openAIP usually provides elevation in meters (unit 0)
    elev_ft = _m_to_ft(elev_val)

    embed = discord.Embed(
        title=f"✈️ Airport Info — {name} ({icao})",
        description=f"📍 {country} | Elevation: **{elev_ft:,} ft**",
        colour=discord.Colour.blue(),
        url=f"https://www.openaip.net/airports/{airport.get('_id')}"
    )

    # ─── Runways & Helipads ───
    runways = airport.get("runways", [])
    rwy_text = ""
    heli_text = ""
    
    for rwy in runways:
        designator = rwy.get("designator", "??")
        dim = rwy.get("dimension", {})
        length_m = dim.get("length", {}).get("value", 0)
        length_ft = _m_to_ft(length_m)
        width_m = dim.get("width", {}).get("value", 0)
        width_ft = _m_to_ft(width_m)
        
        surface_obj = rwy.get("surface", {})
        # Surface types are often integers, but openAIP sometimes provides names 
        # For simplicity, we'll just show designator and length
        desc = f"**{designator}**: {length_ft:,} x {width_ft:,} ft"
        
        # Simple heuristic for helipads (H designator or very short/circular)
        if "H" in designator.upper() or length_ft < 300:
            heli_text += f"• {desc}\n"
        else:
            rwy_text += f"• {desc}\n"

    if rwy_text:
        embed.add_field(name="🏁 Runways", value=rwy_text, inline=True)
    if heli_text:
        embed.add_field(name="🚁 Helipads", value=heli_text, inline=True)

    # ─── Frequencies ───
    freqs = airport.get("frequencies", [])
    if freqs:
        # Deduplicate and format
        freq_lines = []
        for f in freqs:
            f_name = f.get("name", "Unknown")
            f_val = f.get("value", "0.0")
            freq_lines.append(f"**{f_val}** — {f_name}")
        
        # Grouping or just listing the first few to avoid embed limits
        f_text = "\n".join(freq_lines[:12]) # Max 12 frequencies
        if len(freq_lines) > 12:
            f_text += f"\n*...and {len(freq_lines)-12} more*"
        embed.add_field(name="📡 Frequencies", value=f_text, inline=False)

    embed.set_footer(text="Data provided by openAIP.net")
    await ctx.send(embed=embed)


BOT_TOKEN = config.get("discord_bot_token") or os.getenv("DISCORD_BOT_TOKEN")

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Error: Missing Bot Token.")
        print("Please paste your Discord Bot Token inside 'discord_bot_token' in server_config.json.")
        input("Press Enter to exit...")
    else:
        bot.run(BOT_TOKEN)
