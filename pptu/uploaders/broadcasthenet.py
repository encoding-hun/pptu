import json
import re
import subprocess

import httpx
from guessit import guessit
from langcodes import Language
from pyotp import TOTP
from rich.progress import track
from rich.prompt import Prompt

from ..utils import eprint, generate_thumbnails, load_html, print, wprint
from . import Uploader


class BroadcasTheNetUploader(Uploader):
    name = "BroadcasTheNet"
    abbrev = "BTN"
    announce_url = "http://landof.tv/{passkey}/announce"

    COUNTRY_MAP = {
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

    @property
    def passkey(self):
        res = self.session.get("https://backup.landof.tv/upload.php").text
        soup = load_html(res)
        return soup.select_one("input[value$='/announce']")["value"].split("/")[-2]

    def login(self, *, auto):
        # Allow cookies from either broadcasthe.net or backup.landof.tv
        for cookie in self.session.cookies:
            cookie.domain = cookie.domain.replace("broadcasthe.net", "backup.landof.tv")

        r = self.session.get("https://backup.landof.tv/user.php")
        if "login.php" not in r.url:
            return True

        wprint("Cookies missing or expired, logging in...")

        if not (username := self.config.get(self, "username")):
            eprint("No username specified in config, cannot log in.")
            return False

        if not (password := self.config.get(self, "password")):
            eprint("No password specified in config, cannot log in.")
            return False

        print("Logging in")
        r = self.session.post(
            url="https://backup.landof.tv/login.php",
            data={
                "username": username,
                "password": password,
                "keeplogged": "1",
                "login": "Log In!",
            },
        )
        r.raise_for_status()

        if "login.php" in r.url:
            if totp_secret := self.config.get(self, "totp_secret"):
                tfa_code = TOTP(totp_secret).now()
            else:
                if auto:
                    eprint("No TOTP secret specified in config")
                    return False
                tfa_code = Prompt.ask("Enter 2FA code")

            r = self.session.post(
                url="https://backup.landof.tv/login.php",
                data={
                    "code": tfa_code,
                    "act": "authenticate",
                },
            )
            r.raise_for_status()

        return "login.php" not in r.url

    def prepare(self, path, mediainfo, snapshots, *, auto):
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
        release_name = re.sub(r"\.([a-z]+)\.?([\d.]+)\.Atmos", r"\.\1A\2", release_name, flags=re.I)
        if m := re.search(r"\.(?:DV|DoVi)(?:\.HDR(?:10(?:\+|P|Plus))?)?\b", release_name, flags=re.I):
            release_name = release_name.replace(m.group(), "")
            release_name = re.sub(r"\.(\d+p)", r".DV.\1", release_name)
        elif m := re.search(r"\.(?:\.HDR(?:10(?:\+|P|Plus)))\b", release_name, flags=re.I):
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
        soup = load_html(r.text)
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
            title = f"Season {gi['season']} - {re.sub(r'^Special ', '', gi['episode_title'])}"
        else:
            artist = soup.select_one('[name="artist"]').get("value")
            title = soup.select_one('[name="title"]').get("value")

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
            file = list(sorted([*path.glob("*.mkv"), *path.glob("*.mp4")]))[0]
        else:
            file = path
        if file.suffix == ".mkv":
            info = json.loads(subprocess.run(["mkvmerge", "-J", file], capture_output=True, encoding="utf-8").stdout)
            audio = next(x for x in info["tracks"] if x["type"] == "audio")
            lang = audio["properties"].get("language_ietf") or audio["properties"].get("language")
            if not lang:
                eprint("Unable to determine audio language.")
                return False
            lang = Language.get(lang)
            if not lang.language:
                eprint("Primary audio track has no language set.")
            lang = lang.fill_likely_values()
        elif file.suffix == ".mp4":
            eprint("MP4 is not yet supported.")  # TODO
            return False
        else:
            eprint("File must be MKV or MP4.")
            return False

        if lang.territory == "419":
            if auto:
                lang.territory = "ES"  # Technically Latin America but we can't guess automatically
            else:
                lang.territory = Prompt.ask("Enter country code")

        print(f"Detected language as {lang.language}")
        print(f"Detected country as {lang.territory}")

        # Strip episode title if name is too long
        if len(release_name) > 100:
            release_name = release_name.replace(gi["episode_title"].replace(" ", "."), "").replace("..", ".")

        thumbnails_str = ""
        if imgbin_api_key := self.config.get(self, "imgbin_api_key"):
            snapshot_urls = []
            for snap in track(snapshots, description="Uploading snapshots"):
                with open(snap, "rb") as fd:
                    # requests gets blocked by Cloudflare here, have to use httpx
                    res = httpx.post(
                        url="https://imgbin.broadcasthe.net/upload",
                        files={
                            "file": fd,
                        },
                        headers={
                            "Authorization": f"Bearer {imgbin_api_key}",
                        },
                        timeout=60,
                    ).json()
                    snapshot_urls.append(next(iter(res.values()))["hotlink"])

            thumbnail_row_width = min(530, self.config.get(self, "snapshot_row_width", 530))
            thumbnail_width = (thumbnail_row_width / self.config.get(self, "snapshot_columns", 2)) - 5
            thumbnail_urls = []
            for thumb in track(
                generate_thumbnails(snapshots, width=thumbnail_width), description="Uploading thumbnails"
            ):
                with open(thumb, "rb") as fd:
                    res = httpx.post(
                        url="https://imgbin.broadcasthe.net/upload",
                        files={
                            "file": fd,
                        },
                        headers={
                            "Authorization": f"Bearer {imgbin_api_key}",
                        },
                        timeout=60,
                    ).json()
                    thumbnail_urls.append(next(iter(res.values()))["hotlink"])

            for i in range(len(snapshots)):
                snap = snapshot_urls[i]
                thumb = thumbnail_urls[i]
                thumbnails_str += rf"[url={snap}][img]{thumb}[/img][/url]"
                if i % self.config.get(self, "snapshot_columns", 2) == 0:
                    thumbnails_str += " "
                else:
                    thumbnails_str += "\n"
        else:
            wprint("No imgbin API key specified, skipping snapshots")

        self.data = {
            "submit": "true",
            "type": type_,
            "scenename": release_name,
            "seriesid": (soup.select_one('[name="seriesid"]') or {}).get("value"),
            "artist": artist,
            "title": title,
            "actors": (soup.select_one('[name="actors"]') or {}).get("value"),
            "origin": "Internal" if release_name.endswith(("-BTW", "-NTb", "-TVSmash")) else "P2P",
            "foreign": None if lang.language == "en" else "on",
            "country": self.COUNTRY_MAP.get(lang.territory),
            "year": soup.select_one('[name="year"]').get("value"),
            "tags": soup.select_one('[name="tags"]').get("value") or "action",
            "image": soup.select_one('[name="image"]').get("value"),
            "album_desc": soup.select_one('[name="album_desc"]').text,
            "fasttorrent": "on" if self.config.get(self, "fasttorrent") else None,
            "format": soup.select_one('[name="format"] [selected]').get("value"),
            "bitrate": soup.select_one('[name="bitrate"] [selected]').get("value"),
            "media": soup.select_one('[name="media"] [selected]').get("value"),
            "resolution": (soup.select_one('[name="resolution"] [selected]') or {"value": "SD"}).get("value"),
            "release_desc": f"{mediainfo}\n\n\n{thumbnails_str}".strip(),
            "tvdb": "autofilled",
        }

        return True

    def upload(self, path, mediainfo, snapshots, *, auto):
        torrent_path = self.dirs.user_cache_path / f"{path.name}_files" / f"{path.name}[BTN].torrent"
        self.session.post(
            url="https://backup.landof.tv/upload.php",
            data=self.data,
            files={
                "file_input": (str(torrent_path), torrent_path.open("rb"), "application/x-bittorrent"),
            },
            timeout=60,
        )

        return True
