"""
Command-line interface for Netease Cloud Music.

Usage:
    ncm search "keyword"
    ncm download <song_id>
    ncm playlist <playlist_id>
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from . import __version__
from .client import NCMClient
from .downloader import Downloader
from .models import Song


# XDG Base Directory paths
def get_config_dir() -> Path:
    """Get XDG config directory."""
    xdg_config = os.environ.get('XDG_CONFIG_HOME')
    if xdg_config:
        return Path(xdg_config) / 'ncm'
    return Path.home() / '.config' / 'ncm'


def get_data_dir() -> Path:
    """Get XDG data directory."""
    xdg_data = os.environ.get('XDG_DATA_HOME')
    if xdg_data:
        return Path(xdg_data) / 'ncm'
    return Path.home() / '.local' / 'share' / 'ncm'


def get_cache_dir() -> Path:
    """Get XDG cache directory."""
    xdg_cache = os.environ.get('XDG_CACHE_HOME')
    if xdg_cache:
        return Path(xdg_cache) / 'ncm'
    return Path.home() / '.cache' / 'ncm'


CONFIG_DIR = get_config_dir()
DATA_DIR = get_data_dir()
CACHE_DIR = get_cache_dir()
COOKIE_FILE = CONFIG_DIR / 'cookie'


console = Console()


def get_saved_cookie() -> Optional[str]:
    """Get saved cookie from config file."""
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text().strip()
    return None


def save_cookie(cookie: str) -> None:
    """Save cookie to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(cookie)
    # Set restrictive permissions
    COOKIE_FILE.chmod(0o600)


def create_client(cookie: Optional[str], cookie_file: Optional[str]) -> NCMClient:
    """Create NCMClient with provided credentials."""
    # Try to load saved cookie if none provided
    if not cookie and not cookie_file:
        cookie = get_saved_cookie()
    return NCMClient(cookie=cookie, cookie_file=cookie_file)


def format_song_table(songs: list[Song], title: str = "Songs") -> Table:
    """Create a formatted table of songs."""
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("ID", style="dim", width=12)
    table.add_column("Name", style="green", max_width=40)
    table.add_column("Artist", style="yellow", max_width=30)
    table.add_column("Album", style="blue", max_width=25)
    table.add_column("Duration", justify="right", width=8)

    for i, song in enumerate(songs, 1):
        table.add_row(
            str(i),
            str(song.id),
            song.name[:40],
            song.artist_names[:30],
            song.album.name[:25] if song.album else "",
            song.duration_str
        )

    return table


@click.group()
@click.version_option(version=__version__, prog_name="ncm")
@click.option(
    '--cookie', '-c',
    envvar='NCM_COOKIE',
    help='Authentication cookie (or set NCM_COOKIE env var)'
)
@click.option(
    '--cookie-file', '-f',
    type=click.Path(exists=True),
    envvar='NCM_COOKIE_FILE',
    help='Path to file containing cookie'
)
@click.pass_context
def cli(ctx: click.Context, cookie: Optional[str], cookie_file: Optional[str]):
    """
    Netease Cloud Music CLI - Search and download music.

    \b
    Examples:
      ncm search "周杰伦"           # Search for songs
      ncm download 1234567          # Download a song by ID
      ncm download 1234567 5678901  # Download multiple songs
      ncm playlist 123456789        # Download entire playlist
      ncm album 12345678            # Download entire album

    \b
    Authentication:
      Some features require login. Set your cookie via:
      - --cookie option
      - NCM_COOKIE environment variable
      - --cookie-file option
    """
    ctx.ensure_object(dict)
    ctx.obj['cookie'] = cookie
    ctx.obj['cookie_file'] = cookie_file


