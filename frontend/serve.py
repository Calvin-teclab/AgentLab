#!/usr/bin/env python3
"""
serve.py —— AgentLab 前端静态服务器(带"按需拉起后端"能力)

为什么不用 python -m http.server:
  纯静态服务器无法在"未连接"时帮你启动后端。这个版本在它之上加了一个
  本地接口 POST /__launch_backend:前端那个红色"未连接"徽标点一下,就让
  本进程用 subprocess 拉起 uvicorn。

  关键认知:浏览器里的 JS 无权启动本机进程(沙箱),但"负责发静态文件的
  这个 Python 进程"有权。前端服务器本来就一直开着,于是借它的手完成。

安全边界:
  - 只绑 127.0.0.1,外部网络访问不到。
  - /__launch_backend 执行的是写死的命令,不接收任何请求参数,
    不会退化成"任意命令执行"。
"""
import json
import os
import socket
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent
BACKEND_DIR = FRONTEND_DIR.parent / "backend"
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))


def _python_bin() -> str:
    """优先用 backend 的虚拟环境,否则退回当前解释器(与 start.sh 一致)。"""
    venv = BACKEND_DIR / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _backend_up() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", BACKEND_PORT)) == 0


def _launch_backend() -> str:
    """已在跑就直接返回;否则后台拉起 uvicorn(脱离本进程,日志写 backend.log)。"""
    if _backend_up():
        return "already_running"
    log = open(BACKEND_DIR / "backend.log", "ab")
    subprocess.Popen(
        [_python_bin(), "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=str(BACKEND_DIR),
        stdout=log,
        stderr=log,
        start_new_session=True,  # 脱离本进程,前端服务器重启也不连带杀掉后端
    )
    return "launching"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # 读掉并丢弃请求体,避免连接处理异常(本接口不需要任何参数)
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)

        if self.path == "/__launch_backend":
            try:
                status = _launch_backend()
                self._send_json(200, {"status": status, "backend_port": BACKEND_PORT})
            except Exception as e:  # noqa: BLE001 — 任何启动异常都转成 JSON 回前端
                self._send_json(500, {"status": "error", "error": str(e)})
            return

        self.send_error(404)

    def log_message(self, *args):
        pass  # 静音访问日志,避免刷屏


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", FRONTEND_PORT), Handler)
    print(f"AgentLab frontend → http://127.0.0.1:{FRONTEND_PORT}")
    print(f"  点击\"未连接\"会经 POST /__launch_backend 拉起后端 (:{BACKEND_PORT})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
