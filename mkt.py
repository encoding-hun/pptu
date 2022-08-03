#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
from pathlib import Path

import requests
from platformdirs import PlatformDirs
from requests.adapters import HTTPAdapter, Retry
from rich import print
from ruamel.yaml import YAML

from pymkt.uploaders import (
    AvistaZUploader,
    BroadcasTheNetUploader,
    HDBitsUploader,
    PassThePopcornUploader,
)

TRACKER_MAP = {
    "AVZ": "AvZ",
}
UPLOADER_MAP = {
    "AvZ": AvistaZUploader,
    "BTN": BroadcasTheNetUploader,
    "HDB": HDBitsUploader,
    "PTP": PassThePopcornUploader,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--trackers", type=lambda x: x.split(","), required=True)
    parser.add_argument("file", nargs="+", type=Path)
    parser.add_argument("--snapshots", type=int, default=4)
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    dirs = PlatformDirs(appname="pymkt", appauthor=False)

    config = YAML().load(dirs.user_config_path / "config.yml")

    session = requests.Session()
    for scheme in ("http://", "https://"):
        session.mount(
            scheme,
            HTTPAdapter(
                max_retries=Retry(
                    total=5,
                    backoff_factor=1,
                    allowed_methods=["DELETE", "GET", "HEAD", "OPTIONS", "POST", "PUT", "TRACE"],
                    status_forcelist=[429, 500, 502, 503, 504],
                    raise_on_status=False,
                ),
            ),
        )

    for file in args.file:
        d = dirs.user_cache_path / f"{file.name}_files"
        d.mkdir(parents=True, exist_ok=True)

        print(r"[bold green]\[1/5] Creating torrent files[/bold green]")
        base_torrent_path = d / f"{file.name}.torrent"
        if not base_torrent_path.exists():
            subprocess.run(
                [
                    "torrenttools",
                    "create",
                    "--no-created-by",
                    "--no-creation-date",
                    "--no-cross-seed",
                    "--exclude",
                    r".*\.(txt|nfo|png|jpg|ffindex|srt|torrent)$",
                    "-o",
                    base_torrent_path,
                    file,
                ],
                check=True,
            )
        for tracker in args.trackers:
            tracker_str = TRACKER_MAP.get(t := tracker.upper(), t)
            subprocess.run(
                [
                    "torrenttools",
                    "edit",
                    "--no-created-by",
                    "--no-creation-date",
                    "-a",
                    tracker,
                    "-o",
                    d / f"{file.name}[{tracker_str}].torrent",
                    d / f"{file.name}.torrent",
                ],
                check=True,
            )
            subprocess.run(["chtor", "-H", file, d / f"{file.name}[{tracker_str}].torrent"], check=True)

        print("\n[bold green]\\[2/5] Generating MediaInfo[/bold green]")
        if file.is_file():
            file = file
        else:
            file = list(sorted([*file.glob("*.mkv"), *file.glob("*.mp4")]))[0]
        p = subprocess.run(["mediainfo", file], cwd=file.parent, check=True, capture_output=True, encoding="utf-8")
        mediainfo = p.stdout.strip()
        Path(d / "mediainfo.txt").write_text(mediainfo)
        print("Done!")

        print("\n[bold green]\\[3/5] Generating snapshots[/bold green]")
        if file.is_file():
            files = [file] * args.snapshots
        else:
            files = list(sorted([*file.glob("*.mkv"), *file.glob("*.mp4")]))[: args.snapshots]
        snapshots = []
        for i in range(args.snapshots):
            snap = d / f"{(i + 1):02}.png"
            if snap.exists():
                continue
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-stats",
                    "-ss",
                    str((60 if args.short else 300) * (i + 1)),
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
            subprocess.run(["convert", snap, "-depth", "8", snap], capture_output=True)
            subprocess.run(["oxipng", snap], capture_output=True)
            with open(snap, "rb") as fd:
                r = session.post(
                    url="https://ptpimg.me/upload.php",
                    files={
                        "file-upload[]": fd,
                    },
                    data={
                        "api_key": os.environ["PTPIMG_API_KEY"],
                    },
                    headers={
                        "Referer": "https://ptpimg.me/index.php",
                    },
                    timeout=60,
                )
                r.raise_for_status()
                res = r.json()
                snapshots.append(f'https://ptpimg.me/{res[0]["code"]}.{res[0]["ext"]}')
        print("Done!")

        print("\n[bold green]\\[4/5] Generating thumbnails[/bold green]")
        thumbnails = ""
        for i in range(args.snapshots):
            thumb = d / f"{(i + 1):02}_thumb.png"
            if thumb.exists():
                continue
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-stats", "-i", d / f"{(i + 1):02}.png", "-vf", "scale=300:-1", thumb],
                check=True,
            )
            subprocess.run(["convert", thumb, "-depth", "8", thumb], capture_output=True)
            subprocess.run(["oxipng", thumb], capture_output=True)
            with open(thumb, "rb") as fd:
                r = session.post(
                    url="https://ptpimg.me/upload.php",
                    files={
                        "file-upload[]": fd,
                    },
                    data={
                        "api_key": os.environ["PTPIMG_API_KEY"],
                    },
                    headers={
                        "Referer": "https://ptpimg.me/index.php",
                    },
                    timeout=60,
                )
                r.raise_for_status()
                res = r.json()
                img = snapshots[i]
                thumbnails += rf'[url={img}][img]https://ptpimg.me/{res[0]["code"]}.{res[0]["ext"]}[/img][/url]'
                if i % 2 == 0:
                    thumbnails += " "
                else:
                    thumbnails += "\n"
        print("Done!")

        print("\n[bold green]\\[5/5] Uploading[/bold green]")
        for tracker in args.trackers:
            tracker_str = TRACKER_MAP.get(t := tracker.upper(), t)
            if not (uploader_cls := UPLOADER_MAP.get(tracker_str)):
                print(
                    f"[yellow][bold]WARNING[/bold]: No uploader available for {tracker_str}, "
                    f"you must upload manually.[/yellow]"
                )
                print("\n".join(snapshots))
                print(thumbnails.replace("[", r"\["))
                continue
            uploader = uploader_cls()
            uploader.upload(file, mediainfo, snapshots, thumbnails, auto=args.auto)
            torrent_path = Path(d / f"{file.name}[{tracker_str}].torrent")
            if watch_dir := config.get("watch_dir"):
                shutil.copyfile(torrent_path, (Path(watch_dir) / torrent_path.name).expanduser())


if __name__ == "__main__":
    main()
