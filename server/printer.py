# -*- coding: utf-8 -*-
"""
Windows 打印机输出模块

通过 winspool.drv 将原始字节流写入本地打印机（LQ-630K 等）。
不强制依赖 pywin32；若已安装则优先使用。
"""
from __future__ import print_function

import os
import sys
import time
import logging
import threading

logger = logging.getLogger("printer")

# 尝试 pywin32
try:
    import win32print
    import win32api

    HAS_PYWIN32 = True
except Exception:
    HAS_PYWIN32 = False

# Windows API (ctypes)
IS_WINDOWS = sys.platform.startswith("win")
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # 定义结构
    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [
            ("pDocName", wintypes.LPWSTR),
            ("pOutputFile", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR),
        ]

    # API 签名
    winspool.OpenPrinterW.argtypes = [
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.c_void_p,
    ]
    winspool.OpenPrinterW.restype = wintypes.BOOL

    winspool.StartDocPrinterW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(DOC_INFO_1),
    ]
    winspool.StartDocPrinterW.restype = wintypes.DWORD

    winspool.StartPagePrinter.argtypes = [wintypes.HANDLE]
    winspool.StartPagePrinter.restype = wintypes.BOOL

    winspool.WritePrinter.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    winspool.WritePrinter.restype = wintypes.BOOL

    winspool.EndPagePrinter.argtypes = [wintypes.HANDLE]
    winspool.EndPagePrinter.restype = wintypes.BOOL

    winspool.EndDocPrinter.argtypes = [wintypes.HANDLE]
    winspool.EndDocPrinter.restype = wintypes.BOOL

    winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
    winspool.ClosePrinter.restype = wintypes.BOOL

    winspool.EnumPrintersW.argtypes = [
        wintypes.DWORD,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    winspool.EnumPrintersW.restype = wintypes.BOOL


class PrinterError(Exception):
    """打印机操作异常"""
    pass


class WindowsPrinter(object):
    """
    Windows 本地打印机写入器

    用法:
        p = WindowsPrinter("LQ-630K")
        p.open()
        p.write(b"\\x1b@...")  # ESC/P 数据
        p.close()
    """

    def __init__(self, name, doc_name="Network Print Job", timeout=60):
        self.name = name
        self.doc_name = doc_name
        self.timeout = timeout
        self._handle = None
        self._started = False
        self._backend = None  # "pywin32" or "ctypes"
        self._lock = threading.Lock()
        self._bytes_written = 0

    def open(self):
        """打开打印机并开始文档"""
        if self._handle is not None:
            return
        if not self.name:
            raise PrinterError(u"未指定打印机名称")

        if HAS_PYWIN32:
            try:
                self._handle = win32print.OpenPrinter(self.name)
                win32print.StartDocPrinter(
                    self._handle,
                    1,
                    (self.doc_name, None, "RAW"),
                )
                win32print.StartPagePrinter(self._handle)
                self._started = True
                self._backend = "pywin32"
                self._bytes_written = 0
                logger.debug(u"已打开打印机( pywin32 ): %s", self.name)
                return
            except Exception as exc:
                logger.warning(u"pywin32 打开打印机失败，回退 ctypes: %s", exc)
                try:
                    if self._handle:
                        win32print.ClosePrinter(self._handle)
                except Exception:
                    pass
                self._handle = None

        self._open_ctypes()

    def _open_ctypes(self):
        if not IS_WINDOWS:
            raise PrinterError(u"当前系统不是 Windows，无法访问本地打印机")

        handle = wintypes.HANDLE()
        ok = winspool.OpenPrinterW(
            self.name,
            ctypes.byref(handle),
            None,
        )
        if not ok or not handle:
            err = ctypes.get_last_error()
            raise PrinterError(u"打开打印机失败: %s (错误码 %s)" % (self.name, err))

        di = DOC_INFO_1()
        di.pDocName = self.doc_name
        di.pOutputFile = None
        di.pDatatype = "RAW"

        job_id = winspool.StartDocPrinterW(handle, 1, ctypes.byref(di))
        if not job_id:
            err = ctypes.get_last_error()
            winspool.ClosePrinter(handle)
            raise PrinterError(u"StartDocPrinterW 失败 (错误码 %s)" % err)

        if not winspool.StartPagePrinter(handle):
            err = ctypes.get_last_error()
            winspool.EndDocPrinter(handle)
            winspool.ClosePrinter(handle)
            raise PrinterError(u"StartPagePrinter 失败 (错误码 %s)" % err)

        self._handle = handle
        self._started = True
        self._backend = "ctypes"
        self._bytes_written = 0
        logger.debug(u"已打开打印机(ctypes): %s", self.name)

    def write(self, data):
        """写入原始打印数据"""
        if not data:
            return 0
        if self._handle is None:
            self.open()

        with self._lock:
            # 优先使用 pywin32
            if self._backend == "pywin32":
                try:
                    written = win32print.WritePrinter(self._handle, data)
                    self._bytes_written += written
                    return written
                except Exception as exc:
                    logger.warning(u"pywin32 WritePrinter 失败: %s", exc)
                    raise PrinterError(u"写入打印机失败: %s" % exc)

            # ctypes 路径
            if not IS_WINDOWS:
                raise PrinterError(u"当前系统不是 Windows")

            buf = ctypes.create_string_buffer(data, len(data))
            written = wintypes.DWORD(0)
            ok = winspool.WritePrinter(
                self._handle,
                buf,
                len(data),
                ctypes.byref(written),
            )
            if not ok:
                err = ctypes.get_last_error()
                raise PrinterError(u"WritePrinter 失败 (错误码 %s)" % err)
            self._bytes_written += written.value
            return written.value

    def flush(self):
        """确保数据写入打印队列（Windows 打印机写入即提交）"""
        pass

    def close(self):
        """结束文档并关闭打印机"""
        if self._handle is None:
            return
        try:
            if self._backend == "pywin32" and self._started:
                try:
                    win32print.EndPagePrinter(self._handle)
                    win32print.EndDocPrinter(self._handle)
                    win32print.ClosePrinter(self._handle)
                    logger.debug(u"打印机已关闭( pywin32 ): %s", self.name)
                    return
                except Exception as exc:
                    logger.warning(u"pywin32 关闭打印机异常: %s", exc)

            if self._backend == "ctypes" and self._started and IS_WINDOWS:
                winspool.EndPagePrinter(self._handle)
                winspool.EndDocPrinter(self._handle)
                winspool.ClosePrinter(self._handle)
                logger.debug(u"打印机已关闭(ctypes): %s", self.name)
        except Exception as exc:
            logger.warning(u"关闭打印机异常: %s", exc)
        finally:
            self._handle = None
            self._started = False
            self._backend = None

    @property
    def bytes_written(self):
        return self._bytes_written

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def list_printers():
    """
    列出本机打印机
    返回: [{"name": ..., "is_default": bool, "status": ..., "port": ...}, ...]
    """
    printers = []
    if HAS_PYWIN32:
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for p in win32print.EnumPrinters(flags, None, 1):
                # p = (Flags, Description, Name, Comment, ...)
                printers.append(
                    {
                        "name": p[2],
                        "description": p[1],
                        "is_default": False,
                        "status": "",
                        "port": "",
                    }
                )
            try:
                default = win32print.GetDefaultPrinter()
                for item in printers:
                    if item["name"] == default:
                        item["is_default"] = True
            except Exception:
                pass
            return printers
        except Exception as exc:
            logger.warning(u"枚举打印机失败( pywin32 ): %s", exc)

    if IS_WINDOWS:
        try:
            # PRINTER_ENUM_LOCAL = 2, PRINTER_ENUM_CONNECTIONS = 4
            flags = 2 | 4
            needed = wintypes.DWORD(0)
            count = wintypes.DWORD(0)
            winspool.EnumPrintersW(flags, None, 1, None, 0, ctypes.byref(needed), ctypes.byref(count))
            if needed.value == 0:
                return printers

            buf = ctypes.create_string_buffer(needed.value)

            # PRINTER_INFO_1W
            class PRINTER_INFO_1W(ctypes.Structure):
                _fields_ = [
                    ("Flags", wintypes.DWORD),
                    ("pDescription", wintypes.LPWSTR),
                    ("pName", wintypes.LPWSTR),
                    ("pComment", wintypes.LPWSTR),
                ]

            winspool.EnumPrintersW.argtypes = [
                wintypes.DWORD,
                wintypes.LPWSTR,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
            ]
            ok = winspool.EnumPrintersW(
                flags, None, 1, buf, needed, ctypes.byref(needed), ctypes.byref(count)
            )
            if not ok:
                return printers

            arr = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_1W))
            for i in range(count.value):
                info = arr[i]
                printers.append(
                    {
                        "name": info.pName or "",
                        "description": info.pDescription or "",
                        "is_default": False,
                        "status": "",
                        "port": "",
                    }
                )
        except Exception as exc:
            logger.warning(u"枚举打印机失败(ctypes): %s", exc)

    return printers


