# -*- coding: utf-8 -*-
"""
配置管理模块
支持 INI 格式配置文件，兼容 Windows 7/10/11
"""
from __future__ import print_function

import os
import sys
import logging

try:
    import configparser
except ImportError:
    import ConfigParser as configparser  # type: ignore


DEFAULT_CONFIG = {
    "server": {
        "host": "0.0.0.0",
        "raw_port": "9100",
        "lpd_port": "515",
        "web_port": "8080",
        "enable_raw": "true",
        "enable_lpd": "false",
        "enable_web": "true",
        "max_connections": "50",
        "job_timeout": "300",
    },
    "printer": {
        # 默认打印机名称；留空则自动选择第一台本地打印机
        "default_printer": "",
        # 多端口映射：9100=打印机名,9101=打印机名2
        "port_map": "",
        # 写入失败重试次数
        "retry_count": "3",
        "retry_delay": "0.5",
    },
    "logging": {
        "level": "INFO",
        "file": "logs/print_server.log",
        "max_bytes": "5242880",
        "backup_count": "5",
        "console": "true",
    },
    "security": {
        # 允许访问的客户端 IP，逗号分隔；* 表示允许所有
        "allowed_ips": "*",
        # 是否要求 LPD 认证（暂不启用，预留）
        "require_auth": "false",
    },
}


class Config(object):
    """打印服务器配置"""

    def __init__(self, path=None):
        self.path = path or self._default_path()
        self._parser = configparser.ConfigParser()
        self._load()

    def _default_path(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "config.ini")

    def _load(self):
        # 先写入默认值
        for section, values in DEFAULT_CONFIG.items():
            if not self._parser.has_section(section):
                self._parser.add_section(section)
            for key, val in values.items():
                if not self._parser.has_option(section, key):
                    self._parser.set(section, key, val)

        if os.path.isfile(self.path):
            try:
                self._parser.read(self.path, encoding="utf-8")
            except TypeError:
                self._parser.read(self.path)
            except Exception as exc:
                print(u"读取配置失败: %s，使用默认配置" % exc, file=sys.stderr)

    def save(self):
        try:
            with open(self.path, "w") as f:
                self._parser.write(f)
            return True
        except Exception as exc:
            print(u"保存配置失败: %s" % exc, file=sys.stderr)
            return False

    def get(self, section, key, fallback=None):
        try:
            return self._parser.get(section, key)
        except Exception:
            if fallback is not None:
                return fallback
            return DEFAULT_CONFIG.get(section, {}).get(key, "")

    def getint(self, section, key, fallback=0):
        try:
            return self._parser.getint(section, key)
        except Exception:
            try:
                return int(DEFAULT_CONFIG[section][key])
            except Exception:
                return fallback

    def getfloat(self, section, key, fallback=0.0):
        try:
            return self._parser.getfloat(section, key)
        except Exception:
            try:
                return float(DEFAULT_CONFIG[section][key])
            except Exception:
                return fallback

    def getbool(self, section, key, fallback=False):
        try:
            return self._parser.getboolean(section, key)
        except Exception:
            val = DEFAULT_CONFIG.get(section, {}).get(key, "")
            return str(val).lower() in ("1", "true", "yes", "on")

    # ---- 常用属性 ----

    @property
    def host(self):
        return self.get("server", "host") or "0.0.0.0"

    @property
    def raw_port(self):
        return self.getint("server", "raw_port", 9100)

    @property
    def lpd_port(self):
        return self.getint("server", "lpd_port", 515)

    @property
    def web_port(self):
        return self.getint("server", "web_port", 8080)

    @property
    def enable_raw(self):
        return self.getbool("server", "enable_raw", True)

    @property
    def enable_lpd(self):
        return self.getbool("server", "enable_lpd", False)

    @property
    def enable_web(self):
        return self.getbool("server", "enable_web", True)

    @property
    def max_connections(self):
        return self.getint("server", "max_connections", 50)

    @property
    def job_timeout(self):
        return self.getint("server", "job_timeout", 300)

    @property
    def default_printer(self):
        return self.get("printer", "default_printer") or ""

    @property
    def retry_count(self):
        return self.getint("printer", "retry_count", 3)

    @property
    def retry_delay(self):
        return self.getfloat("printer", "retry_delay", 0.5)

    @property
    def allowed_ips(self):
        raw = self.get("security", "allowed_ips", "*")
        return [x.strip() for x in raw.split(",") if x.strip()]

    def port_map(self):
        """
        解析端口到打印机映射
        格式: 9100=打印机A,9101=打印机B
        返回 {port: printer_name}
        """
        raw = self.get("printer", "port_map", "")
        result = {}
        if not raw:
            return result
        for item in raw.split(","):
            item = item.strip()
            if not item or "=" not in item:
                continue
            port_s, name = item.split("=", 1)
            try:
                port = int(port_s.strip())
            except ValueError:
                continue
            name = name.strip()
            if name:
                result[port] = name
        return result

    def resolve_printer(self, port=None):
        """根据端口解析目标打印机名称"""
        mapping = self.port_map()
        if port and port in mapping:
            return mapping[port]
        return self.default_printer


def setup_logging(cfg):
    """根据配置初始化日志"""
    level_name = (cfg.get("logging", "level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_file = cfg.get("logging", "file") or "logs/print_server.log"
    if not os.path.isabs(log_file):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_file = os.path.join(base, log_file)

    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.isdir(log_dir):
        try:
            os.makedirs(log_dir)
        except Exception:
            pass

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    # 清除旧 handler，避免重复
    for h in list(root.handlers):
        root.removeHandler(h)

    try:
        from logging.handlers import RotatingFileHandler

        max_bytes = cfg.getint("logging", "max_bytes", 5 * 1024 * 1024)
        backup = cfg.getint("logging", "backup_count", 5)
        fh = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    if cfg.getbool("logging", "console", True):
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        root.addHandler(ch)

    return root
