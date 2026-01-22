"""
Data models for Netease Cloud Music API responses.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Artist:
    """Artist information."""
    id: int
    name: str
    alias: List[str] = field(default_factory=list)
    pic_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Artist":
        return cls(
            id=data.get('id', 0),
            name=data.get('name', ''),
            alias=data.get('alias', []) or data.get('alia', []) or [],
            pic_url=data.get('picUrl') or data.get('img1v1Url')
        )


@dataclass
class Album:
    """Album information."""
    id: int
    name: str
    pic_url: Optional[str] = None
    publish_time: Optional[int] = None
    size: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "Album":
        return cls(
            id=data.get('id', 0),
            name=data.get('name', ''),
            pic_url=data.get('picUrl'),
            publish_time=data.get('publishTime'),
            size=data.get('size', 0)
        )


@dataclass
class Song:
    """Song information."""
    id: int
    name: str
    artists: List[Artist]
    album: Album
    duration: int  # milliseconds
    fee: int = 0  # 0=free, 1=vip, 4=album, 8=low-quality-free
    mv_id: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "Song":
        # Handle different response formats
        artists_data = data.get('ar') or data.get('artists', [])
        album_data = data.get('al') or data.get('album', {})

        return cls(
            id=data.get('id', 0),
            name=data.get('name', ''),
            artists=[Artist.from_dict(a) for a in artists_data],
            album=Album.from_dict(album_data) if album_data else Album(0, ''),
            duration=data.get('dt') or data.get('duration', 0),
            fee=data.get('fee', 0),
            mv_id=data.get('mv') or data.get('mvid', 0)
        )

    @property
    def artist_names(self) -> str:
        """Get comma-separated artist names."""
        return ', '.join(a.name for a in self.artists)

    @property
    def duration_str(self) -> str:
        """Get duration as mm:ss string."""
        seconds = self.duration // 1000
        return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass
class SongUrl:
    """Song streaming/download URL information."""
    id: int
    url: Optional[str]
    bitrate: int
    size: int
    type: str  # mp3, flac, etc.
    level: str  # standard, higher, exhigh, lossless, hires
    md5: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "SongUrl":
        return cls(
            id=data.get('id', 0),
            url=data.get('url'),
            bitrate=data.get('br', 0),
            size=data.get('size', 0),
            type=data.get('type', 'mp3'),
            level=data.get('level', 'standard'),
            md5=data.get('md5')
        )


@dataclass
class Playlist:
    """Playlist information."""
    id: int
    name: str
    cover_url: Optional[str]
    track_count: int
    play_count: int
    creator_name: str
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Playlist":
        creator = data.get('creator', {})
        return cls(
            id=data.get('id', 0),
            name=data.get('name', ''),
            cover_url=data.get('coverImgUrl'),
            track_count=data.get('trackCount', 0),
            play_count=data.get('playCount', 0),
            creator_name=creator.get('nickname', '') if creator else '',
            description=data.get('description')
        )


@dataclass
class SearchResult:
    """Search result container."""
    songs: List[Song] = field(default_factory=list)
    song_count: int = 0
    has_more: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "SearchResult":
        result = data.get('result', {})
        songs_data = result.get('songs', [])
        return cls(
            songs=[Song.from_dict(s) for s in songs_data],
            song_count=result.get('songCount', 0),
            has_more=result.get('hasMore', False)
        )


@dataclass
class Lyric:
    """Song lyrics."""
    lrc: str  # Original lyrics in LRC format
    translated: Optional[str] = None  # Translated lyrics
    romanized: Optional[str] = None  # Romanized lyrics

    @classmethod
    def from_dict(cls, data: dict) -> "Lyric":
        return cls(
            lrc=data.get('lrc', {}).get('lyric', ''),
            translated=data.get('tlyric', {}).get('lyric'),
            romanized=data.get('romalrc', {}).get('lyric')
        )
