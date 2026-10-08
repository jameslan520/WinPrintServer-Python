# -*- coding: utf-8 -*-
"""
RAW TCP 打印协议服务器（JetDirect / 端口 9100）

协议说明:
  - 客户端连接 TCP 9100
  - 直接发送原始打印字节流（ESC/P、PCL、PDF 等）
  - 连接关闭表示作业结束
  - 无额外握手，兼容 Windows「标准 TCP/IP 端口」与几乎所有打印客户端

本服务器:
  1. 接受连接
  2. 接收数据
  3. 转发到本机 Windows 打印机
"""
from __future__ import print_function

import socket
import threading
import logging

from .printer import print_raw_data, PrinterError, resolve_printer_name
from .job import job_manager

logger = logging.getLogger("raw")

# 单次 recv 缓冲
BUF_SIZE = 65536
# 作业最大字节（防止恶意超大文件占满内存），0 = 不限制
MAX_JOB_BYTES = 200 * 1024 * 1024


class RawPrintServer(object):
    """RAW 9100 打印服务器"""

    def __init__(self, config):
        self.config = config
        self._sock = None
        self._running = False
        self._threads = []
        self._lock = threading.Lock()

    def start(self):
        host = self.config.host
        port = self.config.raw_port

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Windows 下可选
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass

        try:
            self._sock.bind((host, port))
        except OSError as exc:
            logger.error(u"绑定 RAW 端口失败 %s:%s - %s", host, port, exc)
            raise

        self._sock.listen(self.config.max_connections)
        self._running = True

        logger.info(u"RAW 打印服务器已启动 tcp://%s:%s", host, port)

        t = threading.Thread(target=self._accept_loop, name="raw-accept")
        t.daemon = True
        t.start()
        self._threads.append(t)

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        logger.info(u"RAW 打印服务器已停止")

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._sock.accept()
            except (OSError, socket.error):
                if self._running:
                    logger.error(u"接受连接异常", exc_info=True)
                break

            client_ip = addr[0]
            if not self._ip_allowed(client_ip):
                logger.warning(u"拒绝未授权客户端: %s", client_ip)
                try:
                    client.close()
                except Exception:
                    pass
                continue

            t = threading.Thread(
                target=self._handle_client,
                args=(client, addr),
                name="raw-client-%s" % client_ip,
            )
            t.daemon = True
            t.start()
            with self._lock:
                self._threads.append(t)

    def _ip_allowed(self, ip):
        allowed = self.config.allowed_ips
        if not allowed or "*" in allowed:
            return True
        for rule in allowed:
            rule = rule.strip()
            if not rule:
                continue
            if rule == ip:
                return True
            # 支持简单通配 192.168.1.*
            if rule.endswith("*") and ip.startswith(rule[:-1]):
                return True
            # 支持 CIDR 简写 /24
            if "/" in rule:
                try:
                    import ipaddress

                    net = ipaddress.ip_network(rule, strict=False)
                    if ipaddress.ip_address(ip) in net:
                        return True
                except Exception:
                    pass
        return False

    def _handle_client(self, client, addr):
        client_ip = addr[0]
        timeout = self.config.job_timeout
        data_chunks = []
        total = 0

        job_manager.connection_opened()
        printer_name = resolve_printer_name(
            self.config.resolve_printer(self.config.raw_port)
        )
        job = job_manager.create(client_ip, "raw", printer_name or "(default)")

        logger.info(u"RAW 连接建立: %s:%s", client_ip, addr[1])
        try:
            client.settimeout(timeout)
            while True:
                try:
                    chunk = client.recv(BUF_SIZE)
                except socket.timeout:
                    logger.warning(u"RAW 接收超时: %s", client_ip)
                    break
                if not chunk:
                    break
                data_chunks.append(chunk)
                total += len(chunk)
                if MAX_JOB_BYTES and total > MAX_JOB_BYTES:
                    logger.error(u"作业超过大小限制 %s 字节", MAX_JOB_BYTES)
                    break

            data = b"".join(data_chunks)
            job.size = len(data)

            if not data:
                logger.info(u"RAW 空作业，忽略: %s", client_ip)
                job_manager.mark_done(job, 0)
                return

            job_manager.mark_printing(job)
            try:
                written = print_raw_data(
                    data,
                    printer_name=printer_name or None,
                    doc_name="RAW from %s" % client_ip,
                    retry=self.config.retry_count,
                    retry_delay=self.config.retry_delay,
                )
                job_manager.mark_done(job, written)
            except PrinterError as exc:
                job_manager.mark_failed(job, exc)
                logger.error(u"RAW 打印失败: %s", exc)

        except Exception as exc:
            job_manager.mark_failed(job, exc)
            logger.error(u"RAW 处理异常 %s: %s", client_ip, exc, exc_info=True)
        finally:
            job_manager.connection_closed()
            try:
                client.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
            logger.info(u"RAW 连接关闭: %s", client_ip)
