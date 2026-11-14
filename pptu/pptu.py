from __future__ import annotations

import glob
import math
import random
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import oxipng
import torf
from PIL import Image
from platformdirs import PlatformDirs
from pymediainfo import MediaInfo
from pyrosimple.util.metafile import Metafile
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from torf import Torrent

from pptu.utils.collections import as_list, flatten
from pptu.utils.config import Config
from pptu.utils.io import which
from pptu.utils.log import eprint, print, wprint
from pptu.utils.progress import CustomTransferSpeedColumn

if TYPE_CHECKING:
    from pptu.uploaders import Uploader


# Never put in torrents; mkbrr and imdl skip (some of) these on their own, so
# torf has to as well for a torrent made by one to be reusable by the other
JUNK_FILES = ("thumbs.db", "ehthumbs.db", "desktop.ini")
JUNK_DIR = "@eadir"


def _ci_glob(text: str) -> str:
    """Case-insensitive glob for imdl, e.g. "nfo" -> "[nN][fF][oO]"."""
    return "".join(
        f"[{c.lower()}{c.upper()}]" if c.isalpha() else glob.escape(c) for c in text
    )


class PPTU:
    def __init__(
        self,
        path: Path,
        tracker: Uploader,
        *,
        note: str | None = None,
        auto: bool = False,
        snapshots: bool = False,
        dirs: PlatformDirs,
    ):
        self.path: Path = path
        self.tracker: Uploader = tracker
        self.note: str | None = note
        self.auto: bool = auto

        self.tracker.auto = auto

        self.cache_dir: Path = dirs.user_cache_path / f"{path.name}_files"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config = Config(dirs.user_config_path / "config.toml")

        self.torrent_path: Path = (
            self.cache_dir / f"{self.path.name}[{self.tracker.cli.aliases[0]}].torrent"
        )
        if snapshots and self.config.get(tracker, "snapshots", True):
            self.num_snapshots = max(
                (
                    self.config.get(tracker, "snapshot_columns", 2)
                    * self.config.get(tracker, "snapshot_rows", 2)
                    + tracker.snapshots_plus
                ),
                tracker.min_snapshots,
            )
        else:
            self.num_snapshots = tracker.min_snapshots or 0

    def create_torrent(self) -> bool:
        torrent_creator: str = self.config.get("default", "torrent_creator", "torf")
        if torrent_creator not in ("torf", "mkbrr", "imdl"):
            eprint(
                f"Invalid torrent creator: {torrent_creator} (use torf, mkbrr or imdl)",
                fatal=True,
            )

        announce_url: list[str] = as_list(self.tracker.announce_url)

        passkey = self.config.get(self.tracker, "passkey") or self.tracker.passkey
        if not passkey and any("{passkey}" in x for x in announce_url):
            eprint(f"Passkey not found for tracker [cyan]{self.tracker.cli.name}[cyan].")
            return False

        announce_url = [x.format(passkey=passkey) for x in announce_url]

        cached = glob.escape(f"{self.path.name}[") + "*" + glob.escape("].torrent")
        try:
            time = self.path.stat().st_mtime
            if self.path.is_dir():
                time = min(x.stat().st_mtime for x in self.path.iterdir())
        except Exception:
            time = 0
        # Torrents older than the source (any tracker's) are stale: drop them, so
        # they're neither returned as-is nor reused as the base for new hashes
        for old in self.cache_dir.glob(cached):
            if old.stat().st_mtime < time:
                if old == self.torrent_path:
                    wprint("Source was possible updated, creating new torrent file.")
                old.unlink()

        if self.torrent_path.exists():
            return True

        if isinstance(self.tracker.randomize_infohash, bool):
            randomize_infohash = self.tracker.randomize_infohash
        else:
            randomize_infohash = not self.tracker.source

        exts = self.tracker.exclude_exts
        # torf is also used, whatever the creator, to list the files and to reuse
        # hashes from another tracker's torrent of the same content
        torrent = Torrent(
            self.path,
            trackers=announce_url,
            private=True if self.tracker.private else None,
            source=self.tracker.source,
            created_by=None,
            creation_date=None,
            randomize_infohash=randomize_infohash,
            exclude_regexs=[
                rf"(?i)\.({'|'.join(map(re.escape, exts))})$",
                rf"(?i)(^|[/\\])({'|'.join(map(re.escape, JUNK_FILES))})$",
                rf"(?i)[/\\]{re.escape(JUNK_DIR)}[/\\]",
            ],
        )
        if not torrent.size:
            eprint(f"No files to include in the torrent for [cyan]{self.path}[/].")
            return False

        if base_torrent_path := next(iter(self.cache_dir.glob(cached)), None):
            try:
                reused = torrent.reuse(base_torrent_path)
            except torf.TorfError as e:
                wprint(f"Could not reuse {base_torrent_path.name} ({e}), recreating")
            else:
                if reused:
                    torrent.write(self.torrent_path)
                    return True

        # ~1500 pieces, between 256 KiB and 16 MiB
        exponent = max(18, min(24, round(math.log2(torrent.size / 1500))))

        if torrent_creator == "torf":
            torrent.piece_size = 2**exponent
            print()
            with Progress(
                BarColumn(),
                CustomTransferSpeedColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(elapsed_when_finished=True),
            ) as progress:
                files = []

                def update_progress(
                    torrent: Torrent,
                    filepath: str,
                    pieces_done: int,
                    pieces_total: int,
                ) -> None:
                    if filepath not in files:
                        progress.console.print(
                            f"[bold white]Hashing [not bold white]{Path(filepath).name}..."
                        )
                        files.append(filepath)

                    progress.update(
                        task,
                        completed=pieces_done * torrent.piece_size,
                        total=pieces_total * torrent.piece_size,
                    )

                task = progress.add_task(description="")
                torrent.generate(callback=update_progress)
                torrent.write(self.torrent_path)
            return True

        if not (executable := which(torrent_creator)):
            eprint(f"{torrent_creator} not found in PATH", fatal=True)

        if torrent_creator == "mkbrr":
            cmd = [
                executable,
                "create",
                self.path,
                *(arg for url in announce_url for arg in ("-t", url)),
                *(["-s", self.tracker.source] if self.tracker.source else []),
                f"--private={'true' if self.tracker.private else 'false'}",
                "-l",
                str(exponent),
                "--no-date",
                "--no-creator",
                *(["--entropy"] if randomize_infohash else []),
                # mkbrr skips JUNK_* itself and matches case-insensitively, but
                # unlike torf and imdl it keeps hidden files
                "--exclude",
                ",".join([".*", *(f"*.{x}" for x in exts)]),
                "--skip-prefix",
                "-o",
                self.torrent_path,
            ]
        else:
            cmd = [
                executable,
                "torrent",
                "create",
                "--input",
                self.path,
                "--output",
                self.torrent_path,
                "--force",
                *(["--announce", announce_url[0]] if announce_url else []),
                *(
                    arg
                    for url in (announce_url if len(announce_url) > 1 else [])
                    for arg in ("--announce-tier", url)
                ),
                *(["--source", self.tracker.source] if self.tracker.source else []),
                *(["--private"] if self.tracker.private else []),
                "--piece-length",
                str(2**exponent),
                "--no-created-by",
                "--no-creation-date",
                *(
                    arg
                    for pattern in (
                        *(f"!*.{_ci_glob(x)}" for x in exts),
                        *(f"!**/{_ci_glob(x)}" for x in JUNK_FILES),
                        f"!**/{_ci_glob(JUNK_DIR)}/**",
                    )
                    for arg in ("--glob", pattern)
                ),
            ]

        print()
        if subprocess.run(cmd).returncode or not self.torrent_path.exists():
            eprint(f"{torrent_creator} failed to create the torrent.")
            return False

        if torrent_creator == "imdl" and randomize_infohash:
            # imdl has no option for this
            created = Torrent.read(self.torrent_path)
            created.randomize_infohash = True
            created.write(self.torrent_path, overwrite=True)

        return True

    def get_mediainfo(self) -> str | list[str]:
        mediainfo_path: Path = self.cache_dir / "mediainfo.txt"
        if self.tracker.all_files and self.path.is_dir():
            mediainfo_path = self.cache_dir / "mediainfo_all.txt"

        mediainfo = ""

        if mediainfo_path.exists():
            mediainfo: str = mediainfo_path.read_text().strip()

        if not mediainfo:
            if self.path.is_file() or self.tracker.all_files:
                f: Path = self.path
            else:
                f = sorted(
                    [
                        *self.path.glob("*.mkv"),
                        *self.path.glob("*.mp4"),
                        *self.path.glob("*.m2ts"),
                    ]
                )[0]

            mediainfo = MediaInfo.parse(f, output="", full=False)
            mediainfo = mediainfo.replace(str(f), f.name)
            mediainfo_path.write_text(mediainfo)

        mediainfo_list = [x.strip() for x in re.split(r"\n\n(?=General)", mediainfo)]
        if not self.tracker.all_files:
            return mediainfo_list[0]
        return mediainfo_list

    def generate_snapshots(self) -> list[Path]:
        if self.path.is_dir():
            files = sorted([*self.path.glob("*.mkv"), *self.path.glob("*.mp4")])
        elif self.path.is_file():
            files = [self.path]

        num_snapshots = self.num_snapshots + 1
        if self.tracker.all_files and self.path.is_dir():
            num_snapshots = len(files)

        orig_files = files[:]
        i = 2
        while len(files) < num_snapshots:
            files = flatten(zip(*([orig_files] * i), strict=True))
            i += 1

        snapshots = []
        parsed: dict[Path, MediaInfo] = {}  # parse each file once, not per snapshot
        print()
        if num_snapshots:
            last_file = None
            with Progress(
                TextColumn("[progress.description]{task.description}[/]"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(elapsed_when_finished=True),
            ) as progress:
                for i in progress.track(
                    range(num_snapshots),
                    description=f"[bold green]Generating snapshots ({self.tracker.cli.aliases[0]})[/]",
                ):
                    if files[i] not in parsed:
                        parsed[files[i]] = MediaInfo.parse(files[i])
                    mediainfo_obj = parsed[files[i]]
                    if not mediainfo_obj.video_tracks:
                        eprint("File has no video tracks")
                        return []
                    if not mediainfo_obj.audio_tracks:
                        eprint("File has no audio tracks")
                        return []
                    raw_duration = mediainfo_obj.video_tracks[0].duration
                    if not raw_duration:
                        eprint("Could not determine video duration")
                        return []
                    duration = float(raw_duration) / 1000
                    interval = duration / (num_snapshots + 2)

                    j = i
                    if last_file != files[i]:
                        j = 0
                    last_file = files[i]

                    snap: Path = self.cache_dir / "{num:02}{suffix}.png".format(
                        num=i + 1,
                        suffix=(
                            ("_all" if self.tracker.all_files else "")
                            + ("_rand" if self.tracker.random_snapshots else "")
                        ),
                    )

                    if not snap.exists():
                        subprocess.run(
                            [
                                "ffmpeg",
                                "-y",
                                "-v",
                                "error",
                                "-ss",
                                str(
                                    random.randint(
                                        round(interval * 10),
                                        round(interval * 10 * num_snapshots),
                                    )
                                    / 10
                                    if self.tracker.random_snapshots
                                    else str(interval * (j + 1))
                                ),
                                "-i",
                                files[i],
                                "-vf",
                                "scale='max(sar,1)*iw':'max(1/sar,1)*ih'",
                                "-frames:v",
                                "1",
                                snap,
                            ],
                            check=True,
                        )
                        with Image.open(snap) as img:
                            img.convert("RGB").save(snap)
                        oxipng.optimize(snap)
                    snapshots.append(snap)

        if not snapshots:
            return []
        # try to prevent black images
        min_image = min(snapshots, key=lambda p: p.stat().st_size)

        return [x for x in snapshots if x != min_image]

    def prepare(self, mediainfo: str | list[str] | None, snapshots: list[Path]) -> bool:
        if not self.tracker.prepare(
            path=self.path,
            torrent_path=self.torrent_path,
            mediainfo=mediainfo,
            snapshots=snapshots,
            note=self.note,
        ):
            eprint(f"Preparing upload to [cyan]{self.tracker.cli.name}[/] failed.")
            return False
        return True

    def upload(self, mediainfo: str | list[str] | None, snapshots: list[Path]) -> None:
        if not self.tracker.upload(
            path=self.path,
            torrent_path=self.torrent_path,
            mediainfo=mediainfo,
            snapshots=snapshots,
            note=self.note,
        ):
            eprint(f"Upload to [cyan]{self.tracker.cli.name}[/] failed.")
            return
        else:
            print(f"Upload to [cyan]{self.tracker.cli.name}[/] succeeded.")

        if self.tracker.watch_dir:
            watch_dir_path = Path(self.tracker.watch_dir).expanduser()
            try:
                metafile = Metafile.from_file(self.torrent_path)
                metafile.add_fast_resume(self.path)
                metafile.save(watch_dir_path / self.torrent_path.name)
            except Exception as e:
                wprint(f"Failed to save fast-resume torrent to watch directory: {e}")

    def __str__(self) -> str:
        return f"{self.tracker.cli.aliases[0]} ({self.torrent_path})"