@cli.command()
@click.argument('keyword')
@click.option('--limit', '-l', default=20, help='Number of results (default: 20)')
@click.option('--page', '-p', default=1, help='Page number (default: 1)')
@click.option('--json', '-j', 'as_json', is_flag=True, help='Output as JSON')
@click.pass_context
def search(ctx: click.Context, keyword: str, limit: int, page: int, as_json: bool):
    """
    Search for songs.

    \b
    Examples:
      ncm search "周杰伦"
      ncm search "love song" --limit 50
      ncm search "rock" --page 2
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])
    offset = (page - 1) * limit

    with console.status(f"[cyan]Searching for '{keyword}'..."):
        result = client.search_songs(keyword, limit=limit, offset=offset)

    if as_json:
        data = {
            'songs': [
                {
                    'id': s.id,
                    'name': s.name,
                    'artists': s.artist_names,
                    'album': s.album.name,
                    'duration': s.duration
                }
                for s in result.songs
            ],
            'total': result.song_count,
            'hasMore': result.has_more
        }
        console.print_json(json.dumps(data, ensure_ascii=False))
        return

    if not result.songs:
        console.print(f"[yellow]No results found for '{keyword}'[/yellow]")
        return

    table = format_song_table(result.songs, f"Search Results for '{keyword}'")
    console.print(table)
    console.print(f"\n[dim]Total: {result.song_count} songs | Page {page}[/dim]")

    if result.has_more:
        console.print(f"[dim]Use --page {page + 1} to see more results[/dim]")


@cli.command()
@click.argument('song_ids', nargs=-1, type=int, required=True)
@click.option(
    '--quality', '-q',
    type=click.Choice(['standard', 'higher', 'exhigh', 'lossless', 'hires']),
    default='exhigh',
    help='Audio quality (default: exhigh/320kbps)'
)
@click.option(
    '--output', '-o',
    type=click.Path(),
    default='./downloads',
    help='Output directory (default: ./downloads)'
)
@click.option(
    '--format', '-F',
    'filename_format',
    default='{artist} - {title}',
    help='Filename format (default: "{artist} - {title}")'
)
@click.option('--overwrite', is_flag=True, help='Overwrite existing files')
@click.pass_context
def download(
    ctx: click.Context,
    song_ids: tuple[int, ...],
    quality: str,
    output: str,
    filename_format: str,
    overwrite: bool
):
    """
    Download songs by ID.

    \b
    Quality levels:
      standard  - 128kbps MP3
      higher    - 192kbps MP3
      exhigh    - 320kbps MP3 (HQ)
      lossless  - ~1000kbps FLAC (SQ)
      hires     - Hi-Res FLAC

    \b
    Examples:
      ncm download 1234567
      ncm download 1234567 5678901 -q lossless
      ncm download 1234567 -o ./music -q hires
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])
    downloader = Downloader(
        client,
        output_dir=output,
        quality=quality,
        filename_template=filename_format,
        overwrite=overwrite
    )

    console.print(f"[cyan]Downloading {len(song_ids)} song(s) at {quality} quality...[/cyan]\n")

    success_count = 0
    fail_count = 0

    for song_id in song_ids:
        # Get song info first
        songs = client.get_song_detail([song_id])
        if songs:
            song = songs[0]
            console.print(f"[dim]→ {song.name} - {song.artist_names}[/dim]")

        path = downloader.download_song(song_id, show_progress=True)

        if path:
            console.print(f"[green]✓ Saved to: {path}[/green]\n")
            success_count += 1
        else:
            console.print(f"[red]✗ Failed to download song {song_id}[/red]\n")
            fail_count += 1

    # Summary
    console.print(Panel(
        f"[green]Downloaded: {success_count}[/green] | [red]Failed: {fail_count}[/red]",
        title="Summary"
    ))


