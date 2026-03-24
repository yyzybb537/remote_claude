# 修复启动命令错误传播设计

## 问题背景

Docker 测试脚本中的负面测试失败：当配置无效命令时，`remote-claude start` 未正确返回失败退出码。

### 根本原因

`run_client()` 连接失败时仅返回（不抛异常），导致 `cmd_start` 返回 0（成功）：

```python
# client/client.py
async def run(self):
    if not await self.connect():
        return  # 直接返回，无错误码

# remote_claude.py
def cmd_start(args):
    ...
    run_client(session_name)
    return 0  # 始终返回成功
```

### 影响范围

- 负面测试无法正确检测无效命令配置
- 用户无法通过退出码判断启动是否成功

## 设计方案

### 核心修改

让 `run()` 和 `run_client()` 返回退出码，`cmd_start` 传递该退出码。

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `client/client.py` | `run()` 返回 int；`run_client()` 返回 int |
| `remote_claude.py` | `cmd_start` 返回 `run_client()` 的值 |

### 详细设计

**1. `client/client.py`**

```python
async def run(self) -> int:
    """运行客户端，返回退出码（0=成功，非零=失败）"""
    if not await self.connect():
        return 1  # 连接失败

    self.running = True
    ...
    try:
        await asyncio.gather(...)
    finally:
        self._cleanup()

    return 0  # 正常退出


def run_client(session_name: str) -> int:
    """运行客户端，返回退出码"""
    client = RemoteClient(session_name)
    try:
        return asyncio.run(client.run())
    except KeyboardInterrupt:
        return 130  # 128 + SIGINT(2)，Unix 惯例
```

**2. `remote_claude.py`**

```python
def cmd_start(args):
    ...
    from client.client import run_client
    return run_client(session_name)
```

### 退出码定义

| 场景 | 返回码 | 说明 |
|------|--------|------|
| 正常退出 | 0 | 用户 Ctrl+D 或会话正常结束 |
| 连接失败 | 1 | socket 不存在或服务器已关闭 |
| 用户中断 | 130 | Ctrl+C (128 + SIGINT) |

## 测试验证

修改后，负面测试应能正确检测到无效命令：

```bash
# 配置无效命令
jq '.ui_settings.custom_commands.commands[0].command = "claudeyy"' config.json

# 启动应返回非零
remote-claude start test
echo $?  # 应为 1
```

## 风险评估

- **影响范围小**：仅修改退出码传播逻辑
- **向后兼容**：调用方通常只检查零/非零，不依赖具体值
- **无破坏性变更**：正常流程行为不变
