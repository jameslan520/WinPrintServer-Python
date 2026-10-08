# WinPrintServer — Windows 网络打印服务器

将 Windows 主机上的本地打印机（如 **LQ-630K 针式打印机**）转换为**网络打印服务器**，局域网内客户端可直接连接打印。

兼容 **Windows 7 / 10 / 11**。

---

## 功能特性

| 功能 | 说明 |
|------|------|
| **RAW TCP 9100** | 标准 JetDirect 协议，Windows「标准 TCP/IP 端口」直接可用 |
| **LPD/LPR 515** | Unix/Linux/macOS 与 Windows LPR 端口监视器 |
| **Web 状态页** | 浏览器查看运行状态、打印机列表、最近任务 |
| **多打印机** | 支持端口映射，不同端口对应不同打印机 |
| **访问控制** | 可限制允许连接的客户端 IP |
| **Windows 服务** | 可安装为系统服务，开机自启 |
| **任务日志** | 完整记录每次打印的来源、大小、状态 |

---

## 系统要求

- Windows 7 SP1 / Windows 10 / Windows 11
- Python 3.6+（推荐 3.8，Windows 7 最高支持 3.8）
- 已安装打印机驱动（如 LQ-630K）
- 建议安装 `pywin32`（服务模式必需，打印机访问更稳定）

---

## 快速开始

### 1. 安装 Python 依赖

```bat
pip install -r requirements.txt
```

或仅安装可选依赖：

```bat
pip install pywin32
```

### 2. 查看本机打印机

```bat
python print_server.py --list-printers
```

记下打印机名称（例如 `LQ-630K`）。

### 3. 配置打印机

编辑 `config.ini`：

```ini
[printer]
# 填入上一步看到的打印机名称
default_printer = LQ-630K
```

### 4. 启动服务器

**前台运行（调试）：**

```bat
python print_server.py
```

或双击 `scripts\start.bat`。

**安装为 Windows 服务（推荐生产环境）：**

以管理员身份运行：

```bat
scripts\install_service.bat
```

### 5. 查看状态

浏览器打开：

```
http://localhost:8080
```

或从其他电脑访问 `http://<服务器IP>:8080`。

---

## 客户端连接方法

### Windows 客户端（推荐：标准 TCP/IP 端口）

1. 打开 **控制面板 → 设备和打印机 → 添加打印机**
2. 选择 **「添加本地打印机」**（不是网络打印机）
3. 选择 **「创建新端口」** → 端口类型选 **「Standard TCP/IP Port」**
4. 主机名或 IP 填服务器地址，例如 `192.168.1.100`
   - 端口名会自动填为 `192.168.1.100`（可自定义）
   - 点击下一步后，确保 **端口号为 9100**
5. 安装打印机驱动（选择与服务端相同的型号，如 **Epson LQ-630K**）
6. 完成后即可打印

> **注意**：客户端必须安装对应的打印机驱动。服务端转发的是原始数据，驱动负责生成打印指令。

### Windows 客户端（备选：LPR）

1. 先在「启用或关闭 Windows 功能」中勾选 **「打印和文件服务 → LPD 打印服务 + LPR 端口监视器」**
2. 添加打印机 → 添加本地打印机 → 创建新端口 → **「LPR Port」**
3. 服务器地址填服务器 IP，队列名任意（如 `lp`）
4. 需在服务器端开启 LPD：`config.ini` 中 `enable_lpd = true`

### Linux 客户端（CUPS）

```bash
lpadmin -p LQ630K -E \
  -v socket://192.168.1.100:9100 \
  -m epson-escp2-lq630k
```

或使用 LPD：

```bash
lpadmin -p LQ630K -E -v lpd://192.168.1.100/lp
```

### 打印测试

客户端执行：

```bat
echo Hello from network printer > \\.\LPT1
copy test.txt \\.\LPT1
```

或在任意软件中直接打印测试页。

---

## 配置说明

完整配置见 `config.ini`，关键项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `host` | `0.0.0.0` | 监听地址，`0.0.0.0` 表示所有网卡 |
| `raw_port` | `9100` | RAW 打印协议端口 |
| `lpd_port` | `515` | LPD 协议端口 |
| `web_port` | `8080` | Web 状态页端口 |
| `enable_raw` | `true` | 启用 RAW 服务 |
| `enable_lpd` | `false` | 启用 LPD 服务 |
| `enable_web` | `true` | 启用 Web 状态页 |
| `default_printer` | 空 | 目标打印机名称，空则用系统默认 |
| `port_map` | 空 | 多打印机映射，如 `9100=LQ-630K,9101=HP` |
| `allowed_ips` | `*` | 允许的客户端 IP |
| `job_timeout` | `300` | 任务超时（秒） |

