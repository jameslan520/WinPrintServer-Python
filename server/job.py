# -*- coding: utf-8 -*-
"""
打印任务管理
记录任务状态、字节数、耗时，供 Web 状态页与日志使用
"""
from __future__ import print_function

import time
import threading
import logging
from collections import OrderedDict

logger = logging.getLogger("job")

# 任务状态
STATUS_PENDING = "pending"
STATUS_PRINTING = "printing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class PrintJob(object):
    """单个打印任务"""

    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, client_ip, protocol, printer_name, data=None):
        with PrintJob._seq_lock:
            PrintJob._seq += 1
            self.id = PrintJob._seq
        self.client_ip = client_ip
        self.protocol = protocol  # raw / lpd
        self.printer_name = printer_name
        self.size = len(data) if data else 0
        self.status = STATUS_PENDING
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.error = ""
        self.bytes_written = 0

    def to_dict(self):
        duration = 0
        if self.started_at and self.finished_at:
            duration = round(self.finished_at - self.started_at, 3)
        elif self.started_at:
            duration = round(time.time() - self.started_at, 3)
        return {
            "id": self.id,
            "client_ip": self.client_ip,
            "protocol": self.protocol,
            "printer": self.printer_name,
            "size": self.size,
            "status": self.status,
            "created_at": self.created_at,
            "duration": duration,
            "error": self.error,
            "bytes_written": self.bytes_written,
        }


class JobManager(object):
    """打印任务管理器（线程安全）"""

    def __init__(self, max_history=200):
        self._lock = threading.Lock()
        self._jobs = OrderedDict()  # id -> PrintJob
        self._max_history = max_history
        self._stats = {
            "total_jobs": 0,
            "success_jobs": 0,
            "failed_jobs": 0,
            "total_bytes": 0,
            "started_at": time.time(),
            "active_connections": 0,
        }

    def create(self, client_ip, protocol, printer_name, data=None):
        job = PrintJob(client_ip, protocol, printer_name, data)
        with self._lock:
            self._jobs[job.id] = job
            self._stats["total_jobs"] += 1
            # 修剪历史
            while len(self._jobs) > self._max_history:
                self._jobs.popitem(last=False)
        logger.info(
            u"新建任务 #%d 客户端=%s 协议=%s 打印机=%s 大小=%d",
            job.id,
            client_ip,
            protocol,
            printer_name,
            job.size,
        )
        return job

    def mark_printing(self, job):
        with self._lock:
            job.status = STATUS_PRINTING
            job.started_at = time.time()

    def mark_done(self, job, bytes_written=0):
        with self._lock:
            job.status = STATUS_DONE
            job.finished_at = time.time()
            job.bytes_written = bytes_written
            self._stats["success_jobs"] += 1
            self._stats["total_bytes"] += bytes_written
        logger.info(u"任务 #%d 完成 写入=%d 字节", job.id, bytes_written)

    def mark_failed(self, job, error):
        with self._lock:
            job.status = STATUS_FAILED
            job.finished_at = time.time()
            job.error = str(error)
            self._stats["failed_jobs"] += 1
        logger.warning(u"任务 #%d 失败: %s", job.id, error)

    def connection_opened(self):
        with self._lock:
            self._stats["active_connections"] += 1

    def connection_closed(self):
        with self._lock:
            if self._stats["active_connections"] > 0:
                self._stats["active_connections"] -= 1

    def get_stats(self):
        with self._lock:
            stats = dict(self._stats)
            stats["pending"] = sum(
                1 for j in self._jobs.values() if j.status == STATUS_PENDING
            )
            stats["printing"] = sum(
                1 for j in self._jobs.values() if j.status == STATUS_PRINTING
            )
            return stats

    def get_jobs(self, limit=50):
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.id, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def get_job(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)


# 全局单例
job_manager = JobManager()
