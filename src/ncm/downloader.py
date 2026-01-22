"""
Music downloader for Netease Cloud Music.

Provides functionality to download songs with progress display.
"""

import os
import re
from pathlib import Path
from typing import Optional, Callable

import requests
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TaskID
)

from .client import NCMClient
from .models import Song, SongUrl


def sanitize_filename(filename: str) -> str:
    """
    Remove invalid characters from filename.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename safe for filesystem
    """
    # Remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Remove leading/trailing spaces and dots
    filename = filename.strip(' .')
    # Limit length
    if len(filename) > 200:
        filename = filename[:200]
    return filename or 'untitled'


class Downloader:
    """
    Download manager for Netease Cloud Music songs.

    Example:
        >>> client = NCMClient()
        >>> downloader = Downloader(client)
        >>> downloader.download_song(1234567, output_dir="./music")
    """

    # File extensions for different quality levels
    EXTENSIONS = {
        'standard': 'mp3',
        'higher': 'mp3',
        'exhigh': 'mp3',
        'lossless': 'flac',
        'hires': 'flac',
    }

    def __init__(
        self,
        client: NCMClient,
        output_dir: str = "./downloads",
        quality: str = "exhigh",
        filename_template: str = "{artist} - {title}",
        overwrite: bool = False
    ):
        """
        Initialize the downloader.

        Args:
            client: NCMClient instance
            output_dir: Directory to save downloaded files
            quality: Default quality level
            filename_template: Template for output filenames
                              Available: {title}, {artist}, {album}, {id}
            overwrite: Whether to overwrite existing files
        """
        self.client = client
        self.output_dir = Path(output_dir)
        self.quality = quality
        self.filename_template = filename_template
        self.overwrite = overwrite

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_filename(self, song: Song, extension: str) -> str:
        """Generate filename for a song."""
        filename = self.filename_template.format(
            title=song.name,
            artist=song.artist_names,
            album=song.album.name,
            id=song.id
        )
        filename = sanitize_filename(filename)
        return f"{filename}.{extension}"

    def _download_file(
        self,
        url: str,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Download a file from URL.

        Args:
            url: Download URL
            output_path: Path to save the file
            progress_callback: Optional callback(downloaded, total) for progress

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

            return True

        except Exception:
            # Clean up partial file
            if output_path.exists():
                output_path.unlink()
            return False

    def download_song(
        self,
        song_id: int,
        quality: Optional[str] = None,
        output_dir: Optional[str] = None,
        show_progress: bool = True
    ) -> Optional[Path]:
        """
        Download a single song.

        Args:
            song_id: Song ID to download
            quality: Quality level (overrides default)
            output_dir: Output directory (overrides default)
            show_progress: Whether to show progress bar

        Returns:
            Path to downloaded file or None if failed
        """
        quality = quality or self.quality
        output_dir = Path(output_dir) if output_dir else self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get song details
        songs = self.client.get_song_detail([song_id])
        if not songs:
            return None
        song = songs[0]

        # Get download URL
        song_url = self.client.get_download_url(song_id, quality)
        if not song_url or not song_url.url:
            # Try lower qualities
            fallback_qualities = ['hires', 'lossless', 'exhigh', 'higher', 'standard']
            for q in fallback_qualities:
                if q == quality:
                    continue
                song_url = self.client.get_download_url(song_id, q)
                if song_url and song_url.url:
                    quality = q
                    break
            else:
                return None

        # Determine extension
        extension = song_url.type or self.EXTENSIONS.get(quality, 'mp3')

        # Generate filename
        filename = self._get_filename(song, extension)
        output_path = output_dir / filename

        # Check if file exists
        if output_path.exists() and not self.overwrite:
            return output_path

        # Download with progress
        if show_progress:
            with Progress(
                "[progress.description]{task.description}",
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task(
                    f"[cyan]Downloading {song.name}...",
                    total=song_url.size
                )

                def update_progress(downloaded: int, total: int):
                    progress.update(task, completed=downloaded)

                success = self._download_file(
                    song_url.url,
                    output_path,
                    update_progress
                )
        else:
            success = self._download_file(song_url.url, output_path)

        return output_path if success else None

    def download_songs(
        self,
        song_ids: list[int],
        quality: Optional[str] = None,
        output_dir: Optional[str] = None,
        show_progress: bool = True
    ) -> list[tuple[int, Optional[Path]]]:
        """
        Download multiple songs.

        Args:
            song_ids: List of song IDs
            quality: Quality level
            output_dir: Output directory
            show_progress: Whether to show progress

        Returns:
            List of (song_id, output_path) tuples
        """
        results = []

        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "({task.completed}/{task.total})",
        ) as progress:
            overall = progress.add_task(
                "[green]Overall progress",
                total=len(song_ids)
            )

            for song_id in song_ids:
                path = self.download_song(
                    song_id,
                    quality=quality,
                    output_dir=output_dir,
                    show_progress=False
                )
                results.append((song_id, path))
                progress.update(overall, advance=1)

        return results

    def download_playlist(
        self,
        playlist_id: int,
        quality: Optional[str] = None,
        output_dir: Optional[str] = None
    ) -> list[tuple[int, Optional[Path]]]:
        """
        Download all songs from a playlist.

        Args:
            playlist_id: Playlist ID
            quality: Quality level
            output_dir: Output directory (defaults to playlist name subfolder)

        Returns:
            List of (song_id, output_path) tuples
        """
        # Get playlist info
        playlist = self.client.get_playlist_detail(playlist_id)
        if not playlist:
            return []

        # Create output directory
        if not output_dir:
            dir_name = sanitize_filename(playlist.get('name', str(playlist_id)))
            output_dir = self.output_dir / dir_name

        # Get track IDs
        track_ids = [t['id'] for t in playlist.get('trackIds', [])]

        return self.download_songs(
            track_ids,
            quality=quality,
            output_dir=str(output_dir)
        )

    def download_album(
        self,
        album_id: int,
        quality: Optional[str] = None,
        output_dir: Optional[str] = None
    ) -> list[tuple[int, Optional[Path]]]:
        """
        Download all songs from an album.

        Args:
            album_id: Album ID
            quality: Quality level
            output_dir: Output directory

        Returns:
            List of (song_id, output_path) tuples
        """
        songs = self.client.get_album_songs(album_id)
        if not songs:
            return []

        # Create output directory with album name
        if not output_dir:
            album = self.client.get_album(album_id)
            if album:
                album_info = album.get('album', {})
                dir_name = sanitize_filename(album_info.get('name', str(album_id)))
                output_dir = self.output_dir / dir_name

        song_ids = [s.id for s in songs]
        return self.download_songs(
            song_ids,
            quality=quality,
            output_dir=str(output_dir) if output_dir else None
        )
