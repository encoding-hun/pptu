from abc import ABC, abstractmethod
from http.cookiejar import MozillaCookieJar

import requests
from platformdirs import PlatformDirs
from requests.adapters import HTTPAdapter, Retry

from ..utils import Config, eprint


class Uploader(ABC):
    name = None
    abbrev = None
    all_files = False  # Whether to generate MediaInfo and snapshots for all files
    require_passkey = True
    min_snapshots = 0

    def __init__(self):
        self.dirs = PlatformDirs(appname="pptu", appauthor=False)

        self.config = Config(self.dirs.user_config_path / "config.toml")

        self.cookies_path = self.dirs.user_data_path / "cookies" / f"{self.name.lower()}.txt"
        if not self.cookies_path.exists():
            self.cookies_path = self.dirs.user_data_path / "cookies" / f"{self.abbrev.lower()}.txt"

        self.cookie_jar = MozillaCookieJar(self.cookies_path)
        if self.cookies_path.exists():
            self.cookie_jar.load(ignore_expires=True, ignore_discard=True)

        self.session = requests.Session()
        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=Retry(
                total=5,
                backoff_factor=1,
                allowed_methods=["DELETE", "GET", "HEAD", "OPTIONS", "POST", "PUT", "TRACE"],
                status_forcelist=[429, 500, 502, 503, 504],
                raise_on_status=False,
            )))
        for cookie in self.cookie_jar:
            self.session.cookies.set_cookie(cookie)
        self.session.proxies.update({"all": self.config.get(self, "proxy")})

    def login(self):
        if not self.session.cookies:
            eprint(f"No cookies found for {self.abbrev}, cannot log in.")
            return False

        return True

    @property
    def passkey(self):
        return None

    @abstractmethod
    def upload(self, path, mediainfo, snapshots, thumbnails, *, auto):
        ...
