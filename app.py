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

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/status", methods=["GET"])
def get_status():
    """ダウンロード状態を取得"""
    return jsonify(download_state)

@app.route("/download", methods=["POST"])
def download():
    """ダウンロード処理"""
    data = request.get_json() or {}
    url = data.get("url") or request.args.get("url")
    type_ = data.get("type", "audio") or request.args.get("type", "audio")

    if not url:
        download_state["error"] = "URLが入力されていません"
        download_state["status"] = "error"
        return jsonify({"error": "URL is required"}), 400

    download_state["status"] = "downloading"
    download_state["logs"] = []
    download_state["progress"] = 0
    download_state["error"] = None
    log_message(f"ダウンロード開始: {type_} モード")

    temp_dir = tempfile.mkdtemp()

    try:
        # タイトル取得（事前情報取得）
        log_message("ビデオ情報を取得中...")
        with yt_dlp.YoutubeDL({"cookiefile": "cookies.txt", "quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "downloaded").replace("/", "_").replace("\\", "_")
            download_state["title"] = title
            log_message(f"タイトル: {title}")

        if type_ == "audio":
            output_path = os.path.join(temp_dir, f"{title}.%(ext)s")
            ydl_opts = {
                "format": "bestaudio",
                "outtmpl": output_path,
                "cookiefile": "cookies.txt",
                "quiet": True,
                "progress_hooks": [progress_hook],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            }
            target_file = os.path.join(temp_dir, f"{title}.mp3")
            log_message("音声ファイル形式: MP3")

        else:  # type == video
            output_path = os.path.join(temp_dir, f"{title}.%(ext)s")
            ydl_opts = {
                "format": "bestvideo+bestaudio/best",
                "outtmpl": output_path,
                "cookiefile": "cookies.txt",
                "quiet": True,
                "progress_hooks": [progress_hook],
                "merge_output_format": "mp4",
            }
            target_file = os.path.join(temp_dir, f"{title}.mp4")
            log_message("動画ファイル形式: MP4")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        log_message("処理完了、ファイルを送信中...")
        download_state["status"] = "completed"
        download_state["progress"] = 100
        
        return send_file(target_file, as_attachment=True)

    except Exception as e:
        error_msg = str(e)
        log_message(f"エラー: {error_msg}")
        download_state["error"] = error_msg
        download_state["status"] = "error"
        return jsonify({"error": error_msg}), 500

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
