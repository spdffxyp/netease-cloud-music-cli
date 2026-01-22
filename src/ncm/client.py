"""
Netease Cloud Music API Client.

Provides methods to interact with various Netease Cloud Music API endpoints.
"""

import json
import os
from typing import Dict, List, Optional, Any

import requests

from .crypto import weapi_encrypt
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

    # Search types
    SEARCH_TYPE_SONG = 1
    SEARCH_TYPE_ALBUM = 10
    SEARCH_TYPE_ARTIST = 100
    SEARCH_TYPE_PLAYLIST = 1000
    SEARCH_TYPE_USER = 1002
    SEARCH_TYPE_LYRIC = 1006

    # Quality levels (from lowest to highest)
    QUALITY_STANDARD = 'standard'   # 128kbps
    QUALITY_HIGHER = 'higher'       # 192kbps
    QUALITY_EXHIGH = 'exhigh'       # 320kbps (HQ)
    QUALITY_LOSSLESS = 'lossless'   # ~1000kbps (SQ)
    QUALITY_HIRES = 'hires'         # Hi-Res

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
