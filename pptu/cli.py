#!/usr/bin/env python3

import subprocess
import sys
from copy import copy
from pathlib import Path

import requests
from platformdirs import PlatformDirs
from requests.adapters import HTTPAdapter, Retry
from rich import print

from . import uploaders
from .constants import PROG_NAME, PROG_VERSION
from .pptu import PPTU
from .uploaders import Uploader
from .utils import RParse, eprint


dirs = PlatformDirs(appname="pptu", appauthor=False)


def main():
    parser = RParse(prog=PROG_NAME)
    parser.add_argument("file",
                        type=Path,
                        nargs="+",
                        help="files/directories to create torrents for")
    parser.add_argument("-v", "--version",
                        action="version",
                        version=f"[bold cyan]{PROG_NAME}[/] [not bold white]{PROG_VERSION}[/]",
                        help="show version and exit")
    parser.add_argument("-t", "--trackers",
                        metavar="ABBREV",
                        type=lambda x: x.split(","),
                        required=True,
                        help="tracker(s) to upload torrents to (required)")
    parser.add_argument("-f", "--fast-upload",
                        action="store_true",
                        help="only upload when every step is done for every input")
    parser.add_argument("-a", "--auto",
                        action="store_true",
                        help="upload without confirmation")
    parser.add_argument("-s", "--skip-upload",
                        action="store_true",
                        help="skip upload")
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()

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

    trackers = []

    step_count = 6
    current_step = 1
    print(f"[bold green]\\[{current_step}/{step_count}] Logging in to trackers[/]")
    for i, tracker_name in enumerate(copy(args.trackers)):
        try:
            tracker = next(
                x for x in vars(uploaders).values()
                if isinstance(x, type) and x != Uploader and issubclass(x, Uploader)
                and (x.name.casefold() == tracker_name.casefold() or x.abbrev.casefold() == tracker_name.casefold())
            )()
        except StopIteration:
            eprint(f"Tracker [cyan]{tracker_name}[/] not found.")
            continue
        trackers.append(tracker)

        print(f"[bold cyan]\\[{i + 1}/{len(trackers)}] Logging in to {tracker.abbrev}")

        if not tracker.login():
            eprint(f"Failed to log in to tracker [cyan]{tracker.name}[/].")
            continue
        for cookie in tracker.session.cookies:
            tracker.cookie_jar.set_cookie(cookie)
        tracker.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        tracker.cookie_jar.save(ignore_discard=True)

    for file in args.file:
        if not file.exists():
            eprint(f"File [cyan]{file.name!r}[/] does not exist.")
            continue

        cache_dir = PlatformDirs(appname="pptu", appauthor=False).user_cache_path / f"{file.name}_files"

        current_step += 1
        print(f"\n[bold green]\\[{current_step}/{step_count}] Creating initial torrent file[/]")
        base_torrent_path = cache_dir / f"{file.name}.torrent"
        if not base_torrent_path.exists():
            subprocess.run([
                "torrenttools",
                "create",
                "--no-created-by",
                "--no-creation-date",
                "--no-cross-seed",
                "--exclude", r".*\.(ffindex|jpg|nfo|png|srt|torrent|txt)$",
                "-o", base_torrent_path,
                file,
            ], check=True)
        if not base_torrent_path.exists():
            sys.exit(1)

        for tracker in trackers:
            pptu = PPTU(file, tracker, auto=args.auto)

            current_step += 1
            print(
                f"\n[bold green]\\[{current_step}/{step_count}] Creating torrent file for tracker ({tracker.abbrev})"
            )
            pptu.create_torrent()

            current_step += 1
            print(f"\n[bold green]\\[{current_step}/{step_count}] Generating MediaInfo ({tracker.abbrev})[/]")
            mediainfo = pptu.get_mediainfo()
            print("Done!")

            # Generating snapshots
            current_step += 1
            snapshots = pptu.generate_snapshots(step=f"{current_step}/{step_count}")

            if not args.fast_upload:
                current_step += 1
                if args.skip_upload:
                    print(f"\n[bold green]\\[{current_step}/{step_count}] Skip uploading ({tracker.abbrev})[/]")
                else:
                    print(f"\n[bold green]\\[{current_step}/{step_count}] Uploading ({tracker.abbrev})[/]")
                    pptu.upload(mediainfo, snapshots)
            print()

    if args.fast_upload:
        for file in args.file:
            for tracker in trackers:
                current_step = step_count
                if args.skip_upload:
                    print(f"\n[bold green]\\[{current_step}/{step_count}] Skip uploading ({tracker.abbrev})[/]")
                else:
                    print(f"\n[bold green]\\[{current_step}/{step_count}] Uploading ({tracker.abbrev})[/]")
                    pptu.upload(mediainfo, snapshots)
            print()


if __name__ == "__main__":
    main()
