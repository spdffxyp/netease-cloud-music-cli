import logging
import threading
import os
import glob
from urllib.parse import quote
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from ncm.cli import NCMClient
from ncm.downloader import Downloader
from ncm.models import SongUrl

# --- 配置 ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloaded_music")
DB_PATH = os.path.join(BASE_DIR, "music.db")
SERVER_IP = "192.168.2.99"  # 替换为你的服务器实际 IP
SERVER_PORT = 5000
# 使用你的 Cookie
load_dotenv()  # 加载 .env 文件
COOKIE_DATA = os.getenv("NCM_COOKIE")

# --- 初始化 Flask 和 数据库 ---
app = Flask(__name__)
# 配置数据库 (使用 SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 数据库模型 ---
class Music(db.Model):
    __tablename__ = 'music'
    id = db.Column(db.Integer, primary_key=True)  # 歌曲 ID
    source = db.Column(db.Integer)  # 歌曲源， unkonwn:0, netease:1
    title = db.Column(db.String(255))
    artist = db.Column(db.String(255))
    file_path = db.Column(db.String(1024))  # 相对 DOWNLOAD_DIR 的文件名
    file_size = db.Column(db.Integer, default=0)
    downloaded = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    # 0: 未下载 (Pending)
    # 1: 下载中 (Downloading)
    # 2: 已完成 (Completed)
    status = db.Column(db.Integer)

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "artist": self.artist,
            "file_path": self.file_path,
            "downloaded": self.downloaded,
            "status": self.status
        }

# --- 初始化 NCM 客户端 ---
try:
    client = NCMClient(cookie=COOKIE_DATA)
    user_info = client.get_user_info()
    if user_info and user_info.get('code') == 200 and user_info.get('profile'):
        logger.info(f"登录成功: {user_info['profile']['nickname']} (UID: {user_info['profile']['userId']})")
    else:
        logger.warning("Cookie 可能已过期或无效。")
    
    downloader = Downloader(
        client,
        output_dir=DOWNLOAD_DIR,
        filename_template="netease - {artist} - {title} - {id}",  # 保持文件名只用ID，方便数据库映射
        quality="exhigh"
    )
    logger.info("NCM Client initialized.")
except Exception as e:
    logger.error(f"Initialization failed: {e}")
    client = None
    downloader = None


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


def sync_local_files_to_db():
    """
    启动时运行：扫描本地目录，将数据库中不存在但本地存在的文件入库
    """
    logger.info("Syncing local files to database...")
    # 支持的扩展名
    exts = ['*.mp3', '*.flac']
    found_files = []
    for ext in exts:
        found_files.extend(glob.glob(os.path.join(DOWNLOAD_DIR, ext)))
    
    with app.app_context():
        count = 0
        for file_abs_path in found_files:
            filename = os.path.basename(file_abs_path)
            # 假设文件名格式是 * - {id}.ext
            try:
                song_id = os.path.splitext(filename)[0].split(' - ')
                song_id = int(song_id[-1])
            except ValueError:
                continue  # 跳过不符合命名规则的文件

            # 检查数据库是否已存在
            if not Music.query.get(song_id):
                # 如果没有元数据，尝试从 NCM 获取一下简单的详情，或者暂时留空
                file_size = os.path.getsize(file_abs_path)
                new_music = Music(
                    id=song_id,
                    source=1,  # 当前已存在的文件都是netease
                    title=f"Unknown-{song_id}",  # 如果本地有文件但没库，暂时给个默认名，或者在这里调用API获取详情
                    file_path=filename,
                    file_size=file_size,
                    downloaded=True,
                    status=2
                )
                db.session.add(new_music)
                count += 1
        
        if count > 0:
            db.session.commit()
            logger.info(f"Synced {count} local files to database.")
        else:
            logger.info("Database is up to date.")


def get_file_extension(song_id):
    """辅助检查文件实际扩展名"""
    for ext in ['flac', 'mp3']:
        if os.path.exists(os.path.join(DOWNLOAD_DIR, f"{song_id}.{ext}")):
            return ext
    return None


