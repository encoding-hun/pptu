from __future__ import annotations

import re
import time
import uuid
from abc import ABC
from typing import TYPE_CHECKING, Any

from guessit import guessit
from pymediainfo import MediaInfo
from pyotp import TOTP
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn
from rich.prompt import Confirm, Prompt

from ..utils import eprint, load_html, print, wprint
from . import Uploader


if TYPE_CHECKING:
    from pathlib import Path


class AvistaZNetworkUploader(Uploader, ABC):
    min_snapshots: int = 3
    random_snapshots: bool = True
    exclude_regexs: str = r".*\.(ffindex|jpg|png|srt|nfo|torrent|txt)$"

    year_in_series_name: bool = False
    keep_dubbed_dual_tags: bool = False

    COLLECTION_MAP = {
        "movie": None,
        "episode": 1,
        "season": 2,
        "series": 3,
    }

    @property
    def domain(self) -> str:
        return f"{self.name.lower()}.to"

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}"

    @property
    def announce_url(self) -> str:
        return f"https://tracker.{self.domain}/{{passkey}}/announce"

    def login(self, *, args: Any) -> bool:
        with Console().status("Checking cookie validity..."):
            r = self.session.get(
                f"{self.base_url}/account", allow_redirects=False, timeout=60
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

        totp_secret = self.config.get(self, "totp_secret")

        if not (twocaptcha_api_key := self.config.get(self, "2captcha_api_key")):
            eprint("No 2captcha_api_key specified in config, cannot log in.")
            return False

        attempt = 1
        while True:
            r = self.session.get(f"{self.base_url}/auth/login")
            soup = load_html(r.text)

            if not (el := soup.select_one("input[name=_token]")):
                eprint("Failed to get token.")
                return False
            token = el["value"]

            if not (el := soup.select_one(".img-captcha")):
                eprint("Failed to get captcha URL.")
                return False
            captcha_url = el.attrs["src"]

            print("Submitting captcha to 2captcha")
            res = self.session.post(
                url="https://2captcha.com/in.php",
                data={
                    "key": twocaptcha_api_key,
                    "json": "1",
                },
                files={
                    "file": (
                        "captcha.jpg",
                        self.session.get(captcha_url).content,
                        "image/jpeg",
                    ),
                },
                headers={
                    "User-Agent": "pptu/0.1.0",  # TODO: Get version dynamically
                },
            ).json()
            if res["status"] != 1:
                eprint(f"2Captcha API error: [cyan]{res['request']}[/].")
                return False
            req_id = res["request"]

            print("Waiting for solution.", end="", flush=True)
            while True:
                time.sleep(5)
                res = self.session.get(
                    url="https://2captcha.com/res.php",
                    params={
                        "key": twocaptcha_api_key,
                        "action": "get",
                        "id": req_id,
                        "json": "1",
                    },
                ).json()
                if res["request"] == "CAPCHA_NOT_READY":
                    print(".", end="", flush=True)
                elif res["status"] != 1:
                    eprint(f"2Captcha API error: [cyan]{res['request']}[/].")
                    return False
                else:
                    captcha_answer = res["request"]
                    print(" Received")
                    break

            r = self.session.post(
                url=f"{self.base_url}/auth/login",
                data={
                    "_token": token,
                    "email_username": username,
                    "password": password,
                    "captcha": captcha_answer,
                    "remember": "1",
                },
            )

            if (
                "/captcha" in r.url
                or "Verification failed. You might be a robot!" in r.text
            ):
                self.session.post(
                    url="https://2captcha.com/res.php",
                    params={
                        "key": twocaptcha_api_key,
                        "action": "reportbad",
                        "id": req_id,
                    },
                )

                if attempt > 5:
                    eprint("Captcha answer rejected too many times, giving up.")
                    return False

                wprint("Captcha answer rejected, retrying.")
                attempt += 1
                continue

            self.session.post(
                url="https://2captcha.com/res.php",
                params={
                    "key": twocaptcha_api_key,
                    "action": "reportgood",
                    "id": req_id,
                },
            )
            break

        for cookie in self.session.cookies:
            self.cookie_jar.set_cookie(cookie)
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        self.cookie_jar.save(ignore_discard=True)

        if "/auth/twofa" in r.url:
            print("2FA detected")

            soup = load_html(r.text)

            if totp_secret:
                tfa_code = TOTP(totp_secret).now()
            else:
                if args.auto:
                    eprint("No TOTP secret specified in config")
                    return False
                tfa_code = Prompt.ask("Enter 2FA code")

            if not (el := soup.select_one("input[name=_token]")):
                eprint("Failed to get token.")
                return False
            token = el["value"]

            r = self.session.post(
                url=r.url,
                data={
                    "_token": token,
                    "twofa_code": tfa_code,
                },
            )
            if "/auth/twofa" in r.url:
                eprint("TOTP code rejected.")
                print(r.text)
                return False

        if r.url != self.base_url:
            eprint("Login failed - Unknown error.")
            print(r.url)
            return False

        return True

    @property
    def passkey(self) -> str | None:
        r = self.session.get(f"{self.base_url}/account")
        soup = load_html(r.text)
        if not (el := soup.select_one(".current_pid")):
            eprint("Failed to get passkey.")
            return None
        return el.text

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
        if re.search(r"\.S\d+(E\d+)+\.", str(path)):
            print("Detected episode")
            collection = "episode"
        elif re.search(r"\.S\d+\.", str(path)):
            print("Detected season")
            collection = "season"
        elif re.search(r"\.S\d+-S?\d+\.", str(path)):
            collection = "series"
        else:
            collection = "movie"

        if (m := re.search(r"(.+?)\.S\d+(?:E\d+|\.)", path.name)) or (
            m := re.search(r"(.+?\.\d{4})\.", path.name)
        ):
            title = m.group(1).replace(".", " ")
            print(f"Detected title: [bold cyan]{title}[/]")
        else:
            eprint("Unable to extract title from filename.")
            return False

        season = None
        if collection != "movie":
            if m := re.search(r"\.S(\d+)[E.]", path.name):
                season = int(m.group(1))
            else:
                eprint("Unable to extract season from filename.")
                return False

        episode = None
        if m := re.search(r"\.S\d+E(\d+)\.", path.name):
            episode = int(m.group(1))

        r = self.session.get(self.base_url)
        soup = load_html(r.text)

        if not (el := soup.select_one("meta[name=_token]")):
            eprint("Failed to get token.")
            return False
        token = el["content"]

        year = None
        if m := re.search(r" (\d{4})$", title):
            title = title.replace(m.group(0), "")
            year = int(m.group(1))

        # TODO: Automatically add new titles
        while True:
            res = self.session.get(
                url=f"{self.base_url}/ajax/movies/{'1' if collection == 'movie' else '2'}",
                params={
                    "term": title,
                },
                headers={
                    "x-requested-with": "XMLHttpRequest",
                },
                timeout=60,
            ).json()
            print(res, highlight=True)
            r.raise_for_status()

            try:
                res = next(
                    x for x in res["data"] if x.get("release_year") == year or not year
                )
            except StopIteration:
                err = "Title not found on site, please add it manually and try again."
                if auto:
                    eprint(err)
                    return False
                else:
                    wprint(err)
                    if not Confirm.ask("Retry?"):
                        return False
            else:
                break
        movie_id = res["id"]
        print(
            f"Found title: [bold cyan]{res['title']}[/] ([bold green]{res['release_year']}[/])"
        )
        data = {
            "_token": token,
            "type_id": 1 if collection == "movie" else 2,
            "movie_id": movie_id,
            "media_info": mediainfo,
        }
        if not auto:
            print(data, highlight=True)

        url = f"{self.base_url}/upload/{'movie' if collection == 'movie' else 'tv'}"
        r = self.session.post(
            url=url,
            data=data,
            files={
                "torrent_file": (
                    torrent_path.name,
                    torrent_path.open("rb"),
                    "application/x-bittorrent",
                ),
            },
            headers={
                "Referer": url,
            },
            timeout=60,
        )
        self.upload_url = r.url
        soup = load_html(r.text)

        if errors := soup.select(".form-error"):
            for error in errors:
                eprint(f"[cyan]{escape(error.text)}[cyan]")
            return False

        images = []
        snapshots = snapshots[: len(snapshots) - len(snapshots) % 3]
        with Progress(
            TextColumn("[progress.description]{task.description}[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(elapsed_when_finished=True),
        ) as progress:
            for img in progress.track(snapshots, description="Uploading snapshots"):
                res = self.session.post(
                    url=f"{self.base_url}/ajax/image/upload",
                    data={
                        "_token": token,
                        "qquuid": str(uuid.uuid4()),
                        "qqfilename": img.name,
                        "qqtotalfilesize": img.stat().st_size,
                    },
                    files={
                        "qqfile": (img.name, img.open("rb"), "image/png"),
                    },
                    headers={
                        "x-requested-with": "XMLHttpRequest",
                    },
                    timeout=60,
                ).json()
                r.raise_for_status()
                if res["error"]:
                    wprint(f"Failed to upload image: {res['error']}")
                else:
                    images.append(res["imageId"])

        release_name = path.stem if path.is_file() else path.name

        gi = guessit(release_name)
        if gi.get("episode_details") != "Special":
            # Strip episode title
            release_name = release_name.replace(
                gi.get("episode_title", "").replace(" ", "."), ""
            ).replace("..", ".")

        if path.is_dir():
            file = sorted([*path.glob("*.mkv"), *path.glob("*.mp4")])[0]
        else:
            file = path
        mediainfo_obj = MediaInfo.parse(file)

        if mediainfo_obj.video_tracks[0].encoded_library_name == "x264":
            release_name = re.sub(r"(?i)h\.?264", "x264", release_name)
        if mediainfo_obj.video_tracks[0].encoded_library_name == "x265":
            release_name = re.sub(r"(?i)h\.?265", "x265", release_name)

        if self.year_in_series_name:
            release_name = re.sub(r"\b(S\d+)\b", rf"\1 ({year})", release_name)

        if not self.keep_dubbed_dual_tags:
            release_name = release_name.replace(".DUBBED.", "")
            release_name = release_name.replace(".DUAL.", "")

        if not (el := soup.select_one("input[name=info_hash]")):
            eprint("Failed to get info hash.")
            return False
        info_hash = el["value"]

        if not (el := soup.select_one("select[name=rip_type_id] option[selected]")):
            eprint("Failed to get rip type.")
            return False
        rip_type_id = el["value"]

        if not (
            el := soup.select_one("select[name=video_quality_id] option[selected]")
        ):
            eprint("Failed to get video quality.")
            return False
        video_quality_id = el["value"]

        if not (el := soup.select_one("input[name=video_resolution]")):
            eprint("Failed to get video resolution.")
            return False
        video_resolution = el["value"]

        self.data = {
            "_token": token,
            "info_hash": info_hash,
            "torrent_id": "",
            "type_id": 1 if collection == "movie" else 2,
            "task_id": self.upload_url.split("/")[-1],
            "file_name": (
                release_name.replace(".", " ")
                .replace("H 264", "H.264")
                .replace("H 265", "H.265")
                .replace("2 0 ", "2.0 ")
                .replace("5 1 ", "5.1 ")
            ),
            "anon_upload": "1"
            if self.config.get(self, "anonymous_upload", True)
            else "",
            "description": note or "",
            "qqfile": "",
            "screenshots[]": images,
            "rip_type_id": rip_type_id,
            "video_quality_id": video_quality_id,
            "video_resolution": video_resolution,
            "movie_id": movie_id,
            "tv_collection": self.COLLECTION_MAP[collection],
            "tv_season": season,
            "tv_episode": episode,
            "languages[]": [
                x["value"]
                for x in soup.select("select[name='languages[]'] option[selected]")
            ],
            "subtitles[]": [
                x["value"]
                for x in soup.select("select[name='subtitles[]'] option[selected]")
            ],
            "media_info": mediainfo,
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
        r = self.session.post(url=self.upload_url, data=self.data, timeout=60)
        soup = load_html(r.text)
        r.raise_for_status()

        if not (el := soup.select_one("a[href*='/download/']")):
            eprint("Failed to get torrent download URL.")
            return False
        torrent_url = el.attrs["href"]

        self.session.get(torrent_url, timeout=60)

        return True
