from flask import Flask, request, send_file, send_from_directory, jsonify, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import re
from threading import Lock

app = Flask(__name__, static_folder="static")
CORS(app)

# ダウンロード一時保存ディレクトリ（プロセス単位）
downloads_dir = Path(tempfile.gettempdir()) / "yt_downloader_files"
downloads_dir.mkdir(parents=True, exist_ok=True)

# グローバル状態（単一ジョブ互換）
download_state = {
    "status": "idle",
    "logs": [],
    "progress": 0,
    "title": "",
    "error": None,
    "file_path": None
}
_state_lock = Lock()


def safe_filename(name: str, maxlen: int = 200) -> str:
    """簡易ファイル名サニタイズ"""
    if not isinstance(name, str):
        name = str(name or "downloaded")
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', name)
    name = name.strip()
    if not name:
        name = "downloaded"
    return name[:maxlen]


def log_message(message: str):
    """ログを記録（スレッドセーフ）"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    with _state_lock:
        download_state["logs"].append(log_entry)
        if len(download_state["logs"]) > 100:
            download_state["logs"] = download_state["logs"][-100:]
    print(log_entry)


def progress_hook(d):
    """yt-dlp の進捗フック"""
    try:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            if total and total > 0:
                with _state_lock:
                    download_state["progress"] = int((downloaded / total) * 100)
        elif status == "finished":
            log_message("ダウンロード完了、エンコード処理中...")
            with _state_lock:
                download_state["progress"] = 100
    except Exception as e:
        log_message(f"progress_hook エラー: {e}")


def parse_netscape_cookie_file(cookie_path):
    """Netscape 形式 cookie ファイルを解析"""
    domains = {}
    names = set()
    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain = parts[0].lstrip(".")
                name = parts[5]
                domains.setdefault(domain, []).append(name)
                names.add(name)
    except Exception as e:
        log_message(f"Cookie 解析エラー: {e}")
    return domains, names


def log_cookie_summary(cookie_path, source):
    domains, names = parse_netscape_cookie_file(cookie_path)
    if not domains:
        log_message(f"⚠️ {source} の cookie が正しく読み取れませんでした。")
        return
    auth_names = {"SID", "SAPISID", "APISID", "HSID", "SSID", "SIDCC"}
    found_auth = sorted(names & auth_names)
    if found_auth:
        log_message(f"✅ 認証 cookie を検出しました: {', '.join(found_auth)}")
    else:
        log_message("⚠️ Google/YouTubeの認証 cookie が見つかりません。ログアウト状態の可能性があります。")


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status", methods=["GET"])
def get_status():
    """現在のダウンロード状態を返す"""
    with _state_lock:
        state_copy = dict(download_state)
        state_copy["logs"] = list(download_state["logs"])
    return jsonify(state_copy)


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json() or {}
    url = data.get("url") or request.args.get("url")
    type_ = data.get("type", "audio") or request.args.get("type", "audio")
    user_cookies = data.get("cookies")  # UIから送られたクッキー

    if not url:
        with _state_lock:
            download_state["error"] = "URLが入力されていません"
            download_state["status"] = "error"
        return jsonify({"error": "URL is required"}), 400

    # 初期化
    with _state_lock:
        download_state["status"] = "downloading"
        download_state["logs"] = []
        download_state["progress"] = 0
        download_state["error"] = None
        download_state["title"] = ""
        download_state["file_path"] = None

    log_message(f"ダウンロード開始: {type_} モード")

    temp_dir = tempfile.mkdtemp(dir=str(downloads_dir))
    cookiefile_path = None

    try:
        # 1. UIからのクッキー入力を最優先
        cookie_env = os.environ.get("YOUTUBE_COOKIES")
        if user_cookies and user_cookies.strip():
            cookiefile_path = os.path.join(temp_dir, "cookies.txt")
            with open(cookiefile_path, "w", encoding="utf-8") as f:
                f.write(user_cookies)
            log_message("UIから入力された Cookie を使用します")
            log_cookie_summary(cookiefile_path, "UI入力")
        
        # 2. 環境変数からのクッキー
        elif cookie_env:
            cookiefile_path = os.path.join(temp_dir, "cookies.txt")
            cookie_content = cookie_env.replace("\\n", "\n")
            with open(cookiefile_path, "w", encoding="utf-8") as f:
                f.write(cookie_content)
            log_message("環境変数(YOUTUBE_COOKIES)の Cookie を使用します")
            log_cookie_summary(cookiefile_path, "環境変数")

        # 共通の yt-dlp オプション (Bot対策ヘッダー等)
        base_ydl_opts = {
             "quiet": True,
             "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                }
             },
             "http_headers": {
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                 "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
             }
        }

        log_message("ビデオ情報を取得中...")
        ydl_info_opts = base_ydl_opts.copy()
        if cookiefile_path:
            ydl_info_opts["cookiefile"] = cookiefile_path
            
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title_raw = info.get("title", "downloaded")
            title = safe_filename(title_raw)
            with _state_lock:
                download_state["title"] = title
            log_message(f"タイトル: {title_raw}")

        ydl_opts = base_ydl_opts.copy()
        if type_ == "audio":
            output_path = os.path.join(temp_dir, f"{title}.%(ext)s")
            ydl_opts.update({
                "format": "bestaudio",
                "outtmpl": output_path,
                "noplaylist": True,
                "progress_hooks": [progress_hook],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            })
            target_file = os.path.join(temp_dir, f"{title}.mp3")
        else:
            output_path = os.path.join(temp_dir, f"{title}.%(ext)s")
            ydl_opts.update({
                "format": "best", # ←「一番良い画質のファイル」に条件を緩める
                "outtmpl": output_path,
                "noplaylist": True,
                "progress_hooks": [progress_hook],
                "merge_output_format": "mp4",
            })
            target_file = os.path.join(temp_dir, f"{title}.mp4")

        if cookiefile_path:
            ydl_opts["cookiefile"] = cookiefile_path

        log_message("ダウンロードを開始します...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        log_message("処理完了、ブラウザへ送信します")
        with _state_lock:
            download_state["status"] = "completed"
            download_state["progress"] = 100
            download_state["file_path"] = target_file

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                log_message("一時ファイルをクリーンアップしました")
            except Exception as e:
                log_message(f"クリーンアップ中にエラー: {e}")
            return response

        if not os.path.exists(target_file):
            raise FileNotFoundError(f"出力ファイルが見つかりません: {target_file}")

        return send_file(target_file, as_attachment=True)

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Sign in to confirm you" in error_msg:
            error_msg = "YouTubeのボット対策にブロックされました。最新の Cookie を入力欄に貼り付けて再試行してください。"
        log_message(f"エラー: {error_msg}")
        with _state_lock:
            download_state["error"] = error_msg
            download_state["status"] = "error"
        return jsonify({"error": error_msg}), 500

    except Exception as e:
        error_msg = str(e)
        log_message(f"予期せぬエラー: {error_msg}")
        with _state_lock:
            download_state["error"] = error_msg
            download_state["status"] = "error"
        return jsonify({"error": error_msg}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)