def start_background_download(song_ids):
    """后台线程下载歌曲并更新数据库"""
    
    # 过滤掉已经是 downloaded=True 的歌曲
    # 注意：这里需要 app context 才能查库
    to_download = []
    with app.app_context():
        for sid in song_ids:
            sid = int(sid)
            record = Music.query.get(sid)

            try:
                if not record:
                # 如果没有记录，创建一个“下载中”的占位记录
                    new_record = Music(id=sid, status=1, downloaded=False)
                    db.session.add(new_record)
                    db.session.commit()
                    to_download.append(sid)
                elif record.downloaded is False and record.status != 1:
                    # 如果记录存在但未下载且没在下载中，抢占状态
                    record.status = 1
                    db.session.commit()
                    to_download.append(sid)
                else:
                    # 已下载或正在下载中，跳过
                    continue
            except Exception as e:
                # 如果 commit 失败，说明另一个进程抢先创建了
                db.session.rollback()
                logger.error(f"Failed to preempt song {sid} in DB: {e}")
    
    if not to_download:
        return

    # 定义线程运行函数
    def run(app_instance, ids_to_dl):
        logger.info(f"Starting background download for {len(ids_to_dl)} songs...")
        # 获取这批歌曲的详情信息，以便存入数据库
        try:
            details = client.get_song_detail(ids_to_dl)
            detail_map = {d.id: d for d in details}
        except Exception as e:
            logger.error(f"get song details error: {e}")
            detail_map = {}

        ids_to_dl = [i for i in detail_map]
        results = {}
        for sid in ids_to_dl:
            full_path = None
            # 1. 下载 (NCM downloader 负责写文件)
            try:
                # Downloader 可能会抛出异常，需要捕获以免线程崩溃
                logger.info(f"Starting background download for song: {sid}")
                full_path = downloader.download_song(sid, show_progress=False)
                # _results = downloader.download_songs(ids_to_dl, show_progress=False)
                results[sid] = full_path
            except Exception as e:
                logger.error(f"Download process error: {e}")

            try:
                if full_path:
                    # 2. 下载完成后，在应用上下文中更新数据库
                    with app_instance.app_context():
                        filename = os.path.basename(full_path)
                        if os.path.exists(os.path.join(DOWNLOAD_DIR, filename)):
                            full_path = os.path.join(DOWNLOAD_DIR, filename)
                            file_size = os.path.getsize(full_path)

                            # 获取歌曲信息
                            song_info = detail_map.get(sid)
                            title = song_info.name if song_info else f"Song-{sid}"
                            artist = song_info.artist_names if song_info else "Unknown"

                            # 更新或插入
                            music_record = Music.query.get(sid)
                            if not music_record:
                                music_record = Music(id=sid)

                            music_record.source = 1
                            music_record.title = title
                            music_record.artist = artist
                            music_record.file_path = str(filename)
                            music_record.file_size = file_size
                            music_record.downloaded = True
                            music_record.status = 2

                            db.session.add(music_record)

                            db.session.commit()
                            logger.info(f"Database updated for song: {sid}")
                else:
                    # 下载返回为空（可能版权限制或无链接）
                    logger.warning(f"Download returned empty path for song: {sid}")
                    # 这里会进入下面的 finally 处理 status 重置
            except Exception as e:
                logger.error(f"Thread execution error for song {sid}: {e}")
            finally:
                # 失败回退机制
                # 如果代码执行到这里，downloaded 依然是 False，说明失败了
                # 必须把 status 改回 0，否则这首歌会被永久“锁死”在下载中状态
                with app_instance.app_context():
                    final_check = Music.query.get(sid)
                    if final_check and not final_check.downloaded:
                        final_check.status = 0
                        db.session.commit()
                        logger.info(f"Reset status to 0 for failed song: {sid}")

        logger.info("Background download task finished.")

    # 传递 app 实例给线程，以便在线程内建立上下文
    threading.Thread(target=run, args=(app, to_download), daemon=True).start()


# --- 路由接口 ---
@app.route('/stream/<filename>')
def serve_downloaded_file(filename):
    """供播放器下载/流式播放本地文件的接口"""
    return send_from_directory(DOWNLOAD_DIR, filename)


