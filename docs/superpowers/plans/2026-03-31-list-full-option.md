# list 命令 --full 选项 + shell 入口 -h/--help 参数实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `list` 命令添加 `--full` 选项显示完整名称，为 `bin/remote-claude` 添加 `-h`/`--help` 参数显示命令概览

**Architecture:** 修改 Python 端的参数解析和输出逻辑，在 shell 入口添加帮助处理分支

**Tech Stack:** Python argparse, POSIX shell

---

## Task 1: 为 list 命令添加 --full 参数

**Files:**
- Modify: `remote_claude.py:1375-1377`

- [ ] **Step 1: 添加 --full 参数到 list_parser**

在 `remote_claude.py` 第 1375 行附近，为 `list_parser` 添加 `--full` 参数：

```python
    # list 命令
    list_parser = subparsers.add_parser("list", help="列出所有会话")
    list_parser.add_argument("--full", action="store_true", help="显示完整名称（不截断）")
    add_remote_args(list_parser)
    list_parser.set_defaults(func=cmd_list)
```

- [ ] **Step 2: 验证参数解析**

运行命令验证参数添加成功：
```bash
uv run python remote_claude.py list --help
```

预期输出包含：
```
  --full    显示完整名称（不截断）
```

---

## Task 2: 修改 cmd_list 函数支持 --full 选项

**Files:**
- Modify: `remote_claude.py:539-592`

- [ ] **Step 1: 修改 cmd_list 函数，添加动态宽度逻辑**

将 `cmd_list` 函数（第 539-592 行）替换为以下实现：

```python
def cmd_list(args):
    """列出所有会话（支持远程模式）"""
    # 远程模式
    if getattr(args, 'remote', False):
        result = validate_remote_args(args)
        if result is None:
            return 1
        host, port, session, token = result
        _log_remote_args("list", host, port, session or 'list', token)
        return run_remote_control(host, port, session or 'list', token, 'list')

    # 本地模式
    sessions = list_active_sessions()

    if not sessions:
        print("没有活跃的会话")
        return 0

    # 加载运行时配置获取会话映射
    from utils.runtime_config import load_runtime_config
    config = load_runtime_config()

    # ANSI 颜色码
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    RESET = "\033[0m"

    # 检查 --full 选项
    show_full = getattr(args, 'full', False)

    # 计算名称列最大宽度
    if show_full:
        name_col_width = max(len(s['name']) for s in sessions)
    else:
        name_col_width = 20

    # 计算路径列最大宽度
    def get_path(s):
        return _normalize_original_path(config.get_session_mapping(s['name']))

    if show_full:
        path_col_width = max(len(get_path(s)) for s in sessions)
    else:
        path_col_width = 52

    # 表头
    header = f"{'类型':<8} {'PID':<8} {'tmux':<6} {'名称':<{name_col_width}} {'原始路径'}"
    print("活跃会话:")
    print("-" * (8 + 8 + 6 + name_col_width + path_col_width + 4))
    print(header)
    print("-" * (8 + 8 + 6 + name_col_width + path_col_width + 4))

    for s in sessions:
        tmux_status = "是" if s["tmux"] else "否"
        cli_type = s.get('cli_type', 'claude')
        session_name = s['name']
        original_path = get_path(s)

        # 根据类型选择颜色
        if cli_type == CliType.CODEX:
            cli_colored = f"{GREEN}{cli_type}{RESET}"
        else:
            cli_colored = f"{YELLOW}{cli_type}{RESET}"
        # 带颜色的字段需要单独计算宽度
        padding = " " * (8 - len(cli_type))

        # 名称显示
        if show_full:
            name_display = session_name
        else:
            name_display = session_name[:18] + ".." if len(session_name) > 20 else session_name

        # 路径显示
        if show_full:
            path_display = original_path
        else:
            path_display = original_path[:50] + ".." if len(original_path) > 52 else original_path

        print(f"{cli_colored}{padding} {s['pid']:<8} {tmux_status:<6} {name_display:<{name_col_width}} {path_display}")

    print("-" * (8 + 8 + 6 + name_col_width + path_col_width + 4))
    print(f"共 {len(sessions)} 个会话")

    return 0
```

