import logging
import threading
import os
from dotenv import load_dotenv
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from ncm.cli import NCMClient
from ncm.downloader import Downloader  # 确保你的项目结构可以导入
from ncm.models import SongUrl

# --- 配置 ---
DOWNLOAD_DIR = "downloaded_music"
SERVER_IP = "192.168.2.99"  # 替换为你的服务器实际 IP
SERVER_PORT = 5000
# 使用你的 Cookie
load_dotenv()  # 加载 .env 文件
COOKIE_DATA = os.getenv("NCM_COOKIE")

# 初始化 Flask
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 初始化 NCM 客户端和下载器
try:
    client = NCMClient(cookie=COOKIE_DATA)
    # 验证一下用户信息
    user_info = client.get_user_info()
    if user_info and user_info.get('code') == 200 and user_info.get('profile'):
        logger.info(f"登录成功: {user_info['profile']['nickname']} (UID: {user_info['profile']['userId']})")
    else:
        logger.warning("Cookie 可能已过期或无效，部分功能可能受限。")
    # 下载模板为仅使用 ID，方便后续检索
    downloader = Downloader(
        client,
        output_dir=DOWNLOAD_DIR,
        filename_template="{id}",
        quality="exhigh"
    )
    logger.info("NCM Client and Downloader initialized.")
except Exception as e:
    logger.error(f"Initialization failed: {e}")


# --- 辅助函数 ---
def serialize(obj):
    """
    尝试将 NCM 对象转换为字典，以便 jsonify 处理。
    NCMClient 返回的对象通常是 Python 对象，直接 JSON 序列化会失败。
    """
    if obj is None:
        return None
    if isinstance(obj, list):
        return [serialize(i) for i in obj]
    if hasattr(obj, '__dict__'):
        return {k: serialize(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
    return obj


def start_background_download(song_ids):
    """后台线程下载歌曲"""

    def run():
        logger.info(f"Starting background download for {len(song_ids)} songs...")
        # 转换 ID 为 int 列表
        ids = [int(sid) for sid in song_ids]
        downloader.download_songs(ids, show_progress=False)
        logger.info("Background download task finished.")

    threading.Thread(target=run, daemon=True).start()


def find_local_file(song_id):
    """在下载目录寻找对应的文件 (支持 mp3 和 flac)"""
    for ext in ['mp3', 'flac']:
        file_path = Path(DOWNLOAD_DIR) / f"{song_id}.{ext}"
        if file_path.exists():
            return f"{song_id}.{ext}"
    return None


 --- 路由接口 ---
@app.route('/stream/<filename>')
def serve_downloaded_file(filename):
    """供播放器下载/流式播放本地文件的接口"""
    return send_from_directory(DOWNLOAD_DIR, filename)


@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "running",
        "endpoints": {
            "/search": "参数: q (关键词), limit (数量, 默认30)",
            "/song/url": "参数: id (歌曲ID), level (standard/exhigh/lossless/hires, 默认lossless)",
            "/song/detail": "参数: id (歌曲ID，可多个用逗号分隔)",
            "/user/info": "获取当前 Cookie 对应的用户信息"
        }
    })


@app.route('/search', methods=['GET'])
def search_song():
    """
    搜索歌曲
    示例: /search?q=周杰伦&limit=5
    """
    keyword = request.args.get('q')
    limit = int(request.args.get('limit', 30))

    if not keyword:
        return jsonify({"code": 400, "error": "缺少关键词 'q'"}), 400

    try:
        # 默认搜索类型为 1 (歌曲)
        result = client.search(keyword, limit=limit)
        return jsonify({"code": 200, "data": serialize(result)})
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return jsonify({"code": 500, "error": str(e)}), 500


