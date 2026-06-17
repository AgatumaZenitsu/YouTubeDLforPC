from flask import Flask, request, send_file, send_from_directory, jsonify
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import shutil
import threading
from datetime import datetime

app = Flask(__name__, static_folder="static")
CORS(app)

# グローバルダウンロード状態
download_state = {
    "status": "ready",
    "logs": [],
    "progress": 0,
    "title": "",
    "error": None
}

def log_message(message):
    """ログを記録"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    download_state["logs"].append(log_entry)
    print(log_entry)
    # 最新100件のログのみ保持
    if len(download_state["logs"]) > 100:
        download_state["logs"] = download_state["logs"][-100:]

def progress_hook(d):
    """yt_dlpのプログレス情報"""
    if d['status'] == 'downloading':
        total = d.get('total_bytes', 0)
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            download_state["progress"] = int((downloaded / total) * 100)
        log_message(f"ダウンロード中... {download_state['progress']}%")
    elif d['status'] == 'finished':
        log_message("ダウンロード完了、処理中...")
        download_state["progress"] = 100


def get_local_cookie_file():
    """ローカルの cookies.txt を返す"""
    cookie_file = os.path.join(os.getcwd(), "cookies.txt")
    if os.path.isfile(cookie_file) and os.path.getsize(cookie_file) > 0:
        return cookie_file
    return None


def create_cookiefile_from_env(temp_dir):
    """YOUTUBE_COOKIES 環境変数から一時 cookie ファイルを作成"""
    env_cookie = os.environ.get("YOUTUBE_COOKIES", "")
    if not env_cookie or not env_cookie.strip():
        return None

    # Render の環境変数に貼り付けたときに \n がエスケープされる場合にも対応
    env_cookie = env_cookie.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    cookie_file = os.path.join(temp_dir, "cookies.txt")
    with open(cookie_file, "w", encoding="utf-8") as f:
        f.write(env_cookie)
    return cookie_file


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/status", methods=["GET"])
def get_status():
    """ダウンロード状態を取得"""
    return jsonify(download_state)

@app.route("/download", methods=["GET", "POST"])
def download():
    """ダウンロード処理"""
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = request.form.to_dict()
    else:
        data = request.args.to_dict()

    url = data.get("url")
    type_ = data.get("type", "audio")

    log_message(f"リクエスト受信: method={request.method}, url={url}, type={type_}, args={request.args.to_dict()}, form={request.form.to_dict()}")

    if not url:
        download_state["error"] = "URLが入力されていません"
        download_state["status"] = "error"
        log_message("リクエストに URL がありません")
        return jsonify({"error": "URL is required"}), 400

    download_state["status"] = "downloading"
    download_state["logs"] = []
    download_state["progress"] = 0
    download_state["error"] = None
    log_message(f"ダウンロード開始: {type_} モード")

    temp_dir = tempfile.mkdtemp()

    try:
        # environment variable cookies and local cookies.txt
        cookie_file = create_cookiefile_from_env(temp_dir) or get_local_cookie_file()
        cookie_options = {"quiet": True, "js_runtime": "node"}
        if cookie_file:
            cookie_options["cookiefile"] = cookie_file
            log_message(f"Cookieファイル使用: {cookie_file}")
        else:
            log_message("Cookieファイル未検出: YOUTUBE_COOKIES または cookies.txt が必要な場合があります")

        # タイトル取得（事前情報取得）
        log_message("ビデオ情報を取得中...")
        with yt_dlp.YoutubeDL(cookie_options) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "downloaded").replace("/", "_").replace("\\", "_")
            download_state["title"] = title
            log_message(f"タイトル: {title}")

        if type_ == "audio":
            output_path = os.path.join(temp_dir, f"{title}.%(ext)s")
            ydl_opts = {
                "format": "bestaudio",
                "outtmpl": output_path,
                "quiet": True,
                "progress_hooks": [progress_hook],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "js_runtime": "node",
            }
            target_file = os.path.join(temp_dir, f"{title}.mp3")
            log_message("音声ファイル形式: MP3")

        else:  # type == video
            output_path = os.path.join(temp_dir, f"{title}.%(ext)s")
            ydl_opts = {
                "format": "bestvideo+bestaudio/best",
                "outtmpl": output_path,
                "quiet": True,
                "progress_hooks": [progress_hook],
                "merge_output_format": "mp4",
                "js_runtime": "node",
            }
            target_file = os.path.join(temp_dir, f"{title}.mp4")
            log_message("動画ファイル形式: MP4")

        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        log_message("処理完了、ファイルを送信中...")
        download_state["status"] = "completed"
        download_state["progress"] = 100
        
        return send_file(target_file, as_attachment=True)

    except Exception as e:
        error_msg = str(e)
        if "Sign in to confirm you\'re not a bot" in error_msg or "cookies-from-browser" in error_msg or "--cookies" in error_msg:
            error_msg = (
                "YouTubeのアクセス制限によりダウンロードできませんでした。"
                " cookies.txt を使った認証が必要な場合があります。"
                " 自分のYouTubeクッキーを cookies.txt に保存し、再デプロイしてください。"
            )
        log_message(f"エラー: {error_msg}")
        download_state["error"] = error_msg
        download_state["status"] = "error"
        return jsonify({"error": error_msg}), 500

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
