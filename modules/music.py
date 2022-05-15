import disnake
from disnake.embeds import Embed
from disnake.ext import commands
import traceback
import wavelink
import asyncio
from fake_useragent import UserAgent
import sys
import json
from random import shuffle
from typing import Literal, Union
from urllib import parse
from utils.client import BotCore
from utils.music.errors import GenericError, MissingVoicePerms
from utils.music.spotify import SpotifyPlaylist, process_spotify
from utils.music.checks import check_voice, user_cooldown, has_player, has_source, is_requester, is_dj, can_send_message
from utils.music.models import LavalinkPlayer, LavalinkTrack, YTDLTrack, YTDLPlayer, YTDLManager
from utils.music.converters import time_format, fix_characters, string_to_seconds, get_track_index, URL_REG, \
    YOUTUBE_VIDEO_REG, search_suggestions, queue_tracks, seek_suggestions, queue_author, queue_playlist, \
    node_suggestions, fav_add_autocomplete, fav_list
from utils.music.interactions import VolumeInteraction, QueueInteraction, SelectInteraction
from utils.others import check_cmd, send_message, send_idle_embed

PlayOpts = commands.option_enum(
    {
        "Mixa Playlist": "shuffle",
        "Inverti Playlist": "reversed",
    }
)

SearchSource = commands.option_enum(
    {
        "Youtube": "ytsearch",
        "Soundcloud": "scsearch"
    }
)


desc_prefix = "🎶 [Musica] 🎶 | "


