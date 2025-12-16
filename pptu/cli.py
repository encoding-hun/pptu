#!/usr/bin/env python3

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cloup
from cloup import Context, HelpFormatter, HelpTheme, Style
from platformdirs import PlatformDirs
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from pptu import PROG_NAME, __version__, uploaders
from pptu.pptu import PPTU
from pptu.uploaders import Uploader
from pptu.utils.click import AliasedGroup, CaseInsensitiveSection
from pptu.utils.config import Config
from pptu.utils.log import eprint, print, wprint


CONTEXT_SETTINGS = Context.settings(
    help_option_names=["-h", "--help"],
    max_content_width=116,
    align_option_groups=False,
    align_sections=True,
    token_normalize_func=lambda token: token.lower(),
    formatter_settings=HelpFormatter.settings(
        indent_increment=3,
        col1_max_width=50,
        col_spacing=3,
        theme=HelpTheme(
            section_help=Style(fg="bright_white", bold=True),
            command_help=Style(fg="bright_white", bold=True),
            invoked_command=Style(fg="cyan"),
            heading=Style(fg="yellow", bold=True),
            col1=Style(fg="green"),
            col2=Style(fg="bright_white", bold=True),
        ),
    ),
)


@cloup.group(
    cls=AliasedGroup,
    context_settings=CONTEXT_SETTINGS,
    chain=True,
    invoke_without_command=True,
)
@cloup.version_option(
    __version__,
    "-v",
    "--version",
    prog_name=PROG_NAME,
    message="%(prog)s %(version)s",
)
@cloup.option(
    "-i",
    "--input",
    type=cloup.Path(
        exists=True, file_okay=True, dir_okay=True, readable=True, path_type=Path
    ),
    metavar="PATH",
    multiple=True,
    required=False,
    help="Files or directories to create torrents for.",
)
@cloup.option(
    "--fast-upload/--no-fast-upload",
    default=None,  # tri-state: None / True / False
    help="Upload only after all steps succeed (or force-disable).",
)
@cloup.option(
    "-c",
    "--confirm",
    is_flag=True,
    help="Ask for confirmation before uploading.",
)
@cloup.option(
    "-a",
    "--auto",
    is_flag=True,
    help="Run non-interactively (never prompt).",
)
@cloup.option(
    "-ds",
    "--disable-snapshots",
    is_flag=True,
    help="Skip creating description snapshots.",
)
@cloup.option(
    "-s",
    "--skip-upload",
    is_flag=True,
    help="Create torrents but don't upload.",
)
@cloup.option(
    "-n",
    "--note",
    help="Note to attach to the upload.",
)
@cloup.option(
    "-lt",
    "--list-trackers",
    is_flag=True,
    help="Show the list of supported trackers and exit.",
)
@cloup.pass_context
def main(ctx: cloup.Context, **kwargs: Any) -> None:
    args = SimpleNamespace(**kwargs)
    if len(sys.argv) == 1:
        if getattr(sys, "frozen", False):
            wprint(
                "\nPlease use PPTU from the command line if you double-clicked "
                "the standalone build."
            )
            time.sleep(10)
        sys.exit(1)

    dirs = PlatformDirs(appname=PROG_NAME, appauthor=False)
    config = Config(dirs.user_config_path / "config.toml")

    if args.list_trackers:
        supported_trackers = Table(
            title="Supported trackers", title_style="not italic bold magenta"
        )
        supported_trackers.add_column("Site", style="cyan")
        supported_trackers.add_column("Abbreviation", style="bold green")
        for cmd_name, cmd in main.commands.items():
            supported_trackers.add_row(cmd_name, ", ".join(cmd.aliases))
        console = Console()
        console.print(supported_trackers)
        sys.exit(0)

    ctx.obj = SimpleNamespace(
        config=config,
        dirs=dirs,
    )


@main.result_callback()
@cloup.pass_context
def result(ctx: cloup.Context, trackers: list[Uploader], **kwargs: Any) -> None:
    args = SimpleNamespace(**kwargs)

    for tracker in trackers:
        if tracker.needs_login:
            print("[bold green]Logging in to tracker[/]")
            print(f"[bold cyan]Logging in to {tracker.cli.aliases[0]}[/]")
            if not tracker.login(args=args):
                eprint(f"Failed to log in to tracker [cyan]{tracker.cli.name}[/].")
                continue
        for cookie in tracker.session.cookies:
            tracker.cookie_jar.set_cookie(cookie)
        tracker.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        # prevent corrupted cookies file
        try:
            tracker.cookies_path.unlink(missing_ok=True)
        except PermissionError:
            pass

        tracker.cookie_jar.save(ignore_discard=True)

    jobs: list[tuple[PPTU, str | list[str] | None, list[Path]]] = list()

    fast_upload = args.fast_upload or (
        ctx.obj.config.get("default", "fast_upload", False)
        and args.fast_upload is not False
    )

    for path in args.input:
        if not path.exists():
            eprint(f"File [cyan]{path.name!r}[/] does not exist.")
            continue

        cache_dir = ctx.obj.dirs.user_cache_path / f"{path.name}_files"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for tracker in trackers:
            pptu = PPTU(
                path,
                tracker,
                note=args.note,
                auto=args.auto,
                snapshots=not args.disable_snapshots,
                dirs=ctx.obj.dirs,
            )

            print(
                f"\n[bold green]Creating torrent file for tracker ({tracker.cli.aliases[0]})[/]"
            )
            pptu.create_torrent()

            mediainfo: str | list[str] | None = None
            if tracker.mediainfo:
                print(f"\n[bold green]Generating MediaInfo ({tracker.cli.aliases[0]})[/]")
                if not (mediainfo := pptu.get_mediainfo()):
                    eprint("Failed to generate MediaInfo")
                    continue
                print("Done!")

            # Generating snapshots
            snapshots = pptu.generate_snapshots()

            print(f"\n[bold green]Preparing upload ({tracker.cli.aliases[0]})[/]")
            if not pptu.prepare(mediainfo, snapshots):
                continue

            if fast_upload:
                jobs.append((pptu, mediainfo, snapshots))
            else:
                print(f"\n[bold green]Uploading ({tracker.cli.aliases[0]})[/]")
                if args.confirm and pptu.tracker.data:
                    print(pptu.tracker.data, highlight=True)
                if args.skip_upload or (
                    args.confirm and not Confirm.ask("Upload torrent?")
                ):
                    print("Skipping upload")
                    continue
                pptu.upload(mediainfo, snapshots)

    if fast_upload:
        for pptu, mediainfo, snapshots in jobs:
            print(f"\n[bold green]Uploading ({pptu.tracker.cli.aliases[0]})[/]")  # type: ignore
            if args.confirm and pptu.tracker.data:
                print(pptu.tracker.data, highlight=True)
            if args.skip_upload or (args.confirm and not Confirm.ask("Upload torrent?")):
                print("Skipping upload")
                continue
            pptu.upload(mediainfo, snapshots)
            print()


section = CaseInsensitiveSection("Uploaders")
for name in uploaders.successful_uploader:
    obj = getattr(uploaders, name)
    if getattr(obj, "cli", None):
        section.add_command(obj.cli)

section.title += f" ({len(section.commands)})"
main.add_section(section)


if __name__ == "__main__":
    main()