@app.route('/song/url', methods=['GET'])
def get_song_url():
    """
    获取歌曲下载/播放链接
    示例: /song/url?id=210049&level=lossless
    """
    song_id = request.args.get('id')
    level = request.args.get('level', 'exhigh')

    if not song_id:
        return jsonify({"code": 400, "error": "Missing id"}), 400

    # 1. 检查本地是否存在
    local_filename = find_local_file(song_id)
    if local_filename:
        local_url = f"http://{SERVER_IP}:{SERVER_PORT}/stream/{local_filename}"
        logger.info(f"Serving local file for song {song_id}")
        # 构造一个符合 SongUrl 模型的返回格式
        return jsonify({
            "code": 200,
            "data": [{
                "id": int(song_id),
                "url": local_url,
                "local": True
            }]
        })

    # 2. 本地没有，走原逻辑
    try:
        url_info = client.get_song_url_eapi([int(song_id)], level=level)
        if not url_info or not url_info[0].url:
            # 如果 EAPI 失败，尝试普通接口
            url_info = client.get_song_url([int(song_id)], level=level)

        if not url_info:
            return jsonify({"code": 404, "error": "URL not found"}), 404

        return jsonify({"code": 200, "data": serialize(url_info)})
    except Exception as e:
        logger.error(f"获取链接失败: {e}")
        return jsonify({"code": 500, "error": str(e)}), 500


@app.route('/song/detail', methods=['GET'])
def get_song_detail():
    """
    获取歌曲详情
    示例: /song/detail?id=210049
    """
    song_ids_str = request.args.get('id')
    if not song_ids_str:
        return jsonify({"code": 400, "error": "缺少歌曲ID 'id'"}), 400

    try:
        # 支持传入多个 ID，逗号分隔
        song_ids = [int(x) for x in song_ids_str.split(',')]
        details = client.get_song_detail(song_ids)
        return jsonify({"code": 200, "data": serialize(details)})
    except Exception as e:
        logger.error(f"获取详情失败: {e}")
        return jsonify({"code": 500, "error": str(e)}), 500


@app.route('/personalFM', methods=['GET'])
def get_personal_fm_v2():
    """
    获取personal FM
    """
    try:
        songs = client.get_personal_fm()
        start_background_download([s.id for s in songs])

        response = []
        for song in songs:
            response.append({
                "id": str(song.id),
                "title": song.name,
                "artist": song.artist_names,
                "duration": int(song.duration / 1000),
                "url": ""
            })
        return jsonify(response)
    except Exception as e:
        return jsonify({"code": 500, "error": str(e)}), 500


@app.route('/redHeart', methods=['GET'])
def get_red_heart_songs():
    """
    获取personal FM
    """
    try:
        start = request.args.get('start')
        limit = int(request.args.get('limit', 10))

        response = []
        play_list = client.get_red_heart_playlist()
        if play_list and play_list.id:
            songs = client.get_playlist_tracks(play_list.id)
            for song in songs:
                response.append(
                    {
                        "id": str(song.id),
                        "title": song.name,
                        "artist": song.artist_names,
                        "duration": int(song.duration/1000),
                        "url": ""
                    }
                )
        response = response[start: start+limit]
        return jsonify(response)
    except Exception as e:
        return jsonify({"code": 500, "error": str(e)}), 500

@app.route('/playList', methods=['GET'])
def get_play_list_songs():
    try:
        _id = request.args.get('id', "FM")
        start = int(request.args.get('start', 0))
        limit = int(request.args.get('limit', 10))

        if _id.upper() == "REDHEART":
            pl = client.get_red_heart_playlist()
            songs = client.get_playlist_tracks(pl.id) if pl else []
        elif _id.isnumeric():
            songs = client.get_playlist_tracks(int(_id))
        else:
            songs = client.get_personal_fm()
            start = 0

        # 分页
        paged_songs = songs[start: start + limit]

        # 触发异步下载任务
        song_ids = [s.id for s in paged_songs]
        start_background_download(song_ids)

        response = []
        for song in paged_songs:
            response.append({
                "id": str(song.id),
                "title": song.name,
                "artist": song.artist_names,
                "duration": int(song.duration / 1000),
                "url": ""  # 客户端会再次请求 /song/url 获取
            })
        return jsonify(response)
    except Exception as e:
        return jsonify({"code": 500, "error": str(e)}), 500


@app.route('/user/info', methods=['GET'])
def user_info():
    """
    获取当前登录用户信息
    """
    try:
        info = client.get_user_info()
        return jsonify(info)
    except Exception as e:
        return jsonify({"code": 500, "error": str(e)}), 500


if __name__ == '__main__':
    # 确保下载目录存在
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    # 启动服务器，默认端口 5000
    print("服务已启动: http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=False)
