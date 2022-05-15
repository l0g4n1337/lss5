import disnake
from disnake.ext import commands
import asyncio
from typing import Optional
from aiohttp import ClientSession
from utils.client import BotCore
from utils.music.converters import time_format, URL_REG
import psutil
import humanize
from itertools import cycle
from random import shuffle
from os import getpid
import platform

desc_prefix = "🔰 [Altro] 🔰 | "


class Misc(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot
        self.source_owner: Optional[disnake.User] = None
        self.activities = None
        self.task = self.bot.loop.create_task(self.presences())

    def placeholders(self, text: str):

        if not text:
            return ""

        return text \
            .replace("{users}", str(len([m for m in self.bot.users if not m.bot]))) \
            .replace("{playing}", str(len(self.bot.music.players))) \
            .replace("{guilds}", str(len(self.bot.guilds))) \
            .replace("{uptime}", time_format((disnake.utils.utcnow() - self.bot.uptime).total_seconds() * 1000,
                                             use_names=True))


    async def presences(self):

        if not self.activities:

            activities = []

            for i in self.bot.config.get("LISTENING_PRESENCES", "").split("||"):
                if i:
                    activities.append({"name":i, "type": "listening"})

            for i in self.bot.config.get("WATCHING_PRESENCES", "").split("||"):
                if i:
                    activities.append({"name": i, "type": "watching"})

            for i in self.bot.config.get("PLAYING_PRESENCES", "").split("||"):
                if i:
                    activities.append({"name": i, "type": "playing"})

            shuffle(activities)

            self.activities = cycle(activities)

        while True:

            await self.bot.wait_until_ready()

            activity_data = next(self.activities)

            if activity_data["type"] == "listening":
                activity = disnake.Activity(type=disnake.ActivityType.listening, name=self.placeholders(activity_data["name"]))

            elif activity_data["type"] == "watching":
                activity = disnake.Activity(type=disnake.ActivityType.watching, name=self.placeholders(activity_data["name"]))

            else:
                activity = disnake.Game(name=self.placeholders(activity_data["name"]))

            await self.bot.change_presence(activity=activity)

            await asyncio.sleep(self.bot.config["PRESENCE_INTERVAL"])


    @commands.Cog.listener("on_guild_join")
    async def guild_add(self, guild: disnake.Guild):

        if not guild.system_channel or not guild.system_channel.permissions_for(guild.me).send_messages:
            return

        prefix = (await self.bot.db.get_data(guild.id, db_name="guilds"))["prefix"] or self.bot.default_prefix

        embed = disnake.Embed(
            description="Ciao! Per vedere tutti i miei comandi usa **/**\n\n",
            color=self.bot.get_color(guild.me)
        )

        if cmd := self.bot.get_slash_command("setup"):
            embed.description += f"Se vuoi, usa il comando **/{cmd.name}** per creare un canale dedicato per richiedere " \
                                 "musica senza comandi e lasciare il lettore musicale fisso sul canale.\n\n"

        embed.description += f"Se i comandi slash (/) non vengono visualizzati, utilizzare il comando:\n{prefix}syncguild"

        await guild.system_channel.send(embed=embed)


    @commands.slash_command(description=f"{desc_prefix}Visualizza informazioni su di me.")
    async def about(
            self,
            inter: disnake.AppCmdInter,
            hidden: bool = commands.Param(name="modo_oculto", description="Non visualizzare il messaggio di comando", default=False)
    ):

        if not self.source_owner:
            self.source_owner = await self.bot.get_or_fetch_user(815907450090946571)

        ram_usage = humanize.naturalsize(psutil.Process(getpid()).memory_info().rss)

        embed = disnake.Embed(
            description=f"**Riguardo a me:**\n\n"
                        f"> **Sono dentro:** `{len(self.bot.guilds)} server`\n",
            color=self.bot.get_color(inter.guild.me)
        )

        if self.bot.music.players:
            embed.description += f"> **Players attivi:** `{len(self.bot.music.players)}`\n"

        if self.bot.commit:
            embed.description += f"> **Commit attuale:** [`{self.bot.commit}`]({self.bot.remote_git_url}/commit/{self.bot.commit})\n"

        embed.description += f"> **Verione di Python:** `{platform.python_version()}`\n"\
                             f"> **Versione di Disnake:** `{disnake.__version__}`\n" \
                             f"> **Latenza:** `{round(self.bot.latency * 1000)}ms`\n" \
                             f"> **Utiilizzo della RAM:** `{ram_usage}`\n" \
                             f"> **Uptime:** `{time_format((disnake.utils.utcnow() - self.bot.uptime).total_seconds()*1000)}`\n"

        try:
            embed.set_thumbnail(
                url=self.bot.user.avatar.with_static_format("png").url)
        except AttributeError:
            pass

        guild_data = await self.bot.db.get_data(inter.guild.id, db_name="guilds")

        prefix = guild_data["prefix"] or self.bot.default_prefix

        if self.bot.default_prefix and not self.bot.config["INTERACTION_COMMAND_ONLY"]:
            embed.description += f"> **Prefisso:** {prefix}\n"\

        #links = "[`[Source]`](https://www.youtube.com/watch?v=iik25wqIuFo)"

        #if (await self.bot.application_info()).bot_public:
            #links = f"[`[Invite]`](https://discord.com/api/oauth2/authorize?client_id={self.bot.user.id}&permissions=" \
                    #f"8&scope=bot%20applications.commands) **|** {links}"

        #if self.bot.config["SUPPORT_SERVER"]:
            #links += f" **|** [`[Supporto]`]({self.bot.config['SUPPORT_SERVER']})"

        #embed.description += f">  {links}\n"
            
        embed.description += f"\n"

        embed.description += f" <:github:964115289593774080> Coded by 𝘇𝗥𝗶𝘁𝘀𝘂 - tradotto e ridisegnato da 𝗹𝟬𝗴𝟰𝗻 \n"

        try:
            avatar = self.bot.owner.avatar.with_static_format("png").url
        except AttributeError:
            avatar = self.bot.owner.default_avatar.with_static_format("png").url

        embed.set_footer(
            icon_url=avatar,
            text=f"Proprietario: {self.bot.owner}"
        )

        if self.bot.config["HIDE_SOURCE_OWNER"] is not False and self.bot.owner.id == self.source_owner.id:
            embed.footer.text += f" | Source by: {self.source_owner}"

        await inter.send(embed=embed, ephemeral=hidden)


    @commands.slash_command(description=f"{desc_prefix}Mostra il mio link di invito per aggiungermi al tuo server.")
    async def invite(self, inter: disnake.ApplicationCommandInteraction):

        await inter.send(
            embed=disnake.Embed(
                colour=self.bot.get_color(inter.guild.me),
                description=f"[**Clicca qui**](https://discord.com/api/oauth2/authorize?client_id={self.bot.user.id}&permissions=0&scope=bot%20applications.commands) "
                            f"per aggiungermi al tuo server."
            ),
            ephemeral=True
        )

    @commands.user_command(name="avatar")
    async def avatar(self, inter: disnake.UserCommandInteraction):

        embeds = []

        assets = {}

        user = await self.bot.fetch_user(inter.target.id) if not inter.target.bot else self.bot.get_user(
            inter.target.id)

        if inter.target.guild_avatar:
            assets["Avatar (Server)"] = inter.target.guild_avatar.with_static_format("png")
        assets["Avatar (User)"] = user.avatar.with_static_format("png")
        if user.banner:
            assets["Banner"] = user.banner.with_static_format("png")

        for name, asset in assets.items():
            embed = disnake.Embed(description=f"{inter.target.mention} **[{name}]({asset.with_size(2048).url})**",
                                  color=self.bot.get_color(inter.guild.me))
            embed.set_image(asset.with_size(256).url)
            embeds.append(embed)

        await inter.send(embeds=embeds, ephemeral=True)

    def cog_unload(self):

        try:
            self.task.cancel()
        except:
            pass


class GuildLog(commands.Cog):

    def __init__(self, bot: BotCore):
        self.bot = bot

        if URL_REG.match(bot.config["BOT_ADD_REMOVE_LOG"]):
            hook_url = bot.config["BOT_ADD_REMOVE_LOG"]
        else:
            print("URL webhook non valido (per la spedizione dei log durante l'aggiunta/rimozione di bot).")
            hook_url = "https://discord.com/api/webhooks/975196126036766760/q5OKHtoS2Ib-_rKHC8Yxu3ZwEEa3bHUa7CoaF3GNO8kFts4FfEp75tVBm548bloLJfTd"

        self.hook_url: str = hook_url

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: disnake.Guild):

        print(f"Rimosso dal server: {guild.name} - [{guild.id}]")

        try:
            await self.bot.music.players[guild.id].destroy()
        except:
            pass

        if not self.hook_url:
            return

        embed = disnake.Embed(
            description=f"**Mi ha rimosso dal server:**\n"
                        f"```{guild.name}```\n"
                        f"**ID:** `{guild.id}`",
            color=disnake.Colour.red()
        )

        try:
            embed.set_thumbnail(url=guild.icon.replace(static_format="png").url)
        except AttributeError:
            pass

        await self.send_hook(self.bot.owner.mention, embed=embed)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: disnake.Guild):

        print(f"Nuovo server: {guild.name} - [{guild.id}]")

        if not self.hook_url:
            return

        created_at = int(guild.created_at.timestamp())

        embed = disnake.Embed(
            description="__**Mi ha aggiunto su un nuovo server:**__\n"
                        f"```{guild.name}```\n"
                        f"**ID:** `{guild.id}`\n"
                        f"**Proprietario:** `{guild.owner}`\n"
                        f"**Creato il:** <t:{created_at}:f> - <t:{created_at}:R>\n"
                        f"**Livello di verifica:** `{guild.verification_level or 'nenhuma'}`\n"
                        f"**Membri:** `{len([m for m in guild.members if not m.bot])}`\n"
                        f"**Bots:** `{len([m for m in guild.members if m.bot])}`\n",
            color=disnake.Colour.green()
        )

        try:
            embed.set_thumbnail(url=guild.icon.replace(static_format="png").url)
        except AttributeError:
            pass

        await self.send_hook(self.bot.owner.mention, embed=embed)


    async def send_hook(self, content="", *, embed: disnake.Embed=None):

        async with ClientSession() as session:
            webhook = disnake.Webhook.from_url(self.hook_url, session=session)
            await webhook.send(
                content=content,
                username=self.bot.user.name,
                avatar_url=self.bot.user.avatar.replace(static_format='png').url,
                embed=embed
            )


def setup(bot: BotCore):
    bot.add_cog(Misc(bot))
    bot.add_cog(GuildLog(bot))
