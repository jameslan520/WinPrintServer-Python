# -*- coding: utf-8 -*-
"""
LPD / LPR 打印协议服务器（RFC 1179，端口 515）

用于 Unix/Linux/macOS 以及 Windows「LPR 端口监视器」客户端。
协议流程（接收作业）:
  1. 客户端连接 515
  2. 客户端发送: 0x02 + 队列名 + \n
  3. 服务器回复 0x00
  4. 客户端发送控制文件: 0x02 + size + " cfA***" + \n，再发控制文件内容
  5. 服务器回复 0x00
  6. 客户端发送数据文件: 0x03 + size + " dfA***" + \n，再发数据文件内容
  7. 服务器回复 0x00
  ...
  8. 作业结束（连接关闭）

本实现将数据文件内容原样转发到本机打印机。
"""
from __future__ import print_function

import socket
import threading
import logging

from .printer import print_raw_data, PrinterError, resolve_printer_name
from .job import job_manager

logger = logging.getLogger("lpd")

BUF_SIZE = 65536
MAX_JOB_BYTES = 200 * 1024 * 1024


def _recv_line(sock, max_len=1024):
    """接收以 \n 结尾的一行"""
    buf = b""
    while len(buf) < max_len:
        try:
            b = sock.recv(1)
        except socket.timeout:
            break
        if not b:
            break
        if b == b"\n":
            return buf
        buf += b
    return buf


def _recv_exact(sock, size):
    """精确接收 size 字节"""
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(BUF_SIZE, size - len(data)))
        if not chunk:
            break
        data += chunk
    return data


class LPDPrintServer(object):
    """LPD 515 打印服务器"""

    def __init__(self, config):
        self.config = config
        self._sock = None
        self._running = False
        self._threads = []
        self._lock = threading.Lock()

    def start(self):
        host = self.config.host
        port = self.config.lpd_port

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._sock.bind((host, port))
        except OSError as exc:
            logger.error(u"绑定 LPD 端口失败 %s:%s - %s", host, port, exc)
            logger.error(
                u"提示: 端口 515 通常需要管理员权限，且可能被 Windows LPD 服务占用"
            )
            raise

        self._sock.listen(self.config.max_connections)
        self._running = True
        logger.info(u"LPD 打印服务器已启动 tcp://%s:%s", host, port)

        t = threading.Thread(target=self._accept_loop, name="lpd-accept")
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
        logger.info(u"LPD 打印服务器已停止")

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._sock.accept()
            except (OSError, socket.error):
                if self._running:
                    logger.error(u"LPD 接受连接异常", exc_info=True)
                break

            client_ip = addr[0]
            t = threading.Thread(
                target=self._handle_client,
                args=(client, addr),
                name="lpd-client-%s" % client_ip,
            )
            t.daemon = True
            t.start()
            with self._lock:
                self._threads.append(t)

    def _handle_client(self, client, addr):
        client_ip = addr[0]
        timeout = self.config.job_timeout
        job_manager.connection_opened()
        job = None

        logger.info(u"LPD 连接建立: %s:%s", client_ip, addr[1])
        try:
            client.settimeout(timeout)

            # 1. 接收命令行: 0x02 + queue + \n  (接收作业)
            line = _recv_line(client)
            if not line:
                return

            cmd = line[0:1]
            if cmd != b"\x02":
                # 可能是其他命令（打印已排队作业等）
                logger.warning(u"LPD 非接收命令: %r", line[:20])
                client.sendall(b"\x01")  # 失败
                return

            queue = line[1:].decode("utf-8", "replace").strip()
            logger.info(u"LPD 接收作业 队列=%s 客户端=%s", queue, client_ip)

            printer_name = resolve_printer_name(
                self.config.resolve_printer(self.config.lpd_port) or queue
            )
            job = job_manager.create(client_ip, "lpd", printer_name or queue)
            client.sendall(b"\x00")  # 接受

            data_parts = []
            total_data = 0

            # 2. 读取控制文件与数据文件（一个或多个子文件）
            while True:
                header = _recv_line(client)
                if not header:
                    break

                hcmd = header[0:1]
                if hcmd not in (b"\x02", b"\x03"):
                    # 0x01 = abort
                    logger.warning(u"LPD 子文件命令: %r", header[:20])
                    break

                # 解析: 0x02/0x03 + decimal_size + " " + filename + \n
                try:
                    rest = header[1:].decode("utf-8", "replace")
                    size_str = rest.split(" ")[0]
                    fname = rest.split(" ", 1)[1].strip() if " " in rest else ""
                    fsize = int(size_str)
                except Exception:
                    logger.warning(u"LPD 子文件头解析失败: %r", header)
                    client.sendall(b"\x01")
                    break

                content = _recv_exact(client, fsize)
                if len(content) != fsize:
                    logger.warning(
                        u"LPD 子文件不完整: 期望 %d 实际 %d", fsize, len(content)
                    )
                    client.sendall(b"\x01")
                    break

                # 期望以 \n 结束
                try:
                    term = client.recv(1)
                except Exception:
                    term = b""

                if hcmd == b"\x03":
                    # 数据文件
                    data_parts.append(content)
                    total_data += len(content)
                    logger.debug(
                        u"LPD 数据文件 %s (%d 字节)", fname, fsize
                    )
                else:
                    # 控制文件，仅记录
                    logger.debug(u"LPD 控制文件 %s (%d 字节)", fname, fsize)

                client.sendall(b"\x00")

                if MAX_JOB_BYTES and total_data > MAX_JOB_BYTES:
                    logger.error(u"LPD 作业超过大小限制")
                    break

            data = b"".join(data_parts)
            job.size = len(data)

            if data:
                job_manager.mark_printing(job)
                try:
                    written = print_raw_data(
                        data,
                        printer_name=printer_name or None,
                        doc_name="LPD from %s" % client_ip,
                        retry=self.config.retry_count,
                        retry_delay=self.config.retry_delay,
                    )
                    job_manager.mark_done(job, written)
                except PrinterError as exc:
                    job_manager.mark_failed(job, exc)
                    logger.error(u"LPD 打印失败: %s", exc)
            else:
                job_manager.mark_done(job, 0)

        except Exception as exc:
            if job:
                job_manager.mark_failed(job, exc)
            logger.error(u"LPD 处理异常 %s: %s", client_ip, exc, exc_info=True)
        finally:
            job_manager.connection_closed()
            try:
                client.close()
            except Exception:
                pass
            logger.info(u"LPD 连接关闭: %s", client_ip)
