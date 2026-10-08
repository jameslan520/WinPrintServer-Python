# -*- coding: utf-8 -*-
"""
端到端集成测试
在本机启动服务并模拟客户端打印
"""
from __future__ import print_function

import os
import sys
import socket
import time
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from server.config import Config
from server.raw_server import RawPrintServer
from server.web_ui import WebStatusServer
from server.job import job_manager


def test_raw(server_cfg):
    print(u"测试 RAW 9100 ...")
    s = socket.socket()
    s.settimeout(10)
    try:
        s.connect(("127.0.0.1", server_cfg.raw_port))
        # 模拟 ESC/P 初始化 + 文本
        data = b"\x1b@WinPrintServer E2E Test\nHello Printer\n\x0c"
        s.sendall(data)
        time.sleep(0.8)
        s.close()
        print(u"  RAW 发送成功 (%d 字节)" % len(data))
        return True
    except Exception as exc:
        print(u"  RAW 失败: %s" % exc)
        return False


def test_web(server_cfg):
    print(u"测试 Web 8080 ...")
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect(("127.0.0.1", server_cfg.web_port))
        s.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        chunks = []
        while True:
            try:
                b = s.recv(4096)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
        s.close()
        text = b"".join(chunks).decode("utf-8", "replace")
        status_line = text.split("\r\n")[0] if text else ""
        if "200" in status_line and ("ok" in text.lower() or "true" in text.lower()):
            print(u"  Web 健康检查通过")
            return True
        print(u"  Web 响应异常: %s" % text[:150])
        return False
    except Exception as exc:
        print(u"  Web 失败: %s" % exc)
        return False


def test_web_page(server_cfg):
    print(u"测试 Web 状态页 ...")
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect(("127.0.0.1", server_cfg.web_port))
        s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        chunks = []
        while True:
            try:
                b = s.recv(8192)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
        s.close()
        body = b"".join(chunks)
        if b"WinPrintServer" in body or b"200" in body:
            print(u"  状态页可访问 (%d 字节)" % len(body))
            return True
        print(u"  状态页异常")
        return False
    except Exception as exc:
        print(u"  状态页失败: %s" % exc)
        return False


def main():
    print(u"=" * 50)
    print(u"WinPrintServer 端到端测试")
    print(u"=" * 50)

    cfg = Config()
    # 测试期间关闭 LPD，避免权限问题
    if not cfg._parser.has_section("server"):
        cfg._parser.add_section("server")
    cfg._parser.set("server", "enable_lpd", "false")

    raw = RawPrintServer(cfg)
    web = WebStatusServer(cfg)

    try:
        raw.start()
        web.start()
    except Exception as exc:
        print(u"服务启动失败: %s" % exc)
        return 1

    time.sleep(0.3)

    results = []
    results.append(("RAW", test_raw(cfg)))
    results.append(("Web健康", test_web(cfg)))
    results.append(("Web页面", test_web_page(cfg)))

    # 检查任务记录（等待打印重试完成）
    time.sleep(2.5)
    jobs = job_manager.get_jobs(limit=5)
    print(u"最近任务数: %d" % len(jobs))
    for j in jobs:
        print(u"  #%s %s %s %s bytes status=%s" % (
            j.get("id"), j.get("protocol"), j.get("client_ip"),
            j.get("size"), j.get("status"),
        ))

    # 关闭
    raw.stop()
    web.stop()

    print(u"=" * 50)
    all_ok = all(r[1] for r in results)
    for name, ok in results:
        print(u"  %s: %s" % (name, u"PASS" if ok else u"FAIL"))
    print(u"=" * 50)
    print(u"结果: %s" % (u"全部通过" if all_ok else u"存在失败"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
