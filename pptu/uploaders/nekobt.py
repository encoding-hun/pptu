from __future__ import annotations

import base64
import re
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import cloup
from beaupy import select_multiple
from guessit import guessit
from langcodes import Language
from pymediainfo import MediaInfo
from rich import print as rprint
from rich.prompt import Prompt
from rich.status import Status
from rich.tree import Tree

from pptu.uploaders import Uploader
from pptu.utils import is_close_match
from pptu.utils.anilist import (
    extract_name_from_filename,
    get_anilist_data,
    get_anilist_title,
)
from pptu.utils.click import comma_separated_param
from pptu.utils.collections import first_or_else
from pptu.utils.image import ImgUploader
from pptu.utils.log import eprint, print, wprint
from pptu.utils.regex import find


if TYPE_CHECKING:
    from pathlib import Path


class nekoBT(Uploader):
    randomize_infohash = False

    VIDEO_CODEC_MAP: dict[str, int] = {
        "AVC": 1,  # H.264
        "HEVC": 2,  # H.265
        "AV1": 3,
        "VP9": 4,
        "MPEG-2": 5,
        "XviD": 6,
        "WMV": 7,
        "VC-1": 8,
        "Other": 0,
    }
    VIDEO_TYPE_MAP: dict[str, int] = {
        "Hybrid": 15,
        "BD - Remux": 14,
        "BD - Encode": 13,
        "BD - Mini": 12,
        "BD - Disc": 11,
        "WEB-DL": 9,
        "WEB - Encode": 8,
        "WEB - Mini": 7,
        "DVD - Encode": 6,
        "DVD - Remux": 5,
        "DVD - Disc": 16,
        "TV - Raw": 4,
        "TV - Encode": 3,
        "LaserDisc": 2,
        "VHS": 1,
        "Other": 0,
    }
    LANG_CONVERT: dict[str, str] = {
        "jp": "ja",
        "eng": "en",
        "en-jp": "enm",
        "spa-419": "es-419",
        "es": "es-es",
        "pt": "pt-pt",
        "fr": "fr-fr",
        "tg": "fil",
        "nb": "no",
        "nn": "no",
    }

    @staticmethod
    @cloup.command(
        name="nekoBT",
        aliases=["nBT"],
        short_help="https://nekobt.to/",
        help=__doc__,
    )
    @cloup.option_group(
        "Release Metadata",
        cloup.option(
            "-m",
            "--movie",
            is_flag=True,
            default=False,
            help="This torrent only contains a movie.",
        ),
        cloup.option(
            "-vt",
            "--video-type",
            type=cloup.Choice([str(i) for i in range(16)]),
            metavar="ID",
            default=None,
            help="Set video type with ID. (https://wiki.nekobt.to/info/metadata/#video-type)",
        ),
        cloup.option(
            "-l",
            "--link",
            type=str,
            metavar="URL",
            default=None,
            help="Anilist link to use for title.",
        ),
        cloup.option(
            "-npi",
            "--no-plus-info",
            is_flag=True,
            default=False,
            help="Skip romaji title and 'Multi-Subs' in display name",
        ),
    )
    @cloup.option_group(
        "Translation & Subtitles",
        cloup.option(
            "-sl",
            "--sub-level",
            type=cloup.Choice(["-1", "0", "1", "2", "3", "4"]),
            metavar="LEVEL",
            default="0",
            help="Set subtitle level (-1 = no subs). Default: 0.",
        ),
        cloup.option(
            "-mtl",
            "--machine-translation",
            is_flag=True,
            default=False,
            help="The release uses machine translation for their fansubs.",
        ),
        cloup.option(
            "-ot",
            "--original-translation",
            is_flag=True,
            default=False,
            help="Release uses original translation for their fansubs.",
        ),
        cloup.option(
            "-hs",
            "--hardsub",
            is_flag=True,
            default=False,
            help="The fansubs are hardsubbed ('burnt in') into the video.",
        ),
        cloup.option(
            "-flo",
            "--fansub-langs-only",
            default="",
            callback=comma_separated_param,
            metavar="LANG",
            help="Subtitle languages to set as fansub only. (Comma-separated)",
        ),
        cloup.option(
            "-flt",
            "--fansub-langs-too",
            default="",
            callback=comma_separated_param,
            metavar="LANG",
            help="Subtitle languages to set as fansub too. (Comma-separated)",
        ),
    )
    @cloup.option_group(
        "Group Information",
        cloup.option(
            "-pg",
            "--primary-group",
            default="",
            metavar="GROUP",
            help="Primary group, if not set in config.",
        ),
        cloup.option(
            "-pgm",
            "--primary-group-members",
            default="",
            callback=comma_separated_param,
            metavar="NAME",
            help="Primary group members. (Comma-separated)",
        ),
        cloup.option(
            "-sg",
            "--secondary-groups",
            default="",
            callback=comma_separated_param,
            metavar="GROUPS;;ROLE",
            help="Secondary groups. (Comma-separated)",
        ),
    )
    @cloup.option_group(
        "Upload Options",
        cloup.option(
            "-iw",
            "--ignore-warnings",
            is_flag=True,
            default=False,
            help="Ignore validation warnings, and upload.",
        ),
        cloup.option(
            "-hi",
            "--hidden",
            is_flag=True,
            default=False,
            help="Hidden Torrent.",
        ),
        cloup.option(
            "-a",
            "--anonymous",
            is_flag=True,
            default=False,
            help="Upload Anonymously.",
        ),
    )
    @cloup.pass_context
    def cli(ctx: cloup.Context, **kwargs: Any) -> nekoBT:
        return nekoBT(ctx, SimpleNamespace(**kwargs))

    def __init__(self, ctx: cloup.Context, args: Any) -> None:
        super().__init__(ctx)

        self.needs_login = False
        self.private = False

        self.movie: bool = args.movie
        self.video_type: int | None = args.video_type
        self.link: str = args.link
        self.no_plus_info: bool = args.no_plus_info

        self.sub_level: int = args.sub_level
        self.mtl: bool = args.machine_translation
        self.otl: bool = args.original_translation
        self.hardsub: bool = args.hardsub
        self.fansub_langs_only: tuple[str, ...] = tuple(args.fansub_langs_only)
        self.fansub_langs_too: tuple[str, ...] = tuple(args.fansub_langs_too)

        self.primary_group: str = args.primary_group
        self.primary_group_members: tuple[str, ...] = tuple(args.primary_group_members)
        self.secondary_groups: tuple[str, ...] = args.secondary_groups

        self.ignore_warnings: bool = args.ignore_warnings
        self.hidden: bool = args.hidden
        self.anonymous: bool = args.anonymous

        if not self.video_type:
            eprint("Missing video type!\n", fatal=False)
            categories = Tree("[chartreuse2]Available video type:[white /not bold]")
            for x, y in reversed(self.VIDEO_TYPE_MAP.items()):
                categories.add(f"[{y}] [cornflower_blue not bold]{x}[white /not bold]")
            rprint(categories)
            sys.exit(1)

    @property
    def announce_url(self) -> list[str]:
        default_t = [
            "https://tracker.nekobt.to/api/tracker/public/announce",
        ]

        if self.config.get(self, "watch_dir"):
            self.private = True
            self.randomize_infohash = True
            default_t.append(
                "https://tracker.nekobt.to/api/tracker/{passkey}/announce",
            )

        if external_t := self.config.get(self, "announce_urls", ""):
            default_t.extend(external_t)

        return default_t

    @property
    def exclude_regex(self) -> str:
        return r".*\.(ffindex|jpg|png|srt|nfo|torrent|txt)$"

    @property
    def passkey(self) -> str | None:
        if self.config.get(self, "watch_dir"):
            res = self.session.get(
                url="https://nekobt.to/api/v1/users/@me",
                cookies={"ssid": self.config.get(self, "api_key", "")},
            ).json()

            if res.get("error"):
                eprint(res.get("message"), fatal=False)
                return None

            info: dict[str, str] = res.get("data", {})

            if torrent_key := info.get("torrent_key"):
                return torrent_key

        return None

    def prepare(  # type: ignore[override]
        self,
        path: Path,
        torrent_path: Path,
        mediainfo: str,
        snapshots: list[Path],
        *,
        note: str | None,
        auto: bool,
    ) -> bool:
        description: str = ""
        v_codec: int = 0
        name_plus: list[str] = []
        primary_group_members: list[dict[str, str | list[dict[str, str]]]] = []
        secondary_groups: list[dict[str, Any]] = []

        if path.is_dir():
            files: list[Path] = sorted([*path.glob("*.mkv"), *path.glob("*.mp4")])
        else:
            files = [path]

        if not (group_name := self.primary_group):
            if not (group_name := self.config.get(self, "group_tag", "")):
                gi = guessit(path.name)
                group_name = gi.get("release_group")

        primary_group_info: Any = self._get_group_info(group_name)
        members_from_primary_group: list[dict[str, Any]] = primary_group_info.get(
            "members", []
        )

        for primary_group_member in self.primary_group_members:
            role = ""
            display_name = ""
            if ";;" in primary_group_member:
                temp = primary_group_member.split(";;")
                display_name = temp[0]
                role = temp[-1]
            else:
                display_name = primary_group_member

            if member := first_or_else(
                [
                    x
                    for x in members_from_primary_group
                    if x["display_name"] == display_name or x["username"] == display_name
                ],
                None,
            ):
                primary_group_members.append(
                    {
                        "id": member["id"],
                        "display_name": member["display_name"],
                        "role": role,
                    }
                )

        if not auto:
            if not self.primary_group_members:
                options = []
                for member in members_from_primary_group:
                    options.append(
                        f"{member['display_name']} [[grey100]{member['id']}[/grey100]]"
                    )

                try:
                    selected_indices = select_multiple(
                        options,
                        return_indices=True,
                        pagination=True,
                        page_size=10,
                        tick_style="grey100",
                        cursor_style="blue",
                    )
                except KeyboardInterrupt:
                    selected_indices = []
                    wprint("Selection cancelled by user.")

                if selected_indices:
                    for num, member in enumerate(members_from_primary_group):
                        role = Prompt.ask(f"Role for {member['display_name']}")
                        if num in selected_indices:
                            primary_group_members.append(
                                {
                                    "id": member["id"],
                                    "display_name": member["display_name"],
                                    "role": role,
                                }
                            )

        for secondary_group in self.secondary_groups:
            role = ""
            secondary_group_name = ""
            if ";;" in secondary_group:
                temp = secondary_group.split(";;")
                display_name = temp[0]
                role = temp[-1]
            else:
                secondary_group_name = secondary_group

            secondary_group_info = self._get_group_info(secondary_group_name)

            if not role:
                role = Prompt.ask(f"Role for {secondary_group_name}")

            secondary_groups.append(
                {
                    "id": secondary_group_info.get("id", ""),
                    "role": role,
                }
            )

        try:
            with Status(f"[bold magenta]Parsing {files[0]}...") as _:
                mediainfo_data: MediaInfo = MediaInfo.parse(files[0], full=True)
                if not mediainfo_data:
                    eprint("MediaInfo parsing failed.", exit_code=1, fatal=True)
        except KeyboardInterrupt:
            eprint("Mediainfo parse stopped", exit_code=1, fatal=True)

        if video := first_or_else(mediainfo_data.video_tracks, None):
            v_codec = self.VIDEO_CODEC_MAP.get(video.format, 0)

        audios_langs = list(
            dict.fromkeys(
                self.LANG_CONVERT.get(z := str(Language.get(x.language)), z)
                for x in mediainfo_data.audio_tracks
            )
        )
        subtitles_langs = list(
            dict.fromkeys(
                self.LANG_CONVERT.get(z := str(Language.get(x.language)), z)
                for x in mediainfo_data.text_tracks
            )
        )

        if len(subtitles_langs) == 0:
            print("No subtitle detected")
            self.sub_level = -1

        fansub_langs = ""
        if self.fansub_langs_only:
            if "all" in self.fansub_langs_only:
                fansub_langs = ",".join(subtitles_langs)
                subtitles_langs = []
            else:
                fansub_langs += ",".join(
                    [
                        x
                        for x in subtitles_langs
                        if is_close_match(x, self.fansub_langs_only)
                    ]
                )
                subtitles_langs = [
                    x
                    for x in subtitles_langs
                    if not is_close_match(x, self.fansub_langs_only)
                ]
        if self.fansub_langs_too:
            fansub_langs += ",".join(
                [x for x in subtitles_langs if is_close_match(x, self.fansub_langs_too)]
            )

        title, is_movie = extract_name_from_filename(path.stem)

        if is_movie and not self.movie:
            print("Movie detected")
            self.movie = True

        if not self.no_plus_info:
            if self.link and (plus_data := get_anilist_data(anilist_url=self.link)):
                if plus_title := get_anilist_title(anilist_data=plus_data):
                    name_plus.append(plus_title)
            elif plus_title := get_anilist_title(search_name=title):
                name_plus.append(plus_title)
            if len(subtitles_langs) > 1:
                name_plus.append("Multi-Subs")

        columns = self.config.get(self, "snapshot_columns", 3)
        rows = self.config.get(self, "snapshot_rows", 2)

        if note:
            description = f">{note}\n\n<br><hr><br>\n"

        if advert := self.config.get(self, "advert", ""):
            description += f"{advert}\n<br><hr><br>\n"

        uploader = ImgUploader(self)
        if images := uploader.upload(snapshots):
            for i, image in enumerate(images, start=1):
                if image:
                    url = f"https://i.kek.sh/{image['filename']}"
                    description += f"| [![]({url})]({url}) "
                    if i == columns:
                        description += f"\n{'|---' * columns}|\n"
                    elif i % rows == 0:
                        description += "\n"

        if auto:
            if not self.video_type and re.search(r"\bweb-dl?\b", str(path), flags=re.I):
                self.video_type = 9

        self.data = {
            "torrent": base64.b64encode(torrent_path.read_bytes()).decode(),
            "title": self._format_display_name(path.stem, name_plus, group_name),
            "movie": self.movie,
            "category": "1",  # TODO: for now only one category
            "video_codec": v_codec,
            "hidden": self.hidden,
            "video_type": self.video_type,
            "level": self.sub_level,
            "mtl": self.mtl,
            "otl": self.otl,
            "hardsub": self.hardsub,
            "anonymous": self.anonymous,
            "primary_group": {
                "id": primary_group_info.get("id"),
                "members": primary_group_members,
            },
            "secondary_groups": secondary_groups,
            "audio_langs": ",".join(audios_langs).lower(),
            "sub_langs": ",".join(subtitles_langs).lower(),
            "fansub_langs": fansub_langs,
            "description": description,
            "mediainfo": mediainfo,
            "ignore_warnings": self.ignore_warnings,
        }

        res = self.session.put(
            url="https://nekobt.to/api/v1/upload/checks",
            cookies={"ssid": self.config.get(self, "api_key", "")},
            json={
                "title": self.data["title"],
                "movie": self.data["movie"],
                "video_type": self.data["video_type"],
                "video_codec": self.data["video_codec"],
                "files": [{"name": x.name} for x in files],
                "level": self.data["level"],
                "mtl": self.data["mtl"],
                "otl": self.data["otl"],
                "hardsub": self.data["hardsub"],
                "audio_langs": self.data["audio_langs"],
                "sub_langs": self.data["sub_langs"],
                "fansub_langs": self.data["fansub_langs"],
                "announce_urls": self.announce_url,
            },
        ).json()

        if res.get("error"):
            eprint(res.get("message"), fatal=False)
            return False

        info = res.get("data", {})

        if warns := info.get("warns", []):
            for warn in warns:
                wprint(f"Warning from {self.cli.name}: {warn}")

        if fails := info.get("fails", []):
            for fail in fails:
                eprint(f"Fail from {self.cli.name}: {fail}", fatal=False)

        return True

    def upload(  # type: ignore[override]
        self,
        path: Path,
        torrent_path: Path,
        mediainfo: str,
        snapshots: list[Path],
        *,
        note: str | None,
        auto: bool,
    ) -> bool:
        res = self.session.post(
            url="https://nekobt.to/api/v1/upload",
            cookies={"ssid": self.config.get(self, "api_key", "")},
            json=self.data,
        ).json()

        if warns := res.get("warns", []):
            for warn in warns:
                wprint(f"Warning from {self.cli.name}: {warn}")

        if fails := res.get("fails", []):
            for fail in fails:
                eprint(f"Fail from {self.cli.name}: {fail}", fatal=False)

        if res.get("error"):
            eprint(res.get("message"), fatal=False)
            return False

        info = res.get("data", {})

        if site_id := info.get("id"):
            print(
                f"Link: https://nekobt.to/torrents/{site_id}",
                True,
            )

        return True

    def _get_group_info(
        self, grp_name: str | None = None, grp_id: str | int | None = None
    ) -> Any:
        if grp_name:
            res = self.session.get(
                "https://nekobt.to/api/v1/groups/search",
                params={"order": "asc", "limit": "5", "query": grp_name},
            ).json()

            if res.get("error"):
                eprint(res.get("message"), exit_code=1)

            if group := first_or_else(res.get("data", {}).get("results", []), {}):
                grp_id = group.get("id")
                print(f"Detected group: {group.get('display_name')} [{grp_id}]")

        res = self.session.get(f"https://nekobt.to/api/v1/groups/{grp_id}").json()
        if res.get("error"):
            eprint(res.get("message"), exit_code=1)

        return res.get("data", {})

    def _format_display_name(
        self, name: str, name_plus: list[str], group_name: str
    ) -> str:
        final_name: str = name.replace(".", " ")
        if channel := find(r"[A-Z]{3}[2|5|7] [0|1]", final_name):
            final_name = final_name.replace(channel, channel.replace(" ", "."))
        if codec := find(r"H 26[4|5]", final_name):
            final_name = final_name.replace(codec, codec.replace(" ", "."))

        if self.config.get(self, "group_at_start", False):
            final_name = re.sub(rf"(?:-)?{group_name}", "", final_name)
            final_name = f"[{group_name}] " + final_name

        return f"{final_name} ({', '.join(name_plus)})" if name_plus else final_name
