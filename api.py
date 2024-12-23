from flask import Flask, request, jsonify, send_file, send_from_directory, url_for
import subprocess
import os
import shutil
import uuid
import zipfile
import threading
import logging

app = Flask(__name__)

# 设置工作目录和临时文件路径
TOOLKIT_WORKDIR = "/home/zhanghao83/app/toolkit_service/app/toolkit"
TOOLKIT_TMP_DIR = "/home/zhanghao83/tmp/toolkit/"
TOOLKIT_LOG_FILE = os.path.join(TOOLKIT_TMP_DIR, "toolkit.log")
RECORDER_WORKDIR = "/home/zhanghao83/app/toolkit_service/app/recorder"
RECORDER_TMP_DIR = "/home/zhanghao83/tmp/recorder/"
RECORDER_LOG_FILE = os.path.join(RECORDER_TMP_DIR, "extract.log")

os.makedirs(TOOLKIT_TMP_DIR, exist_ok=True)
os.makedirs(RECORDER_TMP_DIR, exist_ok=True)

# 存储转换任务状态和文件路径
tasks = {}
tasks_lock = threading.Lock()

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@app.route("/")
def index():
    return send_file("static/index.html")

def convert_toolkit_file(task_id, input_path, conversion_mode, output_path):
    try:
        command = ["sh", "run_toolkit.sh", f"-{conversion_mode}", input_path, output_path]
        with open(TOOLKIT_LOG_FILE, "a") as toolkit_log_file:
            subprocess.run(
                command,
                cwd=TOOLKIT_WORKDIR,
                check=True,
                stdout=toolkit_log_file,
                stderr=subprocess.STDOUT,
                text=True
            )
        if not os.path.exists(output_path):
            with tasks_lock:
                tasks[task_id]["status"] = "failed"
                tasks[task_id]["error"] = "Output file generation failed."
            return

        zip_path = os.path.join(TOOLKIT_TMP_DIR, f"{task_id}.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(output_path, os.path.basename(output_path))
            zipf.write(TOOLKIT_LOG_FILE, os.path.basename(TOOLKIT_LOG_FILE))

        with tasks_lock:
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["file"] = zip_path
    except Exception as e:
        with tasks_lock:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)
        logging.error(f"Error in task {task_id}: {e}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)

@app.route("/upload", methods=["POST"])
def upload_file():
    input_file = request.files.get("input_file")
    conversion_mode = request.form.get("conversion_mode")

    if not input_file or not conversion_mode:
        return jsonify({"error": "File and conversion mode are required."}), 400

    task_id = str(uuid.uuid4())
    input_path = os.path.join(TOOLKIT_TMP_DIR, f"input_{task_id}.sq3")
    output_path = os.path.join(TOOLKIT_TMP_DIR, f"output_{task_id}.sq3")

    input_file.save(input_path)
    with tasks_lock:
        tasks[task_id] = {"status": "processing"}

    thread = threading.Thread(target=convert_toolkit_file, args=(task_id, input_path, conversion_mode, output_path))
    thread.start()

    return jsonify({"task_id": task_id, "status_url": url_for('check_status', task_id=task_id, _external=True)})

@app.route("/status/<task_id>", methods=["GET"])
def check_status(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found."}), 404

    if task["status"] == "completed":
        return jsonify({"status": "completed", "download_url": url_for('download_file', task_id=task_id, _external=True)})
    elif task["status"] == "failed":
        return jsonify({"status": "failed", "error": task.get("error")})
    else:
        return jsonify({"status": "processing"})

@app.route("/download/<task_id>", methods=["GET"])
def download_file(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
    if not task or task["status"] != "completed":
        return jsonify({"error": "Task not ready or not found."}), 404

    return send_file(task["file"], as_attachment=True, download_name=f"{task_id}.zip")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)