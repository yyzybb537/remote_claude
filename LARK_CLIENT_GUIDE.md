# 飞书客户端管理指南

本指南介绍如何使用 Remote Claude 的飞书客户端管理功能。

## 🚀 快速开始

### 启动飞书客户端

```bash
python3 remote_claude.py lark start
```

**输出示例：**
```
正在启动飞书客户端...
✓ 飞书客户端已启动
  PID: 12345
  日志: /path/to/lark_client.log

使用 'python3 remote_claude.py lark status' 查看状态
使用 'python3 remote_claude.py lark stop' 停止
```

**特性：**
- ✅ 后台运行，关闭终端后进程继续运行
- ✅ 日志自动追加到 `lark_client.log`
- ✅ 进程崩溃会记录到日志

### 查看运行状态

```bash
python3 remote_claude.py lark status
```

**输出示例：**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
飞书客户端状态
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
状态:     运行中 ✓
PID:      12345
启动时间: 2026-03-03 14:30:15
运行时长: 2小时35分钟
日志文件: /path/to/lark_client.log
日志大小: 123.4 KB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

最近日志:
----------------------------------------
  [INFO] 飞书客户端已启动
  [INFO] 用户 ou_xxx 发送消息: /attach demo
  [INFO] 用户 ou_xxx attach 到会话 demo
  [INFO] 发送消息到飞书成功
  [INFO] 收到会话输出: 100 字节
----------------------------------------
```

### 停止飞书客户端

```bash
python3 remote_claude.py lark stop
```

**输出示例：**
```
正在停止飞书客户端 (PID: 12345)...
✓ 飞书客户端已停止
```

**行为：**
- 发送 SIGTERM 信号，等待进程优雅退出（最多 5 秒）
- 如果进程未响应，强制 SIGKILL
- 自动清理 PID 和状态文件

### 重启飞书客户端

```bash
python3 remote_claude.py lark restart
```

等同于先执行 `stop`，再执行 `start`。

## 📊 状态文件说明

飞书客户端运行时会创建以下文件：

| 文件路径 | 说明 | 格式 |
|---------|------|------|
| `/tmp/remote-claude/lark.pid` | 进程 PID | 纯文本，一行 |
| `/tmp/remote-claude/lark.status` | 状态信息 | JSON 格式 |
| `lark_client.log` | 运行日志 | 纯文本，追加写入 |

**状态文件格式：**
```json
{
  "pid": 12345,
  "start_time": 1709481234.567
}
```

## 🔍 日志查看

### 实时查看日志

```bash
tail -f lark_client.log
```

### 查看最近 50 行日志

```bash
tail -50 lark_client.log
```

### 搜索日志中的错误

```bash
grep ERROR lark_client.log
```

### 清空日志（谨慎操作）

```bash
> lark_client.log
```

## ⚠️ 常见问题

### 1. 启动失败："✗ 启动失败，请查看日志"

**原因：**
- 配置文件 `.env` 不存在或配置错误
- 飞书应用权限未正确配置
- 端口被占用

**解决方案：**
```bash
# 查看日志
tail -20 lark_client.log

# 检查配置
cat .env

# 检查飞书应用配置（开放平台）
```

### 2. 进程启动后立即退出

**检查步骤：**
```bash
# 1. 查看日志
cat lark_client.log

# 2. 手动前台运行，查看错误
python3 lark_client/main.py
```

常见原因：
- `.env` 中的 App ID 或 Secret 错误
- 飞书应用未启用或被禁用
- Python 依赖未安装

### 3. status 显示"飞书客户端未运行"，但进程存在

**原因：** PID 文件损坏或被删除

**解决方案：**
```bash
# 1. 查找进程
ps aux | grep "lark_client/main.py"

# 2. 手动终止
kill -9 <PID>

# 3. 清理残留文件
rm -f /tmp/remote-claude/lark.pid
rm -f /tmp/remote-claude/lark.status

# 4. 重新启动
python3 remote_claude.py lark start
```

### 4. 日志文件过大

**查看日志大小：**
```bash
ls -lh lark_client.log
```

**归档旧日志：**
```bash
# 1. 停止客户端
python3 remote_claude.py lark stop

# 2. 归档日志
mv lark_client.log lark_client.log.$(date +%Y%m%d_%H%M%S)

# 3. 重新启动
python3 remote_claude.py lark start
```

**或使用 logrotate（推荐）：**
```bash
# 创建 logrotate 配置
cat > /etc/logrotate.d/remote-claude << EOF
/path/to/remote_claude/lark_client.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
```

### 5. 无法停止进程

**强制终止：**
```bash
# 获取 PID
cat /tmp/remote-claude/lark.pid

# 强制终止
kill -9 <PID>

# 清理文件
python3 remote_claude.py lark stop
```

## 🔄 开机自启动（可选）

### macOS（launchd）

创建 `~/Library/LaunchAgents/com.remote-claude.lark.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.remote-claude.lark</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/remote_claude/remote_claude.py</string>
        <string>lark</string>
        <string>start</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/remote_claude</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/remote_claude/lark_client.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/remote_claude/lark_client.log</string>
</dict>
</plist>
```

加载：
```bash
launchctl load ~/Library/LaunchAgents/com.remote-claude.lark.plist
```

### Linux（systemd）

创建 `/etc/systemd/system/remote-claude-lark.service`：

```ini
[Unit]
Description=Remote Claude Lark Client
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/remote_claude
ExecStart=/usr/bin/python3 /path/to/remote_claude/remote_claude.py lark start
ExecStop=/usr/bin/python3 /path/to/remote_claude/remote_claude.py lark stop
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用：
```bash
sudo systemctl daemon-reload
sudo systemctl enable remote-claude-lark
sudo systemctl start remote-claude-lark

# 查看状态
sudo systemctl status remote-claude-lark
```

## 📈 监控和健康检查

### 简单监控脚本

创建 `monitor_lark.sh`：

```bash
#!/bin/bash

while true; do
    if ! python3 remote_claude.py lark status > /dev/null 2>&1; then
        echo "[$(date)] 飞书客户端未运行，正在重启..." | tee -a monitor.log
        python3 remote_claude.py lark start
    fi
    sleep 60
done
```

后台运行：
```bash
nohup ./monitor_lark.sh > /dev/null 2>&1 &
```

### 健康检查 API

可以在 `lark_client/main.py` 中添加健康检查端点（未实现）：

```python
# 伪代码
@app.route('/health')
def health():
    return {'status': 'ok', 'uptime': get_uptime()}
```

## 🔧 高级用法

### 多实例运行（不推荐）

目前不支持同时运行多个飞书客户端实例。如果需要，可以：
1. 修改 PID 文件路径，使用不同的前缀
2. 配置不同的飞书应用
3. 使用不同的日志文件

### 自定义日志路径

在启动时设置环境变量：

```bash
LARK_LOG_FILE=/custom/path/lark.log python3 remote_claude.py lark start
```

（需要在代码中支持此环境变量，当前未实现）

## 📞 获取帮助

如果遇到其他问题：

1. 查看完整文档：[CLAUDE.md](./CLAUDE.md)
2. 提交 Issue：[GitHub Issues](https://github.com/yourusername/remote_claude/issues)
3. 查看测试脚本：`test_lark_management.sh`

---

祝使用愉快！🚀