- [ ] **Step 2: 验证默认模式（名称截断）**

运行命令：
```bash
uv run python remote_claude.py list
```

预期：名称列最多显示 20 字符，超长名称显示 `..` 后缀

- [ ] **Step 3: 验证 --full 模式（完整名称）**

运行命令：
```bash
uv run python remote_claude.py list --full
```

预期：名称列显示完整内容，表格宽度根据最长名称动态调整

- [ ] **Step 4: 提交更改**

```bash
git add remote_claude.py
git commit -m "feat(list): 添加 --full 选项显示完整会话名称

- 默认模式保持名称列截断为 20 字符
- --full 模式显示完整名称，表格宽度动态调整

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 为 bin/remote-claude 添加 -h/--help 支持

**Files:**
- Modify: `bin/remote-claude`

- [ ] **Step 1: 在 shell 入口添加帮助处理**

在 `bin/remote-claude` 文件中，找到 `lark` 子命令处理之后、`cd "$STARTUP_DIR"` 之前的位置（约第 62-64 行），添加以下代码：

```sh
# -h/--help：显示简明命令概览（在 shell 层处理，无需 Python 初始化）
case "${1:-}" in
    -h|--help)
        cat <<'EOF'
Remote Claude - 双端共享 Claude CLI 工具

命令概览：
  命令        说明                     示例
  ───────────────────────────────────────────────────────────
  start       启动新会话               remote-claude start mywork
  attach      连接到会话               remote-claude attach mywork
  list        列出所有会话             remote-claude list
  kill        终止会话                 remote-claude kill mywork
  status      显示会话状态             remote-claude status mywork
  log         查看会话日志             remote-claude log mywork
  lark        飞书客户端管理           remote-claude lark start
  config      配置管理                 remote-claude config show
  connection  远程连接配置管理         remote-claude connection list
  token       Token 管理               remote-claude token generate mywork

选项：
  --remote    远程连接模式
  --host      远程服务器地址
  --token     认证令牌

更多信息请运行: remote-claude <command> --help
EOF
        exit 0
        ;;
esac
```

- [ ] **Step 2: 验证 -h 选项**

运行命令：
```bash
bin/remote-claude -h
```

预期输出：显示命令概览表格

- [ ] **Step 3: 验证 --help 选项**

运行命令：
```bash
bin/remote-claude --help
```

预期输出：与 `-h` 相同的命令概览表格

- [ ] **Step 4: 提交更改**

```bash
git add bin/remote-claude
git commit -m "feat(cli): 添加 -h/--help 显示命令概览

在 shell 层处理 -h/--help，无需 Python 初始化

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 更新设计文档并清理

**Files:**
- Modify: `docs/superpowers/specs/2026-03-31-list-full-option-design.md`

- [ ] **Step 1: 更新设计文档状态**

在设计文档末尾添加实现状态：

```markdown
---

## 实现状态

- [x] Task 1: 为 list 命令添加 --full 参数
- [x] Task 2: 修改 cmd_list 函数支持 --full 选项
- [x] Task 3: 为 bin/remote-claude 添加 -h/--help 支持
```

- [ ] **Step 2: 提交最终更改**

```bash
git add docs/superpowers/specs/2026-03-31-list-full-option-design.md
git commit -m "docs(spec): 更新实现状态

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## 验收检查清单

- [ ] `remote-claude list` 默认行为保持不变（名称截断）
- [ ] `remote-claude list --full` 显示完整名称
- [ ] `remote-claude -h` 显示命令概览表格
- [ ] `remote-claude --help` 显示命令概览表格
- [ ] 快捷命令（cla/cl/cx/cdx）的 `-h`/`--help` 保持现有行为
