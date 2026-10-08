# WinPrintServer 架构设计

## 1. 系统概述

WinPrintServer 是一个运行在 Windows 主机上的网络打印服务器。它将本机已安装的打印机（USB/并口/网络直连）通过 TCP 网络协议暴露给局域网客户端，使客户端无需共享打印机即可远程打印。

### 设计目标

1. **兼容性**：支持 Windows 7/10/11，客户端支持 Windows/Linux/macOS
2. **简单可靠**：尽量依赖标准库，降低部署门槛
3. **协议标准**：实现业界通用的 RAW 9100 与 LPD 协议
4. **可运维**：日志、Web 状态页、Windows 服务

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                        WinPrintServer                        │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ RAW Server  │  │ LPD Server  │  │ Web UI      │          │
│  │ TCP :9100   │  │ TCP :515    │  │ HTTP :8080  │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                │                │                  │
│         └────────────────┼────────────────┘                  │
│                          ▼                                   │
│                 ┌─────────────────┐                          │
│                 │   Job Manager   │  任务/统计/历史           │
│                 └────────┬────────┘                          │
│                          ▼                                   │
│                 ┌─────────────────┐                          │
│                 │ Printer Module  │  winspool.drv / pywin32  │
│                 └────────┬────────┘                          │
│                          │                                   │
└──────────────────────────┼───────────────────────────────────┘
                           ▼
                  Windows Print Spooler
                           │
                           ▼
                    Physical Printer
                     (LQ-630K ...)
```

---

## 3. 模块说明

### 3.1 `server/config.py`

- 解析 `config.ini`
- 提供类型化配置访问（int/bool/属性）
- 支持端口到打印机的映射表

### 3.2 `server/printer.py`

Windows 打印机输出的统一接口：

- **优先**：`pywin32` 的 `win32print`
- **回退**：`ctypes` 直接调用 `winspool.drv`

关键 API 调用序列：

```
OpenPrinter()
  → StartDocPrinter()
    → StartPagePrinter()
      → WritePrinter()  # 循环写入
    → EndPagePrinter()
  → EndDocPrinter()
ClosePrinter()
```

数据类型固定为 `RAW`，保证 ESC/P 等指令原样透传。

### 3.3 `server/job.py`

线程安全的任务管理器：

- 创建任务记录（ID、客户端 IP、协议、打印机、大小）
- 状态流转：`pending → printing → done / failed`
- 保留最近 N 条历史（默认 200）
- 提供统计：成功/失败数、累计字节、活动连接数

### 3.4 `server/raw_server.py`（核心）

实现 **JetDirect / RAW TCP 9100** 协议：

```
Client                          Server
  │                               │
  │──── TCP SYN ─────────────────►│  accept
  │                               │
  │──── ESC/P / PCL data ────────►│  recv 循环
  │──── more data ───────────────►│
  │                               │──► WritePrinter(data)
  │──── FIN ─────────────────────►│  连接关闭 = 作业结束
  │                               │──► EndDocPrinter()
```

特点：
- 无握手，连接即开始接收
- 连接关闭标志作业结束
- 支持作业大小上限（默认 200MB）
- 支持 IP 白名单 / CIDR / 通配符

### 3.5 `server/lpd_server.py`

实现 **RFC 1179 LPD/LPR** 协议：

```
Client                          Server
  │                               │
  │── \x02 + queue + \n ─────────►│  接收作业请求
  │◄────── \x00 ─────────────────│  接受
  │                               │
  │── \x02 + size + cfAxxx ──────►│  控制文件头
  │── control file content ──────►│
  │◄────── \x00 ─────────────────│
  │                               │
  │── \x03 + size + dfAxxx ──────►│  数据文件头
  │── print data content ────────►│  原始打印数据
  │◄────── \x00 ─────────────────│
  │                               │──► WritePrinter(data)
```

将数据文件（`dfA*`）内容转发到打印机；控制文件仅记录日志。

### 3.6 `server/web_ui.py`

基于 `http.server` 的状态页与 JSON API：

| 路径 | 说明 |
|------|------|
| `/` | HTML 状态面板（自动刷新） |
| `/api/status` | 服务器状态 JSON |
| `/api/jobs` | 任务列表 JSON |
| `/api/printers` | 打印机列表 JSON |
| `/health` | 健康检查 |

### 3.7 `print_server.py`

主入口，负责：

- 解析命令行
- 加载配置、初始化日志
- 启动各服务线程
- 信号处理与优雅退出
- 服务安装/卸载

---

## 4. 数据流

一次完整打印：

```
1. 客户端发起 TCP 连接 → server IP:9100
2. RawPrintServer accept 连接
3. 校验客户端 IP（allowed_ips）
4. JobManager 创建任务记录 (pending)
5. 循环 recv 累积数据
6. 连接关闭，得到完整 data
7. JobManager 标记 printing
8. printer.print_raw_data(data)
     → WindowsPrinter.open()
     → WindowsPrinter.write(data)
     → WindowsPrinter.close()
9. 成功 → mark_done(bytes)
   失败 → mark_failed(error)
10. 日志记录
```

---

## 5. 并发模型

- **接受线程**：每个协议一个 accept 循环
- **处理线程**：每个客户端连接一个独立线程
- **写入锁**：`WindowsPrinter` 内部互斥锁，避免交叉写入
- **任务管理锁**：`JobManager` 全局锁保护统计与历史

建议 `max_connections` 根据机器性能调整（默认 50）。

---

## 6. 安全考虑

| 风险 | 措施 |
|------|------|
| 未授权访问 | `allowed_ips` 白名单 |
| 超大作业耗尽内存 | `MAX_JOB_BYTES` 上限（200MB） |
| 连接耗尽 | `max_connections` + `job_timeout` |
| 敏感数据 | 日志不记录打印内容，仅元数据 |
| 端口暴露 | 建议防火墙仅对内网网段开放 |

---

## 7. Windows 7 兼容性

| 项目 | 说明 |
|------|------|
| Python | 最高 3.8.10 |
| 语法 | 使用 `from __future__ import print_function` |
| 编码 | 文件 UTF-8，日志 UTF-8 |
| API | `winspool.drv` 自 Vista 起稳定 |
| TLS/新特性 | 不依赖 Python 3.7+ 的 asyncio 等 |

---

## 8. 扩展点

1. **多打印机路由**：已支持 `port_map`，可扩展按队列名路由
2. **作业持久化**：可将 `JobManager` 接入 SQLite
3. **IPP 协议**：可增加 `ipp_server.py`（端口 631）
4. **用户认证**：预留 `security.require_auth`
5. **打印配额**：在 `JobManager` 中增加配额检查

---

## 9. 性能参考

| 场景 | 预期 |
|------|------|
| 单任务 10KB 发票 | 端到端 < 500ms |
| 并发 20 连接 | 正常 |
| 单任务 50MB 报表 | 正常，受打印机速度限制 |
| 内存占用 | 空闲约 20-40MB |

瓶颈通常在打印机本身（针式打印机速度有限）与 Windows Spooler。

---

## 10. 依赖说明

| 依赖 | 必须 | 用途 |
|------|------|------|
| Python 3.6+ | 是 | 运行环境 |
| 标准库 | 是 | socket / threading / http.server / ctypes |
| pywin32 | 推荐 | 服务模式、更稳定的打印 API |
| PyInstaller | 可选 | 打包单文件 exe |
