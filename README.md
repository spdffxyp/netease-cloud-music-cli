# NCM CLI

A command-line tool for searching and downloading music from Netease Cloud Music.

## Disclaimer

**This project is for personal learning and research purposes only. Do not use for commercial or illegal purposes!**

**The author is not responsible for any account bans or other issues that may occur from using this tool. Please consider carefully before use!**

**If there is any infringement, please contact for removal!**

## API Reference

The API interfaces in this project are based on [chaunsin/netease-cloud-music](https://github.com/chaunsin/netease-cloud-music).

## Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd ncm-cli

# Install with pip
pip install -e .

# Or install with all dependencies
pip install -e ".[dev]"
```

## Usage

### Search for Songs

```bash
# Basic search
ncm search "周杰伦"

# Search with more results
ncm search "love song" --limit 50

# Pagination
ncm search "rock" --page 2

# Output as JSON
ncm search "周杰伦" --json
```

### Download Songs

```bash
# Download a single song (320kbps by default)
ncm download 1234567

# Download multiple songs
ncm download 1234567 5678901 9012345

# Download with specific quality
ncm download 1234567 -q lossless    # FLAC
ncm download 1234567 -q hires       # Hi-Res FLAC
ncm download 1234567 -q standard    # 128kbps MP3

# Specify output directory
ncm download 1234567 -o ./my-music

# Custom filename format
ncm download 1234567 -F "{title} - {artist}"
```

### Download Playlist

```bash
# Download entire playlist
ncm playlist 123456789

# Preview playlist without downloading
ncm playlist 123456789 --list-only

# Download with high quality
ncm playlist 123456789 -q lossless
```

### Download Album

```bash
# Download entire album
ncm album 12345678

# Preview album tracks
ncm album 12345678 --list-only
```

### Get Lyrics

```bash
# Get song lyrics
ncm lyric 1234567

# Include translated lyrics
ncm lyric 1234567 --translated

# Save to file
ncm lyric 1234567 -s lyrics.lrc
```

### Get Song Information

```bash
# Get song details
ncm info 1234567

# Multiple songs as JSON
ncm info 1234567 5678901 --json
```

### Discover New Music

```bash
# Get new releases
ncm new

# Filter by region
ncm new --area chinese
ncm new --area western
ncm new --area japanese
ncm new --area korean
```

### User Features (Requires Login)

```bash
# Get daily recommendations
ncm recommend

# Show user info
ncm me
```

## Quality Levels

| Level | Format | Bitrate | Description |
|-------|--------|---------|-------------|
| `standard` | MP3 | 128kbps | Standard quality |
| `higher` | MP3 | 192kbps | Higher quality |
| `exhigh` | MP3 | 320kbps | HQ (High Quality) |
| `lossless` | FLAC | ~1000kbps | SQ (Super Quality) |
| `hires` | FLAC | - | Hi-Res |

## Login & Authentication

### Cookie Login

```bash
# Login with MUSIC_U cookie value
ncm login --cookie "your_music_u_value"

# Or with full cookie string
ncm login -c "MUSIC_U=xxxxx; ..."

# Or set environment variable
export NCM_COOKIE="MUSIC_U=xxxxx"
```

### How to Get Your Cookie

1. Open [music.163.com](https://music.163.com) in your browser
2. Log in to your account
3. Press `F12` to open Developer Tools
4. Go to **Application** (Chrome) or **Storage** (Firefox) tab
5. Find **Cookies** → **music.163.com**
6. Copy the **MUSIC_U** cookie value

### Check Login Status

```bash
# Show current user info
ncm me

# Logout
ncm logout
```

## Project Structure

```
src/
└── ncm/
    ├── __init__.py      # Package initialization
    ├── cli.py           # CLI interface (Click)
    ├── client.py        # API client
    ├── crypto.py        # Encryption utilities
    ├── downloader.py    # Download manager
    └── models.py        # Data models
```

## License

MIT License