### 多打印机示例

```ini
[printer]
default_printer = LQ-630K
port_map = 9100=LQ-630K,9101=HP LaserJet 1020,9102=Zebra GK888
```

客户端连接 `IP:9100` → LQ-630K，`IP:9101` → HP，`IP:9102` → Zebra。

---

## 命令行参数

```
python print_server.py [选项]

  --config, -c PATH    指定配置文件
  --list-printers      列出本机打印机
  --install            安装为 Windows 服务
  --uninstall          卸载 Windows 服务
  --version            显示版本
```

---

## Windows 服务管理

```bat
# 启动
net start WinPrintServer

# 停止
net stop WinPrintServer

# 查看状态
sc query WinPrintServer
```

服务名称：`WinPrintServer`  
显示名称：`Windows Network Print Server`

---

## 目录结构

```
printservices/
├── print_server.py          # 主程序入口
├── config.ini               # 配置文件
├── requirements.txt         # Python 依赖
├── README.md                # 本文件
├── server/                  # 核心代码
│   ├── __init__.py
│   ├── config.py            # 配置管理
│   ├── printer.py           # Windows 打印机输出
│   ├── job.py               # 打印任务管理
│   ├── raw_server.py        # RAW TCP 9100 服务器
│   ├── lpd_server.py        # LPD 515 服务器
│   └── web_ui.py            # Web 状态页
├── scripts/                 # 安装/启动脚本
│   ├── install_service.bat
│   ├── uninstall_service.bat
│   ├── start.bat
│   └── list_printers.bat
├── client/                  # 客户端连接说明
│   └── 客户端连接指南.md
├── docs/                    # 技术文档
│   └── ARCHITECTURE.md
└── logs/                    # 运行日志
    └── print_server.log
```

---

## 常见问题

### Q: 客户端无法连接？
1. 检查防火墙是否放行 TCP 9100（及 515/8080）
2. 确认服务端已启动：`net start WinPrintServer`
3. 确认服务器 IP 正确，两台机器在同一网段
4. 在服务端浏览器打开 `http://localhost:8080` 确认运行中

### Q: 提示「未找到打印机」？
1. 先在「设备和打印机」中安装好打印机驱动
2. 运行 `python print_server.py --list-printers` 确认名称
3. 在 `config.ini` 的 `default_printer` 中填入准确名称

### Q: Windows 7 安装 Python？
Windows 7 最高支持 **Python 3.8.10**，请从官网下载对应版本：
https://www.python.org/downloads/release/python-3810/

### Q: 端口 515 被占用？
Windows 自带的「LPD 打印服务」可能占用 515。请：
1. 在「启用或关闭 Windows 功能」中关闭「打印和文件服务 → LPD 打印服务」
2. 或修改 `config.ini` 中的 `lpd_port`

### Q: 如何开机自启？
安装为 Windows 服务即可（`scripts\install_service.bat`）。

### Q: 支持 PDF / 图片打印吗？
服务器转发的是**原始字节流**。客户端使用对应打印机驱动打印时，驱动会自动转换为打印机指令。一般办公软件（Word、Excel、开票软件）直接打印即可。

### Q: LQ-630K 打印乱码？
1. 确认客户端安装了 **Epson LQ-630K** 官方驱动
2. 确认打印的是 ESC/P 原始数据或经过驱动正确渲染
3. 开票类软件通常直接发送 ESC/P，此时服务端可配置为「RAW 透传」

---

## 技术架构

```
┌─────────────┐     TCP 9100      ┌──────────────────┐     Windows Spooler     ┌──────────┐
│  Windows    │ ────────────────► │  WinPrintServer  │ ──────────────────────► │ LQ-630K  │
│  客户端     │     RAW 协议       │  (本程序)        │     WritePrinter        │ 打印机   │
└─────────────┘                   │                  │                         └──────────┘
                                  │  · RAW Server    │
┌─────────────┐     TCP 515       │  · LPD Server    │
│  Linux/Unix │ ────────────────► │  · Web 状态页    │
│  客户端     │     LPD 协议       │  · 任务管理      │
└─────────────┘                   └──────────────────┘
```

详细设计见 `docs/ARCHITECTURE.md`。

---

## 许可

MIT License
