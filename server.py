import logging
import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from ncm.cli import NCMClient

# 初始化 Flask 应用
from ncm.models import SongUrl

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 配置部分 ---
# 使用你提供的 Cookie 字符串
load_dotenv()  # 加载 .env 文件
COOKIE_DATA = os.getenv("NCM_COOKIE")

# 初始化 NCM 客户端
try:
    client = NCMClient(cookie=COOKIE_DATA)
    # 验证一下用户信息
    user_info = client.get_user_info()
    if user_info and user_info.get('code') == 200 and user_info.get('profile'):
        logger.info(f"登录成功: {user_info['profile']['nickname']} (UID: {user_info['profile']['userId']})")
    else:
        logger.warning("Cookie 可能已过期或无效，部分功能可能受限。")
except Exception as e:
    logger.error(f"客户端初始化失败: {e}")


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


# --- 路由接口 ---

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
    level = request.args.get('level', 'lossless')  # standard, higher, exhigh, lossless, hires

    if not song_id:
        return jsonify({"code": 400, "error": "缺少歌曲ID 'id'"}), 400

    try:
        # 注意：get_download_url 接收 int，但 eapi 可能效果更好
        # 这里优先尝试 eapi 接口，因为它通常对 VIP 歌曲支持更好
        url_info = client.get_song_url_eapi([int(song_id)], level=level)

        if not url_info:
            # 如果 EAPI 失败，尝试普通接口
            url_info = client.get_song_url([int(song_id)], level=level)

        if not url_info:
            return jsonify({"code": 404, "error": "无法获取链接或无权访问"}), 404

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
def get_personal_fm():
    """
    获取personal FM
    """
    try:
        personal_fm_songs = client.get_personal_fm()
        response = []
        for song in personal_fm_songs:
            song_url = client.get_song_url_eapi([song.id])
            if isinstance(song_url, list) and len(song_url) > 0 and isinstance(song_url[0], SongUrl) and song_url[0].url:
                response.append(
                    {
                        "id": str(song.id),
                        "title": song.name,
                        "artist": song.artist_names,
                        "duration": int(song.duration/1000),
                        "url": song_url[0].url
                    }
                )
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
    """
    获取personal FM
    """
    try:
        _id = request.args.get('id', "")
        try:
            start = int(request.args.get('start', 0))
        except ValueError:
            start = 0
        try:
            limit = int(request.args.get('limit', 10))
        except ValueError:
            limit = 10

        if _id == "":
            _id = "FM"

        response = []

        if _id.upper() == "REDHEART":
            play_list = client.get_red_heart_playlist()
            if play_list and play_list.id:
                songs = client.get_playlist_tracks(play_list.id)
        elif _id.isnumeric():
            songs = client.get_playlist_tracks(int(_id))
        else:  # FM or other
            songs = client.get_personal_fm()
            start = 0

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
    # 启动服务器，默认端口 5000
    print("服务已启动: http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
