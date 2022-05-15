from __future__ import annotations
from inspect import iscoroutinefunction
from typing import TYPE_CHECKING, Union, Optional
import disnake
from disnake.ext import commands

if TYPE_CHECKING:
    from utils.client import BotCore


class ProgressBar:

    def __init__(
            self,
            position: Union[int, float],
            total: Union[int, float],
            bar_count: int = 10
    ):
        self.start = int(bar_count * (position / total))
        self.end = int(bar_count - self.start) - 1


def sync_message(bot: BotCore):
    app_commands_invite = f"https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&scope=applications.commands"
    bot_invite = f"https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=397287680080&scope=bot%" \
                 f"20applications.commands"

    return f"`Se i comandi slash non vengono visualizzati,` [`clicca qui`]({app_commands_invite}) `per permettermi " \
           "di creare comandi slash sul server.`\n\n" \
           "`Nota: in alcuni casi i comandi slash possono richiedere fino a un'ora per essere visualizzati/aggiornati su tutti " \
           "i server. Se vuoi usare i comandi slash immediatamente sul server dovrai farlo " \
           f"cacciandomi via dal server per poi riaggiungimi di nuovo attraverso questo ` [`link`]({bot_invite})..."


async def check_cmd(cmd, inter: Union[disnake.Interaction, disnake.ModalInteraction]):

    bucket = cmd._buckets.get_bucket(inter)  # type: ignore
    if bucket:
        retry_after = bucket.update_rate_limit()
        if retry_after:
            raise commands.CommandOnCooldown(cooldown=bucket, retry_after=retry_after, type=cmd._buckets.type)

    for command_check in cmd.checks:
        c = (await command_check(inter)) if iscoroutinefunction(command_check) else command_check(inter)
        if not c:
            raise commands.CheckFailure()


async def send_message(
        inter: Union[disnake.Interaction, disnake.ApplicationCommandInteraction],
        text=None,
        *,
        embed: disnake.Embed = None,
        components: Optional[list] = None,
):

    # correção temporária usando variavel kwargs.
    kwargs = {}

    if embed:
        kwargs["embed"] = embed

    if inter.response.is_done() and isinstance(inter, disnake.AppCmdInter):
        await inter.edit_original_message(content=text, components=components, **kwargs)

    else:

        if components:
            kwargs["components"] = components

        await inter.send(text, ephemeral=True, **kwargs)


async def send_idle_embed(target: Union[disnake.Message, disnake.TextChannel, disnake.Thread], text="", *, bot: BotCore):

    embed = disnake.Embed(description="**Prima di procedere con una richiesta, unisciti a un canale vocale. Puoi richiedere della musica scrivendo in questo canale o cliccando su uno dei pulsanti qui sotto.**\n\n"
                          "**FORMATOI SUPPORTATI (nome, link):**"                          
                          " ```ini\n[Youtube, Soundcloud, Spotify, Twitch]```\n",
                          color=bot.get_color(target.guild.me))

    if text:
        embed.description += f"**ULTIMA AZIONE:** {text.replace('**', '')}\n"

    try:
        avatar = target.guild.me.avatar.url
    except:
        avatar = target.guild.me.default_avatar.url
    embed.set_thumbnail(avatar)

    components = [
        disnake.ui.Button(
            emoji="<:musicalnote:959073198413058169>",
            custom_id="musicplayer_add_song",
            style=disnake.ButtonStyle.grey,
            label="Richiedi una canzone."
        ),
        disnake.ui.Button(
            emoji="<:stardt:959012001244405840>",
            custom_id="musicplayer_enqueue_fav",
            style=disnake.ButtonStyle.grey,
            label="Aggiungi/Riproduci preferito."
        )
    ]

    if isinstance(target, disnake.Message):
        if target.author == target.guild.me:
            await target.edit(embed=embed, content=None, components=components)
            message = target
        else:
            message = await target.channel.send(embed=embed, components=components)
    else:
        message = await target.send(embed=embed, components=components)

    return message
