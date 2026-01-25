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

musicdl_client = None
try:
    from musicdl.modules.sources import NeteaseMusicClient
    from musicdl.modules.utils.neteaseutils import MUSIC_QUALITIES, EapiCryptoUtils
    from musicdl.modules.utils import safeextractfromdict, resp2json, SongInfo, legalizestring, cleanlrc
    import json
    import random
    import copy
    import pickle
    from typing import Tuple, Optional, Dict, Any
    musicdl_client = NeteaseMusicClient()
except ImportError:
    musicdl_client = False


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
        output_dir: str = ".",
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
        # Use anonymous client for URL fetching (avoids CDN auth issues)
        self._url_client = NCMClient()
        self.output_dir = Path(output_dir)
        self.quality = quality
        self.filename_template = filename_template
        self.overwrite = overwrite
        self.last_error: Optional[str] = None

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
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://music.163.com/',
            }
            response = requests.get(url, headers=headers, stream=True, timeout=60)
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

        except requests.HTTPError as e:
            if e.response.status_code == 403:
                self.last_error = "Access denied (403) - may be region/IP restricted or require VIP"
            else:
                self.last_error = f"HTTP {e.response.status_code}: Download failed"
            if output_path.exists():
                output_path.unlink()
            return False
        except Exception as e:
            self.last_error = str(e)
            if output_path.exists():
                output_path.unlink()
            return False

    def get_song_info_and_url_by_id(self, song_id: str, client: Optional['NeteaseMusicClient'] = None,
                                    quality: str = 'jymaster', request_overrides: dict = None) \
            -> Tuple[Optional[SongInfo], Optional[Dict[str, Any]]]:
        """
        根据歌曲ID获取歌曲信息和下载URL

        Args:
            song_id (str): 网易云音乐歌曲ID
            client (NeteaseMusicClient, optional): 已初始化的NeteaseMusicClient实例，如果为None则创建新的
            quality (str): 音质，可选值: 'standard', 'higher', 'exhigh', 'lossless', 'hires', 'sky' (默认: 'exhigh')
            request_overrides (dict): 请求覆盖参数

        Returns:
            Tuple[Optional[SongInfo], Optional[Dict]]: (songinfo, songurl)
            songurl结构: {
                'id': song_id,
                'url': download_url,
                'bitrate': bitrate,
                'size': file_size,
                'type': file_type,
                'level': quality_level,
                'md5': file_md5
            }
        """

    # def get_netease_song_by_id(song_id: int) -> Tuple[Optional[SongInfo], Optional[SongUrl]]:
    def get_netease_song_by_id(self, song_id: str, client: Optional['NeteaseMusicClient'] = None,
                                    request_overrides: dict = None) \
            -> Tuple[Optional[SongInfo], Optional[SongUrl]]:
        """
        根据 song_id 获取 SongInfo 和 SongUrl
        """
        # 1. 初始化客户端
        if not client:
            client = NeteaseMusicClient()

        # 2. 构造一个模拟的搜索结果，只需包含 ID
        # 因为 _parsewiththirdpartapis 和 _search 内部逻辑主要依赖 search_result['id']
        search_result_mock = {
            'id': str(song_id),
            'name': 'Unknown',  # 占位，解析后会更新
            'ar': [{'name': 'Unknown'}],
            'al': {'name': 'Unknown', 'picUrl': ''},
            'dt': 0
        }

        # 3. 尝试获取歌曲信息 (SongInfo)
        # 我们优先尝试调用客户端的私有解析方法，这些方法会尝试多个 API 源（如 cgg, bugpk, xiaoqin）
        # 如果第三方 API 失败，我们可以参考 _search 里的逻辑

        song_info = None
        request_overrides = request_overrides or {}

        # 模拟 progress 对象以适配 _search 的调用（如果需要调用 _search）
        # 但由于我们要的是特定 ID，直接调用内部解析链更精准
        try:
            # 尝试通过第三方 API 获取高质量链接（含 Flac）
            song_info = client._parsewiththirdpartapis(search_result_mock, request_overrides)
            # print(song_info)
            # song_info = None

            # 如果第三方没搜到有效的 url，尝试用官方 EAPI (对应 _search 里的逻辑)
            if not (song_info and song_info.with_valid_download_url):
                for quality in MUSIC_QUALITIES:
                    params = {
                        'ids': [song_id],
                        'level': quality,
                        'encodeType': 'flac',
                        'header': json.dumps({
                            "os": "pc",
                            "appver": "", "osver": "",
                            "deviceId": "pyncm!",
                            "requestId": str(random.randrange(20000000, 30000000))
                        })
                    }
                    if quality == 'sky':
                        params['immerseType'] = 'c51'

                    # 加密参数
                    encrypted_params = EapiCryptoUtils.encryptparams(
                        url='https://interface3.music.163.com/eapi/song/enhance/player/url/v1',
                        payload=params
                    )

                    cookies = {"os": "pc",
                               "appver": "",
                               "osver": "",
                               "deviceId": "pyncm!"
                               }
                    cookies.update(client.default_cookies or {})

                    resp = client.post(
                        'https://interface3.music.163.com/eapi/song/enhance/player/url/v1',
                        data={"params": encrypted_params},
                        cookies=cookies
                    )
                    download_result = resp2json(resp)
                    # print(download_result)
                    download_url: str = safeextractfromdict(download_result, ['data', 0, 'url'], '')
                    if not download_url:
                        continue

                    song_info = SongInfo(
                        raw_data={
                            'search': {},
                            'download': download_result,
                            'lyric': {},
                            'quality': quality
                        },
                        source='NeteaseMusicClient',
                        song_name='',
                        singers='',
                        album='',
                        ext=download_url.split('?')[0].split('.')[-1],
                        file_size='NULL',
                        identifier=song_id,
                        duration_s=0,
                        duration=0,
                        lyric=None,
                        cover_url=None,
                        download_url=download_url,
                        download_url_status=client.audio_link_tester.test(download_url, request_overrides),
                    )
                    song_info.download_url_status['probe_status'] = client.audio_link_tester.probe(song_info.download_url, request_overrides)
                    song_info.file_size = song_info.download_url_status['probe_status']['file_size']
                    song_info.ext = song_info.download_url_status['probe_status']['ext'] if (song_info.download_url_status['probe_status']['ext'] and song_info.download_url_status['probe_status']['ext'] != 'NULL') else song_info.ext

                    if song_info.with_valid_download_url:
                        break
            # --lyric results
            data = {'id': song_id, 'cp': 'false', 'tv': '0', 'lv': '0', 'rv': '0', 'kv': '0', 'yv': '0',
                    'ytv': '0', 'yrv': '0'}
            try:
                resp = client.post('https://interface3.music.163.com/api/song/lyric', data=data, **request_overrides)
                resp.raise_for_status()
                lyric_result: dict = resp2json(resp)
                lyric = safeextractfromdict(lyric_result, ['lrc', 'lyric'], 'NULL')
                lyric = 'NULL' if not lyric else cleanlrc(lyric)
            except Exception as e:
                print(f"获取歌词 {song_id} 失败: {e}")
                lyric_result, lyric = dict(), 'NULL'
            song_info.raw_data['lyric'] = lyric_result
            song_info.lyric = lyric
        except Exception as e:
            print(f"解析歌曲 {song_id} 失败: {e}")
            return None, None

        if not song_info or not song_info.download_url:
            return None, None

        # 4. 构造 SongUrl
        # 从 raw_data 中提取详细的比特率、文件大小等信息
        download_data = song_info.raw_data.get('download', {})

        # 不同的 API 返回结构不同，这里做一个兼容处理
        if 'data' in download_data and isinstance(download_data['data'], list):
            # 官方 EAPI 格式
            main_data = download_data['data'][0]
            song_url = SongUrl(
                id=int(song_id),
                url=song_info.download_url,
                bitrate=main_data.get('br', 0),
                size=main_data.get('size', 0),
                type=main_data.get('type', song_info.ext),
                level=main_data.get('level', song_info.raw_data.get('quality', 'standard')),
                md5=main_data.get('md5')
            )
        elif 'data' in download_data and isinstance(download_data['data'], dict):
            # 第三方 API 格式 (如 cenguigui)
            main_data = download_data['data']
            # 尝试转换 size 字符串为字节 (如果是 "167.61MB")
            raw_size = main_data.get('size', '0')
            try:
                size_val = int(float(str(raw_size).lower().replace('mb', '').strip()) * 1024 * 1024)
            except:
                size_val = 0

            song_url = SongUrl(
                id=int(song_id),
                url=song_info.download_url,
                bitrate=0,  # 第三方 API 有时不提供码率
                size=size_val,
                type=song_info.ext,
                level=song_info.raw_data.get('quality', 'standard')
            )
        else:
            # 保底逻辑
            song_url = SongUrl(
                id=int(song_id),
                url=song_info.download_url,
                bitrate=0,
                size=0,
                type=song_info.ext,
                level=song_info.raw_data.get('quality', 'standard')
            )

        return song_info, song_url

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
        fallback_qualities = ['jymaster', 'sky', 'jyeffect', 'hires', 'lossless', 'exhigh', 'higher', 'standard']
  # musicdl MUSIC_QUALITIES: ['jymaster', 'dolby', 'sky', 'jyeffect', 'hires', 'lossless', 'exhigh', 'standard']

        song_info = None
        is_vip_song = song.fee in [1, 4]
        if isinstance(musicdl_client, NeteaseMusicClient):
            song_info, song_url = self.get_netease_song_by_id(str(song_id), musicdl_client, {})
        else:
            song_url = None

            # For VIP songs, try EAPI (mobile app API) first with authenticated client
            # Use streaming URL API (better quality support than download API)
            if is_vip_song:
                # Try EAPI streaming URL with requested quality
                urls = self.client.get_song_url_eapi([song_id], quality)
                if urls and urls[0].url:
                    song_url = urls[0]
                else:
                    # Try fallback qualities
                    for q in fallback_qualities:
                        if q == quality:
                            continue
                        urls = self.client.get_song_url_eapi([song_id], q)
                        if urls and urls[0].url:
                            song_url = urls[0]
                            quality = q
                            break

            # Fall back to WEAPI (anonymous client works for free songs)
            if not song_url or not song_url.url:
                for url_client in [self._url_client, self.client]:
                    # Try download URL API
                    song_url = url_client.get_download_url(song_id, quality)
                    if song_url and song_url.url:
                        break

                    # Try lower qualities with download API
                    for q in fallback_qualities:
                        if q == quality:
                            continue
                        song_url = url_client.get_download_url(song_id, q)
                        if song_url and song_url.url:
                            quality = q
                            break
                    if song_url and song_url.url:
                        break

                    # Try streaming URL API as fallback
                    for q in fallback_qualities:
                        urls = url_client.get_song_url([song_id], q)
                        if urls and urls[0].url:
                            song_url = urls[0]
                            quality = q
                            break
                    if song_url and song_url.url:
                        break

        if not song_url or not song_url.url:
            self.last_error = f"Song requires VIP (fee={song.fee})" if is_vip_song else "Song unavailable"
            return None

        # Determine extension
        extension = song_url.type or self.EXTENSIONS.get(quality, 'mp3')

        # Generate filename
        filename = self._get_filename(song, extension)
        output_path = output_dir / filename

        if song_info:
            pickle_name = self._get_filename(song, 'pkl')
            with open(output_dir / pickle_name, 'wb') as f:
                pickle.dump([song_info.todict(), ], f)

        # Check if file exists
        if output_path.exists() and not self.overwrite:
            return output_path

        # Download with progress
        # print(song_url)
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
