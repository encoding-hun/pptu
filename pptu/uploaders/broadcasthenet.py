from __future__ import annotations

import re
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import cloup
import orjson
from guessit import guessit
from langcodes import Language
from pymediainfo import MediaInfo
from pyotp import TOTP
from rich.prompt import Prompt

from pptu.uploaders import Uploader
from pptu.utils.image import ImgUploader, generate_thumbnails
from pptu.utils.log import eprint, print, wprint
from pptu.utils.regex import find
from pptu.utils.xml import load_html


if TYPE_CHECKING:
    from pathlib import Path


class BroadcasTheNet(Uploader):
    COUNTRY_MAP: dict[str, int] = {
        "AD": 65,
        "AF": 51,
        "AG": 86,
        "AL": 62,
        "AN": 68,
        "AO": 33,
        "AR": 19,
        "AT": 34,
        "AU": 20,
        "BA": 64,
        "BB": 82,
        "BD": 83,
        "BE": 16,
        "BF": 57,
        "BG": 100,
        "BN": 113,
        "BR": 18,
        "BS": 79,
        "BZ": 31,
        "CA": 5,
        "CD": 50,
        "CH": 54,
        "CL": 48,
        "CN": 8,
        "CO": 95,
        "CR": 98,
        "CU": 49,
        "CZ": 43,
        "DE": 7,
        "DK": 10,
        "DO": 38,
        "DZ": 32,
        "EC": 78,
        "EE": 94,
        "EG": 99,
        "ES": 22,
        "FI": 4,
        "FJ": 102,
        "FR": 6,
        "GB": 12,
        "GR": 39,
        "GT": 40,
        "HK": 30,
        "HN": 76,
        "HR": 93,
        "HU": 71,
        "IL": 41,
        "IS": 13,
        "IT": 9,
        "JM": 28,
        "JP": 17,
        "KG": 77,
        "KH": 81,
        "KI": 55,
        "KP": 92,
        "KR": 27,
        "KW": 104,
        "LA": 84,
        "LB": 96,
        "LK": 105,
        "LT": 66,
        "LU": 29,
        "LV": 97,
        "MK": 103,
        "MX": 24,
        "MY": 37,
        "NG": 58,
        "NL": 15,
        "NO": 11,
        "NR": 60,
        "NZ": 21,
        "PE": 80,
        "PH": 56,
        "PK": 42,
        "PL": 14,
        "PR": 47,
        "PT": 23,
        "PY": 87,
        "RO": 72,
        "RS": 44,
        "RU": 3,
        "SA": 108,
        "SC": 45,
        "SE": 1,
        "SG": 25,
        "SK": 110,
        "SN": 90,
        "SU": 88,
        "TG": 91,
        "TM": 64,
        "TR": 52,
        "TT": 75,
        "TW": 46,
        "UA": 69,
        "US": 2,
        "UY": 85,
        "UZ": 53,
        "VE": 70,
        "VN": 74,
        "VU": 73,
        "WS": 36,
        "YU": 35,
        "ZA": 26,
    }

    @staticmethod
    @cloup.command(
        name="BroadcasTheNet",
        aliases=["BTN"],
        short_help="https://broadcasthe.net/",
        help=__doc__,
    )
    @cloup.pass_context
    def cli(ctx: cloup.Context, **kwargs: Any) -> BroadcasTheNet:
        return BroadcasTheNet(ctx, SimpleNamespace(**kwargs))

    def __init__(self, ctx: cloup.Context, args: Any) -> None:
        super().__init__(ctx)

    @property
    def announce_url(self) -> str:
        return "https://landof.tv/{passkey}/announce"

    @property
    def exclude_regex(self) -> str:
        return r".*\.(ffindex|jpg|png|srt|nfo|torrent|txt)$"

    @property
    def passkey(self) -> str | None:
        if res := self.session.get("https://backup.landof.tv/upload.php").text:
            soup = load_html(res)
            if not (el := soup.select_one("input[value$='/announce']")):
                return None
            return el.attrs["value"].split("/")[-2]
        return None

    def login(self, *, args: Any = None) -> bool:
        # Allow cookies from either broadcasthe.net or backup.landof.tv
        for cookie in self.session.cookies:
            cookie.domain = cookie.domain.replace("broadcasthe.net", "backup.landof.tv")

        r = self.session.get("https://backup.landof.tv/user.php")
        if "login.php" not in str(r.url):
            return True

        wprint("Cookies missing or expired, logging in...")

        if not (username := self.config.get(self, "username")):
            eprint("No username specified in config, cannot log in.")
            return False

        if not (password := self.config.get(self, "password")):
            eprint("No password specified in config, cannot log in.")
            return False

        print("Logging in")

        tfa_code = ""
        if totp_secret := self.config.get(self, "totp_secret"):
            tfa_code = TOTP(totp_secret).now()
        r = self.session.post(
            url="https://backup.landof.tv/login.php",
            data={
                "username": username,
                "password": password,
                "keeplogged": "1",
                "code": tfa_code,
                "login": "Log In!",
            },
        )

        if "Your IP is banned indefinitely." in str(r.text):
            eprint("Your IP is banned indefinitely.", fatal=True)

        r.raise_for_status()

        if "login.php" in str(r.url):
            if args.auto:
                eprint("No TOTP secret specified in config")
                return False
            tfa_code = Prompt.ask("Enter 2FA code")

            r = self.session.post(
                url="https://backup.landof.tv/login.php",
                data={
                    "username": username,
                    "password": password,
                    "keeplogged": "1",
                    "code": tfa_code,
                    "login": "Log In!",
                },
            )
            r.raise_for_status()

        return "login.php" not in str(r.url)

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
        if re.search(r"\.S\d+(E\d+|\.Special)+\.", str(path)):
            print("Detected episode")
            type_ = "Episode"
        elif re.search(r"\.S\d+\.", str(path)):
            print("Detected season")
            type_ = "Season"
        else:
            print("Detected movie")
            type_ = "Episode"

        release_name = path.stem if path.is_file() else path.name
        release_name = re.sub(
            r"\.([a-z]+)\.?([\d.]+)\.Atmos", r".\1A\2", release_name, flags=re.I
        )
        if m := re.search(
            r"\.(?:DV|DoVi)(?:\.HDR(?:10(?:\+|P|Plus))?)?\b", release_name, flags=re.I
        ):
            release_name = release_name.replace(m.group(), "")
            release_name = re.sub(r"\.(\d+p)", r".DV.\1", release_name)
        elif m := re.search(
            r"\.(?:\.HDR(?:10(?:\+|P|Plus)))\b", release_name, flags=re.I
        ):
            release_name = release_name.replace(m.group(), "")
            release_name = re.sub(r"\.(\d+p)", r".HDR.\1", release_name)
        elif m := re.search(r"\.HLG\b", release_name, flags=re.I):
            release_name = release_name.replace(m.group(), "")
            release_name = re.sub(r"\.(\d+p)", r".HLG.\1", release_name)
        release_name = release_name.replace(".DUBBED", "")
        release_name = release_name.replace(".DUAL", "")

        r = self.session.post(
            url="https://backup.landof.tv/upload.php",
            data={
                "type": type_,
                "scene_yesno": "yes",
                "autofill": release_name,
                "tvdb": "Get Info",
            },
            timeout=60,
        )
        soup = load_html(str(r.text))
        if r.status_code == 302:
            eprint("Cookies expired.")
            return False
        if r.status_code != 200:
            eprint(f"HTTP Error [cyan]{r.status_code}[/]")
            print(soup.prettify(), highlight=True)
            return False

        gi = guessit(release_name)

        if gi.get("episode_details") == "Special":
            artist = gi["title"]
            title = (
                f"Season {gi['season']} - {re.sub(r'^Special ', '', gi['episode_title'])}"
            )
        else:
            artist = title = "AutoFill Fail"
            if el := soup.select_one("[name=artist]"):
                artist = el.attrs["value"]
            if el := soup.select_one("[name=title]"):
                title = el.attrs["value"]

        if artist == "AutoFill Fail" or title == "AutoFill Fail":
            if auto:
                eprint("AutoFill Fail.")
                return False
            else:
                wprint("AutoFill Fail, please enter details manually.")
                if type_ == "Movie":
                    artist = Prompt.ask("TV Network / Series Title")
                    title = Prompt.ask("Movie Title")
                else:
                    artist = Prompt.ask("Series Title")
                    title = Prompt.ask("Season/Episode")
        else:
            print("AutoFill complete.")

        if path.is_dir():
            file = sorted([*path.glob("*.mkv"), *path.glob("*.mp4")])[0]
        else:
            file = path

        info = (
            orjson.loads(MediaInfo.parse(file, output="JSON", full=False))
            .get("media", {})
            .get("track", [])
        )

        audio = next(x for x in info if x["@type"] == "Audio")
        lang = audio.get("Language")
        if not lang:
            eprint("Unable to determine audio language.")
            return False
        lang = Language.get(lang)
        if not lang.language:
            eprint("Primary audio track has no language set.")
        lang = lang.fill_likely_values()

        if lang.territory == "419":
            if auto:
                lang.territory = (
                    "ES"  # Technically Latin America but we can't guess automatically
                )
            else:
                lang.territory = Prompt.ask("Enter country code")

        print(f"Detected language as {lang.language}")
        print(f"Detected country as {lang.territory}")

        # Strip episode title if name is too long
        if len(release_name) > 100:
            release_name = release_name.replace(
                gi["episode_title"].replace(" ", "."), ""
            ).replace("..", ".")

        thumbnails_str = ""
        uploader = ImgUploader(self)
        snapshot_urls = []
        for snapshot in uploader.upload(snapshots):
            snapshot_urls.append(
                f"https://i.kek.sh/{snapshot['filename']}"
                if snapshot.get("filename")
                else ""
            )

        if snapshot_urls:
            thumbnail_row_width = min(
                530, self.config.get(self, "snapshot_row_width", 530)
            )
            thumbnail_width = (
                thumbnail_row_width / self.config.get(self, "snapshot_columns", 2)
            ) - 5
            thumbnail_urls = []
            thumbnails = generate_thumbnails(
                snapshots, file_type="jpg", width=thumbnail_width
            )

            for thumb in uploader.upload(thumbnails):
                thumbnail_urls.append(
                    f"https://i.kek.sh/{thumb['filename']}"
                    if thumb.get("filename")
                    else ""
                )

            for i in range(len(snapshots)):
                snapshot = snapshot_urls[i]
                thumb = thumbnail_urls[i]
                thumbnails_str += rf"[url={snapshot}][img]{thumb}[/img][/url]"
                if i % self.config.get(self, "snapshot_columns", 2) == 0:
                    thumbnails_str += " "
                else:
                    thumbnails_str += "\n"

        series_id = None
        if el := soup.select_one("[name=seriesid]"):
            series_id = el.get("value")

        actors = None
        if el := soup.select_one("[name=actors]"):
            actors = el.get("value")

        year = None
        if el := soup.select_one("[name=year]"):
            year = el.get("value")

        tags = "action"
        if el := soup.select_one("[name=tags]"):
            tags = el.attrs.get("value") or tags

        image = None
        if el := soup.select_one("[name=image]"):
            image = el.get("value")

        album_desc = None
        if el := soup.select_one("[name=album_desc]"):
            album_desc = el.text

        format_ = None
        if el := soup.select_one("[name=format] [selected]"):
            format_ = el.get("value")

        bitrate = None
        if el := soup.select_one("[name=bitrate] [selected]"):
            bitrate = el.get("value")

        media: str | list[str] | None = None
        if el := soup.select_one("[name=media] [selected]"):
            media = el.get("value")
        else:
            source: list = [
                "HDTV",
                "PDTV",
                "DSR",
                "DVDRip",
                "TVRip",
                "VHSRip",
                "Bluray",
                "BDRip",
                "BRRip",
                "DVD5",
                "DVD9",
                "HDDVD",
                "WEB-DL",
                "WEBRip",
                "BD5",
                "BD9",
                "BD25",
                "BD50",
                "Mixed",
            ]
            media = next(iter([x for x in source if x in release_name] or []), None)
        if not media:
            media = "Unknown"

        resolution: str = "SD"
        if el := soup.select_one("[name=resolution] [selected]"):
            resolution = el.attrs.get("value") or resolution

        # There must be two blank lines between mediainfo and snapshots per staff due to their parser scripts.
        # The first newline here is just the line terminator for the mediainfo.
        description = f"{mediainfo}\n\n\n{thumbnails_str}"
        if note:
            description = f"[quote]{note}[/quote]\n{description}"
        description = description.strip()

        if release_name.endswith(("-BTW", "-NTb", "-TVSmash")):
            origin: str = "Internal"
        elif release_name.endswith("-NOGRP"):
            origin: str = "None"
        else:
            origin: str = "P2P"

        self.data = {
            "submit": "true",
            "type": type_,
            "scenename": release_name,
            "seriesid": series_id,
            "artist": artist,
            "title": title,
            "actors": actors,
            "origin": origin,
            "foreign": None if lang.language == "en" else "on",
            "country": self.COUNTRY_MAP.get(lang.territory),
            "year": year,
            "tags": tags,
            "image": image,
            "album_desc": album_desc,
            "fasttorrent": "on" if self.config.get(self, "fasttorrent") else None,
            "format": format_,
            "bitrate": bitrate,
            "media": media,
            "resolution": resolution,
            "release_desc": description,
            "tvdb": "autofilled",
        }

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
        r = self.session.post(
            url="https://backup.landof.tv/upload.php",
            data=self.data,
            files={
                "file_input": (
                    str(torrent_path),
                    torrent_path.open("rb"),
                    "application/x-bittorrent",
                ),
            },
            timeout=60,
        )

        soup = load_html(str(r.text))
        if el := soup.select_one("p[style*='color: red']"):
            error = el.text
            eprint(f"Upload failed: [cyan]{error}[/cyan]")
            return False

        id = find(r'<a href="(torrents\.php\?id=\d+)">', str(r.text))
        if id:
            print(
                f"Link: https://broadcasthe.net/{id}",
                True,
            )

        return True