@cli.command()
@click.argument('playlist_id', type=int)
@click.option(
    '--quality', '-q',
    type=click.Choice(['standard', 'higher', 'exhigh', 'lossless', 'hires']),
    default='exhigh',
    help='Audio quality'
)
@click.option('--output', '-o', type=click.Path(), help='Output directory')
@click.option('--list-only', '-L', is_flag=True, help='List songs without downloading')
@click.pass_context
def playlist(
    ctx: click.Context,
    playlist_id: int,
    quality: str,
    output: Optional[str],
    list_only: bool
):
    """
    Download all songs from a playlist.

    \b
    Examples:
      ncm playlist 123456789
      ncm playlist 123456789 -q lossless
      ncm playlist 123456789 --list-only
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])

    with console.status("[cyan]Fetching playlist..."):
        playlist_info = client.get_playlist_detail(playlist_id)

    if not playlist_info:
        console.print(f"[red]Playlist {playlist_id} not found[/red]")
        return

    name = playlist_info.get('name', 'Unknown')
    track_count = playlist_info.get('trackCount', 0)

    console.print(Panel(
        f"[bold]{name}[/bold]\n"
        f"Tracks: {track_count} | "
        f"Plays: {playlist_info.get('playCount', 0):,}",
        title="Playlist Info"
    ))

    if list_only:
        # Just show the track list
        songs = client.get_playlist_tracks(playlist_id)
        if songs:
            table = format_song_table(songs[:50], "Playlist Tracks")
            console.print(table)
            if len(songs) > 50:
                console.print(f"[dim]... and {len(songs) - 50} more tracks[/dim]")
        return

    # Download all tracks
    downloader = Downloader(
        client,
        output_dir=output or './downloads',
        quality=quality
    )

    results = downloader.download_playlist(playlist_id, quality=quality, output_dir=output)

    success = sum(1 for _, path in results if path)
    failed = len(results) - success

    console.print(Panel(
        f"[green]Downloaded: {success}[/green] | [red]Failed: {failed}[/red]",
        title="Summary"
    ))


@cli.command()
@click.argument('album_id', type=int)
@click.option(
    '--quality', '-q',
    type=click.Choice(['standard', 'higher', 'exhigh', 'lossless', 'hires']),
    default='exhigh',
    help='Audio quality'
)
@click.option('--output', '-o', type=click.Path(), help='Output directory')
@click.option('--list-only', '-L', is_flag=True, help='List songs without downloading')
@click.pass_context
def album(
    ctx: click.Context,
    album_id: int,
    quality: str,
    output: Optional[str],
    list_only: bool
):
    """
    Download all songs from an album.

    \b
    Examples:
      ncm album 12345678
      ncm album 12345678 -q hires
      ncm album 12345678 --list-only
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])

    with console.status("[cyan]Fetching album..."):
        album_data = client.get_album(album_id)

    if not album_data:
        console.print(f"[red]Album {album_id} not found[/red]")
        return

    album_info = album_data.get('album', {})
    name = album_info.get('name', 'Unknown')
    artist = album_info.get('artist', {}).get('name', 'Unknown')
    size = album_info.get('size', 0)

    console.print(Panel(
        f"[bold]{name}[/bold]\n"
        f"Artist: {artist} | Tracks: {size}",
        title="Album Info"
    ))

    songs = [Song.from_dict(s) for s in album_data.get('songs', [])]

    if list_only:
        if songs:
            table = format_song_table(songs, "Album Tracks")
            console.print(table)
        return

    # Download all tracks
    downloader = Downloader(
        client,
        output_dir=output or './downloads',
        quality=quality
    )

    results = downloader.download_album(album_id, quality=quality, output_dir=output)

    success = sum(1 for _, path in results if path)
    failed = len(results) - success

    console.print(Panel(
        f"[green]Downloaded: {success}[/green] | [red]Failed: {failed}[/red]",
        title="Summary"
    ))


