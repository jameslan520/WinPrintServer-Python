# -*- coding: utf-8 -*-
"""
简易 Web 状态页
提供服务器运行状态、打印机列表、最近任务
纯标准库实现（http.server），兼容 Windows 7+
"""
from __future__ import print_function

import json
import socket
import threading
import logging
import time
from datetime import datetime

try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
except ImportError:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler  # type: ignore
    from urlparse import urlparse, parse_qs  # type: ignore

from .printer import list_printers, get_default_printer
from .job import job_manager

logger = logging.getLogger("web")

PAGE_TEMPLATE = u"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WinPrintServer 状态</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    background: #0f1419; color: #e7ecf1;
    line-height: 1.5;
  }}
  .wrap {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ font-size: 22px; font-weight: 600; margin: 0 0 4px; }}
  .sub {{ color: #8b9bab; font-size: 13px; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 28px; }}
  .card {{
    background: #1a2332; border: 1px solid #2a3a4d; border-radius: 10px;
    padding: 16px;
  }}
  .card .label {{ color: #8b9bab; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
  .card .value {{ font-size: 26px; font-weight: 600; margin-top: 6px; }}
  .card .value.ok {{ color: #3dd68c; }}
  .card .value.warn {{ color: #f5a524; }}
  .card .value.err {{ color: #f07178; }}
  section {{ margin-bottom: 28px; }}
  h2 {{ font-size: 15px; font-weight: 600; margin: 0 0 12px; color: #c5d0da; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #2a3a4d; }}
  th {{ color: #8b9bab; font-weight: 500; font-size: 12px; }}
  tr:hover td {{ background: #1f2b3d; }}
  .tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 600;
  }}
  .tag.done {{ background: #1a3d2e; color: #3dd68c; }}
  .tag.printing {{ background: #3d3018; color: #f5a524; }}
  .tag.failed {{ background: #3d1a1e; color: #f07178; }}
  .tag.pending {{ background: #1a2a3d; color: #6cb6ff; }}
  .empty {{ color: #5a6a7a; padding: 20px; text-align: center; }}
  .footer {{ color: #5a6a7a; font-size: 12px; margin-top: 32px; }}
  .mono {{ font-family: Consolas, "Courier New", monospace; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>WinPrintServer</h1>
  <div class="sub">Windows 网络打印服务器 · 运行状态面板</div>

  <div class="grid">
    <div class="card">
      <div class="label">运行状态</div>
      <div class="value ok">运行中</div>
    </div>
    <div class="card">
      <div class="label">活动连接</div>
      <div class="value">{active_connections}</div>
    </div>
    <div class="card">
      <div class="label">成功任务</div>
      <div class="value ok">{success_jobs}</div>
    </div>
    <div class="card">
      <div class="label">失败任务</div>
      <div class="value {failed_class}">{failed_jobs}</div>
    </div>
    <div class="card">
      <div class="label">累计字节</div>
      <div class="value">{total_bytes_human}</div>
    </div>
    <div class="card">
      <div class="label">运行时长</div>
      <div class="value">{uptime_human}</div>
    </div>
  </div>

  <section>
    <h2>服务端点</h2>
    <table>
      <tr><th>协议</th><th>地址</th><th>说明</th></tr>
      <tr>
        <td><span class="tag done">RAW</span></td>
        <td class="mono">{host}:{raw_port}</td>
        <td>标准 TCP/IP · Windows 添加打印机时选「Standard TCP/IP Port」</td>
      </tr>
      <tr>
        <td><span class="tag {lpd_tag}">LPD</span></td>
        <td class="mono">{host}:{lpd_port}</td>
        <td>LPR/LPD · Unix 与 Windows LPR 端口监视器</td>
      </tr>
      <tr>
        <td><span class="tag done">WEB</span></td>
        <td class="mono">{host}:{web_port}</td>
        <td>本状态页</td>
      </tr>
    </table>
  </section>

  <section>
    <h2>本机打印机</h2>
    {printers_html}
  </section>

  <section>
    <h2>最近打印任务</h2>
    {jobs_html}
  </section>

  <div class="footer">默认打印机: <strong>{default_printer}</strong> · 生成时间 {now}</div>
</div>
<script>
setTimeout(function(){{ location.reload(); }}, 10000);
</script>
</body>
</html>
"""


def _human_bytes(n):
    try:
        n = float(n)
    except Exception:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def _human_duration(seconds):
    try:
        seconds = int(seconds)
    except Exception:
        return "0s"
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm %ds" % (seconds // 60, seconds % 60)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return "%dh %dm" % (h, m)


class WebHandler(BaseHTTPRequestHandler):
    server_version = "WinPrintServer/1.0"
    config = None  # 由 WebStatusServer 注入

    def log_message(self, fmt, *args):
        logger.debug("web: " + fmt, *args)

    def _send(self, code, content_type, body):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._serve_page()
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/jobs":
            self._serve_jobs()
        elif path == "/api/printers":
            self._serve_printers()
        elif path == "/health":
            self._send(200, "application/json", json.dumps({"ok": True}))
        else:
            self._send(404, "text/html", u"<h1>404 Not Found</h1>")

    def _serve_page(self):
        cfg = self.config
        stats = job_manager.get_stats()
        printers = list_printers()
        default = get_default_printer()
        jobs = job_manager.get_jobs(limit=20)

        failed = stats.get("failed_jobs", 0)
        failed_class = "err" if failed else "ok"
        uptime = time.time() - stats.get("started_at", time.time())

        # 打印机表格
        if printers:
            rows = []
            for p in printers:
                mark = u"★" if p.get("is_default") else u""
                rows.append(
                    u"<tr><td>%s %s</td><td>%s</td></tr>"
                    % (
                        _esc(p.get("name", "")),
                        mark,
                        _esc(p.get("description", "")),
                    )
                )
            printers_html = u"<table><tr><th>打印机名称</th><th>描述</th></tr>%s</table>" % (
                u"".join(rows)
            )
        else:
            printers_html = u'<div class="empty">未检测到打印机</div>'

        # 任务表格
        if jobs:
            rows = []
            for j in jobs:
                st = j.get("status", "")
                cls = {
                    "done": "done",
                    "printing": "printing",
                    "failed": "failed",
                    "pending": "pending",
                }.get(st, "pending")
                ts = datetime.fromtimestamp(j.get("created_at", 0)).strftime(
                    "%H:%M:%S"
                )
                rows.append(
                    u"<tr><td>#%s</td><td>%s</td><td>%s</td><td class='mono'>%s</td>"
                    u"<td>%s</td><td><span class='tag %s'>%s</span></td></tr>"
                    % (
                        j.get("id"),
                        ts,
                        _esc(j.get("client_ip", "")),
                        _esc(j.get("protocol", "")),
                        _human_bytes(j.get("size", 0)),
                        cls,
                        _esc(st),
                    )
                )
            jobs_html = (
                u"<table><tr><th>#</th><th>时间</th><th>客户端</th>"
                u"<th>协议</th><th>大小</th><th>状态</th></tr>%s</table>"
                % u"".join(rows)
            )
        else:
            jobs_html = u'<div class="empty">暂无任务</div>'

        html = PAGE_TEMPLATE.format(
            active_connections=stats.get("active_connections", 0),
            success_jobs=stats.get("success_jobs", 0),
            failed_jobs=failed,
            failed_class=failed_class,
            total_bytes_human=_human_bytes(stats.get("total_bytes", 0)),
            uptime_human=_human_duration(uptime),
            host=_esc(cfg.host if cfg.host != "0.0.0.0" else "0.0.0.0"),
            raw_port=cfg.raw_port,
            lpd_port=cfg.lpd_port,
            web_port=cfg.web_port,
            lpd_tag="done" if cfg.enable_lpd else "pending",
            printers_html=printers_html,
            jobs_html=jobs_html,
            default_printer=_esc(default or u"(未设置)"),
            now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._send(200, "text/html", html)

    def _serve_status(self):
        cfg = self.config
        stats = job_manager.get_stats()
        payload = {
            "ok": True,
            "version": "1.0.0",
            "uptime": time.time() - stats.get("started_at", time.time()),
            "stats": stats,
            "endpoints": {
                "raw": {"enabled": cfg.enable_raw, "host": cfg.host, "port": cfg.raw_port},
                "lpd": {"enabled": cfg.enable_lpd, "host": cfg.host, "port": cfg.lpd_port},
                "web": {"enabled": cfg.enable_web, "host": cfg.host, "port": cfg.web_port},
            },
            "default_printer": get_default_printer(),
        }
        self._send(200, "application/json", json.dumps(payload, ensure_ascii=False))

    def _serve_jobs(self):
        qs = parse_qs(urlparse(self.path).query)
        limit = 50
        try:
            limit = int(qs.get("limit", ["50"])[0])
        except Exception:
            pass
        jobs = job_manager.get_jobs(limit=limit)
        self._send(200, "application/json", json.dumps({"jobs": jobs}, ensure_ascii=False))

    def _serve_printers(self):
        printers = list_printers()
        self._send(
            200,
            "application/json",
            json.dumps({"printers": printers, "default": get_default_printer()}, ensure_ascii=False),
        )


def _esc(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class WebStatusServer(object):
    """Web 状态服务"""

    def __init__(self, config):
        self.config = config
        self._httpd = None
        self._thread = None

    def start(self):
        host = self.config.host
        port = self.config.web_port

        handler = type("Handler", (WebHandler,), {"config": self.config})
        try:
            self._httpd = HTTPServer((host, port), handler)
        except OSError as exc:
            logger.error(u"启动 Web 状态页失败 %s:%s - %s", host, port, exc)
            raise

        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="web-status", kwargs={"poll_interval": 0.5}
        )
        self._thread.daemon = True
        self._thread.start()
        logger.info(u"Web 状态页已启动 http://%s:%s", host, port)

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        logger.info(u"Web 状态页已停止")
