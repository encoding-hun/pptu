from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha1
from http.cookiejar import MozillaCookieJar
from typing import TYPE_CHECKING, Any

import requests
from platformdirs import PlatformDirs
from requests.adapters import HTTPAdapter, Retry

from ..utils import Config, eprint


if TYPE_CHECKING:
    from pathlib import Path


class Uploader(ABC):
    name: str  # Name of the tracker
    abbrev: str  # Abbreviation of the tracker

    source: str | None = None  # Source tag to use in created torrent files

    all_files: bool = False  # Whether to generate MediaInfo and snapshots for all files
    min_snapshots: int = 0
    snapshots_plus: int = 0  # Number of extra snapshots to generate
    random_snapshots: bool = False
    mediainfo: bool = True

    def __init__(self) -> None:
        self.dirs = PlatformDirs(appname="pptu", appauthor=False)

        self.config = Config(self.dirs.user_config_path / "config.toml")
        self.cookies_path = (
            self.dirs.user_data_path
            / "cookies"
            / f"""{self.name.lower()}_{sha1(f"{self.config.get(self, 'username')}".encode()).hexdigest()}.txt"""
        )
        if not self.cookies_path.exists():
            self.cookies_path = (
                self.dirs.user_data_path
                / "cookies"
                / f"""{self.name.lower()}_{sha1(f"{self.config.get(self, 'username')}".encode()).hexdigest()}.txt"""
            )
        self.cookie_jar = MozillaCookieJar(self.cookies_path)
        if self.cookies_path.exists():
            self.cookie_jar.load(ignore_expires=True, ignore_discard=True)

        self.session = requests.Session()
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
    def announce_url(self) -> str:
        """Announce URL of the tracker. May include {passkey} variable."""

    @property
    @abstractmethod
    def exclude_regexs(self) -> str:
        """Torrent excluded file of the tracker."""

    def login(self, *, args: Any) -> bool:
        if not self.session.cookies:
            eprint(f"No cookies found for {self.abbrev}, cannot log in.")
            return False

        return True

    @property
    def passkey(self) -> str | None:
        """
        This method can define a way to get the passkey from the tracker
        if not specified by the user in the config.
        """
        return None

    @abstractmethod
    def prepare(
        self,
        path: Path,
        torrent_path: Path,
        mediainfo: str | list[str],
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
        mediainfo: str | list[str],
        snapshots: list[Path],
        *,
        note: str | None,
        auto: bool,
    ) -> bool:
        """Perform the actual upload."""
