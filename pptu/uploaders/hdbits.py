from __future__ import annotations

import hashlib
import re
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import cloup
from guessit import guessit
from imdb import Cinemagoer
from pyotp import TOTP
from rich.prompt import Prompt

from pptu.uploaders import Uploader
from pptu.utils import ImgUploader, eprint, load_html, print, wprint


if TYPE_CHECKING:
    from pathlib import Path


ia = Cinemagoer()


class HDBits(Uploader):
    source = "HDBits"
    min_snapshots = 4  # 2 for movies and single episodes

    CAPTCHA_MAP = {
        "efe8518424149278ddfaaf609b6a0b1a4749f61b61ef28824da67d68fb333af3": "bug",
        "efa72724b28ccc386cc5c1384ea68ecd51ff9c7f7351dae908853aba40230ed1": "clock",
        "d462f4dde17c39168868373f8a2733f7e373ca89a471eb4ea247c55f096f0d7e": "flag",
        "4cee2b7c0807bf5301bb1c5ac89b160eac7b2b36d3ec88cfc4fb592146731654": "heart",
        "33a0bcf45bf94fa6e157310f4d99193a011b4287629c9a95cde49910741b164b": "house",
        "4e1a3fd65b3e7434429b9a207ecb7f1e357c2e0b46c081cf85533f7a419f5710": "key",
        "755c605d2d5b87dcc9d77e7640cdcbf10662f375e9294694e046dddb99a19474": "light bulb",
        "d38add46e8860bbb7e3ff577d0dfcad301dd68e23429e26e1447c31dc50d6ca2": "musical note",
        "8ef0ee9ba6b93a1dd5b1dbda7e24510d130cafb9a3453c2be710d09474274a5e": "pen",
        "518eb4eb8aaea5916d14531b479f046a0f1323fd0dbb2a9325b45a65715b9084": "world",
    }
    CATEGORY_MAP = {
        "Movie": 1,
        "TV": 2,
    }
    CODEC_MAP = {
        "H.264": 1,
        "HEVC": 5,
        "MPEG-2": 2,
        "VC-1": 3,
        "VP9": 6,
        "XviD": 4,
    }
    MEDIUM_MAP = {
        "Blu-ray/HD-DVD": 1,
        "Capture": 4,
        "Encode": 3,
        "Remux": 5,
        "WEB-DL": 6,
    }
    TAG_MAP = {
        # Formats
        r"\b(?:Atmos|DDPA|TrueHDA)\b": 5,  # Dolby Atmos
        r"DTS[\.-]?X": 7,  # DTS:X
        r"\b(?:DV|DoVi)\b": 6,  # Dolby Vision
        r"\bHDR": 9,  # HDR10
        r"(?i)\bHDR10(?:\+|P(?:lus)?)\b": 25,  # HDR10+
        r"\bHFR\b": 36,  # HFR
        r"\bHLG\b": 10,  # HLG
        r"\bIMAX\b": 14,  # IMAX
        r"\bOM\b": 58,  # Open Matte
        r"\bTC\b|(?i)\btheatrical\b": 94,  # Theatrical Cut
        r"\bDC\b": 93,  # Director's Cut
        # Streaming services
        r"\bAMZN\b": 28,  # Amazon
        r"\bATVP\b": 27,  # Apple TV+
        r"\bB?CORE\b": 66,  # Bravia Core
        r"\bCRAV\b": 80,  # Crave
        r"\bCRKL\b": 73,  # Crackle
        r"\bCR\b": 72,  # Crunchyroll
        r"\bDSNP\b": 33,  # Disney+
        r"\bFUNI\b": 74,  # Funimation
        r"\bHLMK\b": 71,  # Hallmark Channel
        r"\bHMAX\b": 30,  # HBO Max
        r"\bMAX\b": 88,  # MAX
        r"\bHS\b": 79,  # Hotstar
        r"\bHULU\b": 34,  # Hulu
        r"\biP\b": 56,  # BBC iPlayer
        r"\biT\b": 38,  # iTunes
        r"\bMA\.WEB\b": 77,  # Movies Anywhere
        r"\bNF\b": 29,  # Netflix
        r"\bPCOK\b": 31,  # Peacock
        r"\bPMTP\b": 69,  # Paramount+
        r"\bSHO\b": 76,  # Showtime
        r"\bSTAN\b": 32,  # Stan
        r"\bROKU\b": 87,  # Roku
        r"\bALL4\b": 107,  # Channel4
        r"\bNOW\b": 96,  # NOW
    }

    @staticmethod
    @cloup.command(
        name="HDBits",
        aliases=["HDB"],
        short_help="https://hdbits.org/",
        help=__doc__,
    )
    @cloup.pass_context
    def cli(ctx: cloup.Context, **kwargs: Any) -> HDBits:
        return HDBits(ctx, SimpleNamespace(**kwargs))

    def __init__(self, ctx: cloup.Context, args: Any) -> None:
        super().__init__(ctx)

    @property
    def announce_url(self) -> str:
        return "https://tracker.hdbits.org/announce.php"

    @property
    def exclude_regex(self) -> str:
        return r".*\.(ffindex|jpg|png|srt|nfo|torrent|txt)$"

    @property
    def passkey(self) -> str | None:
        if res := self.session.get("https://hdbits.org/").text:
            if m := re.search(r"passkey=([a-f0-9]+)", res):
                return m.group(1)
        return None

    def login(self, *, args: Any = None) -> bool:
        r = self.session.get("https://hdbits.org")
        if not str(r.url).startswith("https://hdbits.org/login"):
            return True

        wprint("Cookies missing or expired, logging in...")

        captcha = self.session.get(
            "https://hdbits.org/simpleCaptcha.php", params={"numImages": "5"}
        ).json()
        correct_hash = None
        for image in captcha["images"]:
            if r := self.session.get(
                "https://hdbits.org/simpleCaptcha.php", params={"hash": image}
            ).content:
                if self.CAPTCHA_MAP.get(hashlib.sha256(r).hexdigest()) == captcha["text"]:
                    correct_hash = image
                    print(
                        f"Found captcha solution: [bold cyan]{captcha['text']}[/] ([cyan]{correct_hash}[/])"
                    )
                    break
        if not correct_hash:
            eprint("Unable to solve captcha, perhaps it has new images?")
            return False

        r = self.session.get(
            "https://hdbits.org/login?returnto=/", params={"returnto": "/"}
        )
        soup = load_html(str(r.text))

        totp_secret = self.config.get(self, "totp_secret")

        if not (el := soup.select_one("[name=csrf]")):
            eprint("Failed to extract CSRF token.")
            print(f"Cookies location: {self.cookies_path}")
            return False
        csrf_token = el["value"]

        r = self.session.post(
            url="https://hdbits.org/login/doLogin",
            data={
                "csrf": csrf_token,
                "uname": self.config.get(self, "username"),
                "password": self.config.get(self, "password"),
                "twostep_code": TOTP(totp_secret).now() if totp_secret else None,
                "captchaSelection": correct_hash,
                "returnto": "/",
            },
        )
        if "error=7" in str(r.url):
            print("2FA detected")
            if args.auto:
                eprint("No TOTP secret specified in config")
                return False
            r = self.session.post(
                url="https://hdbits.org/login/doLogin",
                data={
                    "csrf": csrf_token,
                    "uname": self.config.get(self, "username"),
                    "password": self.config.get(self, "password"),
                    "twostep_code": Prompt.ask("Enter 2FA code"),
                    "captchaSelection": correct_hash,
                    "returnto": "/",
                },
            )

        if "error" in str(r.url):
            soup = load_html(str(r.text))
            if el := soup.find("td", {"class": "text"}):
                error = re.sub(r"\s+", " ", el.text).strip()
            elif el := soup.select_one("embedded"):
                error = re.sub(r"\s+", " ", el.text).strip()
            else:
                error = "Unknown error"
                if m := re.search(r"error=(\d+)", str(r.url)):
                    error += f" {m[1]}"
            eprint(error, True)

        return True

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
        if re.search(r"\.S\d+(E\d+)*\.", str(path)):
            print("Detected series")
            category = "TV"
        else:
            print("Detected movie")
            category = "Movie"

        if category == "TV":
            imdb = None

            res = self.session.get(
                url="https://hdbits.org/ajax/tvdb.php",
                params={
                    "action": "parsename",
                    "title": path.name,
                    "uid": str(int(time.time() * 1000)),
                },
            ).json()

            for key, value in res.items():
                print(f"{key}: [cyan][bold]{value}[/]")

            if not (tvdb := res.get("tvdb_id")):
                r = self.session.get(
                    url="https://hdbits.org/ajax/tvdb.php",
                    params={
                        "action": "showsearch",
                        "search": res["showname"],
                        "uid": str(int(time.time() * 1000)),
                    },
                )
                r.raise_for_status()
                if res2 := r.json():
                    tvdb = next(iter(res2.keys()))
            if not tvdb:
                if auto:
                    eprint("Unable to get TVDB ID")
                tvdb = Prompt.ask("Enter TVDB ID")

            season = res["season"]
            episode = res["episode"]
        else:
            imdb = None
            if (m := re.search(r"(.+?)\.S\d+(?:E\d+|\.)", path.name)) or (
                m := re.search(r"(.+?\.\d{4})\.", path.name)
            ):
                title = re.sub(r" (\d{4})$", r" (\1)", m.group(1).replace(".", " "))
                print(f"Detected title: [bold cyan]{title}[/]")

                if imdb_results := ia.search_movie(title):
                    # needs more testing
                    # imdb_results.sort(
                    #    key=lambda x: similar(x.data["title"], title), reverse=True
                    # )
                    imdb = f"https://www.imdb.com/title/tt{imdb_results[0].movieID}/"
            else:
                wprint("Unable to extract title from filename.")
            imdb = imdb or input("Enter IMDb URL: ")
            tvdb = None
            season = None
            episode = None

        if re.search(r"\b(?:[hx]\.?264|avc)\b", str(path), flags=re.I):
            codec = "H.264"
        elif re.search(r"\b(?:[hx]\.?265|hevc)\b", str(path), flags=re.I):
            codec = "HEVC"
        elif re.search(r"\b(?:mp(?:eg)?-?2)\b", str(path), flags=re.I):
            codec = "MPEG-2"
        elif re.search(r"\b(?:vc-?1)\b", str(path), flags=re.I):
            codec = "VC-1"
        elif re.search(r"\b(?:vp-?9)\b", str(path), flags=re.I):
            codec = "VP9"
        elif re.search(r"\b(?:divx|xvid|[hx]\.?263)\b", str(path), flags=re.I):
            codec = "XviD"
        else:
            eprint("Unable to determine video codec")
            return False
        print(f"Detected codec as [bold cyan]{codec}[/]")

        if re.search(r"\b(?:b[dr]-?rip|blu-?ray|hd-?dvd)\b", str(path), flags=re.I):
            medium = "Blu-ray/HD-DVD"
        elif re.search(r"\b[ph]dtv\b|\.ts$", str(path), flags=re.I):
            medium = "Capture"
        elif re.search(
            r"\bweb-?rip\b", str(path), flags=re.I
        ):  # TODO: Detect more encodes
            medium = "Encode"
        elif re.search(r"\bremux\b", str(path), flags=re.I):
            medium = "Remux"
        elif re.search(r"\bweb(?:-?dl)?\b", str(path), flags=re.I):
            medium = "WEB-DL"
        else:
            eprint("Unable to determine medium")
            return False
        print(f"Detected medium as [bold cyan]{medium}[/]")

        name: str = path.name

        tags = []
        for pattern, tag_id in self.TAG_MAP.items():
            if re.search(pattern, name):
                tags.append(tag_id)

        gi = guessit(path.name)
        if gi.get("episode_details") != "Special":
            # Strip episode title
            name = name.replace(
                gi.get("episode_title", "").replace(" ", "."), ""
            ).replace("..", ".")
        # Strip streaming service
        name = re.sub(r"(\d+p)\.[a-z0-9]+\.(web)", r"\1.\2", name, flags=re.IGNORECASE)
        # Strip Atmos
        name = re.sub(r"\.atmos", "", name, flags=re.IGNORECASE)
        # DV/HDR normalization
        name = re.sub(r"HDR10(?:\+|P|Plus)", "HDR", name, flags=re.IGNORECASE)
        name = re.sub(r"(?:DV|DoVi)\.HDR", "DoVi", name)
        # Strip other tags
        name = name.replace(".DUBBED", "")
        name = name.replace(".DUAL", "")

        thumbnail_row_width = min(900, self.config.get(self, "snapshot_row_width", 900))
        allowed_widths = [100, 150, 200, 250, 300, 350]
        thumbnail_width = (
            thumbnail_row_width / self.config.get(self, "snapshot_columns", 2)
        ) - 5
        thumbnail_width = max(x for x in allowed_widths if x <= thumbnail_width)

        thumbnails_str = ""
        uploader = ImgUploader(self)
        for i, url in enumerate(uploader.upload(snapshots, thumbnail_width, name)):
            thumbnails_str += url
            if i % self.config.get(self, "snapshot_columns", 2) == 0:
                thumbnails_str += " "
            else:
                thumbnails_str += "\n"

        description = "[center]"
        if note:
            description += f"[quote]{note}[/quote]\n"
        description += f"{thumbnails_str}[/center]"

        self.data = {
            "name": name,
            "category": self.CATEGORY_MAP[category],
            "codec": self.CODEC_MAP[codec],
            "medium": self.MEDIUM_MAP[medium],
            "origin": 0,  # TODO: Support internal
            "descr": description if thumbnails_str else "",
            "techinfo": mediainfo,
            "tags[]": tags,
            "imdb": imdb,
            "tvdb": tvdb,
            "tvdb_season": 0 if gi.get("episode_details") == "Special" else season,
            "tvdb_episode": episode,  # TODO: Get special episode number from TVDB
            "anidb_id": None,  # TODO
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
        res = self.session.post(
            url="https://hdbits.org/upload/upload",
            files={
                "file": (
                    torrent_path.name.replace("[HDB]", ""),
                    torrent_path.open("rb"),
                    "application/x-bittorrent",
                ),
            },
            data=self.data,
        ).text

        soup = load_html(res)
        if not (el := soup.select_one(".js-download")):
            eprint("Failed to get torrent download URL.")
            return False

        torrent_url = f"https://hdbits.org{el.attrs['href']}"
        torrent_path.write_bytes(self.session.get(torrent_url).content)

        return True
