from __future__ import annotations

import glob
import random
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import oxipng
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
from wand.image import Image

from .utils import Config, CustomTransferSpeedColumn, eprint, flatten


if TYPE_CHECKING:
    from .uploaders import Uploader


class PPTU:
    def __init__(self, file: Path, tracker: Uploader, *, auto: bool = False):
        self.file = file
        self.tracker = tracker
        self.auto = auto

        dirs = PlatformDirs(appname="pptu", appauthor=False)
        self.cache_dir = dirs.user_cache_path / f"{file.name}_files"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config = Config(dirs.user_config_path / "config.toml")

        self.num_snapshots = max(
            self.config.get(tracker, "snapshot_columns", 2) * self.config.get(tracker, "snapshot_rows", 2),
            tracker.min_snapshots,
        )

    def create_torrent(self) -> bool:
        passkey = self.config.get(self.tracker, "passkey") or self.tracker.passkey
        if not passkey and "{passkey}" in self.tracker.announce_url:
            eprint(f"Passkey not found for tracker [cyan]{self.tracker.name}[cyan].")
            return False

        base_torrent_path = next(iter(
            self.cache_dir.glob(glob.escape(f"{self.file.name}[") + "*" + glob.escape("].torrent"))
        ), None)
        output = self.cache_dir / f"{self.file.name}[{self.tracker.abbrev}].torrent"

        if output.exists():
            return True

        if base_torrent_path:
            torrent = Torrent(base_torrent_path)
            torrent.trackers = [self.tracker.announce_url.format(passkey=passkey)]
            torrent.source = self.tracker.source
            torrent.private = True
            torrent.write(output)
        else:
            torrent = Torrent(
                self.file,
                trackers=[self.tracker.announce_url.format(passkey=passkey)],
                private=True,
                source=self.tracker.source,
                created_by=None,
                randomize_infohash=not self.tracker.source,
                exclude_regexs=[r".*\.(ffindex|jpg|nfo|png|srt|torrent|txt)$"],
            )
            print()
            with Progress(
                BarColumn(),
                CustomTransferSpeedColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(elapsed_when_finished=True),
            ) as progress:
                files = []

                def update_progress(torrent: Torrent, filepath: str, pieces_done: int, pieces_total: int) -> None:
                    if filepath not in files:
                        print(f"Hashing {Path(filepath).name}...")
                        files.append(filepath)

                    progress.update(
                        task, completed=pieces_done * torrent.piece_size, total=pieces_total * torrent.piece_size
                    )

                task = progress.add_task(description="")
                torrent.generate(callback=update_progress, interval=1)
                torrent.write(output)

        return True

    def get_mediainfo(self) -> str | list[str]:
        mediainfo_path = self.cache_dir / "mediainfo.txt"
        if self.tracker.all_files and self.file.is_dir():
            mediainfo_path = self.cache_dir / "mediainfo_all.txt"

        if mediainfo_path.exists():
            mediainfo = mediainfo_path.read_text()
        else:
            if self.file.is_file() or self.tracker.all_files:
                f = self.file
            else:
                f = sorted([*self.file.glob("*.mkv"), *self.file.glob("*.mp4")])[0]

            p = subprocess.run(
                ["mediainfo", f], cwd=self.file.parent, check=True, capture_output=True, encoding="utf-8"
            )
            mediainfo = p.stdout
            mediainfo_path.write_text(mediainfo)

        mediainfo_list = [x.strip() for x in re.split(r"\n\n(?=General)", mediainfo)]
        if not self.tracker.all_files:
            return mediainfo_list[0]
        return mediainfo_list

    def generate_snapshots(self) -> list[Path]:
        if self.file.is_dir() or self.tracker.all_files:
            files = sorted([*self.file.glob("*.mkv"), *self.file.glob("*.mp4")])
        elif self.file.is_file():
            files = [self.file]

        num_snapshots = self.num_snapshots
        if self.tracker.all_files:
            num_snapshots = len(files)

        orig_files = files[:]
        i = 2
        while len(files) < num_snapshots:
            files = flatten(zip(*([orig_files] * i)))
            i += 1

        snapshots = []

        print()
        last_file = None
        with Progress(
            TextColumn("[progress.description]{task.description}[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(elapsed_when_finished=True),
        ) as progress:
            for i in progress.track(
                range(num_snapshots), description=f"[bold green]Generating snapshots ({self.tracker.abbrev})[/]"
            ):
                mediainfo_obj = MediaInfo.parse(files[i])
                if not mediainfo_obj.video_tracks:
                    eprint("File has no video tracks")
                    return []
                if not mediainfo_obj.audio_tracks:
                    eprint("File has no audio tracks")
                    return []
                duration = float(mediainfo_obj.video_tracks[0].duration) / 1000
                interval = duration / (num_snapshots + 1)

                j = i
                if last_file != files[i]:
                    j = 0
                last_file = files[i]

                snap = self.cache_dir / "{num:02}{suffix}.png".format(
                    num=i + 1,
                    suffix=(
                        ("_all" if self.tracker.all_files else "")
                        + ("_rand" if self.tracker.random_snapshots else "")
                    ),
                )

                if not snap.exists():
                    subprocess.run([
                        "ffmpeg",
                        "-y",
                        "-v", "error",
                        "-ss", str(
                            random.randint(round(interval * 10), round(interval * 10 * num_snapshots)) / 10
                            if self.tracker.random_snapshots
                            else str(interval * (j + 1))
                        ),
                        "-i", files[i],
                        "-vf", "scale='max(sar,1)*iw':'max(1/sar,1)*ih'",
                        "-frames:v", "1",
                        snap,
                    ], check=True)
                    with Image(filename=snap) as img:
                        img.depth = 8
                        img.save(filename=snap)
                    oxipng.optimize(snap)
                snapshots.append(snap)

        return snapshots

    def prepare(self, mediainfo: str | list[str], snapshots: list[Path]) -> bool:
        if not self.tracker.prepare(self.file, mediainfo, snapshots, auto=self.auto):
            eprint(f"Preparing upload to [cyan]{self.tracker.name}[/] failed.")
            return False
        return True

    def upload(self, mediainfo: str | list[str], snapshots: list[Path]) -> None:
        if not self.tracker.upload(self.file, mediainfo, snapshots, auto=self.auto):
            eprint(f"Upload to [cyan]{self.tracker.name}[/] failed.")
            return

        torrent_path = self.cache_dir / f"{self.file.name}[{self.tracker.abbrev}].torrent"
        if watch_dir := self.config.get(self.tracker, "watch_dir"):
            watch_dir = Path(watch_dir).expanduser()
            metafile = Metafile.from_file(torrent_path)
            metafile.add_fast_resume(self.file)
            metafile.save(watch_dir / torrent_path.name)
