from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from imdb import Cinemagoer
from pymediainfo import MediaInfo
from pyotp import TOTP
from rich.markup import escape
from rich.prompt import Prompt

from ..utils import Img, eprint, load_html, print, wprint
from . import Uploader


if TYPE_CHECKING:
    from pathlib import Path


ia = Cinemagoer()


class PassThePopcornUploader(Uploader):
    name: str = "PassThePopcorn"
    abbrev: str = "PTP"
    source: str = "PTP"
    announce_url: str = "http://please.passthepopcorn.me:2710/{passkey}/announce"  # HTTPS tracker cert is expired
    exclude_regexs: str = r".*\.(ffindex|jpg|png|srt|nfo|torrent|txt)$"
    all_files: bool = True

    # TODO: Some of these have potential for false positives if they're in the movie name
    EDITION_MAP: dict = {
        r"\.DC\.": "Director's Cut",
        r"(?i)\.extended\.": "Extended Edition",
        r"\.TC\.": "Theatrical Cut",
        r"(?i)\.theatrical\.": "Theatrical Cut",
        r"(?i)\.uncut\.": "Uncut",
        r"(?i)\.unrated\.": "Unrated",
        r"Hi10P": "10-bit",
        r"DTS[\.-]?X": "DTS:X",
        r"\.(?:Atmos|DDPA|TrueHDA)\.": "Dolby Atmos",
        r"\.(?:DV|DoVi)\.": "Dolby Vision",
        r"\.DUAL\.": "Dual Audio",
        r"\.DUBBED\.": "English Dub",
        r"(?i)\.extras\.": "Extras",
        r"\bHDR": "HDR10",
        r"(?i)\bHDR10(?:\+|P(?:lus)?)\b": "HDR10+",
        r"(?i)\.remux\.": "Remux",
        r"(?i)\.Hybrid\.": "Hybrid",
    }

    def __init__(self) -> None:
        super().__init__()
        self.anti_csrf_token: str | None = None

    @property
    def passkey(self) -> str | None:
        r = self.session.get("https://passthepopcorn.me/upload.php")
        soup = load_html(r.text)
        if not (el := soup.select_one("input[value$='/announce']")):
            eprint("Failed to get announce URL.")
            return None
        return el.attrs["value"].split("/")[-2]

    def login(self, *, args: Any) -> bool:
        r = self.session.get(
            "https://passthepopcorn.me/user.php?action=edit", allow_redirects=False
        )
        if r.status_code == 200:
            return True

        wprint("Cookies missing or expired, logging in...")

        if not (username := self.config.get(self, "username")):
            eprint("No username specified in config, cannot log in.")
            return False

        if not (password := self.config.get(self, "password")):
            eprint("No password specified in config, cannot log in.")
            return False

        if not (passkey := self.config.get(self, "passkey")):
            eprint("No passkey specified in config, cannot log in.")
            return False

        totp_secret = self.config.get(self, "totp_secret")

        res = self.session.post(
            url="https://passthepopcorn.me/ajax.php?action=login",
            data={
                "Popcron": "",
                "username": username,
                "password": password,
                "passkey": passkey,
                "WhatsYourSecret": "Hacker! Do you really have nothing better to do than this?",
                "keeplogged": "1",
                **(
                    {
                        "TfaType": "normal",
                        "TfaCode": TOTP(totp_secret).now(),
                    }
                    if totp_secret
                    else {}
                ),
            },
        ).json()

        if res["Result"] == "TfaRequired":
            if args.auto:
                eprint("No TOTP secret specified in config")
                return False
            tfa_code = Prompt.ask("Enter 2FA code")
            res = self.session.post(
                url="https://passthepopcorn.me/ajax.php?action=login",
                data={
                    "Popcron": "",
                    "username": username,
                    "password": password,
                    "passkey": passkey,
                    "WhatsYourSecret": "Hacker! Do you really have nothing better to do than this?",
                    "keeplogged": "1",
                    "TfaType": "normal",
                    "TfaCode": tfa_code,
                },
            ).json()

        if res["Result"] != "Ok":
            eprint(f"Login failed: [cyan]{res['Result']}[/]")
            return False

        self.anti_csrf_token = res["AntiCsrfToken"]
        return True

    def prepare(  # type: ignore[override]
        self,
        path: Path,
        torrent_path: Path,
        mediainfo: list[str],
        snapshots: list[Path],
        *,
        note: str | None,
        auto: bool,
    ) -> bool:
        imdb = None
        try:
            if (m := re.search(r"(.+?)\.S\d+(?:E\d+|\.)", path.name)) or (
                m := re.search(r"(.+?\.\d{4})\.", path.name)
            ):
                title = re.sub(r" (\d{4})$", r" (\1)", m.group(1).replace(".", " "))
                print(f"Detected title: [bold cyan]{title}[/]")

                if imdb_results := ia.search_movie(title):
                    imdb = f"https://www.imdb.com/title/tt{imdb_results[0].movieID}/"
            else:
                wprint("Unable to extract title from filename.")
        except Exception as e:
            wprint(f"Cinemagoer got error {str(e)}")
        if not imdb:
            if auto:
                eprint("Unable to get IMDb URL")
                return False
            imdb = Prompt.ask("Enter IMDb URL")

        if not imdb:
            eprint("No IMDb URL provided")
            return False

        if not (m := re.search(r"tt(\d+)", imdb)):
            eprint("Invalid IMDb URL")
            return False

        imdb_movie = ia.get_movie(m.group(1))
        title = imdb_movie.data.get("original title") or imdb_movie.data.get(
            "localized title"
        )
        if not title:
            wprint("Unable to get movie title from IMDb")
            title = Prompt.ask("Movie title")
        year = imdb_movie.data.get("year")
        if not year:
            wprint("Unable to get movie year from IMDb")
            year = Prompt.ask("Movie year")

        print(f"IMDb: [cyan][bold]{title}[/] [not bold]({year})[/][/]")

        self.groupid = None
        torrent_info = self.session.get(
            url="https://passthepopcorn.me/ajax.php",
            params={
                "action": "torrent_info",
                "imdb": imdb,
                "fast": "1",
            },
        ).json()[0]
        print("Info to ptp:")
        for key, value in torrent_info.items():
            print(f"{key}: [cyan][bold]{value}[/]")
        self.groupid = torrent_info.get("groupid")

        r = self.session.get(
            "https://passthepopcorn.me/upload.php", params={"groupid": self.groupid}
        )

        if not self.anti_csrf_token:
            soup = load_html(r.text)
            if not (el := soup.select_one("[name=AntiCsrfToken]")):
                eprint("Failed to extract CSRF token.")
                return False
            self.anti_csrf_token = el.attrs["value"]

        if path.is_dir():
            file = sorted([*path.glob("*.mkv"), *path.glob("*.mp4")])[0]
        else:
            file = path
        mediainfo_obj = MediaInfo.parse(file)
        no_eng_subs = all(
            not x.language.startswith("en") for x in mediainfo_obj.audio_tracks
        ) and all(not x.language.startswith("en") for x in mediainfo_obj.text_tracks)
        any_sub = any(x for x in mediainfo_obj.text_tracks)

        snapshot_urls = []
        uploader = Img(self)
        for snap in uploader.upload(snapshots):
            snapshot_urls.append(
                f'https://ptpimg.me/{snap[0]["code"]}.{snap[0]["ext"]}'
            )

        if re.search(r"\.S\d+\.", str(path)):
            print("Detected series")
            type_ = "Miniseries"
            desc = ""
            for i in range(len(mediainfo)):
                desc += "[mi]\n{mediainfo}\n[/mi]\n{snapshots}\n\n".format(
                    mediainfo=mediainfo[i],
                    snapshots=snapshot_urls[i],
                )
        else:
            # TODO: Detect other types
            print("Detected movie")
            type_ = "Feature Film"
            desc = "[mi]\n{mediainfo}\n[/mi]\n{snapshots}".format(
                mediainfo=mediainfo[0],
                snapshots="\n".join(snapshot_urls),
            )
        if note:
            desc = f"[quote]{note}[/quote]\n{desc}"
        desc = desc.strip()

        if re.search(r"\b(?:b[dr]-?rip|blu-?ray)\b", str(path), flags=re.I):
            source = "Blu-ray"
        elif re.search(r"\bhd-?dvd\b", str(path), flags=re.I):
            source = "HD-DVD"
        elif re.search(r"\bdvd(?:rip)?\b", str(path), flags=re.I):
            source = "DVD"
        elif re.search(r"\bweb-?(?:dl|rip)?\b", str(path), flags=re.I):
            source = "WEB"
        elif re.search(r"\bhdtv\b", str(path), flags=re.I):
            source = "HDTV"
        elif re.search(r"\bpdtv\b|\.ts$", str(path), flags=re.I):
            source = "TV"
        elif re.search(r"\bvhs(?:rip)?\b", str(path), flags=re.I):
            source = "VHS"
        else:
            source = "Other"
        print(f"Detected source: [bold cyan]{source}[/]")

        tag = (path.name if path.is_dir() else path.stem).split("-")[-1]

        remaster_title = " / ".join(
            {v for k, v in self.EDITION_MAP.items() if re.search(k, str(path))}
        )

        self.data = {
            "AntiCsrfToken": self.anti_csrf_token,
            "type": type_,
            "imdb": imdb,
            "image": imdb_movie.data["cover url"],
            "remaster_title": remaster_title,
            "remaster": "on" if remaster_title else "off",
            "remaster_year": "",
            **(
                {"internalrip": "on"}
                if tag in self.config.get(self, "personal_rip_tags", [])
                else {}
            ),
            "source": source,
            "other_source": "",
            "codec": "* Auto-detect",
            "container": "* Auto-detect",
            "resolution": "* Auto-detect",
            "tags": imdb_movie.data["genres"],
            "other_resolution_width": "",
            "other_resolution_height": "",
            "release_desc": desc,
            "subtitles[]": "" if any_sub else "44",
            "nfo_text": "",
            "trumpable[]": [14] if no_eng_subs else [],
            "uploadtoken": "",
            **torrent_info,
        }

        return True

    def upload(  # type: ignore[override]
        self,
        path: Path,
        torrent_path: Path,
        mediainfo: list[str],
        snapshots: list[str],
        *,
        note: str | None,
        auto: bool,
    ) -> bool:
        r = self.session.post(
            url="https://passthepopcorn.me/upload.php",
            params={
                "groupid": self.groupid,
            },
            data=self.data,
            files={
                "file_input": (
                    torrent_path.name,
                    torrent_path.open("rb"),
                    "application/x-bittorrent",
                )
            },
        )
        soup = load_html(r.text)
        if error := soup.select_one(".alert--error"):
            eprint(escape(error.get_text()))
            return False

        return True
