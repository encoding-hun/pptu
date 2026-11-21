from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from torf import Torrent

from pptu.utils.log import wprint

if TYPE_CHECKING:
    from pathlib import Path

_KEYED_ANNOUNCE = re.compile(
    r"[?&](?:passkey|authkey|torrent_pass|key|pk|uid)="
    r"|/[A-Za-z0-9_-]{16,}(?:/|$)"
    r"|/api/tracker/(?!public/)[^/]+/announce",
    re.IGNORECASE,
)


def is_keyed_announce(url: str) -> bool:
    return bool(_KEYED_ANNOUNCE.search(url))


def public_torrent_bytes(torrent_path: Path) -> bytes:
    torrent = Torrent.read(torrent_path)
    removed: list[str] = []

    def wanted(url: str) -> bool:
        if not is_keyed_announce(url):
            return True
        removed.append(url)
        return False

    trackers: Any = [
        tier
        for tier in ([u for u in map(str, t) if wanted(u)] for t in torrent.trackers)
        if tier
    ]
    torrent.trackers = trackers
    torrent.comment = None
    torrent.created_by = None
    torrent.creation_date = None
    if removed:
        wprint(
            f"Left {len(removed)} keyed announce URL(s) out of the uploaded torrent "
            "(kept in the local copy)."
        )
    return torrent.dump()
