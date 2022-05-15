import traceback
import disnake
from disnake.ext import commands
import asyncio
from subprocess import check_output
from os import path
from utils.music.errors import GenericError
from utils.music.local_lavalink import run_lavalink
from utils.client import BotCore
from utils.db import MongoDatabase, LocalDatabase, guild_prefix
from utils.music.spotify import spotify_client
from web_app import start
from config_loader import load_config

CONFIGS = load_config()

if not CONFIGS["DEFAULT_PREFIX"]:
    CONFIGS["DEFAULT_PREFIX"] = "!!!"

if CONFIGS['START_LOCAL_LAVALINK'] is True and CONFIGS['YTDLMODE'] is False:
    run_lavalink(
        lavalink_file_url=CONFIGS['LAVALINK_FILE_URL'],
        lavalink_initial_ram=CONFIGS['LAVALINK_INITIAL_RAM'],
        lavalink_ram_limit=CONFIGS['LAVALINK_RAM_LIMIT'],
        lavalink_additional_sleep=int(CONFIGS['LAVALINK_ADDITIONAL_SLEEP']),
    )

# intents necessárias para a source atual
intents_dict = {
    "guilds": True,
    "emojis": True,
    "webhooks": True,
    "guild_messages": True,
    "voice_states": True,

    #privileged intents (caso esteja ativado não esqueça de ativar no developer portal)
    "members": True,
    "message_content": True
}

# adicionar intents
intents_dict.update({i.lower(): True for i in CONFIGS["INTENTS"].split(" ") if i})

# desativar intents
intents_dict.update({i.lower(): False for i in CONFIGS["DISABLE_INTENTS"].split(" ") if i})

intents = disnake.Intents(**intents_dict)

mongo_key = CONFIGS.get("MONGO")

if not mongo_key:
    print(f"Il token mongoDB non é configurato! Un file json verrà utilizzato per il database.\n{'-' * 30}")

spotify = spotify_client(CONFIGS)

try:
    commit = check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
    print(f"Commit ver: {commit}\n{'-' * 30}")
except:
    commit = None

try:
    remote_git_url = check_output(['git', 'remote', '-v']).decode(
        'ascii').strip().split("\n")[0][7:].replace(".git (fetch)", "")
except:
    remote_git_url = ""

bots = []


def load_bot(bot_name: str, token: str, main=False):
    try:
        token, default_prefix = token.split()
    except:
        default_prefix = CONFIGS["DEFAULT_PREFIX"]

    try:
        test_guilds = list([int(i) for i in CONFIGS[f"TEST_GUILDS_{bot_name}"].split("||")])
    except:
        test_guilds = None

    bot = BotCore(
        command_prefix=guild_prefix,
        case_insensitive=True,
        intents=intents,
        test_guilds=test_guilds,
        sync_commands=CONFIGS["AUTO_SYNC_COMMANDS"] is True,
        sync_commands_debug=True,
        config=CONFIGS,
        color=CONFIGS["EMBED_COLOR"],
        commit=commit,
        spotify=spotify,
        remote_git_url=remote_git_url,
        default_prefix=default_prefix,
    )

    bot.token = token

    bot.load_extension('jishaku')
    bot.get_command("jsk").hidden = True
    bot.load_modules(bot_name)


    @bot.check
    async def check_commands(ctx: commands.Context):

        if bot.config['INTERACTION_COMMAND_ONLY'] and not (await bot.is_owner(ctx.author)):
            raise GenericError("**I comandi di testo sono disabilitati!\nUtilizza i comandi slash /**")

        return True


    @bot.listen()
    async def on_ready():
        print(f'{bot.user} [{bot.user.id}] Online.')

        if not bot.bot_ready:

            if not bot.owner:
                botowner = (await bot.application_info())
                try:
                    bot.owner = botowner.team.members[0]
                except AttributeError:
                    bot.owner = botowner.owner

            bot.db = MongoDatabase(bot=bot, token=mongo_key, name=str(bot.user.id)) if mongo_key \
                else LocalDatabase(bot, rename_db=main and path.isfile("./database.json"))

            if spotify:
                try:
                    await bot.spotify.authorize()
                except Exception:
                    traceback.print_exc()

            if not CONFIGS["RUN_RPC_SERVER"] and CONFIGS["RPC_SERVER"] == "ws://localhost:$PORT/ws":
                pass
            else:
                bot.loop.create_task(bot.ws_client.ws_loop())

            bot.bot_ready = True

    bots.append(bot)


main_token = CONFIGS.get("TOKEN")

if main_token:
    load_bot("Main Bot", main_token, main=True)

for k, v in CONFIGS.items():

    if not k.lower().startswith("token_bot_"):
        continue

    bot_name = k[10:] or "Sec. Bot"

    load_bot(bot_name, v)

if not bots:
    raise Exception("Il token del bot non é configurato correttamente!")


async def start_bots():
    await asyncio.wait(
        [asyncio.create_task(bot.start(bot.token)) for bot in bots]
    )


loop = asyncio.get_event_loop()

if CONFIGS["RUN_RPC_SERVER"]:

    for bot in bots:
        loop.create_task(bot.start(bot.token))

    start(bots)

else:

    loop.run_until_complete(start_bots())
