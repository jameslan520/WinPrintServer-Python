# -*- coding: utf-8 -*-
"""
快速自检脚本
验证模块导入、配置加载、打印机枚举是否正常

用法:
  python self_check.py
"""
from __future__ import print_function

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main():
    ok = True
    print(u"WinPrintServer 自检开始")
    print(u"-" * 50)

    # 1. 模块导入
    print(u"[1] 检查模块导入...")
    try:
        from server import config, printer, job
        from server import raw_server, lpd_server, web_ui
        print(u"    OK: 全部核心模块可导入")
    except Exception as exc:
        print(u"    FAIL: %s" % exc)
        ok = False
        return 1

    # 2. 配置
    print(u"[2] 检查配置文件...")
    try:
        cfg = config.Config()
        print(u"    OK: 配置加载成功 (%s)" % cfg.path)
        print(u"    RAW 端口: %s  LPD 端口: %s  Web 端口: %s" % (
            cfg.raw_port, cfg.lpd_port, cfg.web_port))
    except Exception as exc:
        print(u"    FAIL: %s" % exc)
        ok = False

    # 3. 日志
    print(u"[3] 检查日志初始化...")
    try:
        config.setup_logging(cfg)
        print(u"    OK: 日志已初始化")
    except Exception as exc:
        print(u"    FAIL: %s" % exc)
        ok = False

    # 4. 打印机枚举
    print(u"[4] 检查打印机枚举...")
    try:
        printers = printer.list_printers()
        default = printer.get_default_printer()
        if printers:
            print(u"    OK: 找到 %d 台打印机" % len(printers))
            for p in printers[:5]:
                mark = u" [默认]" if p.get("name") == default else u""
                print(u"      - %s%s" % (p.get("name"), mark))
        else:
            print(u"    WARN: 未检测到打印机（可在安装驱动后重试）")
    except Exception as exc:
        print(u"    FAIL: %s" % exc)
        ok = False

    # 5. 任务管理器
    print(u"[5] 检查任务管理器...")
    try:
        j = job.job_manager.create("127.0.0.1", "raw", "TEST", b"hello")
        job.job_manager.mark_printing(j)
        job.job_manager.mark_done(j, 5)
        stats = job.job_manager.get_stats()
        print(u"    OK: 任务管理器正常 (total=%s)" % stats.get("total_jobs"))
    except Exception as exc:
        print(u"    FAIL: %s" % exc)
        ok = False

    # 6. 端口映射解析
    print(u"[6] 检查打印机解析...")
    try:
        name = printer.resolve_printer_name(cfg.default_printer)
        print(u"    OK: 目标打印机 = %s" % (name or u"(未找到)"))
    except Exception as exc:
        print(u"    FAIL: %s" % exc)
        ok = False

    print(u"-" * 50)
    if ok:
        print(u"自检完成: 全部通过")
        return 0
    print(u"自检完成: 存在问题")
    return 1


if __name__ == "__main__":
    sys.exit(main())
