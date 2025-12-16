from __future__ import annotations

from typing import TYPE_CHECKING

import humanize
from rich.progress import ProgressColumn
from rich.text import Text


if TYPE_CHECKING:
    from rich.progress import Task


class CustomTransferSpeedColumn(ProgressColumn):
    def render(self, task: Task) -> Text:
        speed = task.finished_speed or task.speed
        if speed is None:
            return Text("--", style="progress.data.speed")
        data_speed = humanize.naturalsize(int(speed), binary=True)
        return Text(f"{data_speed}/s", style="progress.data.speed")
