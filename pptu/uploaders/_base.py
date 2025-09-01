from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha1
from http.cookiejar import MozillaCookieJar
from typing import TYPE_CHECKING, Any

import cloup
import niquests
from niquests.adapters import HTTPAdapter
from urllib3_future.util.retry import Retry

from pptu.utils import Config, eprint


if TYPE_CHECKING:
    from pathlib import Path


class Uploader(ABC):
    source: str | None = None  # Source tag to use in created torrent files
    all_files: bool = False  # Whether to generate MediaInfo and snapshots for all files
    min_snapshots: int = 0
    snapshots_plus: int = 0  # Number of extra snapshots to generate
    random_snapshots: bool = False
    mediainfo: bool = True

    def __init__(self, ctx: cloup.Context) -> None:
        self.dirs = ctx.obj.dirs
        self.config: Config = ctx.obj.config

        self.cookies_path = (
            self.dirs.user_data_path
            / "cookies"
            / f"""{self.cli.name.lower()}_{sha1(f"{self.config.get(self, 'username')}".encode()).hexdigest()}.txt"""
        )
        if not self.cookies_path.exists():
            self.cookies_path = (
                self.dirs.user_data_path
                / "cookies"
                / f"""{self.cli.aliases[0].lower()}_{sha1(f"{self.config.get(self, 'username')}".encode()).hexdigest()}.txt"""
            )
        self.cookie_jar = MozillaCookieJar(self.cookies_path)
        if self.cookies_path.exists():
            self.cookie_jar.load(ignore_expires=True, ignore_discard=True)

        self.session = niquests.Session(disable_http3=True)
        for scheme in ("http://", "https://"):
            self.session.mount(
                scheme,
                HTTPAdapter(
                    max_retries=Retry(
                        total=5,
                        backoff_factor=1,
                        allowed_methods=[
                            "DELETE",
                            "GET",
                            "HEAD",
                            "OPTIONS",
                            "POST",
                            "PUT",
                            "TRACE",
                        ],
                        status_forcelist=[429, 500, 502, 503, 504],
                        raise_on_status=False,
                    )
                ),
            )

        for cookie in self.cookie_jar:
            self.session.cookies.set_cookie(cookie)

        self.session.proxies.update({"all": self.config.get(self, "proxy")})

        self.data: dict[str, Any] = {}

    @property
    @abstractmethod
    def announce_url(self) -> list[str] | str:
        """Announce URL of the tracker. May include {passkey} variable."""

    @property
    @abstractmethod
    def exclude_regex(self) -> str:
        """Torrent excluded file of the tracker."""

    @property
    def passkey(self) -> str | None:
        """
        This method can define a way to get the passkey from the tracker
        if not specified by the user in the config.
        """
        return None

    def login(self, *, args: Any = None) -> bool:
        if not self.session.cookies:
            eprint(f"No cookies found for {self.cli.aliases[0]}, cannot log in.")
            return False

        return True

    @abstractmethod
    def prepare(
        self,
        path: Path,
        torrent_path: Path,
        mediainfo: str | list[str] | None,
        snapshots: list[Path],
        *,
        note: str | None,
        auto: bool,
    ) -> bool:
        """
        Do any necessary preparations for the upload.
        This is a separate stage because of --fast-upload.
        """

    @abstractmethod
    def upload(
        self,
        path: Path,
        torrent_path: Path,
        mediainfo: str | list[str] | None,
        snapshots: list[Path],
        *,
        note: str | None,
        auto: bool,
    ) -> bool:
        """Perform the actual upload."""
