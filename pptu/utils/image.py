from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import oxipng
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from wand.image import Image

from pptu.utils.log import eprint, print, wprint


if TYPE_CHECKING:
    from pptu.uploaders import Uploader


class ImgUploader:
    def __init__(self, tracker: Uploader):
        self.tracker = tracker
        self.uploader = tracker.config.get(tracker, "img_uploader")
        self.api_key = tracker.config.get("default", f"{self.uploader}_api_key", None)

    def hdbimg(
        self, files: list[Path], thumbnail_width: int, name: str
    ) -> list[Any | None] | None:
        if self.tracker.cli.name != "HDBits":
            eprint("HDBImg uploader can only be used for HDBits!")
            return []

        with (
            Console().status("Uploading snapshots..."),
            contextlib.ExitStack() as stack,
        ):
            r = self.tracker.session.post(
                url="https://img.hdbits.org/upload_api.php",
                files={
                    **{
                        f"images_files[{i}]": stack.enter_context(  # type: ignore[misc]
                            snap.open("rb")
                        )
                        for i, snap in enumerate(files)
                    },
                    "thumbsize": f"w{thumbnail_width}",
                    "galleryoption": "1",
                    "galleryname": name,
                },
                timeout=60,
            )
        res = r.text
        if res.startswith("error"):
            error = re.sub(r"^error: ", "", res)
            eprint(f"Snapshot upload failed: [cyan]{error}[/cyan]")
            return []

        return res.split()

    def keksh(self, files: list[Path]) -> list[dict[Any, Any] | None] | None:
        res = []
        headers = {}

        if not files:
            return res

        if self.api_key:
            headers = {"x-kek-auth": self.api_key}

        with Progress(
            TextColumn("[progress.description]{task.description}[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(elapsed_when_finished=True),
        ) as progress:
            for snap in progress.track(files, description="Uploading snapshots"):
                with open(snap, "rb") as fd:
                    r = self.tracker.session.post(
                        url="https://kek.sh/api/v1/posts",
                        headers=headers,
                        files={
                            "file": fd,
                        },
                        timeout=60,
                    )
                    r.raise_for_status()
                    res.append(r.json())

        return res

    def ptpimg(self, files: list[Path]) -> list[dict[Any, Any] | None] | None:
        res = []

        if not files:
            return res

        with Progress(
            TextColumn("[progress.description]{task.description}[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(elapsed_when_finished=True),
        ) as progress:
            for snap in progress.track(files, description="Uploading snapshots"):
                with open(snap, "rb") as fd:
                    r = self.tracker.session.post(
                        url="https://ptpimg.me/upload.php",
                        files={
                            "file-upload[]": fd,
                        },
                        data={
                            "api_key": self.api_key,
                        },
                        headers={
                            "Referer": "https://ptpimg.me/index.php",
                        },
                        timeout=60,
                    )
                    r.raise_for_status()
                    res.append(r.json())

        return res

    def upload(
        self,
        files: list[Path],
        thumbnail_width: int | None = None,
        name: str | None = None,
    ) -> list[dict[Any, Any] | None] | None:
        if self.uploader == "keksh":
            return self.keksh(files)
        elif self.uploader == "ptpimg":
            return self.ptpimg(files)
        elif self.uploader == "hdbimg":
            return self.hdbimg(files, thumbnail_width or 220, name or "")
        else:
            if not self.uploader:
                wprint("Img uploader missing for from config!")
            else:
                wprint("Set Img uploader doesn't exist!")

            return []


def generate_thumbnails(
    snapshots: list[Path],
    width: int = 300,
    file_type: str = "png",
    *,
    progress_obj: Progress | None = None,
) -> list[Path]:
    width = int(width)
    print(f"Using thumbnail width: [bold cyan]{width}[/]")

    thumbnails = []

    with progress_obj or Progress(
        TextColumn("[progress.description]{task.description}[/]"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(elapsed_when_finished=True),
    ) as progress:
        for snap in progress.track(snapshots, description="Generating thumbnails"):
            thumb = snap.with_name(f"{snap.stem}_thumb_{width}.{file_type}")
            if not thumb.exists():
                with Image(filename=snap) as img:
                    img.resize(width, round(img.height / (img.width / width)))
                    img.depth = 8
                    img.save(filename=thumb)
                if file_type == "png":
                    oxipng.optimize(thumb)

            thumbnails.append(thumb)

    return thumbnails
