from __future__ import annotations

import re
import sys
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cloup
import orjson
from langcodes import Language
from pymediainfo import MediaInfo

from pptu.uploaders import Uploader
from pptu.utils.anilist import (
    process_anilist_info,
)
from pptu.utils.image import ImgUploader
from pptu.utils.log import eprint, print
from pptu.utils.mal import process_mal_info
from pptu.utils.regex import find
from pptu.utils.rentry import rentry_upload
from pptu.utils.telegram import send_telegram_message

# Constants
SUB_CODEC_MAP = {"UTF-8": "SRT"}
AUDIO_CODEC_MAP = {
    "E-AC-3": "DDP",
    "AC-3": "DD",
    "fLaC": "FLAC",
    "DTS-UHD": "DTS",
}
CHANNEL_MAP = {
    "1": "1.0",
    "2": "2.0",
    "6": "5.1",
    "8": "7.1",
}


class Nyaa(Uploader):
    """Upload torrents to Nyaa.si.
    Based on https://github.com/varyg1001/nyaaup
    """

    randomize_infohash = False

    CATEGORIES = {
        "1_1": "Anime - Anime Music Video",
        "1_2": "Anime - English-translated",
        "1_3": "Anime - Non-English-translated",
        "1_4": "Anime - Raw",
        "4_1": "Live Action - English-translated",
        "4_3": "Live Action - Non-English-translated",
        "4_4": "Live Action - Raw",
    }
    SHORTCUT_MAP = {
        "1": "1_2",
        "2": "1_3",
        "3": "1_4",
        "4": "4_1",
        "5": "4_3",
        "6": "4_4",
        "7": "1_1",
    }

    @staticmethod
    @cloup.command(
        name="Nyaa",
        aliases=["nyaa"],
        short_help="https://nyaa.si/",
        help=__doc__,
    )
    @cloup.option_group(
        "Category & Metadata",
        cloup.option(
            "-c",
            "--category",
            type=cloup.Choice(["1", "2", "3", "4", "5", "6", "7"]),
            default=None,
            help="Select category for Nyaa.si.",
        ),
        cloup.option(
            "-d",
            "--database",
            type=cloup.Choice(["anilist", "myanimelist", "mal"]),
            default="anilist",
            help="Select database to fetch anime title (anilist or myanimelist).",
        ),
        cloup.option(
            "-l",
            "--link",
            type=str,
            metavar="URL",
            help="AniList or MyAnimeList link to set anime manually.",
        ),
        cloup.option(
            "-sl",
            "--skip-database",
            is_flag=True,
            help="Skip anime database.",
        ),
    )
    @cloup.option_group(
        "Release Tags",
        cloup.option(
            "-u",
            "--uncensored",
            is_flag=True,
            help="Use Uncensored tag in display name.",
        ),
        cloup.option(
            "-b",
            "--batch",
            is_flag=True,
            help="Use Batch tag in display name.",
        ),
        cloup.option(
            "-ms",
            "--multi-subs",
            is_flag=True,
            help="Use Multi-Subs tag in display name.",
        ),
        cloup.option(
            "-da",
            "--dual-audio",
            is_flag=True,
            help="Use Dual-Audio tag in display name.",
        ),
        cloup.option(
            "-ma",
            "--multi-audios",
            is_flag=True,
            help="Use Multi-Audios tag in display name.",
        ),
    )
    @cloup.option_group(
        "Upload Settings",
        cloup.option(
            "-an",
            "--anonymous",
            is_flag=True,
            default=False,
            help="Set upload as anonymous.",
        ),
        cloup.option(
            "-hi",
            "--hidden",
            is_flag=True,
            default=False,
            help="Set upload as hidden.",
        ),
        cloup.option(
            "-co",
            "--complete",
            is_flag=True,
            default=False,
            help="Set upload as complete batch.",
        ),
        cloup.option(
            "-re",
            "--remake",
            is_flag=True,
            default=False,
            help="Set upload as remake.",
        ),
    )
    @cloup.option_group(
        "Media & Extra Info",
        cloup.option(
            "-e",
            "--edit-code",
            type=str,
            help="Set edit code for Mediainfo on Rentry.co",
        ),
        cloup.option(
            "-i",
            "--info",
            type=str,
            help="Set information (URL or text).",
        ),
        cloup.option(
            "-ad",
            "--advert",
            type=str,
            help="Put advert in to the description.",
        ),
        cloup.option(
            "-M",
            "--no-mediainfo",
            is_flag=True,
            default=False,
            help="Do not attach Mediainfo to the torrent.",
        ),
    )
    @cloup.pass_context
    def cli(ctx: cloup.Context, **kwargs: Any) -> Nyaa:
        return Nyaa(ctx, SimpleNamespace(**kwargs))

    def __init__(self, ctx: cloup.Context, args: Any) -> None:
        super().__init__(ctx)
        self.args = args

        self.category: str = args.category

        if self.category in self.SHORTCUT_MAP:
            self.category = self.SHORTCUT_MAP[self.category]

        # Tags options
        self.uncensored: bool = args.uncensored
        self.batch: bool = args.batch
        self.multi_subs: bool = args.multi_subs
        self.dual_audio: bool = args.dual_audio
        self.multi_audios: bool = args.multi_audios

        # Settings
        self.anonymous: bool = args.anonymous
        self.hidden: bool = args.hidden
        self.complete: bool = args.complete
        self.remake: bool = args.remake

        self.edit_code: str | None = args.edit_code
        self.info: str | None = args.info or self.config.get(self, "info")
        self.advert: str | None = args.advert

        self.link: str | None = args.link

        if self.link:
            parsed = urllib.parse.urlparse(self.link)
            hostname = (parsed.hostname or "").lower()
            if hostname == "myanimelist.net" or hostname.endswith(".myanimelist.net"):
                self.database = "myanimelist"
            elif hostname == "anilist.co" or hostname.endswith(".anilist.co"):
                self.database = "anilist"
            else:
                self.database = (
                    args.database or self.config.get(self, "database", "anilist")
                ).lower()
        else:
            self.database = (
                args.database or self.config.get(self, "database", "anilist")
            ).lower()

        self.skip_database: bool = args.skip_database

        self.no_mediainfo: bool = args.no_mediainfo

        self.private = False
        self.needs_login = False

        self.min_snapshots = 3
        self.snapshots_plus = 0
        self.default_announces = [
            "http://nyaa.tracker.wf:7777/announce",
        ]

        self.display_name = ""
        self.description = ""
        self.info_url = ""
        self.data: dict[str, Any] = {}

        # Validate category
        if not self.category:
            if self.auto:
                self.category = "1_2"
            else:
                from rich import print as rprint
                from rich.tree import Tree

                eprint("Missing category!\n", fatal=False)
                categories_tree = Tree(
                    "[chartreuse2]Available categories:[white /not bold]"
                )
                for cat_id, cat_desc in self.CATEGORIES.items():
                    categories_tree.add(
                        f"[{self.SHORTCUT_MAP.get(cat_id)}] [cornflower_blue not bold]{cat_desc}[white /not bold]"
                    )
                rprint(categories_tree)
                sys.exit(1)

    @property
    def announce_url(self) -> list[str]:
        if external_t := self.config.get(self, "announce_urls"):
            if isinstance(external_t, str):
                return [external_t]
            return list(external_t)
        return self.default_announces

    @property
    def exclude_regex(self) -> str:
        return r".*\.(ffindex|jpg|png|srt|nfo|torrent|txt)$"

    def prepare(
        self,
        path: Path,
        torrent_path: Path,  # noqa: ARG002
        mediainfo: str | list[str] | None,
        snapshots: list[Path],
        note: str | None,
        *_: Any,
        **__: Any,
    ) -> bool:
        if path.is_dir():
            files = sorted([*path.glob("*.mkv"), *path.glob("*.mp4")])
            if not files:
                eprint("No video files found in directory!")
                return False
            media_file = files[0]
        else:
            media_file = path

        try:
            mediainfo_data = MediaInfo.parse(media_file, parse_speed=0.5, full=True)
            general_track = next(iter(mediainfo_data.general_tracks), None)
            duration = getattr(general_track, "duration", None)
            has_audio_bitrate = all(
                getattr(t, "bit_rate", None) is not None
                for t in mediainfo_data.audio_tracks
            )
            if not duration or not has_audio_bitrate:
                mediainfo_data = MediaInfo.parse(media_file, parse_speed=1.0, full=True)
        except Exception as e:
            eprint(f"MediaInfo parsing failed: {e}")
            return False

        video_track = next(iter(mediainfo_data.video_tracks), None)
        video_info = _process_video_track(video_track) if video_track else ""

        audio_info = [
            _process_audio_track(track) for track in mediainfo_data.audio_tracks
        ]
        audio_langs_count = len(
            {t.language for t in mediainfo_data.audio_tracks if t.language}
        )

        subtitle_info = [
            _process_subtitle_track(track) for track in mediainfo_data.text_tracks
        ]

        subtitle_langs_count = len(
            {t.language for t in mediainfo_data.text_tracks if t.language}
        )

        name_plus: list[str] = []
        db_info_url = ""
        if not self.skip_database:
            plus_title = None
            if self.database in {"myanimelist", "mal"}:
                plus_title, db_info_url = process_mal_info(self.link, path.name)
                print(plus_title)
                if not plus_title and not db_info_url:
                    plus_title, db_info_url = process_anilist_info(self.link, path.name)
            else:
                plus_title, db_info_url = process_anilist_info(self.link, path.name)
                if not plus_title and not db_info_url:
                    plus_title, db_info_url = process_mal_info(self.link, path.name)

            if plus_title:
                name_plus.append(plus_title)

        # Explicit CLI/config info overrides database info URL
        self.info_url = self.info or db_info_url or ""

        # Add tags
        dual_audio = self.dual_audio
        multi_audio = self.multi_audios
        multi_sub = self.multi_subs

        if self.auto:
            dual_audio = dual_audio or (audio_langs_count == 2)
            multi_audio = multi_audio or (audio_langs_count > 2)
            multi_sub = multi_sub or (subtitle_langs_count > 1)

        if dual_audio:
            name_plus.append("Dual-Audio")
        elif multi_audio:
            name_plus.append("Multi-Audio")
        if multi_sub:
            name_plus.append("Multi-Subs")
        if self.uncensored:
            name_plus.append("Uncensored")
        if self.batch:
            name_plus.append("Batch")

        # Generate display name
        display_name = self._format_display_name(
            path.stem if path.is_file() else path.name, name_plus
        )

        # Build description
        description = ""
        if note:
            description += f">{note}\n\n---\n\n"

        advert = self.advert or self.config.get(self, "advert")
        if advert:
            description += f"{advert}\n\n---\n\n"

        chapter_track = next(iter(mediainfo_data.menu_tracks), None)
        chapter_str = "Yes" if chapter_track else "No"

        general_track = next(iter(mediainfo_data.general_tracks), None)
        duration_val = getattr(general_track, "duration", None)
        if duration_val:
            try:
                total_seconds = float(duration_val) / 1000.0
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                secs = total_seconds % 60
                duration_str = f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
            except Exception:
                duration_str = "?"
        else:
            duration_str = "?"

        sub_str = " │ ".join(subtitle_info) if subtitle_info else "**N/A**"
        description += (
            f"`Tech Specs:`\n"
            f"* `Video:` {video_info}\n"
            f"* `Audios ({audio_langs_count}):` {' │ '.join(audio_info)}\n"
            f"* `Subtitles ({subtitle_langs_count}):` {sub_str}\n"
            f"* `Chapters:` **{chapter_str}**\n"
            f"* `Duration:` **~{duration_str}**\n"
        )

        # Upload mediainfo to rentry.co if enabled and not disabled
        if not self.no_mediainfo and mediainfo:
            if isinstance(mediainfo, list):
                raw_text = mediainfo[0] if mediainfo else None
            else:
                raw_text = mediainfo
            if isinstance(raw_text, str):
                print("Uploading MediaInfo to rentry.co...")
                rentry_res = rentry_upload(raw_text, self.edit_code)

                if rentry_res:
                    url = rentry_res.get("url")
                    edit_code = rentry_res.get("edit_code")
                    description += f"\n\n[Full MediaInfo]({url})"
                    print(f"MediaInfo link: [cornflower_blue]{url}[/]")
                    if edit_code:
                        print(f"Edit code: [cornflower_blue]{edit_code}[/]")

        # Upload snapshots
        if snapshots:
            uploader = ImgUploader(self)
            print("Uploading snapshots...")
            snapshot_urls = uploader.upload(snapshots)
            if snapshot_urls:
                description += "\n\n---\n\n"
                cols = min(
                    self.config.get(self, "snapshot_columns", 3), len(snapshot_urls)
                )
                if cols > 0:
                    for i, img_url in enumerate(snapshot_urls, start=1):
                        description += f"| [![]({img_url})]({img_url}) "
                        if i == min(cols, len(snapshot_urls)):
                            description += f"|\n{'|---' * cols}|\n"
                        elif i % cols == 0:
                            description += "|\n"

        self.display_name = display_name
        self.description = description

        self.data = {
            "name": display_name,
            "category": self.category,
            "description": description,
            "anonymous": "anonymous" if self.anonymous else None,
            "hidden": "hidden" if self.hidden else None,
            "complete": "complete" if self.complete else None,
            "remake": "remake" if self.remake else None,
            "trusted": "trusted" if self.config.get(self, "trusted") else None,
            "information": self.info_url,
        }

        return True

    def upload(
        self,
        path: Path,  # noqa: ARG002
        torrent_path: Path,
        mediainfo: str | list[str] | None,  # noqa: ARG002
        snapshots: list[Path],  # noqa: ARG002
        note: str | None,  # noqa: ARG002
        *_: Any,
        **__: Any,
    ) -> bool:
        username = self.config.get(self, "username")
        password = self.config.get(self, "password")

        if not username or not password:
            eprint("No username or passwordy specified in config, cannot upload.")
            return False

        print(f"Uploading to {self.cli.name}...")

        try:
            torrent_data = torrent_path.read_bytes()
        except Exception as e:
            eprint(f"Failed to read torrent file: {e}")
            return False

        try:
            files: dict[str, Any] = {
                "torrent": (
                    torrent_path.name,
                    torrent_data,
                    "application/x-bittorrent",
                ),
                "torrent_data": (
                    None,
                    orjson.dumps(self.data).decode(),
                ),
            }
            res = self.session.post(
                "https://nyaa.si/api/v2/upload",
                files=files,
                auth=(username, password),
                timeout=120,
            )

            if res.status_code == 200:
                result = res.json()
                if errors := result.get("errors"):
                    self._handle_upload_errors(errors)
                    return False

                site_url: Any = result.get("url")
                download_url = f"https://nyaa.si/download/{result.get('id')}.torrent"
                print("Upload succeeded!")
                print(f"Link: {site_url}", True)

                if self.telegram:
                    self._send_telegram_notification(
                        self.display_name, site_url, download_url
                    )

                return True
            else:
                eprint(f"Upload failed: HTTP {res.status_code}\n{res.text}")
                return False

        except Exception as e:
            eprint(f"Upload request failed: {e}")
            return False

    @staticmethod
    def _handle_upload_errors(errors: dict[str, Any] | str | list[str]) -> None:
        if isinstance(errors, str):
            eprint(f"Failed to upload: {errors}", fatal=False)
        elif isinstance(errors, list):
            eprint(f"Failed to upload: {errors[0]}", fatal=False)
        else:
            info = next(iter(errors))
            eprint(f"Failed to upload with {info} error: {errors[info][0]}", fatal=False)

    def _format_display_name(self, name: str, name_plus: list[str]) -> str:
        name_nyaa = name.replace(".", " ")
        if codec := find(r"H 26[4|5|6]", name_nyaa):
            name_nyaa = name_nyaa.replace(codec, codec.replace(" ", "."))
        if channel := find(r"[A-Z]{2,3}[2|5|7] [0|1]", name_nyaa):
            name_nyaa = name_nyaa.replace(channel, channel.replace(" ", "."))
        return f"{name_nyaa} ({', '.join(name_plus)})" if name_plus else name_nyaa

    def _send_telegram_notification(
        self, name: str, site_url: str, download_url: str
    ) -> None:
        cat_desc = self.CATEGORIES.get(self.category, self.category)
        message = (
            f"\n<b>{name}</b>\n\n"
            f"- <b>Category</b>: {cat_desc}\n"
            "- <b>Link</b>: "
            f'<a href="{site_url}">View site</a> | '
            f'<a href="{download_url}">Torrent file</a>'
        )
        send_telegram_message(self, message)