@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "running",
        "db_status": "connected",
        "endpoints": {
            "/search": "参数: q (关键词), limit (数量, 默认30)",
            "/song/url": "参数: id (歌曲ID), level (standard/exhigh/lossless/hires, 默认lossless)",
            "/song/detail": "参数: id (歌曲ID，可多个用逗号分隔)",
            "/user/info": "获取当前 Cookie 对应的用户信息",
            "/library/list": "查看本地已下载的歌曲列表",
        }
    })


@app.route('/library/list', methods=['GET'])
def library_list():
    """查看数据库中已下载的歌曲"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('limit', 20))
    
    pagination = Music.query.filter_by(downloaded=True).order_by(Music.created_at.desc()).paginate(page=page, per_page=per_page)
    
    return jsonify({
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page,
        "data": [m.to_dict() for m in pagination.items]
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
        return jsonify({"code": 400, "error": "Missing 'q'"}), 400

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

    song_id_int = int(song_id)

    # 1. 优先查询数据库
    local_music = Music.query.filter_by(id=song_id_int, downloaded=True).first()
    
    # 双重检查：数据库说有，还得看文件是否真的还在
    if local_music and local_music.file_path:
        filename = os.path.basename(local_music.file_path)
        if os.path.exists(os.path.join(DOWNLOAD_DIR, filename)):
            safe_filename = quote(filename)
            local_url = f"http://{SERVER_IP}:{SERVER_PORT}/stream/{safe_filename}"
            logger.info(f"Hit database/cache for song {song_id}")
            # 构造一个符合 SongUrl 模型的返回格式
            return jsonify({
                "code": 200,
                "data": [{
                    "id": song_id_int,
                    "url": local_url,
                    "local": True,
                    "type": local_music.file_path.split('.')[-1]
                }]
            })

    # 2. 数据库没有或文件丢失，走网络请求
    try:
        url_info = client.get_song_url_eapi([song_id_int], level=level)
        if not url_info or not url_info[0].url:
            # 如果 EAPI 失败，尝试普通接口
            url_info = client.get_song_url([song_id_int], level=level)

        if not url_info:
            return jsonify({"code": 404, "error": "URL not found"}), 404

        # 如果请求了 URL，自动触发下载
        start_background_download([song_id_int])

        return jsonify({"code": 200, "data": serialize(url_info)})
    except Exception as e:
        logger.error(f"Get URL failed: {e}")
        return jsonify({"code": 500, "error": str(e)}), 500


@app.route('/song/detail', methods=['GET'])
def get_song_detail():
    """
    获取歌曲详情
    示例: /song/detail?id=210049
    """
    song_ids_str = request.args.get('id')
    if not song_ids_str:
        return jsonify({"code": 400, "error": "Missing id"}), 400

    try:
        # 支持传入多个 ID，逗号分隔
        song_ids = [int(x) for x in song_ids_str.split(',')]
        details = client.get_song_detail(song_ids)
        return jsonify({"code": 200, "data": serialize(details)})
    except Exception as e:
        logger.error(f"获取详情失败: {e}")
        return jsonify({"code": 500, "error": str(e)}), 500


# 通用的处理逻辑封装，用于 FM, RedHeart, Playlist
def process_song_list(songs, start=0, limit=10):
    paged_songs = songs[start: start + limit]
    
    # 触发异步下载
    song_ids = [s.id for s in paged_songs]
    start_background_download(song_ids)
    
    response = []
    for song in paged_songs:
        response.append({
            "id": str(song.id),
            "title": song.name,
            "artist": song.artist_names,
            "duration": int(song.duration / 1000),
            "url": ""
        })
    return response


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
        else: # FM or other
            songs = client.get_personal_fm()
            start = 0 # FM 通常没有分页概念，每次都是新的

        data = process_song_list(songs, start, limit)
        return jsonify(data)
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
    
    # 首次运行时创建数据库表
    with app.app_context():
        db.create_all()
    
    # 同步本地文件到数据库
    sync_local_files_to_db()

    print(f"Database initialized at: {DB_PATH}")
    print(f"Service running at: http://0.0.0.0:{SERVER_PORT}")
    
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=False)