def get_default_printer():
    """获取默认打印机名称，无则返回空字符串"""
    if HAS_PYWIN32:
        try:
            return win32print.GetDefaultPrinter() or ""
        except Exception:
            pass
    printers = list_printers()
    for p in printers:
        if p.get("is_default"):
            return p.get("name") or ""
    if printers:
        return printers[0].get("name") or ""
    return ""


def resolve_printer_name(preferred=""):
    """
    解析最终使用的打印机名称
    优先: preferred → 系统默认 → 第一台本地打印机
    """
    if preferred:
        return preferred
    name = get_default_printer()
    if name:
        return name
    printers = list_printers()
    if printers:
        return printers[0].get("name") or ""
    return ""


def print_raw_data(data, printer_name=None, doc_name="Network Print Job", retry=3, retry_delay=0.5):
    """
    将原始数据发送到打印机（带重试）
    成功返回写入字节数，失败抛出 PrinterError
    """
    name = resolve_printer_name(printer_name)
    if not name:
        raise PrinterError(u"未找到可用打印机，请检查打印机是否已安装")

    last_exc = None
    for attempt in range(1, max(1, retry) + 1):
        try:
            with WindowsPrinter(name, doc_name=doc_name) as p:
                written = p.write(data)
            logger.info(
                u"打印完成: 打印机=%s 字节数=%d 尝试=%d",
                name,
                written,
                attempt,
            )
            return written
        except PrinterError as exc:
            last_exc = exc
            logger.warning(
                u"打印失败(尝试 %d/%d): %s", attempt, retry, exc
            )
            if attempt < retry:
                time.sleep(retry_delay)
        except Exception as exc:
            last_exc = PrinterError(str(exc))
            logger.error(u"打印异常: %s", exc)
            if attempt < retry:
                time.sleep(retry_delay)

    raise last_exc or PrinterError(u"打印失败")