class Music(commands.Cog, wavelink.WavelinkMixin):

    def __init__(self, bot: BotCore):

        self.bot = bot

        self.bot.loop.create_task(self.process_nodes())

        self.song_request_concurrency = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

        self.player_interaction_concurrency = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)


    """@check_voice()
    @commands.dynamic_cooldown(user_cooldown(2, 5), commands.BucketType.member)
    @can_send_message()
    @commands.user_command(name="enqueue presence track")
    async def user_play(self, inter: disnake.UserCommandInteraction):

        #inter.target.activities fica retornando None mesmo com intents.presences ativada.
        member = inter.guild.get_member(inter.target.id)

        query = ""

        for a in member.activities:
            if isinstance(a, disnake.activity.Spotify):
                query = f"{a.title} - {a.artists[0]}"
                break

            if not isinstance(a, disnake.Activity):
                continue

            ac = a.to_dict()

            if a.application_id == 463097721130188830:

                if not ac.get('buttons'):
                    continue

                query = a.details.split("|")[0]
                break

            if a.application_id == 367827983903490050:

                state = ac.get('state')

                detais = ac.get('details')

                if not state:
                    continue

                if state.lower() in ['afk', 'idle', 'looking for a game']:
                    raise GenericError(
                        f"{member.mention} está jogando **OSU!** mas no momento não está com uma música ativa...")

                if not detais:
                    raise GenericError(
                        f"{member.mention} está jogando **OSU!** mas no momento não está com uma música ativa...")

                query = "[".join(detais.split("[")[:-1])

                break

        if not query:
            raise GenericError(f"{member.mention} não está com status do spotify, OSU! ou youtube.")

        await self.play(
            inter,
            query=query,
            position=0,
            options="",
            manual_selection=False,
            source="ytsearch",
            repeat_amount=0,
        )"""


    @check_voice()
    @commands.dynamic_cooldown(user_cooldown(2, 5), commands.BucketType.member)
    @can_send_message()
    @commands.message_command(name="add to queue")
    async def message_play(self, inter: disnake.MessageCommandInteraction):

        if not inter.target.content:
            emb = disnake.Embed(description=f"Non c'è testo nel [messaggio]({inter.target.jump_url}) selezionato...", color=disnake.Colour.red())
            await inter.send(embed=emb, ephemeral=True)
            return

        await self.play(
            inter,
            query=inter.target.content,
            position=0,
            options="",
            manual_selection=False,
            source="ytsearch",
            repeat_amount=0,
        )


    @check_voice()
    @can_send_message()
    @commands.dynamic_cooldown(user_cooldown(2, 5), commands.BucketType.member)
    @commands.slash_command(name="search", description=f"{desc_prefix}Cerca i brani e scegline uno tra i risultati da riprodurre.")
    async def search(
            self,
            inter: disnake.ApplicationCommandInteraction,
            query: str = commands.Param(name="ricerca", desc="Nome o link del brano.", autocomplete=search_suggestions), *,
            position: int = commands.Param(name="posizione", description="Metti il brano in una posizione specifica", default=0),
            options: PlayOpts = commands.Param(name="opzioni", description="Opzioni per l'elaborazione della playlist", default=False),
            source: SearchSource = commands.Param(name="fonte", description="Seleziona il sito per cercare la musica (non i link)", default="ytsearch"),
            repeat_amount: int = commands.Param(name="ripetizioni", description="Impostare il numero di ripetizioni.", default=0),
            hide_playlist: bool = commands.Param(description="Non includere i dettagli della playlist nei brani.", default=False),
            server: str = commands.Param(name="server", desc="Utilizzare un server musicale specifico nella ricerca.", autocomplete=node_suggestions, default=None)
    ):

        await self.play(
            inter,
            query=query,
            position=position,
            options=options,
            manual_selection=True,
            source=source,
            repeat_amount=repeat_amount,
            hide_playlist=hide_playlist,
            server=server
        )

    @has_player()
    @is_dj()
    @commands.slash_command(description=f"{desc_prefix}Collegami a un canale vocale (o passa a uno).")
    async def connect(
            self,
            inter: disnake.ApplicationCommandInteraction,
            channel: Union[disnake.VoiceChannel, disnake.StageChannel] = commands.Param(name="canale", description="Canale per connettersi", default=None)
    ):
        await self.do_connect(inter, channel)

    async def do_connect(self, ctx: Union[disnake.AppCmdInter, commands.Context, disnake.Message],
                         channel: Union[disnake.VoiceChannel, disnake.StageChannel]):

        player = self.bot.music.players[ctx.guild.id]

        guild_data = await self.bot.db.get_data(ctx.guild.id, db_name="guilds")

        if not channel:
            channel: Union[disnake.VoiceChannel, disnake.StageChannel] = ctx.author.voice.channel

        if guild_data["check_other_bots_in_vc"] and any(m for m in channel.members if m.bot and m != ctx.guild.me):
            raise GenericError(f"**C'è un altro bot collegato al canale:** <#{ctx.author.voice.channel.id}>")

        if isinstance(ctx, disnake.AppCmdInter) and ctx.application_command == self.connect:

            perms = channel.permissions_for(ctx.guild.me)

            if not perms.connect or not perms.speak:
                raise MissingVoicePerms(channel)

            await player.connect(channel.id)

            txt = [
                f"{'mi ha spostato nel' if channel != ctx.guild.me.voice and ctx.guild.me.voice.channel else 'mi ha ricollegato nel'}"
                f" canale <#{channel.id}>",
                f"**collegare nessun canale** <#{channel.id}>."
            ]
            await self.interaction_message(ctx, txt, rpc_update=True)

        else:
            await player.connect(channel.id)

        try:
            player.members_timeout_task.cancel()
        except:
            pass

        if isinstance(channel, disnake.StageChannel):

            while not ctx.guild.me.voice:
                await asyncio.sleep(1)

            stage_perms = channel.permissions_for(ctx.guild.me)

            if stage_perms.manage_roles:
                await ctx.guild.me.edit(suppress=False)
            else:

                embed = disnake.Embed(color=self.bot.get_color(ctx.guild.me))

                if stage_perms.request_to_speak:
                    await ctx.guild.me.request_to_speak()
                    embed.description = f"Ho bisogno che accetti la mia richiesta di parlare sul palco."
                else:
                    embed.description = f"Non ho l'autorità per parlare automaticamente sul palco (ho bisogno del permesso di qualcuno dello staff)"

                await ctx.channel.send(ctx.author.mention, embed=embed, delete_after=13)

    @check_voice()
    @commands.dynamic_cooldown(user_cooldown(2, 5), commands.BucketType.member)
    @commands.slash_command(name="play", description=f"{desc_prefix}Riproduci musica su un canale vocale.")
    async def play(
            self,
            inter: disnake.ApplicationCommandInteraction,
            query: str = commands.Param(name="ricerca", desc="Nome o collegamento del brano.", autocomplete=fav_add_autocomplete), *,
            position: int = commands.Param(name="posizione", description="Metti il brano in una posizione specifica", default=0),
            options: PlayOpts = commands.Param(name="opzioni" ,description="Opzioni per l'elaborazione della playlist", default=False),
            manual_selection: bool = commands.Param(name="selezionare_manualmente", description="Scegli manualmente un brano tra i risultati trovati", default=False),
            source: SearchSource = commands.Param(name="fonte", description="Seleziona il sito per cercare la musica (non i link)", default="ytsearch"),
            repeat_amount: int = commands.Param(name="ripetizioni", description="Impostare il numero di ripetizioni.", default=0),
            hide_playlist: bool = commands.Param(name="nascondi_playlist", description="Non includere i dettagli della playlist nei brani.", default=False),
            server: str = commands.Param(name="server", desc="Utilizzare un server musicale specifico nella ricerca.", autocomplete=node_suggestions, default=None)
    ):

        node = self.bot.music.get_node(server)

        if not node:
            node = self.bot.music.get_best_node()

        if not node:
            raise GenericError("Non ci sono server musicali disponibili.")

        static_player = {}

        guild_data = await self.bot.db.get_data(inter.guild.id, db_name="guilds")

        try:
            static_player = guild_data['player_controller']
            channel = inter.guild.get_channel(int(static_player['channel'])) or inter.channel
        except (KeyError, TypeError):
            channel = inter.channel

        if not channel.permissions_for(inter.guild.me).send_messages:
            raise GenericError(f"Non sono autorizzato a inviare messaggi sul canale: {channel.mention}")

        if query.startswith("> fav:"):
            user_data = await self.bot.db.get_data(inter.author.id, db_name="users")
            query = user_data["fav_links"][query[7:]]

        else:

            query = query.strip("<>")

            if not URL_REG.match(query):
                query = f"{source}:{query}"

                if manual_selection and isinstance(self.bot.music, YTDLManager):
                    source += "5"

            elif "&list=" in query:

                view = SelectInteraction(
                    user=inter.author,
                    opts = [
                        disnake.SelectOption(label="Musica", emoji="🎵", description="Carica la canzone solo dal link.", value="music"),
                        disnake.SelectOption(label="Playlist", emoji="🎶", description="Carica la playlist con il brano corrente.", value="playlist"),
                    ], timeout=30)

                embed = disnake.Embed(
                    description="**Il link contiene video con playlist.**\n`selezionare un'opzione entro 30 secondi per procedere.`",
                    color=self.bot.get_color(inter.guild.me)
                )

                await inter.send(embed=embed, view=view, ephemeral=True)

                await view.wait()

                if not view.inter:
                    await inter.edit_original_message(content="Tempo scaduto!", embed=None, view=None)
                    return

                if view.selected == "music":
                    query = YOUTUBE_VIDEO_REG.match(query).group()

                inter = view.inter

        await inter.response.defer(ephemeral=not (isinstance(inter.channel, disnake.Thread) and guild_data['player_controller']["channel"] == str(inter.channel.parent_id)))

        tracks, node = await self.get_tracks(query, inter.user, node=node, track_loops=repeat_amount,
                                             hide_playlist=hide_playlist)

        #skin = self.bot.check_skin(guild_data["player_controller"]["skin"]) TODO: habilitar apenas quando o suporte a skin por servidor for totalmente finalizado.
        skin = self.bot.default_skin

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.get_player(
            guild_id=inter.guild.id,
            cls=LavalinkPlayer,
            requester=inter.author,
            guild=inter.guild,
            channel=channel,
            node_id=node.identifier,
            static=bool(static_player['channel']),
            skin=skin,
            bot=self.bot
        )

        if static_player and not player.message:
            try:
                channel = inter.bot.get_channel(int(static_player['channel']))
            except TypeError:
                channel = None

            if not channel:
                await self.reset_controller_db(inter.guild_id, guild_data, inter=inter)

            else:
                try:
                    message = await channel.fetch_message(int(static_player.get('message_id')))
                except TypeError:
                    await self.reset_controller_db(inter.guild_id, guild_data, inter=inter)
                except:
                    message = await send_idle_embed(inter.channel, bot=self.bot)
                    guild_data['player_controller']['message_id'] = str(message.id)
                    await self.bot.db.update_data(inter.guild.id, guild_data, db_name='guilds')
                player.message = message

        pos_txt = ""

        embed = disnake.Embed(color=disnake.Colour.red())

        embed.colour = self.bot.get_color(inter.guild.me)

        position-=1

        if isinstance(tracks, list):

            if manual_selection and len(tracks) > 1:

                embed.description = f"**Seleziona una canzone qui sotto:**"

                components = [
                    disnake.ui.Select(
                        placeholder='Risultati:',
                        custom_id=f"track_selection_{inter.id}",
                        options=[
                            disnake.SelectOption(
                                label=t.title[:99],
                                value=f"track_select_{n}",
                                description=f"{t.author} [{time_format(t.duration)}]")
                            for n, t in enumerate(tracks[:25])
                        ]
                    )
                ]

                await inter.edit_original_message(embed=embed, components=components)

                try:
                    select_interaction: disnake.MessageInteraction = await self.bot.wait_for(
                        "dropdown",
                        timeout=45,
                        check=lambda i: i.author == inter.author and i.data.custom_id == f"track_selection_{inter.id}"
                    )
                except asyncio.TimeoutError:
                    raise GenericError("Tempo scaduto!")

                track = tracks[int(select_interaction.data.values[0][13:])]


            else:
                track = tracks[0]

            if position < 0:
                player.queue.append(track)
            else:
                player.queue.insert(position, track)
                pos_txt = f" in posizione {position + 1} da fila"

            duration = time_format(track.duration) if not track.is_stream else '🔴 Livestream'

            log_text = f"{inter.author.mention} aggiunto [`{fix_characters(track.title, 20)}`]({track.uri}){pos_txt} `({duration})`."

            embed.set_author(
                name=fix_characters(track.title, 35),
                url=track.uri
            )
            embed.set_thumbnail(url=track.thumb)
            embed.description = f"`{fix_characters(track.author, 15)}`**┃**`{time_format(track.duration) if not track.is_stream else '🔴 Livestream'}`**┃**{inter.author.mention}"

        else:

            if options == "shuffle":
                shuffle(tracks.tracks)

            if position < 0 or len(tracks.tracks) < 2:

                if options == "reversed":
                    tracks.tracks.reverse()
                for track in tracks.tracks:
                    player.queue.append(track)
            else:
                if options != "reversed":
                    tracks.tracks.reverse()
                for track in tracks.tracks:
                    player.queue.insert(position, track)

                pos_txt = f" (Pos. {position + 1})"

            if hide_playlist:
                log_text = f"Aggiunta una playlist con {len(tracks.tracks)} brano(i) {pos_txt}."
            else:
                log_text = f"{inter.author.mention} aggiunto alla playlist [`{fix_characters(tracks.data['playlistInfo']['name'], 20)}`]({query}){pos_txt} `({len(tracks.tracks)})`."

            total_duration = 0

            for t in tracks.tracks:
                if not t.is_stream:
                    total_duration += t.duration

            embed.set_author(
                name=fix_characters(tracks.data['playlistInfo']['name'], 35),
                url=query
            )
            embed.set_thumbnail(url=tracks.tracks[0].thumb)
            embed.description = f"`{len(tracks.tracks)} brano(i)`**┃**`{time_format(total_duration)}`**┃**{inter.author.mention}"

        await inter.edit_original_message(embed=embed, view=None)

        if not player.is_connected:
            await self.do_connect(inter, channel=inter.author.voice.channel)

        if not player.current:
            await player.process_next()
        else:
            player.command_log = log_text
            await player.update_message()


    @check_voice()
    @has_source()
    @is_requester()
    @commands.dynamic_cooldown(user_cooldown(2, 8), commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Salta il brano corrente in riproduzione.")
    async def skip(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if not len(player.queue):
            await send_message(inter, embed=disnake.Embed(description="**Non ci sono canzoni in coda...**", color=disnake.Colour.red()))
            return

        if inter.type.name != "application_command":
            player.command_log = f"{inter.author.mention} saltato il brano."
            await inter.response.defer()
        else:
            player.command_log = f"{inter.author.mention} salta la musica."
            embed = disnake.Embed(description=f"⏭️** ┃ Musica saltellante:** [`{fix_characters(player.current.title, 30)}`]({player.current.uri})", color=self.bot.get_color(inter.guild.me))
            await inter.send(embed=embed, ephemeral=True)

        if player.loop == "current":
            player.loop = False

        player.current.track_loops = 0

        await player.stop()


    @check_voice()
    @has_player()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(2, 8), commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Torna al brano precedente.")
    async def back(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if not len(player.played) and not len(player.queue):

            await player.seek(0)
            await self.interaction_message(inter, "è tornato all'inizio della canzone.", rpc_update=True)
            return

        try:
            track = player.played.pop()
        except:
            track = player.queue.pop()
            player.last_track = None
            player.queue.appendleft(player.current)
        player.queue.appendleft(track)

        if inter.type.name != "application_command":
            player.command_log = f"{inter.author.mention} tornato alla canzone corrente."
            await inter.response.defer()
        else:
            player.command_log = f"{inter.author.mention} tornato alla canzone corrente."
            await inter.send("restituito con successo.", ephemeral=True)

        if player.loop == "current":
            player.loop = False
        player.is_previows_music = True
        if not player.current:
            await player.process_next()
        else:
            await player.stop()


    @check_voice()
    @has_source()
    @commands.slash_command(description=f"{desc_prefix}Vota per saltare la canzone corrente.")
    async def voteskip(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        embed = disnake.Embed()

        if inter.author in player.votes:
            embed.colour = disnake.Colour.red()
            embed.description = f"{inter.author.mention} **hai già votato per saltare la canzone corrente.**"
            await send_message(inter, embed=embed)
            return

        embed.colour = disnake.Colour.green()

        txt = f"{inter.author.mention} **votato per saltare la canzone corrente (voti: {len(player.votes) + 1}/{self.bot.config.get('VOTE_SKIP_AMOUNT', 3)}).**"

        if len(player.votes) < self.bot.config.get('VOTE_SKIP_AMOUNT', 3):
            embed.description = txt
            player.votes.add(inter.author)
            player.command_log = txt
            await inter.send("voto aggiunto!")
            await player.update_message()
            return

        player.command_log = f"{txt}\n**Il precedente è stato saltato immediatamente.**"
        await inter.send("voto aggiunto!", ephemeral=True)
        await player.stop()


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(1, 5), commands.BucketType.member)
    @commands.slash_command(description=f"{desc_prefix}Regola il volume della musica.")
    async def volume(
            self,
            inter: disnake.ApplicationCommandInteraction, *,
            value: int = commands.Param(name="livello", description="livello compreso tra 5 e 150", min_value=5.0, max_value=150.0)
    ):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        embed = disnake.Embed(color=disnake.Colour.red())

        update = False

        if value is None:

            view = VolumeInteraction(inter)

            embed.colour = self.bot.get_color(inter.guild.me)
            embed.description = "**Seleziona il livello del volume qui sotto:**"
            await inter.send(embed=embed, ephemeral=True, view=view)
            await view.wait()
            if view.volume is None:
                return

            value = view.volume
            update = True

        elif not 4 < value < 151:
            embed.description = "Il volume deve essere compreso tra **5** e **150**."
            return await inter.send(embed=embed, ephemeral=True)

        await player.set_volume(value)

        txt = [f"regolato il volume su **{value}%**", f"volume impostato su **{value}**"]
        await self.interaction_message(inter, txt, update=update)


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(2, 10), commands.BucketType.member)
    @commands.slash_command(description=f"{desc_prefix}mettere in pausa la musica.")
    async def pause(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        embed = disnake.Embed(color=disnake.Colour.red())

        if player.paused:
            await send_message(inter, embed=embed)
            return

        await player.set_pause(True)

        txt = ["ha messo in pausa la musica.", "Musica in pausa."]

        await self.interaction_message(inter, txt, rpc_update=True)


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(2, 10), commands.BucketType.member)
    @commands.slash_command(description=f"{desc_prefix}Riprendi/Metti in pausa la musica.")
    async def resume(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        embed = disnake.Embed(color=disnake.Colour.red())

        if not player.paused:
            embed.description = "La musica non è in pausa."
            await send_message(inter, embed=embed)
            return

        await player.set_pause(False)

        txt = ["ha ripreso la musica.", "la musica è ripresa"]
        await self.interaction_message(inter, txt, rpc_update=True)


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(2, 10), commands.BucketType.member)
    @commands.max_concurrency(1, commands.BucketType.member)
    @commands.slash_command(description=f"{desc_prefix}Avanzamento veloce/Riprendi il brano in un punto specifico.")
    async def seek(
            self,
            inter: disnake.ApplicationCommandInteraction,
            position: str = commands.Param(name="tempo", description="È ora di andare avanti/indietro (ex: 1:45 / 40 / 0:30)", autocomplete=seek_suggestions)
    ):

        embed = disnake.Embed(color=disnake.Colour.red())

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if player.current.is_stream:
            embed.description = "Non è possibile utilizzare questo comando in un livestream."
            await send_message(inter, embed=embed)
            return

        position = position.split(" | ")[0]

        seconds = string_to_seconds(position)

        if seconds is None:
            embed.description = "Hai usato un tempo non valido! Usa secondi (1 o 2 cifre) o nel formato (minuti):(secondi)"
            return await send_message(inter, embed=embed)

        milliseconds = seconds * 1000

        if milliseconds < 0:
            milliseconds = 0

        try:
            await player.seek(milliseconds)

            if player.paused:
                await player.set_pause(False)

        except Exception as e:
            embed.description = f"Si è verificato un errore nel comando\n```py\n{repr(e)}```."
            await send_message(inter, embed=embed)
            return

        txt = [
            f"{'Avanzate' if milliseconds > player.position else 'è tornato'} l'ora della musica: {time_format(milliseconds)}",
            f"Il tempo della musica era {'Avanzate' if milliseconds > player.position else 'restituito'} para: {time_format(milliseconds)}"
        ]
        await self.interaction_message(inter, txt)

        await asyncio.sleep(2)
        self.bot.loop.create_task(player.process_rpc())


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(3, 5), commands.BucketType.member)
    @commands.slash_command(description=f"{desc_prefix}Seleziona la modalità di ripetizione tra: corrente / in coda o disattivata.")
    async def loop_mode(
            self,
            inter: disnake.ApplicationCommandInteraction,
            mode: Literal['current', 'queue', 'off'] = commands.Param(name="modo",
                description="current = Brano / coda corrente = fila / off = disattivare"
            )
    ):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if mode == player.loop:
            await self.interaction_message(inter, "Non sono state apportate modifiche alla modalità di ripetizione corrente.")
            return

        if mode == 'off':
            mode = False
            player.current.track_loops = 0

        elif mode == "current":
            player.current.track_loops = 0

        if mode:
            txt = [f"riproduzione attivata di {'música' if mode == 'current' else 'fila'}.", f"ripetizione della {'musica' if mode == 'current' else 'fila'} attivata con successo."]
        else:
            txt = ['spento ripetere.', "Ripeti disabilitato."]

        player.loop = mode

        self.bot.loop.create_task(player.process_rpc())

        await self.interaction_message(inter, txt)


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(3, 5), commands.BucketType.member)
    @commands.slash_command(description=f"{desc_prefix}Imposta il numero di ripetizioni del brano corrente.")
    async def loop_amount(
            self,
            inter: disnake.ApplicationCommandInteraction,
            value: int = commands.Param(name="valore", description="numero di ripetizioni.")
    ):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        player.current.track_loops = value

        embed = disnake.Embed(color=self.bot.get_color(inter.guild.me))

        txt = f"{inter.author.mention} impostare il numero di ripetizioni del brano " \
              f"[`{(fix_characters(player.current.title, 25))}`]({player.current.uri}) per **{value}**."

        player.command_log = txt
        embed.description=f"**Numero di ripetizioni [{value}] messo in musica:** [`{player.current.title}`]({player.current.uri})"
        embed.set_thumbnail(url=player.current.thumb)
        await inter.send(embed=embed, ephemeral=True)

        await player.update_message(rpc_update=True)


    @check_voice()
    @has_player()
    @is_dj()
    @commands.slash_command(description=f"{desc_prefix}Rimuovere un brano specifico dalla coda.")
    async def remove(
            self,
            inter: disnake.ApplicationCommandInteraction,
            query: str = commands.Param(name="nome", description="Nome completo del brano.", autocomplete=queue_tracks)
    ):

        embed = disnake.Embed(color=disnake.Colour.red())

        index = get_track_index(inter, query)

        if index is None:
            embed.description = f"{inter.author.mention} **non ci sono brani in coda con il nome: {query}**"
            await inter.send(embed=embed, ephemeral=True)
            return

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        track = player.queue[index]

        player.queue.remove(track)

        embed = disnake.Embed(color=disnake.Colour.green())

        txt = f"{inter.author.mention} rimosso il brano [`{(fix_characters(track.title, 25))}`]({track.uri}) dalla coda."

        player.command_log = txt
        embed.description=f"**Brano rimosso:** [`{track.title}`]({track.uri})"
        embed.set_thumbnail(url=track.thumb)
        await inter.send(embed=embed, ephemeral=True)

        await player.update_message()


    @check_voice()
    @has_player()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(2, 10), commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Aggiungi nuovamente i brani riprodotti in coda.")
    async def readd(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        embed = disnake.Embed(color=disnake.Colour.red())

        if not player.played:
            embed.description = f"{inter.author.mention} **non ci sono brani in riproduzione.**"
            await inter.send(embed=embed, ephemeral=True)
            return

        embed.colour = disnake.Colour.green()
        txt = f"{inter.author.mention} **aggiunto nuovamente [{(qsize:=len(player.played))}] brano(i) riprodotto(i) in coda.**"

        player.played.reverse()
        player.queue.extend(player.played)
        player.played.clear()

        player.command_log = txt
        embed.description = f"**hai aggiunto {qsize} brano(i).**"
        await inter.send(embed=embed, ephemeral=True)
        await player.update_message()

        if not player.current:
            await player.process_next()
        else:
            await player.update_message()


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(2, 8), commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Salta al brano specificato.")
    async def skipto(
            self,
            inter: disnake.ApplicationCommandInteraction, *,
            query: str = commands.Param(
                name="nome",
                description="Nome completo del brano.",
                autocomplete=queue_tracks
            ),
            bump_only: str = commands.Param(
                choices=["si", "no"],
                description="Ascolta subito il brano (senza ruotare la fila)",
                default="no"
            )
    ):

        embed = disnake.Embed(color=disnake.Colour.red())

        index = get_track_index(inter, query)

        if index is None:
            embed.description = f"{inter.author.mention} **non ci sono brani in coda con il nome: {query}**"
            await inter.send(embed=embed, ephemeral=True)
            return

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        track = player.queue[index]

        player.queue.append(player.last_track)
        player.last_track = None

        if player.loop == "current":
            player.loop = False

        if bump_only == "si":
            del player.queue[index]
            player.queue.appendleft(track)

        elif index > 0:
            player.queue.rotate(0 - (index))

        embed.colour = disnake.Colour.green()

        player.command_log = f"{inter.author.mention} passa al brano corrente"
        embed.description = f"**Sei saltato al ritmo della musica:** [`{track.title}`]({track.uri})"
        embed.set_thumbnail(track.thumb)
        await inter.send(embed=embed, ephemeral=True)

        await player.stop()


    @check_voice()
    @has_source()
    @is_dj()
    @commands.slash_command(description=f"{desc_prefix}Sposta un brano nella posizione specificata nella coda.")
    async def move(
            self,
            inter: disnake.ApplicationCommandInteraction,
            query: str = commands.Param(name="nome", description="Nome completo del brano.", autocomplete=queue_tracks),
            position: int = commands.Param(name="posizione", description="Posizione di destinazione in coda.", default=1)
    ):

        embed = disnake.Embed(colour=disnake.Colour.red())

        if position < 1:
            embed.description = f"{inter.author.mention}, {position} non è una posizione valida."
            await send_message(inter, embed=embed)
            return

        index = get_track_index(inter, query)

        if index is None:
            embed.description = f"{inter.author.mention} **non ci sono brani in coda con il nome: {query}**"
            await inter.send(embed=embed, ephemeral=True)
            return

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        track = player.queue[index]

        player.queue.remove(track)

        player.queue.insert(int(position) - 1, track)

        txt = f"{inter.author.mention} ha spostato il brano [`{fix_characters(track.title, limit=25)}`]({track.uri}) alla posizione **[{position}]** della fila."

        embed = disnake.Embed(color=disnake.Colour.green())

        embed.description = f"**Il brano è stato spostato nella posizione {position} della fila:** [`{fix_characters(track.title)}`]({track.uri})"
        embed.set_thumbnail(url=track.thumb)
        player.command_log = txt
        await inter.send(embed=embed, ephemeral=True)

        await player.update_message()


    @check_voice()
    @has_source()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(2, 10), commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Ruota la fila per il brano specificato.")
    async def rotate(
            self,
            inter: disnake.ApplicationCommandInteraction,
            query: str = commands.Param(
                name="nome", description="Nome completo del brano.", autocomplete=queue_tracks)
    ):

        embed = disnake.Embed(colour=disnake.Colour.red())

        index = get_track_index(inter, query)

        if index is None:
            embed.description = f"{inter.author.mention} **non ci sono brani in coda con il nome: {query}**"
            await inter.send(embed=embed, ephemeral=True)
            return

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        track = player.queue[index]

        if index <= 0:
            embed.description = f"{inter.author.mention} **il brano **[`{track.title}`]({track.uri}) é il prossimo in coda."
            await inter.send(embed=embed, ephemeral=True)
            return

        player.queue.rotate(0 - (index))

        embed.colour = disnake.Colour.green()

        txt = f"{inter.author.mention} ruota i brani in coda [`{(fix_characters(track.title, limit=25))}`]({track.uri})."

        embed.description = f"**Coda dei brani mescolata:** [`{track.title}`]({track.uri})."
        embed.set_thumbnail(url=track.thumb)
        player.command_log = txt
        await inter.send(embed=embed, ephemeral=True)

        await player.update_message()


    @check_voice()
    @has_source()
    @is_dj()
    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Attiva/disattiva l'effetto nightcore (musica accelerata con un tono più alto).")
    async def nightcore(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        player.nightcore = not player.nightcore

        if player.nightcore:
            await player.set_timescale(pitch=1.2, speed=1.1)
            txt = ["attivo", "attivato"]
        else:
            try:
                del player.filters["timescale"]
            except:
                pass
            await player.update_filters()
            txt = ["disattivo", "disattivato"]

        txt = [f"{txt[0]} l'effetto nightcore.", f"Effetto nightcore {txt[1]}."]

        await self.interaction_message(inter, txt, rpc_update=True)


    @has_source()
    @commands.slash_command(description=f"{desc_prefix}Invia nuovamente il messaggio al player con il brano corrente.")
    async def nowplaying(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if player.static:
            await inter.send("questo comando non può essere utilizzato in modalità player fisso.", ephemeral=True)
            return

        if player.has_thread:
            embed = disnake.Embed(
                    color=self.bot.get_color(inter.guild.me),
                    description=f"questo comando non può essere utilizzato con una conversazione attiva su [thread]({player.message.jump_url}) del player."
                )
            await inter.send(embed=embed, ephemeral=True)
            return

        await player.destroy_message()
        await player.invoke_np()

        await inter.send("Bot riavviato con successo!", ephemeral=True)


    @has_player()
    @is_dj()
    @commands.user_command(name="add dj")
    async def adddj_u(self, inter: disnake.UserCommandInteraction):
        await self.add_dj(inter, user=inter.target)


    @has_player()
    @is_dj()
    @commands.slash_command(description=f"{desc_prefix}Aggiungi un membro all'elenco dei DJ nella sessione corrente.")
    async def add_dj(
            self,
            inter: disnake.ApplicationCommandInteraction, *,
            user: disnake.User = commands.Param(name="membro", description="Membro da aggiungere.")
    ):

        error_text = None

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if user == inter.author:
            error_text = "Non puoi aggiungerti alla lista dei DJ."
        elif user.guild_permissions.manage_channels:
            error_text = f"non puoi aggiungere il membro {user.mention} nella DJ list (ha il permesso di **gestire i canali**)."
        elif user in player.dj:
            error_text = f"Il membro {user.mention} è già nell'elenco dei DJ"

        if error_text:
            embed = disnake.Embed(color=disnake.Colour.red(), description=error_text)
            await send_message(inter, embed=embed)
            return

        player.dj.add(user)
        text = [f"aggiunto {user.mention} alla lista dei DJ.", f"{user.mention} è stato aggiunto alla lista dei DJ."]

        if (player.static and inter.channel == player.text_channel) or isinstance(inter.application_command, commands.InvokableApplicationCommand):
            await inter.send(f"{inter.target.mention} aggiunto alla lista dei DJ!")

        await self.interaction_message(inter, txt=text, update=True)


    @check_voice()
    @has_player()
    @is_dj()
    @commands.slash_command(description=f"{desc_prefix}Ferma la riproduzione e disconnettimi dal canale vocale.")
    async def stop(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        embed = disnake.Embed(color=disnake.Colour.red())

        player.command_log = f"{inter.author.mention} **ha fermato la riproduzione!**"
        embed.description = f"**{inter.author.mention} ha fermato la riproduzione!**"
        await inter.send(embed=embed, ephemeral=player.static or player.has_thread)

        await player.destroy()


    @has_player()
    @commands.slash_command(name="queue")
    async def q(self, inter):
        pass


    @check_voice()
    @has_player()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(3, 5), commands.BucketType.member)
    @q.sub_command(name="shuffle", description=f"{desc_prefix}Mixa i brani in coda")
    async def shuffle_(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if len(player.queue) < 3:
            embed = disnake.Embed(color=disnake.Colour.red())
            embed.description = "La coda deve avere almeno 3 brani da mixare."
            await send_message(inter, embed=embed)
            return

        shuffle(player.queue)

        txt = [f"mixato le canzoni in coda.",
               "canzoni mixate con successo."]

        await self.interaction_message(inter, txt)


    @check_voice()
    @is_dj()
    @commands.dynamic_cooldown(user_cooldown(1, 5), commands.BucketType.guild)
    @q.sub_command(description=f"{desc_prefix}Invertire l'ordine dei brani nella coda")
    async def reverse(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if len(player.queue) < 2:
            embed = disnake.Embed(colour=disnake.Colour.red())
            embed.description = "La coda deve avere almeno 2 brani per invertire l'ordine."
            await send_message(inter, embed=Embed)
            return

        player.queue.reverse()

        text = [f"invertito l'ordine dei brani in coda.", "Coda invertita con successo!"]
        await self.interaction_message(inter, txt=text, update=True)


    @q.sub_command(description=f"{desc_prefix}Visualizza i brani in coda.")
    @commands.max_concurrency(1, commands.BucketType.member)
    async def show(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if not player.queue:
            embedvc = disnake.Embed(
                colour=disnake.Colour.red(),
                description='Al momento non ci sono brani in coda.'
            )
            await send_message(inter, embed=embedvc)
            return

        view = QueueInteraction(player, inter.author)
        embed = view.embed

        await inter.send(embed=embed, view=view, ephemeral=True)

        await view.wait()


    @has_player()
    @is_dj()
    @commands.max_concurrency(1, commands.BucketType.guild)
    @commands.cooldown(1, 5, commands.BucketType.member)
    @commands.slash_command(description=f"{desc_prefix}Cancella la coda della musica.")
    async def clear(
            self,
            inter: disnake.ApplicationCommandInteraction,
            song_name: str = commands.Param(name="nome_del_brano",description="Inserisci il nome del brano.", default=None),
            song_author: str = commands.Param(name="autore_del_brano", description="Inserisci il nome dell'autore del brano.", autocomplete=queue_author, default=None),
            user: disnake.Member = commands.Param(name='utente', description="Include i brani richiesti dall'utente selezionato.", default=None),
            playlist: str = commands.Param(description="Inserisci il nome della playlist.", autocomplete=queue_playlist, default=None),
            time_below: str = commands.Param(name="tempo_sotto", description="includere brani con una durata inferiore al tempo impostato (es. 1:23).", default=None),
            time_above: str = commands.Param(name="tempo_sopra", description="includere brani con una durata superiore al tempo impostato (es. 1:45).", default=None),
            range_start: int = commands.Param(name="inzio_intervallo", description="include i brani dalla coda da una posizione specifica nella coda.", min_value=1.0, max_value=500.0, default=None),
            range_end: int = commands.Param(name="fine_intervallo", description="includere i brani dalla coda in una posizione specifica nella coda.", min_value=1.0, max_value=500.0, default=None)
    ):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        if not player.queue:
            await inter.send("Non ci sono brani in coda.", ephemeral=True)
            return

        filters = []

        if song_name:
            filters.append('song_name')
        if song_author:
            filters.append('song_author')
        if user:
            filters.append('user')
        if playlist:
            filters.append('playlist')

        if time_below and time_above:
            raise GenericError("Devi scegliere solo una delle opzioni: **tempo_sotto** o **tempo_sopra**.")

        if time_below:
            filters.append('time_below')
            time_below = string_to_seconds(time_below) * 1000
        if time_above:
            filters.append('time_above')
            time_above = string_to_seconds(time_above) * 1000

        if not filters and not range_start and not range_end:
            player.queue.clear()
            txt = ['cancellata la coda della musica.', '**La coda è stata cancellata correttamente.**']

        else:

            if range_start and range_end:

                if range_start >= range_end:
                    raise GenericError("**La posizione finale deve essere maggiore della posizione iniziale!**")

                song_list = list(player.queue)[range_start-1: range_end-1]

            elif range_start:
                song_list = list(player.queue)[range_start-1:]
            elif range_end:
                song_list = list(player.queue)[:range_end-1]
            else:
                song_list = list(player.queue)

            deleted_tracks = 0

            for t in song_list:

                temp_filter = list(filters)

                if 'time_below' in temp_filter and t.duration <= time_below:
                    temp_filter.remove('time_below')

                elif 'time_above' in temp_filter and t.duration >= time_above:
                    temp_filter.remove('time_above')

                if 'song_name' in temp_filter and song_name.lower() in t.title.lower():
                    temp_filter.remove('song_name')

                if 'song_author' in temp_filter and song_author.lower() in t.author.lower():
                    temp_filter.remove('song_author')

                if 'user' in temp_filter and user == t.requester:
                    temp_filter.remove('user')

                try:
                    if 'playlist' in temp_filter and playlist == t.playlist['name']:
                        temp_filter.remove('playlist')
                except:
                    pass

                if not temp_filter:
                    player.queue.remove(t)
                    deleted_tracks += 1

            if not deleted_tracks:
                await inter.send("Nessuna canzone trovata!", ephemeral=True)
                return

            txt = [f"rimuovi {deleted_tracks} brani dalla coda via clear.",
                   f"{deleted_tracks} brani rimossi con successo dalla coda."]

        await self.interaction_message(inter, txt)


    @has_player()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    @commands.slash_command(description=f"{desc_prefix}Attiva/Disattiva la modalità Non-Stop (24/7).")
    async def nonstop(self, inter: disnake.ApplicationCommandInteraction):

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        player.nonstop = not player.nonstop

        texts = ["attivo", "attivato"] if player.nonstop else ["disattivo", "disattivato"]

        text = [f"{texts[0]} la modaliitá Non-Stop del bot.", f"Modalitá Non-Stop {texts[1]} con successo!"]

        if not len(player.queue):
            player.queue.extend(player.played)
            player.played.clear()

        if player.current:
            await self.interaction_message(inter, txt=text, update=True)
            return

        await self.interaction_message(inter, text)

        await player.process_next()


    @check_voice()
    @has_player()
    @is_dj()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Migrare il bot su un altro server musicale.")
    async def change_node(
            self,
            inter: disnake.ApplicationCommandInteraction,
            node: str = commands.Param(name="server", description="Server musicale", autocomplete=node_suggestions)
    ):

        if isinstance(self.bot.music, YTDLManager):
            raise GenericError("Questo comando non supporta la modalità YTDL abilitata.")

        if not node in self.bot.music.nodes:
            raise GenericError(f"Il server musicale **{node}** non è stato trovato.")

        player: LavalinkPlayer = self.bot.music.players[inter.guild.id]

        if node == player.node.identifier:
            raise GenericError(f"Il bot è già sul server musicale **{node}**.")

        await player.change_node(node)

        txt = [f"Bot migrato sul server musicale **{node}**",
               f"**Il bot è stato migrato al server musicale:** `{node}`"]

        await self.interaction_message(inter, txt)


    @commands.Cog.listener("on_message_delete")
    async def player_message_delete(self, message: disnake.Message):

        if not message.guild:
            return

        try:

            player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[message.guild.id]

            if message.id != player.message.id:
                return

        except (AttributeError, KeyError):
            return

        thread = self.bot.get_channel(message.id)

        if not thread:
            return

        player.message = None
        await thread.edit(archived=True, locked=True, name=f"archiviato: {thread.name}")


    @commands.Cog.listener()
    async def on_ready(self):

        for guild_id in list(self.bot.music.players):
            try:
                player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[guild_id]

                if player.is_connected:
                    continue

                await player.connect(player.channel_id)
            except:
                traceback.print_exc()


    async def process_player_interaction(
            self,
            interaction: Union[disnake.MessageInteraction, disnake.ModalInteraction],
            control: str,
            subcmd: str,
            kwargs: dict
    ):

        cmd = self.bot.get_slash_command(control)

        if not cmd:
            raise GenericError(f"comando {control} non trovato/implementato.")

        await check_cmd(cmd, interaction)

        if subcmd:
            cmd = cmd.children.get(subcmd)
            await check_cmd(cmd, interaction)

        await cmd(interaction, **kwargs)

        try:
            player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[interaction.guild.id]
            player.interaction_cooldown = True
            await asyncio.sleep(1)
            player.interaction_cooldown = False
        except (KeyError, AttributeError):
            pass


    @commands.Cog.listener("on_button_click")
    async def player_controller(self, interaction: disnake.MessageInteraction):

        if not interaction.data.custom_id.startswith("musicplayer_"):
            return

        control = interaction.data.custom_id[12:]

        kwargs = {}

        subcmd = None

        try:

            if control in ("add_song", "enqueue_fav"):

                if not interaction.user.voice:
                    raise GenericError("**Devi entrare in un canale vocale per usare questo pulsante.**")

                if control == "add_song":

                    await interaction.response.send_modal(
                        title="Richiedi una canzone",
                        custom_id="modal_add_song",
                        components=[
                            disnake.ui.TextInput(
                                style=disnake.TextInputStyle.short,
                                label="Nome/link di una canzone.",
                                placeholder="Nome o link youtube/spotify/soundcloud etc.",
                                custom_id="song_input",
                                max_length=150,
                            )
                        ],
                    )

                    return

                else:  # enqueue_fav

                    try:
                        await self.player_interaction_concurrency.acquire(interaction)
                    except Exception:
                        raise GenericError("**Hai già un'interazione aperta...**")

                    await interaction.response.defer()

                    opts = [disnake.SelectOption(label=f, value=f, emoji="<:play:734221719774035968>")
                            for f in (await fav_list(interaction, ""))]

                    if not opts:
                        await self.player_interaction_concurrency.release(interaction)
                        raise GenericError("**Non hai preferiti...\n"
                                           "Aggiungine uno usando il comando /fav add**")

                    opts.append(disnake.SelectOption(label="Annulla", value="cancel", emoji="❌"))

                    components = [
                        disnake.ui.Select(
                            custom_id=f"enqueue_fav_{interaction.id}",
                            options=opts
                        )
                    ]

                    await interaction.send(
                        embed=disnake.Embed(
                            color=self.bot.get_color(interaction.guild.me),
                            description="**Seleziona un preferito:**"
                        ).set_footer(text="Hai solo 45 secondi per scegliere!"),
                        components=components,
                        ephemeral=True
                    )

                    try:
                        select_interaction: disnake.MessageInteraction = await self.bot.wait_for(
                            "dropdown",
                            timeout=45,
                            check=lambda i: i.author == interaction.author and i.data.custom_id == f"enqueue_fav_{interaction.id}"
                        )
                    except asyncio.TimeoutError:
                        await self.player_interaction_concurrency.release(interaction)
                        return

                    await self.player_interaction_concurrency.release(interaction)

                    if select_interaction.data.values[0] == "cancel":
                        await select_interaction.response.edit_message(
                            embed=disnake.Embed(
                                description="**Selezione annullata!**",
                                color=self.bot.get_color(interaction.guild.me)
                            ),
                            components=None
                        )
                        return

                    interaction.token = select_interaction.token
                    interaction.id = select_interaction.id
                    interaction.response = select_interaction.response

                    query = f"> fav: {select_interaction.data.values[0]}"

                    control = "play"

                    kwargs.update(
                        {
                            "query": query,
                            "position": 0,
                            "options": False,
                            "manual_selection": True,
                            "source": "ytsearch",
                            "repeat_amount": 0,
                            "hide_playlist": False,
                            "server": None
                        }
                    )

            else:

                try:
                    player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[interaction.guild.id]
                except KeyError:
                    return

                if interaction.message != player.message:
                    return

                if player.interaction_cooldown:
                    raise GenericError("Il bot è in cooldown, riprova tra un momento.")

                vc = self.bot.get_channel(player.channel_id)

                if not vc:
                    self.bot.loop.create_task(player.destroy(force=True))
                    return

                if control == "help":
                    embed = disnake.Embed(
                        description="<:sqrinfodt:959485004600193106> **INFORMAZIONI SUL BOT** <:sqrinfodt:959485004600193106>\n\n"
                                    "<:playpause:958992461731082270> `= Metti in pausa/riprendi la musica.`\n"
                                    "<:bckwrd:958995440504832050> `= Torna al brano riprodotto in precedenza.`\n"
                                    "<:frward:958994691322421248> `= Salta al brano successivo.`\n"
                                    "<:shufflex:958996209484304384> `= Mescola i brani in coda.`\n"
                                    "<:addsong:958997764694474772> `= Richiedi una canzone.`\n"
                                    # "🇳 `= Ativar/Desativar o efeito Nightcore`\n"
                                    "<:sqrsmall:958999408211542026> `= Arrestare la riproduzione e si disconnette dal canale.`\n"
                                    "<:volumehigh:958986651940556830> `= Regola il volume.`\n"
                                    "<:reppeat:959001381052756039> `= Abilita/Disabilita la ripetizione.`\n"
                                    "<:queue:959000316290945054> `= Visualizza la coda della musica.`\n",
                        color=self.bot.get_color(interaction.guild.me)
                    )

                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                if not interaction.author.voice or interaction.author.voice.channel != vc:
                    raise GenericError(f"Devi essere nel canale <#{vc.id}> per usare i pulsanti del bot.")

                if control == "volume":
                    kwargs = {"value": None}

                elif control == "queue":
                    subcmd = "show"

                elif control == "shuffle":
                    subcmd = "shuffle"
                    control = "queue"

                elif control == "seek":
                    kwargs = {"position": None}

                elif control == "playpause":
                    control = "pause" if not player.paused else "resume"

                elif control == "loop_mode":

                    if player.loop == "current":
                        kwargs['mode'] = 'queue'
                    elif player.loop == "queue":
                        kwargs['mode'] = 'off'
                    else:
                        kwargs['mode'] = 'current'

            await self.process_player_interaction(
                interaction = interaction,
                control = control,
                subcmd = subcmd,
                kwargs = kwargs
            )

        except Exception as e:
            self.bot.dispatch('interaction_player_error', interaction, e)


    @commands.Cog.listener("on_modal_submit")
    async def song_request_modal(self, inter: disnake.ModalInteraction):

        if inter.custom_id != "modal_add_song":
            return

        try:

            query = inter.text_values["song_input"]

            kwargs = {
                "query": query,
                "position": 0,
                "options": False,
                "manual_selection": True,
                "source": "ytsearch",
                "repeat_amount": 0,
                "hide_playlist": False,
                "server": None
            }

            await self.process_player_interaction(
                interaction = inter,
                control = "play",
                kwargs=kwargs,
                subcmd="",
            )
        except Exception as e:
            self.bot.dispatch('interaction_player_error', inter, e)


    @commands.Cog.listener("on_message")
    async def song_requests(self, message: disnake.Message):

        if not message.guild:
            return

        if message.is_system():
            return

        if message.author.bot:

            if message.flags.ephemeral:
                return

            try:
                player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[message.guild.id]
            except KeyError:
                return

            if message.channel != player.text_channel:
                return

            player.last_message_id = message.id
            return

        try:
            data = await self.bot.db.get_data(message.guild.id, db_name='guilds')
        except AttributeError:
            return

        try:
            player: Union[LavalinkPlayer, YTDLPlayer, None] = self.bot.music.players[message.guild.id]
            if player.text_channel == message.channel:
                player.last_message_id = message.id
        except (AttributeError, KeyError):
            player: Union[LavalinkPlayer, YTDLPlayer, None] = None

        if player and isinstance(message.channel, disnake.Thread) and not player.static:

            text_channel = message.channel

        else:

            static_player = data['player_controller']

            channel_id = static_player['channel']

            if not channel_id or (static_player['message_id'] != str(message.channel.id) and str(message.channel.id) != channel_id):
                return

            text_channel = self.bot.get_channel(int(channel_id))

            if not text_channel or not text_channel.permissions_for(message.guild.me).send_messages:
                return

        if not message.content:
            await message.delete()
            await message.channel.send(f"{message.author.mention} devi inviare un link/nome del brano.", delete_after=9)
            return

        try:
            await self.song_request_concurrency.acquire(message)
        except:
            await message.delete()
            await message.channel.send(f"{message.author.mention} devi attendere che la richiesta del brano precedente venga caricata...", delete_after=10)
            return

        message.content = message.content.strip("<>")

        msg = None

        error = None

        try:

            if not URL_REG.match(message.content):
                message.content = f"ytsearch:{message.content}"

            elif "&list=" in message.content:

                view = SelectInteraction(
                    user = message.author,
                    opts = [
                        disnake.SelectOption(label="Musica", emoji="🎵", description="Carica la canzone solo dal link.", value="music"),
                        disnake.SelectOption(label="Playlist", emoji="🎶", description="Carica la playlist con il brano corrente.", value="playlist"),
                    ], timeout=30)

                embed = disnake.Embed(
                    description="**Il link contiene video con playlist.**\n`selezionare un'opzione entro 30 secondi per procedere.`",
                    color=self.bot.get_color(message.guild.me)
                )

                msg = await message.channel.send(message.author.mention,embed=embed, view=view)

                await view.wait()

                try:
                    await view.inter.response.defer()
                except:
                    pass

                if view.selected == "music":
                    message.content = YOUTUBE_VIDEO_REG.match(message.content).group()

            await self.parse_song_request(message, text_channel, data, response=msg)

            if not isinstance(message.channel, disnake.Thread):
                await message.delete()
                try:
                    await msg.delete()
                except:
                    pass

        except GenericError as e:
            error = f"{message.author.mention}. {e}"

        except Exception as e:
            traceback.print_exc()
            error = f"{message.author.mention} **Si è verificato un errore durante il tentativo di ottenere risultati per la tua ricerca:** ```py\n{e}```"

        if error:

            if msg:
                await msg.edit(content=error, embed=None, view=None, delete_after=7)
            else:
                await message.channel.send(error, delete_after=7)
            await message.delete()

        await self.song_request_concurrency.release(message)


    async def parse_song_request(self, message, text_channel, data, *, response=None):

        if not message.author.voice:
            raise GenericError("devi entrare in un canale vocale per richiedere un brano.")

        if not message.author.voice.channel.permissions_for(message.guild.me).connect:
            raise GenericError(f"Non ho l'autorizzazione per collegarmi al canale <{message.author.voice.channel.id}>")

        if not message.author.voice.channel.permissions_for(message.guild.me).speak:
            raise GenericError(f"Non mi è permesso parlare sul canale <{message.author.voice.channel.id}>")

        try:
            if message.guild.me.voice.channel != message.author.voice.channel:
                raise GenericError(f"Devi entrare nel canale <#{message.guild.me.voice.channel.id}> per richiedere un brano.")
        except AttributeError:
            pass

        tracks, node = await self.get_tracks(message.content, message.author)

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.get_player(
            guild_id=message.guild.id,
            cls=LavalinkPlayer,
            requester=message.author,
            guild=message.guild,
            channel=text_channel,
            static=True,
            skin=data["player_controller"]["skin"],
            node_id=node.identifier,
            bot=self.bot
        )

        if not player.message:
            try:
                cached_message = await text_channel.fetch_message(int(data['player_controller']['message_id']))
            except:
                cached_message = await send_idle_embed(message, bot=self.bot)
                data['player_controller']['message_id'] = str(cached_message.id)
                await self.bot.db.update_data(message.guild.id, data, db_name='guilds')

            player.message = cached_message

        embed = disnake.Embed(color=self.bot.get_color(message.guild.me))

        try:
            player.queue.extend(tracks.tracks)
            if isinstance(message.channel, disnake.Thread):
                embed.description = f"> <:addsong:958997764694474772> **┃ Playlist aggiunta:** [`{tracks.data['playlistInfo']['name']}`]({message.content})\n" \
                                    f"> <:faceheadphone:958985516357943337> **┃ Richiesto da:** {message.author.mention}\n" \
                                    f"> <:compactdisc:959076017408978944> **┃ Brano(i):** `[{len(tracks.tracks)}]`"
                embed.set_thumbnail(url=tracks.tracks[0].thumb)
                if response:
                    await response.edit(content=None, embed=embed, view=None)
                else:
                    await message.channel.send(embed=embed)

            else:
                player.command_log = f"{message.author.mention} aggiunto la playlist " \
                                     f"[`{fix_characters(tracks.data['playlistInfo']['name'], 20)}`]({tracks.tracks[0].playlist['url']}) `({len(tracks.tracks)})`."


        except AttributeError:
            player.queue.append(tracks[0])
            if isinstance(message.channel, disnake.Thread):
                embed.description = f"> <:musicalnote:959073198413058169> **┃ Aggiunto:** [`{tracks[0].title}`]({tracks[0].uri})\n" \
                                    f"> <:albumauthorduotone:958976606003683369> **┃ Autore:** `{tracks[0].author}`\n" \
                                    f"> <:faceheadphone:958985516357943337> **┃ Richiesto da** {message.author.mention}\n" \
                                    f"> <:hourglasx:959071281251246110> **┃ Durata:** `{time_format(tracks[0].duration) if not tracks[0].is_stream else '🔴 Livestream'}` "
                embed.set_thumbnail(url=tracks[0].thumb)
                if response:
                    await response.edit(content=None, embed=embed, view=None)
                else:
                    await message.channel.send(embed=embed)

            else:
                duration = time_format(tracks[0].duration) if not tracks[0].is_stream else '🔴 Livestream'
                player.command_log = f"{message.author.mention} aggiunto [`{fix_characters(tracks[0].title, 20)}`]({tracks[0].uri}) `({duration})`."

        if not player.is_connected:
            await self.do_connect(message, channel=message.author.voice.channel)

        if not player.current:
            await player.process_next()
        else:
            await player.update_message()

        await asyncio.sleep(1)


    def cog_unload(self):

        for m in list(sys.modules):
            if m.startswith("utils.music"):
                del sys.modules[m]

    async def cog_before_message_command_invoke(self, inter):
        await self.cog_before_slash_command_invoke(inter)


    async def cog_before_user_command_invoke(self, inter):
        await self.cog_before_slash_command_invoke(inter)


    async def interaction_message(self, inter: disnake.Interaction, txt, update=False, rpc_update=False):

        try:
            txt, txt_ephemeral = txt
        except:
            txt_ephemeral = False

        player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[inter.guild.id]

        component_interaction = isinstance(inter, disnake.MessageInteraction)

        player.command_log = f"{inter.author.mention} {txt}"
        await player.update_message(interaction=False if (update or not component_interaction) else inter, rpc_update=rpc_update)

        if not component_interaction:

            txt = f"{inter.author.mention} **{txt}**"

            embed = disnake.Embed(color=disnake.Colour.green(),
                                description=txt_ephemeral or txt)

            if not inter.response.is_done():
                await inter.send(embed=embed, ephemeral=True)


    async def process_nodes(self):

        if self.bot.config["YTDLMODE"]:
            return

        await self.bot.wait_until_ready()

        for k,v in self.bot.config.items():

            if not k.lower().startswith("lavalink_node_"):
                continue
            try:
                self.bot.loop.create_task(self.connect_node(json.loads(v)))
            except Exception as e:
                print(f"Impossibile aggiungere il nodo: {k}, errore: {repr(e)}")

        if self.bot.config['START_LOCAL_LAVALINK']:
            self.bot.loop.create_task(self.connect_local_lavalink())


    @wavelink.WavelinkMixin.listener("on_node_connection_closed")
    async def node_connection_closed(self, node: wavelink.Node):

        retries = 0
        backoff = 7

        for player in list(node.players.values()):

            try:

                new_node: wavelink.Node = self.bot.music.get_best_node()

                if not new_node:

                    try:
                        await player.text_channel.send("La riproduzione é stata interrotta per mancanza di server musicali...", delete_after=11)
                    except:
                        pass
                    await player.destroy()
                    continue

                await player.change_node(new_node.identifier)
                await player.update_message()

            except:

                traceback.print_exc()
                continue

        print(f"{self.bot.user} - [{node.identifier}] Connessione persa - riconnessione tra {int(backoff)} secondi.")

        await asyncio.sleep(backoff)

        while True:

            if retries == 30:
                print(f"{self.bot.user} - [{node.identifier}] Tutti i tentativi di riconnessione sono falliti...")
                return

            try:
                async with self.bot.session.get(node.rest_uri) as r:
                    if r.status in [401, 200, 400]:
                        await node.connect(self.bot)
                        return
                    error = r.status
            except Exception as e:
                error = repr(e)

            backoff *= 1.5
            print(f'{self.bot.user} - Impossibile riconnettersi al server [{node.identifier}] riprovare {backoff} secondi. Errore: {error}')
            await asyncio.sleep(backoff)
            retries += 1
            continue


    @wavelink.WavelinkMixin.listener("on_websocket_closed")
    async def node_ws_voice_closed(self, node, payload: wavelink.events.WebsocketClosed):

        if payload.code == 1000:
            return

        player: Union[LavalinkPlayer, YTDLPlayer] = payload.player

        print(f"Errore canale vocale! gilda: {player.guild.name} | server: {payload.player.node.identifier} | motivo: {payload.reason} | code: {payload.code}")

        if player.is_closing:
            return

        if payload.code == 4014:

            await asyncio.sleep(3)

            if player.guild.me.voice:
                return

            if player.static:
                player.command_log = "La riproduzione é stata interrotta a causa della perdita di connessione al canale vocale."
            else:
                embed = disnake.Embed(description="**Interruzione della riproduzione per perdita di connessione al canale vocale.**",
                                      color=self.bot.get_color(player.guild.me))
                self.bot.loop.create_task(player.text_channel.send(embed=embed, delete_after=7))
            await player.destroy()
            return

        if payload.code in (
            4000,  # internal error
            1006,
            1001,
            4005  # Already authenticated.
        ):
            await asyncio.sleep(3)

            await player.connect(player.channel_id)
            return

        # fix para dpy 2x (erro ocasionado ao mudar o bot de canal)
        if payload.code == 4006:

            if not player.guild.me.voice:
                return

            await player.connect(player.guild.me.voice.channel.id)
            return


    @wavelink.WavelinkMixin.listener('on_track_exception')
    async def wavelink_track_error(self, node, payload: wavelink.TrackException):
        player: LavalinkPlayer = payload.player
        track = player.last_track
        embed = disnake.Embed(
            description=f"**Impossibile riprodurre la musica:\n[{track.title}]({track.uri})** ```java\n{payload.error}```"
                        f"**Server:** `{player.node.identifier}`",
            color=disnake.Colour.red())
        await player.text_channel.send(embed=embed, delete_after=10 if player.static else None)

        if player.locked:
            return

        player.current = None

        if payload.error == "Questo indirizzo IP è stato bloccato da YouTube (429)":
            player.node.available = False
            newnode = [n for n in self.bot.music.nodes.values() if n != player.node and n.available and n.is_available]
            if newnode:
                player.queue.appendleft(player.last_track)
                await player.change_node(newnode[0].identifier)
            else:
                embed = disnake.Embed(
                    color=self.bot.get_color(player.guild.me),
                    description="**La riproduzione è stata terminata per mancanza di server disponibili.**"
                )
                await player.text_channel.send(embed=embed, delete_after=15)
                await player.destroy(force=True)
                return
        else:
            player.played.append(player.last_track)

        player.locked = True
        await asyncio.sleep(6)
        player.locked = False
        await player.process_next()


    @wavelink.WavelinkMixin.listener()
    async def on_node_ready(self, node: wavelink.Node):
        print(f'{self.bot.user} - Il server musicale: [{node.identifier}] è pronto per l`uso!')


    @wavelink.WavelinkMixin.listener('on_track_start')
    async def track_start(self, node, payload: wavelink.TrackStart):

        player: LavalinkPlayer = payload.player

        if not player.text_channel.permissions_for(player.guild.me).send_messages:
            try:
                print(f"{player.guild.name} [{player.guild.id}] - Chiusura della riproduzione per mancanza di autorizzazione all'invio "
                      f"messaggi del canale: {player.text_channel.name} [{player.text_channel.id}]")
            except Exception:
                traceback.print_exc()
            await player.destroy()
            return

        await player.invoke_np(force=True if (player.static or not player.loop or not player.is_last_message()) else False, rpc_update=True)


    @wavelink.WavelinkMixin.listener()
    async def on_track_end(self, node: wavelink.Node, payload: wavelink.TrackEnd):

        player: LavalinkPlayer = payload.player

        if player.locked:
            return

        try:
            player.message_updater_task.cancel()
        except:
            pass
        player.message_updater_task = None

        if payload.reason == "FINISHED":
            player.command_log = ""
        elif payload.reason == "STOPPED":
            pass
        else:
            return

        await player.track_end()

        await player.process_next()


    async def connect_node(self, data: dict):

        if data["identifier"] in self.bot.music.nodes:
            return

        data['rest_uri'] = ("https" if data.get('secure') else "http") + f"://{data['host']}:{data['port']}"
        data['user_agent'] = UserAgent().random
        search = data.pop("search", True)
        max_retries = data.pop('retries', 0)
        node_website = data.pop('website', '')

        if max_retries:

            backoff = 7
            retries = 1

            print(f"{self.bot.user} - Iniciando servidor de música: {data['identifier']}")

            while not self.bot.is_closed():
                if retries >= max_retries:
                    print(f"{self.bot.user} - Todas as tentativas de conectar ao servidor [{data['identifier']}] falharam.")
                    return
                else:
                    try:
                        async with self.bot.session.get(data['rest_uri'], timeout=10) as r:
                            break
                    except Exception:
                        backoff += 2
                        #print(f'{self.bot.user} - Falha ao conectar no servidor [{data["identifier"]}], nova tentativa [{retries}/{max_retries}] em {backoff} segundos.')
                        await asyncio.sleep(backoff)
                        retries += 1
                        continue

        node = await self.bot.music.initiate_node(auto_reconnect=False, **data)
        node.search = search
        node.website = node_website


    async def get_tracks(
            self, query: str, user: disnake.Member, node: wavelink.Node=None,
            track_loops=0, hide_playlist=False):

        if not node:
            node = self.bot.music.get_best_node()

            if not node:
                raise GenericError("Non ci sono server musicali disponibili.")

        tracks = await process_spotify(self.bot, user, query, hide_playlist=hide_playlist)

        if not tracks:

            if node.search:
                node_search = node
            else:
                try:
                    node_search = sorted([n for n in self.bot.music.nodes.values() if n.search and n.available and n.is_available], key=lambda n: len(n.players))[0]
                except IndexError:
                    node_search = node

            tracks = await node_search.get_tracks(query)

        if not tracks:
            raise GenericError("Non ci sono risultati per la tua ricerca.Non ci sono risultati per la tua ricerca.")

        if isinstance(tracks, list):

            if isinstance(tracks[0], wavelink.Track):
                tracks = [LavalinkTrack(track.id, track.info, requester=user, track_loops=track_loops) for track in tracks]

            elif isinstance(tracks[0], YTDLTrack):
                for track in tracks:
                    track.track_loops = track_loops
                    track.requester = user

        else:

            if not isinstance(tracks, SpotifyPlaylist):

                try:
                    if tracks.tracks[0].info.get("class") == "YoutubeAudioTrack":
                        query = f"https://www.youtube.com/playlist?list={parse.parse_qs(parse.urlparse(query).query)['list'][0]}"
                except IndexError:
                    pass

                playlist = {
                    "name": tracks.data['playlistInfo']['name'],
                    "url": query
                } if not hide_playlist else {}

                if self.bot.config.get('YTDLMODE') is True:
                    for track in tracks.tracks:
                        track.track_loops = track_loops
                        track.requester = user

                else:
                    tracks.tracks = [LavalinkTrack(t.id, t.info, requester=user, playlist=playlist) for t in tracks.tracks]

            if (selected := tracks.data['playlistInfo']['selectedTrack']) > 0:
                tracks.tracks = tracks.tracks[selected:] + tracks.tracks[:selected]

        return tracks, node


    async def connect_local_lavalink(self):

        if 'LOCAL' not in self.bot.music.nodes:
            await asyncio.sleep(7)

            await self.bot.wait_until_ready()

            localnode = {
                'host': '127.0.0.1',
                'port': 8090,
                'password': 'youshallnotpass',
                'identifier': 'LOCAL',
                'region': 'us_central',
                'retries': 25
            }

            self.bot.loop.create_task(self.connect_node(localnode))

    @commands.Cog.listener("on_thread_delete")
    async def player_thread_delete(self, thread: disnake.Thread):

        player: Union[LavalinkPlayer, YTDLPlayer, None] = None

        if not player:
            return

        if player.is_closing:
            return

        if thread.id != player.message.id:
            return


    @commands.Cog.listener("on_thread_join")
    async def join_thread_request(self, thread: disnake.Thread):

        try:
            player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[thread.guild.id]
        except KeyError:
            return

        if player.static or player.message.id != thread.id:
            return

        if thread.guild.me.id in thread._members:
            return

        embed = disnake.Embed(
            description="**Questa conversazione verrà utilizzata temporaneamente per richiedere brani semplicemente inviando "
                        "il nome/link non è necessario utilizzare il comando.**",
            color=self.bot.get_color(thread.guild.me)
        )

        await thread.send(embed=embed)


    @commands.Cog.listener("on_voice_state_update")
    async def player_vc_disconnect(
            self,
            member: disnake.Member,
            before: disnake.VoiceState,
            after: disnake.VoiceState
    ):

        if member.bot and member.id != self.bot.user.id: # ignorar outros bots
            return

        try:
            player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[member.guild.id]
        except KeyError:
            return

        try:
            player.members_timeout_task.cancel()
        except:
            pass

        if self.bot.intents.members:
            if not player.nonstop and player.guild.me.voice and not any(
                m for m in player.guild.me.voice.channel.members if not m.bot):
                player.members_timeout_task = self.bot.loop.create_task(player.members_timeout())
        else:
            player.members_timeout_task = None

        # rich presence stuff

        if player.is_closing or member.bot:
            return

        if not after or before.channel != after.channel:

            try:
                vc = player.guild.me.voice.channel
            except AttributeError:
                vc = before.channel

            self.bot.loop.create_task(player.process_rpc(vc, users=[member], close=True))
            self.bot.loop.create_task(player.process_rpc(vc, users=[m for m in vc.members if m != member and not m.bot]))


    async def reset_controller_db(self, guild_id: int, data: dict, inter: disnake.ApplicationCommandInteraction = None):

        data['player_controller']['channel'] = None
        data['player_controller']['message_id'] = None
        try:
            player: Union[LavalinkPlayer, YTDLPlayer] = self.bot.music.players[guild_id]
            player.static = False
            player.text_channel = inter.channel.parent if isinstance(inter.channel, disnake.Thread) else inter.channel
        except KeyError:
            pass
        await self.bot.db.update_data(guild_id, data, db_name='guilds')

def setup(bot: BotCore):
    bot.add_cog(Music(bot))