@cli.command()
@click.argument('song_id', type=int)
@click.option('--translated', '-t', is_flag=True, help='Include translated lyrics')
@click.option('--romanized', '-r', is_flag=True, help='Include romanized lyrics')
@click.option('--save', '-s', type=click.Path(), help='Save lyrics to file')
@click.pass_context
def lyric(
    ctx: click.Context,
    song_id: int,
    translated: bool,
    romanized: bool,
    save: Optional[str]
):
    """
    Get lyrics for a song.

    \b
    Examples:
      ncm lyric 1234567
      ncm lyric 1234567 --translated
      ncm lyric 1234567 -s lyrics.lrc
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])

    with console.status("[cyan]Fetching lyrics..."):
        lyric_data = client.get_lyric(song_id)

    if not lyric_data.lrc:
        console.print("[yellow]No lyrics found for this song[/yellow]")
        return

    output_text = lyric_data.lrc

    console.print(Panel(lyric_data.lrc, title="Lyrics"))

    if translated and lyric_data.translated:
        console.print(Panel(lyric_data.translated, title="Translated"))
        output_text += "\n\n" + lyric_data.translated

    if romanized and lyric_data.romanized:
        console.print(Panel(lyric_data.romanized, title="Romanized"))
        output_text += "\n\n" + lyric_data.romanized

    if save:
        with open(save, 'w', encoding='utf-8') as f:
            f.write(output_text)
        console.print(f"[green]Lyrics saved to: {save}[/green]")


@cli.command()
@click.argument('song_ids', nargs=-1, type=int, required=True)
@click.option('--json', '-j', 'as_json', is_flag=True, help='Output as JSON')
@click.pass_context
def info(ctx: click.Context, song_ids: tuple[int, ...], as_json: bool):
    """
    Get detailed information for songs.

    \b
    Examples:
      ncm info 1234567
      ncm info 1234567 5678901 --json
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])

    with console.status("[cyan]Fetching song info..."):
        songs = client.get_song_detail(list(song_ids))

    if not songs:
        console.print("[yellow]No songs found[/yellow]")
        return

    if as_json:
        data = [
            {
                'id': s.id,
                'name': s.name,
                'artists': [{'id': a.id, 'name': a.name} for a in s.artists],
                'album': {'id': s.album.id, 'name': s.album.name},
                'duration': s.duration,
                'fee': s.fee
            }
            for s in songs
        ]
        console.print_json(json.dumps(data, ensure_ascii=False))
        return

    for song in songs:
        console.print(Panel(
            f"[bold green]{song.name}[/bold green]\n\n"
            f"[cyan]ID:[/cyan] {song.id}\n"
            f"[cyan]Artists:[/cyan] {song.artist_names}\n"
            f"[cyan]Album:[/cyan] {song.album.name}\n"
            f"[cyan]Duration:[/cyan] {song.duration_str}\n"
            f"[cyan]Fee:[/cyan] {'Free' if song.fee == 0 else 'VIP' if song.fee == 1 else 'Paid'}",
            title="Song Info"
        ))


@cli.command()
@click.option('--area', '-a',
              type=click.Choice(['all', 'chinese', 'japanese', 'korean', 'western']),
              default='all',
              help='Filter by area')
@click.option('--limit', '-l', default=20, help='Number of results')
@click.option('--json', '-j', 'as_json', is_flag=True, help='Output as JSON')
@click.pass_context
def new(ctx: click.Context, area: str, limit: int, as_json: bool):
    """
    Get new song releases.

    \b
    Examples:
      ncm new
      ncm new --area chinese
      ncm new --limit 50
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])
    area_map = {'all': 0, 'chinese': 7, 'japanese': 8, 'korean': 16, 'western': 96}

    with console.status("[cyan]Fetching new songs..."):
        songs = client.get_new_songs(area_map[area])

    songs = songs[:limit]

    if as_json:
        data = [
            {'id': s.id, 'name': s.name, 'artists': s.artist_names, 'album': s.album.name}
            for s in songs
        ]
        console.print_json(json.dumps(data, ensure_ascii=False))
        return

    if not songs:
        console.print("[yellow]No new songs found[/yellow]")
        return

    table = format_song_table(songs, f"New Songs ({area.title()})")
    console.print(table)


@cli.command()
@click.option('--json', '-j', 'as_json', is_flag=True, help='Output as JSON')
@click.pass_context
def recommend(ctx: click.Context, as_json: bool):
    """
    Get daily recommended songs (requires login).

    \b
    Examples:
      ncm recommend
      ncm recommend --json
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])

    with console.status("[cyan]Fetching recommendations..."):
        songs = client.get_recommend_songs()

    if not songs:
        console.print("[yellow]No recommendations available. Make sure you're logged in.[/yellow]")
        console.print("[dim]Set NCM_COOKIE environment variable or use --cookie option[/dim]")
        return

    if as_json:
        data = [
            {'id': s.id, 'name': s.name, 'artists': s.artist_names}
            for s in songs
        ]
        console.print_json(json.dumps(data, ensure_ascii=False))
        return

    table = format_song_table(songs, "Daily Recommendations")
    console.print(table)


