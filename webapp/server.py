"""Local-only browser interface for the question teacher CLI."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
UPLOADS = ROOT / "work" / "web-uploads"
TOOL = ROOT / "agent" / "teacher.py"
MAX_UPLOAD = 100 * 1024 * 1024
ALLOWED = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}
JOBS: dict[str, dict] = {}
UPLOAD_IDS: dict[str, Path] = {}
LOCK = threading.Lock()


def positive(value, default=None):
    if value in (None, ""):
        return default
    number = int(value)
    if not 1 <= number <= 1000:
        raise ValueError("数值须在 1 到 1000 之间")
    return number


def upload_path(upload_id: str, suffixes=ALLOWED) -> Path:
    with LOCK:
        path = UPLOAD_IDS.get(upload_id)
    if not path or not path.is_file() or path.suffix.lower() not in suffixes:
        raise ValueError("上传文件已失效或格式不受支持")
    return path


def command_for(data: dict) -> list[str]:
    action = data.get("action")
    cmd = [sys.executable, str(TOOL), action]
    level = data.get("level")
    if level and level not in ("简单", "中等", "较难", "拓展"):
        raise ValueError("难度选项无效")
    if action == "quiz":
        topic = str(data.get("topic", "")).strip()
        if not topic:
            raise ValueError("请填写知识点")
        cmd += [topic, "--count", str(positive(data.get("count"), 1)), "--level", level or "中等"]
        if data.get("book"):
            cmd += ["--book", str(data["book"]).strip()]
        if data.get("questions_only"):
            cmd.append("--questions-only")
    elif action == "mistake":
        question = str(data.get("question", "")).strip()
        file_ids = data.get("files") or []
        if not question and not file_ids:
            raise ValueError("请填写错题或上传图片/PDF")
        if question:
            cmd += ["--question", question]
        if data.get("work"):
            cmd += ["--work", str(data["work"]).strip()]
        cmd += ["--count", str(positive(data.get("count"), 1))]
        if level:
            cmd += ["--level", level]
        if data.get("show_answers"):
            cmd.append("--show-answers")
        for upload_id in file_ids:
            path = upload_path(str(upload_id))
            cmd += (["--image", str(path)] if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                    else ["--file", str(path)])
    elif action == "paper":
        grade = str(data.get("grade", "")).strip()
        file_ids = data.get("files") or []
        if not grade and not file_ids:
            raise ValueError("请填写年级或上传参考卷")
        for key, flag in (("grade", "--grade"), ("scope", "--scope"), ("title", "--title")):
            if data.get(key): cmd += [flag, str(data[key]).strip()]
        for key, flag in (("question_count", "--question-count"), ("total_score", "--total-score"),
                          ("duration", "--duration")):
            if data.get(key): cmd += [flag, str(positive(data[key]))]
        if level: cmd += ["--level", level]
        if data.get("questions_only"): cmd.append("--questions-only")
        for upload_id in file_ids:
            cmd += ["--reference", str(upload_path(str(upload_id)))]
    elif action == "ingest":
        file_ids = data.get("files") or []
        if len(file_ids) != 1:
            raise ValueError("每次选择一份资料入库")
        kind = data.get("kind")
        if kind not in ("教材", "试卷"):
            raise ValueError("请选择教材或试卷")
        cmd += [str(upload_path(str(file_ids[0]))), "--kind", kind,
                "--scope", "目录与题型" if data.get("scope") == "目录与题型" else "全量"]
        if data.get("edition"): cmd += ["--edition", str(data["edition"]).strip()]
    else:
        raise ValueError("功能类型无效")
    return cmd


def run_job(job_id: str, cmd: list[str]) -> None:
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=1800,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        answer = result.stdout.split("Reading additional input from stdin...", 1)[0].strip()
        if result.returncode != 0:
            answer = (answer + "\n" + result.stderr[-5000:]).strip()
        with LOCK:
            JOBS[job_id].update(status="done" if result.returncode == 0 else "error",
                                output=answer[-200000:],
                                exit_code=result.returncode)
    except subprocess.TimeoutExpired:
        with LOCK:
            JOBS[job_id].update(status="error", output="处理超过 30 分钟，请检查资料库进度后重试。")
    except Exception as exc:
        with LOCK:
            JOBS[job_id].update(status="error", output=str(exc))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[web] {fmt % args}")

    def reply(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            registry = json.loads((ROOT / "library/data/source-register.json").read_text(encoding="utf-8"))
            items = sum(bool(line.strip()) for line in (ROOT / "library/data/question-bank.jsonl").open(encoding="utf-8"))
            collection = ROOT / "library/data/exam-index/shanghai-2026-mock2.json"
            exams = len(json.loads(collection.read_text(encoding="utf-8")).get("districts", [])) if collection.exists() else 0
            catalogs = []
            for file in (ROOT / "library/data/catalogs").glob("*.json"):
                catalog = json.loads(file.read_text(encoding="utf-8"))
                for chapter in catalog.get("chapters", []):
                    for section in chapter.get("sections", []):
                        catalogs.append({"id": section["id"], "title": section["title"]})
            self.reply(200, {"sources": len(registry["sources"]), "items": items,
                             "districts": exams, "sections": catalogs})
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with LOCK: job = JOBS.get(job_id)
            self.reply(200, job.copy()) if job else self.reply(404, {"error": "任务不存在"})
            return
        file = HERE / ("index.html" if path == "/" else path.lstrip("/"))
        if file.parent != HERE or not file.is_file() or file.name not in {"index.html", "app.js", "style.css"}:
            self.send_error(404); return
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_UPLOAD: raise ValueError("文件须小于 100 MB")
                name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
                suffix = Path(name).suffix.lower()
                if suffix not in ALLOWED: raise ValueError("支持 PDF、DOCX、PNG、JPG 和 WEBP")
                UPLOADS.mkdir(parents=True, exist_ok=True)
                upload_id = uuid.uuid4().hex
                target = UPLOADS / f"{upload_id}{suffix}"
                with target.open("wb") as stream:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk: raise ValueError("上传中断")
                        stream.write(chunk); remaining -= len(chunk)
                with LOCK: UPLOAD_IDS[upload_id] = target
                self.reply(200, {"id": upload_id, "name": Path(name).name, "size": size})
                return
            if path == "/api/run":
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size < 65536: raise ValueError("请求过大")
                data = json.loads(self.rfile.read(size))
                cmd = command_for(data)
                if not shutil.which("codex"): raise ValueError("未找到 Codex CLI")
                job_id = uuid.uuid4().hex
                with LOCK: JOBS[job_id] = {"id": job_id, "status": "running", "output": ""}
                threading.Thread(target=run_job, args=(job_id, cmd), daemon=True).start()
                self.reply(202, {"id": job_id})
                return
            self.send_error(404)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.reply(400, {"error": str(exc)})


if __name__ == "__main__":
    host, port = "127.0.0.1", int(os.environ.get("QUESTION_TEACHER_WEB_PORT", "8765"))
    print(f"出题老师网页：http://{host}:{port}/", flush=True)
    server = ThreadingHTTPServer((host, port), Handler)
    if not os.environ.get("QUESTION_TEACHER_NO_BROWSER"):
        threading.Timer(0.4, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
    server.serve_forever()
