"""
Netease Cloud Music API Client.

Provides methods to interact with various Netease Cloud Music API endpoints.
"""

import json
import os
from typing import Dict, List, Optional, Any

import requests

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

from .crypto import weapi_encrypt, eapi_encrypt
from .models import Song, SongUrl, Playlist, SearchResult, Lyric, Album, Artist


class NCMClient:
    """
    Client for Netease Cloud Music API.

    Example:
        >>> client = NCMClient()
        >>> results = client.search("周杰伦")
        >>> for song in results.songs:
        ...     print(f"{song.name} - {song.artist_names}")
    """

    BASE_URL = 'https://music.163.com'
    INTERFACE_URL = 'https://interface.music.163.com'

    DEFAULT_HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'https://music.163.com/',
        'Origin': 'https://music.163.com',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    # Mobile app headers for EAPI
    EAPI_HEADERS = {
        'User-Agent': 'NeteaseMusic/9.3.40.250202172443(9003040);Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Build/UQ1A.240205.004)',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    # Search types
    SEARCH_TYPE_SONG = 1
    SEARCH_TYPE_ALBUM = 10
    SEARCH_TYPE_ARTIST = 100
    SEARCH_TYPE_PLAYLIST = 1000
    SEARCH_TYPE_USER = 1002
    SEARCH_TYPE_LYRIC = 1006

    # Quality levels (from lowest to highest)
    QUALITY_STANDARD = 'standard'   # 128kbps MP3
    QUALITY_HIGHER = 'higher'       # 192kbps MP3
    QUALITY_EXHIGH = 'exhigh'       # 320kbps MP3 (HQ)
    QUALITY_LOSSLESS = 'lossless'   # FLAC (SQ)
    QUALITY_HIRES = 'hires'         # Hi-Res FLAC
    QUALITY_JYEFFECT = 'jyeffect'   # HD Surround FLAC
    QUALITY_SKY = 'sky'             # Immersive Surround FLAC
    QUALITY_JYMASTER = 'jymaster'   # Master Quality FLAC

    def __init__(
        self,
        cookie: Optional[str] = None,
        cookie_file: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize the client.

        Args:
            cookie: Cookie string for authentication
            cookie_file: Path to file containing cookie
            timeout: Request timeout in seconds
        """
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        self.timeout = timeout

        # Load cookie from file if specified
        if cookie_file and os.path.exists(cookie_file):
            with open(cookie_file, 'r') as f:
                cookie = f.read().strip()

        if cookie:
            self.session.headers['Cookie'] = cookie

    def _request(
        self,
        endpoint: str,
        data: Dict[str, Any],
        use_interface: bool = False
    ) -> Dict:
        """
        Make an encrypted API request.

        Args:
            endpoint: API endpoint path
            data: Request payload
            use_interface: Use interface.music.163.com instead of music.163.com

        Returns:
            API response as dictionary
        """
        base = self.INTERFACE_URL if use_interface else self.BASE_URL
        url = f"{base}{endpoint}"

        encrypted_data = weapi_encrypt(data)

        try:
            response = self.session.post(
                url,
                data=encrypted_data,
                timeout=self.timeout
            )
            response.raise_for_status()
            # Store the last response for cookie extraction
            self._last_response = response
            return response.json()
        except requests.Timeout:
            return {'code': -1, 'message': 'Request timeout'}
        except requests.RequestException as e:
            return {'code': -1, 'message': str(e)}
        except json.JSONDecodeError:
            return {'code': -1, 'message': 'Invalid JSON response'}

    def _eapi_request(
        self,
        path: str,
        data: Dict[str, Any]
    ) -> Dict:
        """
        Make an EAPI request (mobile app API).

        Args:
            path: API path (e.g., '/api/song/enhance/player/url/v1')
            data: Request payload

        Returns:
            API response as dictionary
        """
        url = f"https://music.163.com/eapi{path[4:]}"  # /api/... -> /eapi/...

        encrypted_body = eapi_encrypt(path, data)

        # Build cookies for EAPI
        import time
        import random
        import string
        device_id = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        cookies = {
            'appver': '9.3.40',
            'buildver': str(int(time.time()))[:10],
            'os': 'android',
            'deviceId': device_id,
            'channel': 'xiaomi',
            'osver': '14',
        }

        # Add MUSIC_U from session if available
        if 'Cookie' in self.session.headers:
            cookie_str = self.session.headers['Cookie']
            if 'MUSIC_U=' in cookie_str:
                for part in cookie_str.split(';'):
                    if 'MUSIC_U=' in part:
                        cookies['MUSIC_U'] = part.split('=', 1)[1].strip()
                        break

        try:
            response = requests.post(
                url,
                data=encrypted_body,
                headers=self.EAPI_HEADERS,
                cookies=cookies,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.Timeout:
            return {'code': -1, 'message': 'Request timeout'}
        except requests.RequestException as e:
            return {'code': -1, 'message': str(e)}
        except json.JSONDecodeError:
            return {'code': -1, 'message': 'Invalid JSON response'}

    # ==================== Search APIs ====================

    def search(
        self,
        keyword: str,
        search_type: int = SEARCH_TYPE_SONG,
        limit: int = 30,
        offset: int = 0
    ) -> SearchResult:
        """
        Search for songs, albums, artists, or playlists.

        Args:
            keyword: Search keyword
            search_type: Type of search (use SEARCH_TYPE_* constants)
            limit: Number of results per page
            offset: Offset for pagination

        Returns:
            SearchResult object containing the results
        """
        data = {
            's': keyword,
            'type': search_type,
            'limit': limit,
            'offset': offset,
            'total': True,
            'csrf_token': ''
        }
        response = self._request('/weapi/search/get', data)
        return SearchResult.from_dict(response)

    def search_songs(
        self,
        keyword: str,
        limit: int = 30,
        offset: int = 0
    ) -> SearchResult:
        """
        Search for songs.

        Args:
            keyword: Search keyword
            limit: Number of results per page
            offset: Offset for pagination

        Returns:
            SearchResult object
        """
        return self.search(keyword, self.SEARCH_TYPE_SONG, limit, offset)

    # ==================== Song APIs ====================

    def get_song_detail(self, song_ids: List[int]) -> List[Song]:
        """
        Get detailed information for songs.

        Args:
            song_ids: List of song IDs

        Returns:
            List of Song objects
        """
        c = json.dumps([{'id': str(sid), 'v': 0} for sid in song_ids])
        response = self._request('/weapi/v3/song/detail', {'c': c})

        if response.get('code') != 200:
            return []

        return [Song.from_dict(s) for s in response.get('songs', [])]

    def get_song_url(
        self,
        song_ids: List[int],
        level: str = QUALITY_STANDARD
    ) -> List[SongUrl]:
        """
        Get streaming URLs for songs.

        Args:
            song_ids: List of song IDs
            level: Quality level (standard, higher, exhigh, lossless, hires)

        Returns:
            List of SongUrl objects
        """
        data = {
            'ids': json.dumps(song_ids),
            'level': level,
            'encodeType': 'mp3' if level in ['standard', 'higher', 'exhigh'] else 'flac'
        }
        response = self._request('/weapi/song/enhance/player/url/v1', data)

        if response.get('code') != 200:
            return []

        return [SongUrl.from_dict(u) for u in response.get('data', [])]

    def get_download_url(
        self,
        song_id: int,
        level: str = QUALITY_LOSSLESS
    ) -> Optional[SongUrl]:
        """
        Get download URL for a song.

        Args:
            song_id: Song ID
            level: Quality level

        Returns:
            SongUrl object or None if not available
        """
        data = {
            'id': str(song_id),
            'level': level
        }
        response = self._request('/weapi/song/enhance/download/url/v1', data)

        if response.get('code') != 200:
            return None

        data = response.get('data', {})
        if not data.get('url'):
            return None

        return SongUrl.from_dict(data)

    def get_song_url_eapi(
        self,
        song_ids: List[int],
        level: str = QUALITY_STANDARD
    ) -> List[SongUrl]:
        """
        Get streaming URLs for songs using EAPI (mobile app API).

        This may work better for VIP songs as it uses the mobile app protocol.

        Args:
            song_ids: List of song IDs
            level: Quality level (standard, higher, exhigh, lossless, hires)

        Returns:
            List of SongUrl objects
        """
        data = {
            'ids': json.dumps([str(sid) for sid in song_ids]),
            'level': level,
            'encodeType': 'flac' if level in ['lossless', 'hires'] else 'mp3'
        }
        response = self._eapi_request('/api/song/enhance/player/url/v1', data)

        if response.get('code') != 200:
            return []

        return [SongUrl.from_dict(u) for u in response.get('data', [])]

    def get_download_url_eapi(
        self,
        song_id: int,
        level: str = QUALITY_LOSSLESS
    ) -> Optional[SongUrl]:
        """
        Get download URL for a song using EAPI (mobile app API).

        This may work better for VIP songs as it uses the mobile app protocol.

        Args:
            song_id: Song ID
            level: Quality level (standard, higher, exhigh, lossless, hires)

        Returns:
            SongUrl object or None if not available
        """
        # Map quality level to bitrate
        br_map = {
            'standard': 128000,
            'higher': 192000,
            'exhigh': 320000,
            'lossless': 999000,
            'hires': 999000,
        }
        data = {
            'id': song_id,
            'br': br_map.get(level, 999000)
        }
        response = self._eapi_request('/api/song/enhance/download/url', data)

        if response.get('code') != 200:
            return None

        data = response.get('data', {})
        if not data.get('url'):
            return None

        return SongUrl.from_dict(data)

    def get_download_url_musicdl(self, song_id: str, client: Optional['NeteaseMusicClient'] = None,
                                    request_overrides: dict = None) \
            -> Tuple[Optional[SongInfo], Optional[SongUrl]]:
        """
        根据 song_id 获取 SongInfo 和 SongUrl
        """
        if not musicdl_client:
            return None, None
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

    # ==================== Lyrics API ====================

    def get_lyric(self, song_id: int) -> Lyric:
        """
        Get lyrics for a song.

        Args:
            song_id: Song ID

        Returns:
            Lyric object
        """
        data = {
            'id': song_id,
            'tv': -1,
            'lv': -1,
            'rv': -1,
            'kv': -1,
            '_nmclfl': 1
        }
        response = self._request('/weapi/song/lyric', data)
        return Lyric.from_dict(response)

    # ==================== Playlist APIs ====================

    def get_playlist_detail(self, playlist_id: int) -> Optional[Dict]:
        """
        Get playlist details including tracks.

        Args:
            playlist_id: Playlist ID

        Returns:
            Playlist data dictionary
        """
        data = {
            'id': str(playlist_id),
            'n': '100000',
            's': '0'
        }
        response = self._request(
            f'/api/v6/playlist/detail?id={playlist_id}',
            data
        )

        if response.get('code') != 200:
            return None

        return response.get('playlist')

    def get_playlist_tracks(self, playlist_id: int) -> List[Song]:
        """
        Get all tracks from a playlist.

        Args:
            playlist_id: Playlist ID

        Returns:
            List of Song objects
        """
        playlist = self.get_playlist_detail(playlist_id)
        if not playlist:
            return []

        # Get track IDs
        track_ids = [t['id'] for t in playlist.get('trackIds', [])]
        if not track_ids:
            return []

        # Fetch song details in batches
        songs = []
        batch_size = 500
        for i in range(0, len(track_ids), batch_size):
            batch = track_ids[i:i + batch_size]
            songs.extend(self.get_song_detail(batch))

        return songs

    # ==================== Album APIs ====================

    def get_album(self, album_id: int) -> Optional[Dict]:
        """
        Get album details including all songs.

        Args:
            album_id: Album ID

        Returns:
            Album data dictionary with songs
        """
        response = self._request(
            f'/weapi/v1/album/{album_id}',
            {'id': str(album_id)}
        )

        if response.get('code') != 200:
            return None

        return response

    def get_album_songs(self, album_id: int) -> List[Song]:
        """
        Get all songs from an album.

        Args:
            album_id: Album ID

        Returns:
            List of Song objects
        """
        album = self.get_album(album_id)
        if not album:
            return []

        return [Song.from_dict(s) for s in album.get('songs', [])]

    # ==================== Artist APIs ====================

    def get_artist_songs(
        self,
        artist_id: int,
        order: str = 'hot',
        limit: int = 100,
        offset: int = 0
    ) -> List[Song]:
        """
        Get songs by an artist.

        Args:
            artist_id: Artist ID
            order: Sort order ('hot' or 'time')
            limit: Number of songs to fetch
            offset: Offset for pagination

        Returns:
            List of Song objects
        """
        data = {
            'id': artist_id,
            'private_cloud': 'true',
            'work_type': 1,
            'order': order,
            'offset': offset,
            'limit': limit
        }
        response = self._request('/weapi/v1/artist/songs', data)

        if response.get('code') != 200:
            return []

        return [Song.from_dict(s) for s in response.get('songs', [])]

    # ==================== Charts APIs ====================

    def get_toplist(self) -> List[Dict]:
        """
        Get all available top charts.

        Returns:
            List of chart information dictionaries
        """
        response = self._request('/api/toplist', {})

        if response.get('code') != 200:
            return []

        return response.get('list', [])

    def get_new_songs(self, area_id: int = 0) -> List[Song]:
        """
        Get new songs chart.

        Args:
            area_id: Area filter (0=all, 7=chinese, 8=japanese, 16=korean, 96=western)

        Returns:
            List of Song objects
        """
        data = {
            'areaId': area_id,
            'total': True
        }
        response = self._request('/weapi/v1/discovery/new/songs', data)

        if response.get('code') != 200:
            return []

        return [Song.from_dict(s) for s in response.get('data', [])]

    # ==================== Login APIs ====================

    def login_with_cookie(self, cookie: str) -> bool:
        """
        Set authentication cookie.

        Args:
            cookie: Cookie string containing MUSIC_U

        Returns:
            True if cookie appears valid
        """
        self.session.headers['Cookie'] = cookie
        # Verify by checking user info
        user_info = self.get_user_info()
        return user_info is not None and user_info.get('code') == 200

    def get_cookies(self) -> Dict[str, str]:
        """Get current session cookies as dictionary."""
        return {c.name: c.value for c in self.session.cookies}

    def get_cookie_string(self) -> str:
        """Get current cookies as a string for saving."""
        cookies = self.session.cookies
        if not cookies:
            return ''
        return '; '.join(f"{c.name}={c.value}" for c in cookies)

    def has_valid_cookie(self) -> bool:
        """Check if we have a valid MUSIC_U cookie."""
        cookies = self.get_cookies()
        return 'MUSIC_U' in cookies and len(cookies.get('MUSIC_U', '')) > 10

    # ==================== User APIs ====================

    def get_user_info(self) -> Optional[Dict]:
        """
        Get current user info (requires authentication).

        Returns:
            User info dictionary or None if not authenticated
        """
        response = self._request('/weapi/w/nuser/account/get', {})

        if response.get('code') != 200:
            return None

        return response

    def get_recommend_songs(self) -> List[Song]:
        """
        Get daily recommended songs (requires authentication).

        Returns:
            List of Song objects
        """
        response = self._request('/weapi/v3/discovery/recommend/songs', {})

        if response.get('code') != 200:
            return []

        data = response.get('data', {})
        return [Song.from_dict(s) for s in data.get('dailySongs', [])]

    def get_personal_fm(self) -> List[Song]:
        """
        Get personal FM songs (requires authentication).

        Returns:
            List of Song objects
        """
        response = self._request('/weapi/v1/radio/get', {'imageFm': '0'}, use_interface=True)

        if response.get('code') != 200:
            return []

        return [Song.from_dict(s) for s in response.get('data', [])]