@cli.command()
@click.pass_context
def me(ctx: click.Context):
    """
    Show current user info (requires login).
    """
    client = create_client(ctx.obj['cookie'], ctx.obj['cookie_file'])

    with console.status("[cyan]Fetching user info..."):
        user_info = client.get_user_info()

    if not user_info or user_info.get('code') != 200:
        console.print("[yellow]Not logged in or session expired.[/yellow]")
        console.print("[dim]Run 'ncm login' to authenticate[/dim]")
        return

    account = user_info.get('account', {})
    profile = user_info.get('profile', {})

    vip_types = {0: 'None', 1: 'VIP', 11: 'SVIP'}
    vip_type = vip_types.get(account.get('vipType', 0), str(account.get('vipType', 0)))

    console.print(Panel(
        f"[bold]{profile.get('nickname', 'Unknown')}[/bold]\n\n"
        f"[cyan]User ID:[/cyan] {account.get('id', 'N/A')}\n"
        f"[cyan]VIP Type:[/cyan] {vip_type}\n"
        f"[cyan]Status:[/cyan] {'Active' if account.get('status') == 0 else 'Unknown'}",
        title="User Info"
    ))


@cli.command()
@click.option('--cookie', '-c', 'cookie_str', help='Cookie string (MUSIC_U value or full cookie)')
@click.pass_context
def login(ctx: click.Context, cookie_str: Optional[str]):
    """
    Login to Netease Cloud Music with cookie.

    \b
    Examples:
      ncm login --cookie "your_music_u_value"
      ncm login -c "MUSIC_U=xxx; ..."
    """
    if not cookie_str:
        console.print(Panel(
            "[bold]How to get your cookie:[/bold]\n\n"
            "1. Open [blue]https://music.163.com[/blue] in your browser\n"
            "2. Log in to your account\n"
            "3. Press [cyan]F12[/cyan] to open Developer Tools\n"
            "4. Go to [cyan]Application[/cyan] (Chrome) or [cyan]Storage[/cyan] (Firefox) tab\n"
            "5. Find [cyan]Cookies[/cyan] -> [cyan]music.163.com[/cyan]\n"
            "6. Copy the [bold]MUSIC_U[/bold] cookie value\n\n"
            "[dim]Alternative: Network tab -> any request -> copy Cookie header[/dim]",
            title="Login Required",
            border_style="yellow"
        ))
        console.print("\nUsage: [cyan]ncm login --cookie \"your_music_u_value\"[/cyan]")
        return

    # If user provided just the MUSIC_U value (no = sign), wrap it
    if '=' not in cookie_str:
        cookie_str = f"MUSIC_U={cookie_str}"

    client = NCMClient()
    console.print("[cyan]Verifying cookie...[/cyan]")

    if client.login_with_cookie(cookie_str):
        save_cookie(cookie_str)
        console.print("[green]Login successful! Cookie saved.[/green]")

        # Show user info
        user_info = client.get_user_info()
        if user_info and user_info.get('profile'):
            nickname = user_info['profile'].get('nickname', 'Unknown')
            console.print(f"[green]Welcome, {nickname}![/green]")
    else:
        console.print("[red]Invalid cookie or login failed.[/red]")


@cli.command()
def logout():
    """
    Logout and remove saved credentials.
    """
    if COOKIE_FILE.exists():
        COOKIE_FILE.unlink()
        console.print("[green]Logged out successfully.[/green]")
    else:
        console.print("[yellow]Not logged in.[/yellow]")


def main():
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == '__main__':
    main()
