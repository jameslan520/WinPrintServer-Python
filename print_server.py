# -*- coding: utf-8 -*-
"""
WinPrintServer - Windows 网络打印服务器

将本机打印机（如 LQ-630K 针式打印机）转换为网络打印服务器，
客户端可通过 TCP 9100 (RAW) 或 LPD 515 连接打印。

用法:
  python print_server.py                 # 前台运行
  python print_server.py --install       # 安装为 Windows 服务
  python print_server.py --uninstall     # 卸载服务
  python print_server.py --list-printers # 列出本机打印机
  python print_server.py --config path   # 指定配置文件

兼容: Windows 7 / 10 / 11 (Python 3.6+)
"""
from __future__ import print_function

import argparse
import logging
import os
import signal
import sys
import time

# 确保可以导入 server 包
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from server.config import Config, setup_logging
from server.printer import list_printers, get_default_printer, resolve_printer_name
from server.job import job_manager

logger = logging.getLogger("main")


def print_banner(cfg):
    host_display = cfg.host if cfg.host != "0.0.0.0" else "0.0.0.0"
    print(u"""
╔══════════════════════════════════════════════════════╗
║           WinPrintServer v1.0.0                      ║
║       Windows 网络打印服务器                          ║
╠══════════════════════════════════════════════════════╣
║  RAW  : tcp://%s:%s
║  LPD  : tcp://%s:%s  (可选)
║  Web  : http://%s:%s
║  打印机: %s
╚══════════════════════════════════════════════════════╝
""" % (
        host_display,
        cfg.raw_port,
        host_display,
        cfg.lpd_port,
        host_display,
        cfg.web_port,
        resolve_printer_name(cfg.default_printer) or u"(未找到打印机)",
    ))


def cmd_list_printers():
    printers = list_printers()
    default = get_default_printer()
    if not printers:
        print(u"未检测到打印机。请先在「设备和打印机」中安装打印机驱动。")
        return 1
    print(u"\n本机打印机列表:")
    print(u"-" * 60)
    for i, p in enumerate(printers, 1):
        mark = u" [默认]" if p.get("name") == default else u""
        print(u"  %d. %s%s" % (i, p.get("name"), mark))
        if p.get("description") and p.get("description") != p.get("name"):
            print(u"     %s" % p.get("description"))
    print(u"\n默认打印机: %s" % (default or u"(无)"))
    return 0


def cmd_run(cfg_path=None):
    cfg = Config(cfg_path)
    setup_logging(cfg)

    # 检查打印机
    printer_name = resolve_printer_name(cfg.default_printer)
    if not printer_name:
        logger.warning(u"未找到打印机！请先安装打印机驱动。")
        print(u"警告: 未找到打印机，请先安装打印机驱动后再运行。", file=sys.stderr)
    else:
        logger.info(u"目标打印机: %s", printer_name)

    # 显示端口映射
    mapping = cfg.port_map()
    if mapping:
        for port, name in mapping.items():
            logger.info(u"端口映射: %s -> %s", port, name)

    print_banner(cfg)

    servers = []

    # RAW 9100
    if cfg.enable_raw:
        try:
            from server.raw_server import RawPrintServer

            raw = RawPrintServer(cfg)
            raw.start()
            servers.append(raw)
        except Exception as exc:
            logger.error(u"启动 RAW 服务器失败: %s", exc)
            print(u"错误: 启动 RAW 服务器失败: %s" % exc, file=sys.stderr)

    # LPD 515
    if cfg.enable_lpd:
        try:
            from server.lpd_server import LPDPrintServer

            lpd = LPDPrintServer(cfg)
            lpd.start()
            servers.append(lpd)
        except Exception as exc:
            logger.error(u"启动 LPD 服务器失败: %s", exc)
            print(u"错误: 启动 LPD 服务器失败: %s" % exc, file=sys.stderr)
            print(u"提示: 端口 515 可能需要管理员权限或被系统 LPD 服务占用。", file=sys.stderr)

    # Web 状态页
    if cfg.enable_web:
        try:
            from server.web_ui import WebStatusServer

            web = WebStatusServer(cfg)
            web.start()
            servers.append(web)
        except Exception as exc:
            logger.error(u"启动 Web 状态页失败: %s", exc)

    if not servers:
        logger.error(u"没有任何服务启动成功")
        print(u"错误: 没有任何服务启动成功，请检查配置。", file=sys.stderr)
        return 1

    logger.info(u"服务器启动完成，按 Ctrl+C 停止")

    # 等待退出
    stop_flag = {"stop": False}

    def _signal_handler(signum, frame):
        logger.info(u"收到停止信号 %s", signum)
        stop_flag["stop"] = True

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _signal_handler)

    try:
        while not stop_flag["stop"]:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info(u"用户中断")

    # 停止所有服务
    for s in servers:
        try:
            s.stop()
        except Exception:
            pass
    logger.info(u"服务器已停止")
    print(u"\n服务器已停止。")
    return 0