def _get_track_info(track: Any) -> str:
    lang = getattr(track, "language", None)
    if not lang:
        lang_name = "Und"
    else:
        try:
            lang_name = Language.get(lang).display_name()
        except Exception:
            lang_name = str(lang)

    track_name = getattr(track, "title", None)

    if track_name and "(" in lang_name:
        lang_name = lang_name.split(" (")[0]
        return _get_return(lang_name, str(track_name))
    if "(" in lang_name:
        lang_name = lang_name.split(" (")[0]
        return _get_return(lang_name)
    if track_name:
        return _get_return(lang_name, str(track_name))
    return _get_return(lang_name)


def _get_return(lang: str, track_name: str | None = None) -> str:
    if track_name:
        if track_name in {"CC", "SDH", "Forced", "Dubtitle", "MTL"}:
            return f"**{lang}** [{track_name}]"
        if r := re.search(r"(.*) \((CC|SDH|Forced|Dubtitle|MTL)\)", track_name):
            return f"**{lang}** ({r[1]}) [{r[2]}]"
        return f"**{lang}** ({track_name})"
    return f"**{lang}**"


def _process_video_track(track: Any) -> str:
    v_bitrate = ""
    try:
        if track.stream_size and track.duration:
            b_raw = float(float(track.stream_size) * 8 / (float(track.duration) / 1000.0))
            if b_raw / 1000 < 10000:
                b = f"{b_raw / 1000:.0f} kbps"
            else:
                b = f"{b_raw / 1000000:.2f} Mbps"
            v_bitrate = f" @ **{b}**"
    except Exception:
        pass

    codec = ""
    if track.internet_media_type:
        codec = track.internet_media_type.split("/")[1].upper().replace("H264", "H264")
    elif track.format:
        codec = str(track.format).replace(" ", "")

    profile = str(track.format_profile) if track.format_profile else ""
    level = f"L{track.format_level}" if track.format_level else ""

    if profile and level:
        level_str = f"{profile}@{level}"
    elif profile or level:
        level_str = f"{profile}{level}"
    else:
        level_str = ""

    codec_level_part = (
        f"**{codec} {level_str}**".strip()
        if codec and level_str
        else (f"**{codec}**" if codec else None)
    )

    dimensions = f"**{track.width}x{track.height}**" if track.width else None

    parts = [
        codec_level_part,
        f"{dimensions}{v_bitrate}" if dimensions else None,
        f"**{track.frame_rate} fps**" if track.frame_rate else None,
    ]
    return ", ".join(filter(None, parts))


def _process_audio_track(track: Any) -> str:
    a_bitrate = ""
    try:
        bit_rate = getattr(track, "bit_rate", None)
        if bit_rate:
            a_bitrate = f" @ {round(float(bit_rate) / 1000)} kbps"
    except Exception:
        pass

    atmos = "JOC" in str(getattr(track, "format_additional_features", ""))
    codec_name = AUDIO_CODEC_MAP.get(str(track.format), track.format)
    channels = getattr(track, "channel_s", None) or getattr(track, "channels", None)
    channels_str = CHANNEL_MAP.get(str(channels), str(channels or "?"))

    parts = [
        _get_track_info(track),
        f"{codec_name} {channels_str}{' Atmos' if atmos else ''}{a_bitrate}",
    ]
    return ", ".join(filter(None, parts))


def _process_subtitle_track(track: Any) -> str:
    codec_name = SUB_CODEC_MAP.get(str(track.format), track.format)
    parts = [
        _get_track_info(track),
        f"{codec_name}",
    ]
    return ", ".join(filter(None, parts))
