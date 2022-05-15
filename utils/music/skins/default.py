from ..models import LavalinkPlayer
import disnake
from ..converters import fix_characters, time_format
import itertools
from ...others import ProgressBar


def load(player: LavalinkPlayer) -> dict:

    data = {
        "content": None,
        "embeds": None
    }

    embed = disnake.Embed(color=player.bot.get_color(player.guild.me))
    embed_queue = None

    if not player.paused:
        embed.set_author(
            name="In riproduzione:",
            icon_url="https://i.giphy.com/8L0Pbbkno5BI8n4CaI.gif"
        )
    else:
        embed.set_author(
            name="In Pausa:",
            icon_url="https://cdn.discordapp.com/emojis/959006158151098388.png"
        )

    embed.set_footer(
        text=str(player),
        icon_url="https://cdn.discordapp.com/attachments/480195401543188483/907119505971486810/speaker-loud-speaker.gif"
    )

    if player.current.is_stream:
        duration = "```ini\n🔴 [Livestream]```"
    else:

        progress = ProgressBar(
            player.position,
            player.current.duration,
            bar_count=10 if not player.static else (20 if player.current.info.get("sourceName") == "youtube" else 17)
        )

        duration = f"```ini\n[{time_format(player.position)}] {('━'*progress.start)}🔴️{'━'*progress.end} " \
                   f"[{time_format(player.current.duration)}]```\n"

    vc_txt = ""

    if player.static:
        queue_size = 20
        queue_text_size = 33
        queue_img = ""
        playlist_text_size = 20

        try:
            vc_txt = f"\n> <:microphoneline:958987946525069332> **⠂Canale Vocale:** [`{player.guild.me.voice.channel.name}`](http://discordapp.com/channels/{player.guild.id}/{player.guild.me.voice.channel.id})"
        except AttributeError:
            pass

    else:
        queue_size = 3
        queue_text_size = 31
        queue_img = "https://i.imgur.com/lKRifSD.png"
        playlist_text_size = 13

    txt = f"[`{player.current.single_title}`]({player.current.uri})\n\n" \
          f"> <:albumauthorduotone:958976606003683369> **⠂Autore:** {player.current.authors_md}\n" \
          f"> <:faceheadphone:958985516357943337> **⠂Richiesto da:** {player.current.requester.mention}\n" \
          f"> <:volumehigh:958986651940556830> **⠂Volume:** `{player.volume}%`"

    if player.current.track_loops:
        txt += f"\n> 🔂 **⠂Ripetizioni restanti:** `{player.current.track_loops}`"

    if player.nightcore:
        txt += f"\n> 🇳 **⠂Effetto nightcore:** `Attivato`"

    if player.current.album:
        txt += f"\n> <:queue:959000316290945054> **⠂Album:** [`{fix_characters(player.current.album['name'], limit=playlist_text_size)}`]({player.current.album['url']})"

    if player.current.playlist:
        txt += f"\n> <:playlist:959485050901114940> **⠂Playlist:** [`{fix_characters(player.current.playlist['name'], limit=playlist_text_size)}`]({player.current.playlist['url']})"

    if player.nonstop:
        txt += "\n> <:reppeat:959001381052756039> **⠂Loop:** `Attivato`"

    txt += f"{vc_txt}\n"

    if player.command_log:
        txt += f"> <:circlecheck:958990128502685706> **⠂Ultima Interazione:** {player.command_log}\n"

    txt += duration

    if len(player.queue):

        queue_txt = "\n".join(
            f"`{n + 1}) [{time_format(t.duration) if not t.is_stream else '🔴 Livestream'}]` [`{fix_characters(t.title, queue_text_size)}`]({t.uri})"
            for n, t in (enumerate(itertools.islice(player.queue, queue_size)))
        )

        embed_queue = disnake.Embed(title=f"Brani in coda: {len(player.queue)}", color=player.bot.get_color(player.guild.me),
                                    description=f"\n{queue_txt}")
        embed_queue.set_image(url=queue_img)

    embed.description = txt

    if player.static:
        embed.set_image(url=player.current.thumb)
    else:
        embed.set_image(
            url="https://i.imgur.com/lKRifSD.png")
        embed.set_thumbnail(url=player.current.thumb)

    data["embeds"] = [embed_queue, embed] if embed_queue else [embed]

    return data