def cmd_install_service(cfg_path=None):
    """安装为 Windows 服务（需要管理员权限）"""
    if not sys.platform.startswith("win"):
        print(u"仅支持 Windows 系统", file=sys.stderr)
        return 1

    try:
        import win32serviceutil
        import win32service
        import win32event
        import servicemanager
    except ImportError:
        print(u"安装服务需要 pywin32 模块。", file=sys.stderr)
        print(u"请执行:  pip install pywin32", file=sys.stderr)
        print(u"或者使用 scripts/install_service.bat 中的 NSSM 方式。", file=sys.stderr)
        return 1

    # 动态定义服务类
    class PrintServerSvc(win32serviceutil.ServiceFramework):
        _svc_name_ = "WinPrintServer"
        _svc_display_name_ = "Windows Network Print Server"
        _svc_description_ = "将本机打印机转换为网络打印服务器 (RAW 9100 / LPD)"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._running = False

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._running = False
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self._running = True
            # 在服务上下文中运行主循环
            try:
                rc = cmd_run(cfg_path)
            except Exception as exc:
                servicemanager.LogErrorMsg(u"服务运行失败: %s" % exc)
                rc = 1
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    # 将服务类暴露给 win32serviceutil
    import __main__
    __main__.PrintServerSvc = PrintServerSvc

    if len(sys.argv) > 1 and sys.argv[1] == "--install":
        # 重新组织参数供 win32serviceutil 使用
        sys.argv = [sys.argv[0], "install"]
    win32serviceutil.HandleCommandLine(PrintServerSvc)
    return 0


def cmd_uninstall_service():
    try:
        import win32serviceutil

        win32serviceutil.RemoveService("WinPrintServer")
        print(u"服务已卸载")
        return 0
    except ImportError:
        print(u"需要 pywin32，或使用 scripts/uninstall_service.bat", file=sys.stderr)
        return 1
    except Exception as exc:
        print(u"卸载失败: %s" % exc, file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=u"WinPrintServer - Windows 网络打印服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python print_server.py
  python print_server.py --list-printers
  python print_server.py --config config.ini
  python print_server.py --install
  python print_server.py --uninstall
""",
    )
    parser.add_argument("--config", "-c", help=u"配置文件路径 (默认: config.ini)")
    parser.add_argument("--list-printers", action="store_true", help=u"列出本机打印机")
    parser.add_argument("--install", action="store_true", help=u"安装为 Windows 服务")
    parser.add_argument("--uninstall", action="store_true", help=u"卸载 Windows 服务")
    parser.add_argument("--version", action="version", version="WinPrintServer 1.0.0")

    args = parser.parse_args(argv)

    if args.list_printers:
        return cmd_list_printers()
    if args.install:
        return cmd_install_service(args.config)
    if args.uninstall:
        return cmd_uninstall_service()

    return cmd_run(args.config)


if __name__ == "__main__":
    sys.exit(main() or 0)
