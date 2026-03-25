# CLAUDE.md/AGENTS.md

This file provides guidance to Claude-Code/Codex when working with code in this repository.

# **关键语言要求**
你必须完全使用 **简体中文** 进行交互、思考和汇报。

## 项目概述

Remote Claude 是一个双端共享 Claude/Codex CLI 工具。通过 PTY + Unix Socket 架构，支持多个终端客户端和飞书客户端并发连接同一个 Claude 或 Codex 会话，实现协作式 AI 对话。

## 架构

```
Claude/Codex CLI (PTY)
      │
  server.py         ← PTY 代理，管理进程/控制权/历史缓存
      │
  Unix Socket (/tmp/remote-claude/<name>.sock)
      │
  ┌───┴────┐
  │        │
client.py  SessionBridge (lark_client/)
(终端)     (飞书机器人)
```

**核心模块：**
- `remote_claude.py` — CLI 入口，子命令：start / attach / list / kill / lark / connect / remote / token
- `server/server.py` — PTY 代理服务器，`pty.fork()` 启动 Claude/Codex，asyncio Unix Socket 广播输出，支持 WebSocket 远程连接
- `server/parsers/claude_parser.py` — Claude CLI 终端输出解析（区域切分、Block 分类、执行状态判断）
- `server/parsers/codex_parser.py` — Codex CLI 终端输出解析（无分割线、`›` 提示符、背景色区域检测）
- `server/component_parser.py` — 向后兼容 shim（实际实现在 `server/parsers/`）
- `server/shared_state.py` — 共享内存写入（`.mq` 文件）
- `server/biz_enum.py` — 业务枚举定义（CliType：CLI 类型枚举）
- `server/token_manager.py` — Token 管理器，生成/验证/重新生成会话 Token，文件权限 0600，hash 完整性校验
- `server/ws_handler.py` — WebSocket 连接处理器，URL 参数解析、Token 认证、消息转发、连接数限制、控制命令处理
- `client/client.py` — 终端客户端，raw mode 输入转发
- `client/http_client.py` — HTTP/WebSocket 客户端，远程连接支持
- `utils/protocol.py` — 消息协议（JSON + `\n` 分隔，二进制数据 base64 编码）。9 种消息类型：INPUT / OUTPUT / CONTROL / CONTROL_RESPONSE / STATUS / HISTORY / ERROR / RESIZE
- `utils/session.py` — socket 路径管理、会话生命周期、会话名称截断
- `utils/runtime_config.py` — 运行时配置管理（session 映射、lark_group_mappings、UI 设置）
- `utils/components.py` — 控制权状态机，SHARED（默认，所有人可输入）和 EXCLUSIVE（独占）两种模式

**飞书客户端 (`lark_client/`)：**
- `main.py` — WebSocket 入口，事件分发
- `lark_handler.py` — 命令路由，以 `chat_id` 为 key 统一管理群聊/私聊的 bridge 和绑定
- `session_bridge.py` — 连接 Unix Socket，**仅负责输入发送**（send_input/send_key）和连接管理
- `shared_memory_poller.py` — **流式滚动卡片轮询器**：每秒轮询 `.mq` 共享内存，通过 hash diff 驱动 `CardSlice`/`StreamTracker` 就地更新或冻结+开新卡
- `card_builder.py` — **`build_stream_card(blocks, status_line, bottom_bar, is_frozen, agent_panel, option_block, session_name, disconnected)`**：四层结构卡片构建（内容区/状态区/交互区/菜单）+ 辅助卡片（session_list/menu/help/dir 等）；**`build_dir_card(target, entries, ...)`**：目录浏览卡片构建，含 `cli_type` 参数（默认 "claude"），根据 CLI 类型展示匹配的自定义命令按钮，未匹配时隐藏启动按钮
- `card_service.py` — 飞书卡片 API 服务（create/update/send）
- `rich_text_renderer.py` — 持久化 pyte Screen 封装（server 端实时喂入）

**Server 端数据流（全量快照架构）：**
```
PTY data → self._renderer.feed(data) → HistoryScreen(220×100, history=5000) 持久化实时更新
                                            ↓ SU/SD 正确执行（ESC[nS/ESC[nT）
                                            ↓ 滚出行 → history.top（最多 5000 行）
                                            ↓（flush 触发）
                            （开启 --debug-screen）_write_screen_debug(原始 screen) → _screen.log
                                            ↓
                                    VirtualScreen(history.top + screen.buffer)
                                            ↓
                                    ScreenParser.parse(vscreen)
                                            ↓
                                    raw components 列表
                                            ↓
                                    分拣：visible_blocks / status_line / bottom_bar
                                            ↓
                                 ┌── 时序窗口平滑 ──┐
                                 │ _FrameObs 记录原始值 │
                                 │ 平滑 status_line     │
                                 │ 平滑 block blink     │
                                 └────────┬──────────┘
                                          ↓
                                    all_blocks = visible_blocks
                                          ↓
                                    ClaudeWindow 快照
                                          ↓
                                ├→ _messages.log (debug)
                                └→ .mq 共享内存 (全量覆写)
```

> `_screen.log` 只在 CLI 传入 `--debug-screen` 时写入：每次 flush 触发后、正式解析 `pyte.Screen` 之前，`server/server.py` 会覆盖输出当前屏幕快照到 `/tmp/remote-claude/<name>_screen.log`，方便比对 blink 标记、行号与布局切分。

**输出处理管道（流式滚动卡片模型）：**
```
Server (SharedStateWriter) → .mq 文件（ClaudeWindow 全量快照）
                                 ↑ 每秒轮询
SharedMemoryPoller          → StreamTracker（流式跟踪状态）
                                 ↓ hash diff
CardService                 → 同一张卡片就地更新 / 超限时冻结+开新卡
```

核心理念：没有 turn、没有 message。只有一个不断增长的 blocks 流和跟踪它的滚动窗口。

**职责分界（强制约束）：**

| 层 | 职责 | 禁止事项 |
|----|------|---------|
| **server.py**（服务端） | 保证写入共享内存（`.mq` 文件）的 Claude 会话输出**完整、准确**；负责 ANSI 解析、终端状态还原、消息结构化 | — |
| **lark_client/**（飞书客户端） | 从共享内存内容到飞书卡片渲染的**纯展示流程** | **严禁**对内容做字符串修复、ANSI 清理、格式补全等处理；若内容有误，应修 server 端而非在客户端打补丁 |

> **原则：** 飞书客户端拿到的数据应该是已经可以直接渲染的干净内容。任何"内容不对"的问题，根因在 server 端，修复也在 server 端。

**关键设计决策：**
- **tmux 环境变量修复**：server 运行在 detached tmux 会话中，tmux 会覆盖 `TERM_PROGRAM`（改为 `tmux`）并设置 `TMUX`/`TMUX_PANE`，导致 Claude CLI 的 Ink 框架判定不支持 kitty keyboard protocol，Shift+Enter 退化为 Enter。修复方案：`cmd_start` 在构建 server_cmd 时通过 env prefix 注入原始终端变量（`TERM_PROGRAM`/`TERM_PROGRAM_VERSION`/`COLORTERM`）；`_start_pty` 在 PTY 子进程中清除 `TMUX`/`TMUX_PANE`
- **输入端**（`_forward_to_claude` / `handle_option_select`）只调用 `bridge.send_input/send_key`，不创建卡片
- **输出端**完全由 `SharedMemoryPoller` 驱动：attach 时启动轮询，detach/断线时停止
- **流式滚动窗口**：`StreamTracker` 跟踪 blocks 流，`CardSlice` 记录每张卡片的窗口位置（`start_idx`）
- **首次 attach**：取最近 `INITIAL_WINDOW=30` 个 blocks 渲染到一张卡片，更早内容通过 `/history` 查看
- **卡片超限**：`len(blocks) - start_idx > MAX_CARD_BLOCKS=50` 时冻结当前卡（灰色 header、移除状态区和按钮区），从冻结位置之后开新卡
- **群聊/私聊统一**：`_bridges[chat_id]` 和 `_chat_sessions[chat_id]` 统一管理，无需分组
- **降级机制**：update_card 失败时创建新卡片，更新 CardSlice 中的 card_id，sequence 归零
- **持久化绑定**：`~/.remote-claude/lark_chat_bindings.json`（chat_id → session_name）

**飞书卡片布局设计（四层结构）：**

```
┌─── Card Header ──────────────────────────────────────┐
│ ⏳ Thinking... (1m 30s · ↓ 2k tokens)               │ ← 状态决定颜色和标题
├──────────────────────────────────────────────────────┤
│ ❯ 帮我重构这段代码                                    │ ← 第一层：内容区
│                                                      │   ANSI → <font color> 着色
│ <font color="green">●</font> 好的，我来分析这段代码。 │ ← OutputBlock（着色 indicator + content）
│                                                      │
│ 🤔 Which approach do you prefer?                     │ ← OptionBlock 问题文本
│                                                      │
│ ┌────────────── grey background ───────────────────┐ │ ← 第二层：状态区
│ │ ✱ Thinking... (1m 30s · ↓ 2k tokens)             │ │   column_set grey 背景
│ │ ▶▶ bypass permissions on · esc to interrupt      │ │
│ │ 🤖 4 个后台 agent                                 │ │ ← agent_panel（summary 纯文本）
│ │ ```                                              │ │
│ │ 🤖 后台任务 (3)                                   │ │ ← agent_panel（list/detail 代码块）
│ │ ❯ 分析代码架构 (running)                          │ │
│ │   搜索相关文件 (completed)                        │ │
│ │ ```                                              │ │
│ └──────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────┐ │
│ │  1. Approach A                                   │ │ ← 第三层：交互按钮区
│ └──────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────┐ │
│ │  2. Approach B                                   │ │
│ └──────────────────────────────────────────────────┘ │
│ ──────────────────────────────────────────────────── │
│ ┌──────────────────────────────────────────────────┐ │
│ │  ⚡ 菜单                                         │ │ ← 第四层：菜单按钮
│ └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

| 层 | 内容 | 来源 | 渲染方式 |
|----|------|------|---------|
| **第一层：内容区** | 累积型 blocks | blocks 列表中的 OutputBlock / UserInput / **PlanBlock** / **SystemBlock** | OutputBlock/UserInput/SystemBlock：`_ansi_to_lark_md()` 解析 ANSI 着色为 `<font color>` markdown；PlanBlock：`_render_plan_block()` 生成 `collapsible_panel` element |
| **第二层：状态区** | 状态型组件 | status_line + bottom_bar + **agent_panel** + **option_block** 问题文本 | `column_set` grey 背景；status_line/bottom_bar 用 ANSI 着色；option_block 问题/标题文本 |
| **第三层：交互区** | 按钮 | **option_block** 的 options（降级搜索 blocks 中旧 OptionBlock/PermissionBlock） | 每个选项一个独立按钮 |
| **第四层：菜单** | 菜单入口 | 固定 | 连接时：⚡菜单 + 🔌断开 + Enter↵；断开时：⚡菜单 + 🔗重新连接 |

**各 block 类型渲染规则（`_render_block_colored`）：**
- **OutputBlock** → `{prefix}{ansi_indicator_md} {ansi_content_md}`（ANSI → `<font color>` 着色，streaming 时 prefix=⏳，无 ANSI 时回退 `_escape_md`）
- **UserInput** → `{ansi_indicator_md} {ansi_text_md}`（同上）
- **OptionBlock(sub_type="option")** → `🤔 {_escape_md(question)}`（向后兼容：blocks 中的旧 OptionBlock 也按此渲染）
- **OptionBlock(sub_type="permission")** → `🔐 {_escape_md(title)}\n{_escape_md(content)}`（向后兼容：blocks 中的旧 PermissionBlock 也按此渲染）
- **PlanBlock** → `collapsible_panel`（默认展开，header=`📋 {title}`，内容=ANSI 着色 markdown；通过 `_render_plan_block()` 直接生成 element dict，不经过 `_render_block_colored`，在 `build_stream_card` 内容区循环中单独分支处理）
- **SystemBlock** → `{ansi_indicator_md} {ansi_content_md}`（与 OutputBlock 类似，但无 streaming 前缀；首列星号字符 + 内容）

**AgentPanelBlock 渲染规则（column_set grey 状态区内）：**
- **AgentPanelBlock(summary)** → `🤖 {agent_count} 个后台 agent`（纯文本，灰色背景已区分）
- **AgentPanelBlock(list)** → ` ```\n🤖 后台任务 ({count})\n{每行: ❯/空格 name (status)}\n``` `（代码块）
- **AgentPanelBlock(detail)** → ` ```\n🤖 {type} › {name}\n{stats}\nProgress: {progress}\nPrompt: {prompt}\n``` `（代码块）

**Card Header 逻辑：**

| 状态 | Header | 颜色 |
|------|--------|------|
| disconnected=True | ⚪ 已断开 | grey |
| 有 streaming block 或 status_line | ⏳ {action} ({elapsed} · {tokens}) | orange |
| option_block(sub_type="permission") | 🔐 等待权限确认 | red |
| option_block(sub_type="option") | 🤔 等待选择 | blue |
| 已冻结（is_frozen） | 📋 会话记录 | grey |
| 全部完成 | ✅ Claude 就绪 | green |

**流式轮询数据模型：**
```python
CardSlice(card_id, sequence, start_idx, frozen)   # 一张飞书卡片对应的 blocks 窗口
StreamTracker(chat_id, session_name, cards, content_hash, reader)  # 单个 chat_id 的跟踪状态
```

**OutputWatcher 全量快照模型（server/server.py）：**

设计动机：废弃旧的增量 MessageQueue（push_new/update_tail/complete_tail 状态机）。Claude CLI 终端偶尔出现内容错乱帧，增量状态被永久污染。改为持久化 `HistoryScreen`（`self._renderer`，220×100，history=5000），PTY 数据直接实时喂入（含 SU/SD 滚动正确处理）；flush 时构建 `VirtualScreen`（history.top + buffer），直接 parse → 平滑 → 生成 `ClaudeWindow` 快照。历史行由 `HistoryScreen.history.top` 保存，resize 后 renderer 重建、历史丢失（可接受）。

**组件两大分类：**

解析产出的组件分为两类，ClaudeWindow 中分别存储：

| 分类 | 特点 | 类型 | ClaudeWindow 字段 |
|------|------|------|-------------------|
| **累积型 Block** | 随对话推进不断增长，历史保留 | OutputBlock, UserInput, PlanBlock, SystemBlock | `blocks: list` |
| **状态型组件** | 全局唯一，不累积，反映当前瞬时状态 | StatusLine, BottomBar, AgentPanelBlock, OptionBlock | 各自独立字段 |

- **累积型 Block**：出现在输出区，每个 Block 都有 `block_id` 标识，新 Block 追加到列表末尾，旧 Block 保留不动。是对话的"历史记录"。包括 OutputBlock、UserInput、PlanBlock（box-drawing 框线内容）、SystemBlock（不闪烁星号字符提示）。
- **状态型组件**：全局只有一个实例（或 None），每帧覆盖更新。StatusLine 反映执行进度，BottomBar 反映权限/agent 状态，AgentPanelBlock 反映 agent 管理面板，OptionBlock 反映当前选项交互状态。不进入 `blocks` 累积列表。

```
ClaudeWindow {
    blocks: list          ← 累积型：全部历史 blocks（OutputBlock/UserInput）
    status_line: object   ← 状态型：窗口平滑后的 StatusLine | None
    bottom_bar: object    ← 状态型：BottomBar | None（含 has_background_agents/agent_count/agent_summary）
    agent_panel: object   ← 状态型：AgentPanelBlock | None（agent 管理面板）
    option_block: object  ← 状态型：OptionBlock | None（选项交互，sub_type="option"|"permission"）
    input_area_text: str  ← 输入区 ❯ 当前文本
    timestamp: float
    layout_mode: str      ← "normal" | "option" | "detail" | "agent_list" | "agent_detail"
}
```

**Block ID 标识**（累积型 Block 专用）：用首行内容作为跨帧稳定 ID，用于累积列表合并时匹配同一 block：
- `U:{text[:80]}` — UserInput
- `O:{首行内容.strip()[:80]}` — OutputBlock

状态型组件不参与累积合并，无需 block_id。序列化标识（仅用于共享内存）：
- `AP:{agent_name[:80]}` — AgentPanelBlock(detail)
- `AP:summary:{agent_count}` — AgentPanelBlock(summary)
- `AP:list:{agent_count}` — AgentPanelBlock(list)
- `Q:{question[:80]}` — OptionBlock(sub_type="option")
- `P:{question[:80]}` — OptionBlock(sub_type="permission")

**累积列表（VirtualScreen 模式）**：`visible_blocks` 直接来自 VirtualScreen 解析（含 history.top 中已滚出的历史行），`all_blocks = visible_blocks`，不再需要 `_accumulated_blocks` 和 `_merge_blocks`。历史由 `HistoryScreen.history.top`（5000 行容量）保存，parser 通过 VirtualBuffer 透明访问。

**时序窗口平滑**（WINDOW_SECONDS=1.0）：
- 每帧记录 `_FrameObs(ts, status_line, block_blink)` 到 deque，清理过期帧
- **status_line 平滑**：窗口内最新非 None 值（防间歇消失导致闪烁）
- **block blink 平滑**：窗口内任意帧有 blink=True → 最后一个 OutputBlock 标记 is_streaming=True
- 平滑先于 VirtualScreen 解析结果写入 all_blocks（确保存储的是平滑后的值）

**PTY 静止延迟重刷**（`_do_reflush`）：
- `feed()` 每次收到数据时重置 `_reflush_handle` 定时器
- PTY 静止 WINDOW_SECONDS 后触发额外一次 `_flush()`
- 目的：窗口内旧的 blink=True 帧过期后，重刷能正确将 streaming 归零、status_line 归 None

**共享内存布局（`.mq` 文件，200MB mmap，VERSION=2）：**

```
[Header      64B] @0       magic(4B) + version(4B) + snapshot_len(4B) + sequence(4B) + 保留
[Snapshot  ~200MB] @64     JSON 序列化的 ClaudeWindow 快照（全量覆写）
```

- `SharedStateWriter.write_snapshot()` 全量序列化 ClaudeWindow 写入 mmap
- `SharedStateReader.read()` 返回快照 dict

**共享内存中每个 block dict 结构**：
```json
{
    "_type": "OutputBlock",       // 组件类型：OutputBlock / UserInput
    "block_id": "O:首行内容...",  // 稳定标识，与 _block_id() 逻辑一致
    "content": "...",             // 组件字段（因类型而异）
    "is_streaming": false,
    "start_row": 5
}
```

快照中还包含独立的 `option_block` 字段（状态型组件，非 blocks 列表元素）：
```json
{
    "_type": "OptionBlock",
    "sub_type": "permission",     // "option" | "permission"
    "block_id": "P:Do you want...",
    "title": "Bash command",
    "content": "rm -rf /tmp/test",
    "question": "Do you want to proceed?",
    "options": [{"label": "Yes", "value": "yes"}, ...]
}
```

**Block ID 前缀：** `U:` UserInput / `O:` OutputBlock / `Q:` OptionBlock(option) / `P:` OptionBlock(permission) / `AP:` AgentPanelBlock / `PL:` PlanBlock / `S:` SystemBlock

**调试文件**：
- `/tmp/remote-claude/<name>_messages.log` — ClaudeWindow 快照（每个 block 含 block_id）
- `/tmp/remote-claude/<name>_screen.log` — pyte 屏幕快照（`--debug-screen` 开启时写入）
- `/tmp/remote-claude/<name>_debug.log` — server 调试日志（需设置 `SERVER_LOG_LEVEL=DEBUG`，包含 blink 检测和 flush 耗时）

**Claude CLI 终端输出解析规则（重构版）：**

### 第一步：区域切分

终端屏幕从上到下分为 **4 个区域**：

**正常布局（2 条分割线）：**
```
┌─────────────────────────────┐
│  欢迎区域（Welcome）        │  ← 无分割线，首列均为空，通常 < 10 行，直接丢弃
│                             │
├─────────────────────────────┤  ← （欢迎区域结束后，第一个首列有字符的行起为输出区）
│  输出区域（Output）         │  ← Claude 的所有输出内容
│  ...                        │
├─────────────────────────────┤  ← 分割线 1（从底部向上第 2 条）
│  用户输入区（Input）        │  ← ❯ 提示符 + 当前输入 / 选项交互块
├─────────────────────────────┤  ← 分割线 2（从底部向上第 1 条，即最后一条）
│  底部栏（Bottom Bar）       │  ← 权限模式 / 后台任务状态
└─────────────────────────────┘
```

**权限确认布局（1 条分割线 + 编号选项）：**
```
┌─────────────────────────────┐
│  输出区域（Output）         │  ← Claude 的所有输出内容
│  ...                        │
├─────────────────────────────┤  ← 唯一的分割线
│  权限确认区域               │  ← 工具标题 + 命令详情 + "Do you want to proceed?"
│  OptionBlock(permission)    │     + 编号选项（1. Yes / 2. No 等）
└─────────────────────────────┘
```
当 Claude CLI 执行需要人工确认的工具时（如 Bash 命令），底部栏分割线消失，仅剩 1 条分割线。分割线以下含编号选项，解析为 `OptionBlock(sub_type="permission")`。`layout_mode = "option"`。

**Detail 详情布局（1 条分割线）：**
```
┌─────────────────────────────┐
│  输出区域（Output）         │  ← Claude 的全部输出（展开详情模式，显示更多内容）
│  ...                        │
├─────────────────────────────┤  ← 唯一的分割线
│  底部提示栏                 │  ← "Showing detailed transcript · ctrl+o to toggle · ctrl+e to show all"
└─────────────────────────────┘
```
用户按 ctrl+o 切换进入，输入区消失，底部只有模式提示。`layout_mode = "detail"`，检测条件：底部栏文本含 "ctrl+o to toggle"。

**Agent 列表面板布局（1 条分割线）：**
```
┌─────────────────────────────┐
│  输出区域（Output）         │
│  ...                        │
├─────────────────────────────┤  ← 唯一的分割线
│  Background tasks           │  ← 标题
│  N active agents            │
│  ❯ agent-name (running)     │  ← agent 列表（❯ 表示选中）
│    agent-name2 (completed)  │
│  ↑/↓ to select · Esc close │  ← 导航提示
└─────────────────────────────┘
```
用户按 ↓ 展开后台 agent 列表。`layout_mode = "agent_list"`，检测条件：底部文本含 "background tasks" 或 ("to select" + "esc to close")。解析为 `AgentPanelBlock(panel_type="list")`。

**Agent 详情面板布局（1 条分割线）：**
```
┌─────────────────────────────┐
│  输出区域（Output）         │
│  ...                        │
├─────────────────────────────┤  ← 唯一的分割线
│  type › agent-name          │  ← agent 类型和名称
│  2m 15s · 4.3k tokens       │  ← 统计信息
│  Progress                   │
│  正在扫描文件结构...         │
│  Prompt                     │
│  分析项目的代码架构          │
│  ← to go back · Esc close  │  ← 导航提示
└─────────────────────────────┘
```
用户在列表中按 Enter 查看 agent 详情。`layout_mode = "agent_detail"`，检测条件：底部文本含 "← to go back" + "to close"。解析为 `AgentPanelBlock(panel_type="detail")`。

**分割线识别规则：**
- 从底部往上扫描，识别最后 2 条分割线
- 判定条件：整行字符全部为横线字符（`─` `━` 等），不限制行长度
- 只找到 1 条分割线时：input_rows 为空，bottom_rows 可能包含权限确认内容

### 第二步：输出区切 Block

输出区按**第一列**是否有字符来切分 Block：
- **Block 首行** = 第一列（col=0）有非空字符的行
- **Block 内容** = 首行之后、直到下一个 Block 首行之前的所有行（**包括空行，空行是格式的一部分，必须保留**）
- **欢迎区域** = 第一个 Block 之前的内容，首列均为空，通常不超过 10 行，直接丢弃
- **Box 区域合并**：遇到 `╭`/`┌` 时进入 box 模式，持续收集直到 `╰`/`└`，整个区域作为一个 PlanBlock（不将 `│` 行各自视为独立 block 首行）；若 box 未遇到底角行（截断输出），则在循环结束时照常 append

### 第三步：Block 分类

解析产出的组件分为**累积型 Block**（进入 `blocks` 列表，历史保留）和**状态型组件**（全局唯一，每帧覆盖）。

#### 累积型 Block（输出区，随对话增长）

**输出 Block（OutputBlock）：**
- 文本回复、工具调用块、Agent/Plan 块，**三者视为同一种 OutputBlock**
- 无需识别具体工具名称，无需区分工具调用还是文本回复
- 首行首列是圆点字符（`●` `⏺` 等）

**用户输入行（UserInput）：**
- 位于**输出区**中，首列字符为 `❯`，后跟用户已提交的历史文本

**计划块（PlanBlock）：**
- Plan Mode 显示的计划内容，用 box-drawing 字符（`╭│╰` 或 `┌│└`）包裹
- 首行首列是 `╭` 或 `┌`（BOX_CORNER_TOP），整个框线区域合并为一个 block
- 解析时跳过顶/底边框行（`╭─╮` / `╰─╯`），提取 `│` 行内容并去掉左侧 `│`
- `is_streaming` 始终为 False（`╭` 不 blink）
- `block_id` 前缀 `PL:`，格式：`PL:{title[:80]}`

**系统提示块（SystemBlock）：**
- 首行首列是星号字符（STAR_CHARS 集合），但**不闪烁**（blink=False）
- 与 StatusLine 的区别：StatusLine 的星号字符闪烁（blink=True），SystemBlock 不闪烁
- 典型内容：Claude CLI 系统提示信息、上下文加载通知等（如 `✻ Using memory...`）
- `block_id` 前缀 `S:`，格式：`S:{content首行.strip()[:80]}`

**选项交互块（OptionBlock，状态型组件）：**

OptionBlock 已统一为**状态型组件**，存储在 `ClaudeWindow.option_block` 而非 `blocks` 列表。通过 `sub_type` 区分两种场景：

- **`sub_type="option"`**（选项交互）：
  - **位置：出现在用户输入区（Input 区域），2 条分割线之间**
  - 检测方式：`_has_numbered_options()` 匹配编号选项行（`❯? \d+[.)]\s+.+`），需 ≥2 行匹配
  - 找到首个编号选项行后，向前收集 tag/question，向后收集 options + description
  - `layout_mode = "option"`
  - **尾部溢出**：选项数量较多时，末尾 1-2 个选项可能越过第二条分割线出现在底部栏区域
    - 识别方法：通过**缩进一致性**和**数字编号的连续性**判断，与底部栏内容区分

- **`sub_type="permission"`**（权限确认）：
  - **触发条件：** 只有 1 条分割线（底部栏分割线消失），`_has_numbered_options()` 匹配编号选项行
  - **内容：** 工具标题行 + 命令详情 + 确认提示 + 编号选项（❯ 光标选择）
  - `layout_mode = "option"`

#### 状态型组件（全局唯一，不累积，每帧覆盖）

**状态行（StatusLine）：**
- 首行首列是闪烁的星星字符（`✱` `✶` `✷` 等旋转动画字符集）
- 固定出现在输出区**尾部**，可能有多行（当有待执行任务列表时）
- 状态行消失 → 当前任务已完成（特例：底部栏显示仍有子任务时除外）

**底部栏（BottomBar）：**
- 终端最底部的状态栏（权限模式、后台任务状态等）
- 正常布局下含 agent 信息时（如 "4 local agents · ↓ to manage"），填充 `has_background_agents`/`agent_count`/`agent_summary` 字段

**Agent 管理面板块（AgentPanelBlock）：**
- **摘要模式（`panel_type="summary"`）：** 正常 2 条分割线布局，底部栏含 agent 信息（如 "4 local agents · ↓ to manage"）。面板未展开，但 `agent_panel` 不为 None，server 端自动从 BottomBar agent 信息生成 summary 型 AgentPanelBlock
- **列表模式（`panel_type="list"`）：** 1 条分割线，含 "Background tasks" 标题、agent 列表（name + status）、导航提示
- **详情模式（`panel_type="detail"`）：** 1 条分割线，含 "type › name" 首行、统计信息、Progress/Prompt section

### 第四步：执行状态判断

**规则：通过 Block 首行首列字符是否闪烁（blink）来判断，而不是通过内容文字。**

- 首行首列字符 **blink=true** → 该 Block 正在执行中（is_streaming=True）
- 首行首列字符 **blink=false** → 该 Block 已完成（is_streaming=False）

**闪烁检测的帧间持久化策略（重要）：**

正在执行中的 OutputBlock，其首行首列圆点会**时有时无地闪烁**（pyte 快照可能恰好抓到无字符的帧）。处理方案：

- **抓到圆点字符时**：记录该圆点所在的行号及完整行内容到持久缓存（`dot_row_cache`），key 为行号
- **抓到圆点消失的帧时**：该行首列为空，回查 `dot_row_cache` 中对应行号的记录，判断该行实为闪烁中的圆点行（is_streaming=True），并沿用缓存的行内容
- **缓存失效条件**：当 Block 确认完成（blink=false 稳定出现）后，清除对应行的缓存记录
- **布局模式切换时清空整个缓存**：`dot_row_cache` 以行号为 key，但 detail 和 normal 模式下同一行号对应不同内容（detail 模式输出区更大、行号整体上移）。切换时若不清空，残留行号会被误判为"闪烁隐去帧"，产生幽灵 block header 导致 block 重复。采用单一 cache + 模式切换时 `clear()` 的方案，比双缓存（normal/detail 各一份）更简单可靠
- 闪烁频率不固定（可能 1 秒 1 次或 1 秒 2 次），不可依赖固定频率；需结合状态行是否存在辅助判断

---

**Codex CLI 终端输出解析规则（`server/parsers/codex_parser.py`）：**

Codex 与 Claude Code 的终端布局有本质差异，由 `CodexParser` 单独处理。

### Codex 终端布局（实测）

```
┌─────────────────────────────────────────────────────────┐
│  （大量空行）                                            │  ← 欢迎框上方空行，直接跳过
│                                                         │
│ ╭─────────────────────────────────────────────────────╮ │  ← 欢迎框（无固定行号，
│ │ >_ OpenAI Codex (v0.114.0)                          │ │     首列 ╭，第一个非空内容）
│ │  model:     gpt-5.1-codex-2025-11-13 high           │ │
│ │  directory: ~/dev/...                               │ │
│ ╰─────────────────────────────────────────────────────╯ │
│   Tip: New Build faster with the Codex App...           │  ← Tip 行（缩进，跳过）
│                                                         │
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  ← 纯背景色行（无文字，整行 bg）
│ › Output: user typed this                               │  ← 历史 UserInput（› U+203A）
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  ← 纯背景色行
│                                                         │
│ •  Codex response here                                  │  ← OutputBlock（• 圆点）
│                                                         │
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  ← 背景色区域上边界（纯背景色，无字符）
│ › current input text here                               │  ← 背景色区域内容行（› 白色/亮色）
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  ← 背景色区域下边界（纯背景色，无字符）
│   gpt-5.1-codex-2025-11-13 high · 100% left · ~/dev/   │  ← 底部栏（有文字的 bg 行，不属于背景色区域）
└─────────────────────────────────────────────────────────┘
```

**选项交互布局（连续同背景色区域 + 编号选项）：**

```
┌─────────────────────────────────────────────────────────┐
│  输出区域（Output）                                      │
│  ...                                                    │
│  ─────────────────────────────────────────────────────  │ ← 普通分割线（bg分割线上上行出现）
│                                                         │
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← 背景色区域上边界（纯背景色，无字符）
│  Implement this plan?                                   │ ← 内容行（有 bg）
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← 内容行（纯背景色，外观同上下边界！）
│  1. Yes, implement this plan  Switch to Default...      │ ← 内容行（有 bg）
│  › 2. No, stay in Plan mode   Continue planning...     │ ← 内容行（›光标+青色高亮，有 bg）
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← 背景色区域下边界（纯背景色，无字符）
│  Press enter to confirm or esc to go back               │ ← 底部栏（无 bg）
└─────────────────────────────────────────────────────────┘
```

**关键特性**：整个选项交互区域是一个**背景色区域**（连续的同背景色行，首尾为纯背景色行）。区域内的空行（问题行与选项行之间）外观与首尾边界相同（均为纯背景色），不能用「找最后 2 条」算法，需先找完整区域再取首尾纯背景色行作为边界。

与普通模式的关键差异：
- **整体背景色区域**：首尾纯背景色边界 + 内部所有行（含文字行和内部空行）共享同一背景色
- 区域内空行（纯背景色）外观与边界相同，是模式区分的关键难点
- `›` 提示符颜色变为浅蓝色（普通模式为白色/亮色），且不再是区域首行
- 输出区与背景色区域之间多一条普通分割线（默认背景色 ─━═）
- `layout_mode = "option"`，检测方式：提示符颜色 + 上方签名 + `_has_numbered_options` 兜底

解析路径：`_split_regions` Pass 1 `_find_bg_region` 找连续 bg zone 内首尾纯背景色边界对 → `_determine_input_mode` 确定模式 → `input_rows`（边界之间的所有行）→ `_parse_input_area` → `OptionBlock(sub_type="option")`

**与 Claude Code 的关键差异：**

| 特性 | Claude Code | Codex |
|------|------------|-------|
| 区域分割 | `─━═` 分割线 | **无分割线**，用背景色区域（连续 bg 行 + 首尾纯背景色边界）识别输入区域 |
| 输入提示符 | `❯` (U+276F) | **`›` (U+203A)** |
| 欢迎框位置 | 屏幕顶部（行 0） | 屏幕中部（大量空行之后） |
| 欢迎框内容 | `Claude Code vX.X.X` | `>_ OpenAI Codex (vX.X.X)` + `model:` + `directory:` |
| 底部栏 | 最后一条分割线之后 | 输入区之后所有行（含空格开头的模型信息行） |
| StatusLine | 星星字符（✱ blink） | `•` 圆点 blink + 内容含 "esc to interrupt" |

### Codex 区域切分策略（`_split_regions`）

用**背景色区域**（连续 bg 行 + 首尾纯背景色边界）识别输入区域，替代 `─━═` 字符分割线：

**普通模式**（输入区是单行 `›`）：
```
[输出区]
[纯背景色行]     ← 背景色区域上边界（bg + 无字符）
[› 当前输入行]   ← input_rows（› 白色/亮色）
[纯背景色行]     ← 背景色区域下边界（bg + 无字符）
[底部栏]         ← bottom_rows
```

**选项交互模式**（输入区是背景色区域）：
```
[输出区]
[默认背景色空行]                         ← 上方签名（条件 4a）
[默认背景色普通分割线（─━═）]            ← 上方签名（条件 4a）
[默认背景色空行]                         ← 上方签名（条件 4a）
[纯背景色行]     ← 背景色区域上边界
[问题文本行]     ← input_rows（有 bg）
[纯背景色行]     ← input_rows（外观同边界！）
[编号选项行]     ← input_rows（有 bg）
[› 选中选项行]   ← input_rows（› 浅蓝色/青色高亮）
[纯背景色行]     ← 背景色区域下边界
[底部栏]         ← bottom_rows（无 bg）
```

Pass 1 算法（`_find_bg_region`）：从下往上找连续 bg zone → zone 内取首尾纯背景色行作为边界对（区域 >= 3 行）→ 调用 `_determine_input_mode` 确定模式：

**模式区分条件（`_determine_input_mode`）：**
1. **条件 4b（normal）**：背景色区域首个内容行行首是 `›`，颜色为白色/亮色
2. **条件 4a（option）**：背景色区域上方依次是：默认背景色空行 → 默认背景色分割线（─━═）→ 默认背景色空行
3. **条件 4c（option）**：内容行中有浅蓝色 `›` 且整行字符都是同色
4. **兜底**：`_has_numbered_options` → 'option'，否则 'normal'

优先级：
1. **背景色区域（强）**：`_find_bg_region` 成功 → 用 `_determine_input_mode` 确定模式
2. **宽松亮色 `›` 检测（回退）**：只检查行首字符和前景色（亮色）
3. **位置弱信号**：找最后一个其后无 `•`/`›`/星星字符的 `›` 行
4. **纯背景色兜底**：无 `›` 行时用 `_find_chrome_boundary`

**亮色判断逻辑（`_is_bright_color`）：**
- 标准 bright colors (ANSI 90-97)：直接判定为亮色
- 标准 colors (ANSI 30-37)：判定为暗色
- 颜色名含 'bright'：判定为亮色
- 6 位 hex 颜色：通过亮度公式判断（L = 0.2126*R + 0.7152*G + 0.0722*B，L > 128）
- 'default'：非亮色

**注意：** 暗色用于历史 InputBlock，需要排除以区分当前输入区域。

### Codex 欢迎框识别（`_is_welcome_box`）

欢迎框首列是 `╭`，但**顶边框行不含工具名称**（顶边框只有 `─`），名称在框内第一个 `│` 行。
识别方式：检查框内前几行是否含以下任意特征：
- 非默认背景色
- `>_ `（CLI 提示符前缀）
- `model:`、`directory:`、`workspace:`（配置信息行）

### Codex Block 分类（`_classify_block`）

- **UserInput**：首列 `›` (U+203A) 或 `>` (U+003E)，由 `CODEX_PROMPT_CHARS` 控制
- **StatusLine**：首列圆点字符（`•` 等）且 **blink=True** → 状态行（Codex 用 blink 区分，不用星星字符）
- **OutputBlock**：首列圆点字符（`•` 等）且 **blink=False** → 已完成的输出块
- **SystemBlock**：`△`（Codex 系统警告）等首列字符，blink=False

> Codex 与 Claude Code 的核心区别：Claude Code 用**不同字符**区分（星星=StatusLine，圆点=OutputBlock），Codex 用**同一圆点字符 + blink 属性**区分。

## 文件结构

```
remote_claude/
├── remote_claude.py            # CLI 入口
│
├── server/                     # PTY 代理服务器
│   ├── server.py               # 主服务，管理 PTY 进程/控制权/广播
│   ├── component_parser.py     # 向后兼容 shim
│   ├── biz_enum.py             # 业务枚举定义（CliType）
│   ├── parsers/
│   │   ├── base_parser.py      # 解析器基类
│   │   ├── claude_parser.py    # Claude CLI 解析器
│   │   └── codex_parser.py     # Codex CLI 解析器（背景色区域检测/›提示符/颜色模式区分）
│   ├── shared_state.py         # 共享内存写入（.mq 文件）
│   └── rich_text_renderer.py   # 历史文件（暂保留）
│
├── client/                     # 终端客户端
│   └── client.py               # raw mode 输入转发
│
├── utils/                      # 公共工具
│   ├── protocol.py             # 消息协议（JSON + \n，7 种消息类型）
│   ├── session.py              # socket 路径管理、会话生命周期（resolve_session_name 使用延迟导入避免循环依赖）
│   ├── runtime_config.py       # 运行时配置管理（runtime.json）
│   └── components.py           # 控制权状态机等组件
│
├── lark_client/                # 飞书客户端
│   ├── main.py                 # WebSocket 入口
│   ├── lark_handler.py         # 命令路由（群聊/私聊统一逻辑）
│   ├── session_bridge.py       # Unix Socket 桥接（仅输入发送）
│   ├── shared_memory_poller.py # 流式滚动卡片轮询器（CardSlice/StreamTracker）
│   ├── card_builder.py         # 卡片构建（build_stream_card + 辅助卡片）
│   ├── card_service.py         # 卡片更新服务
│   ├── config.py
│   ├── capture_output.py       # 调试工具
│   ├── output_cleaner.py       # 历史文件（暂保留）
│   ├── terminal_buffer.py      # 历史文件（暂保留）
│   └── terminal_renderer.py    # 历史文件（暂保留）
│
├── tests/                      # 测试文件
│   ├── TEST_PLAN.md            # 测试计划文档
│   │
│   │── # 核心单元测试
│   ├── test_format_unit.py     # 格式化单元测试
│   ├── test_component_parser.py # 组件解析器测试
│   ├── test_stream_poller.py   # 流式卡片模型测试
│   ├── test_session_truncate.py # 会话名称截断测试
│   ├── test_runtime_config.py  # 运行时配置测试
│   ├── test_renderer.py        # 终端渲染器测试
│   │
│   │── # Codex 解析测试
│   ├── test_codex_parser_utils.py
│   ├── test_codex_split_regions.py
│   ├── test_codex_option_block.py
│   │
│   │── # 功能测试
│   ├── test_option_block.py    # 选项块测试
│   ├── test_option_select.py   # 选项选择测试
│   ├── test_card_interaction.py # 卡片交互测试
│   ├── test_disconnected_state.py # 断开状态测试
│   ├── test_list_display.py    # 列表显示测试
│   ├── test_log_level.py       # 日志级别测试
│   ├── test_stats.py           # 统计功能测试
│   ├── test_portable_python.py # 便携式 Python 测试
│   ├── test_socks_proxy.py     # SOCKS 代理测试
│   │
│   │── # 集成/端到端测试
│   ├── test_integration.py
│   ├── test_e2e.py
│   ├── test_attach_dedup.py
│   ├── test_message_queue.py
│   ├── test_mock_conversation.py
│   ├── test_real.py
│   ├── test_session.py
│   │
│   └── lark_client/            # lark_client 内部测试
│       ├── test_mock_output.py
│       ├── test_cjk_width.py
│       └── test_full_simulation.py
│
├── 文档
│   ├── CLAUDE.md
│   ├── CHANGELOG.md
│   ├── CONTRIBUTING.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   └── QUICKSTART.md
│
├── lark_client/
│   ├── GUIDE.md                 # 飞书客户端完整指南
│   └── ...
├── resources/                   # 资源文件
│   └── defaults/                # 默认配置模板
│       ├── .env.example         # 环境变量模板
│       ├── config.default.json  # 用户配置模板
│       └── runtime.default.json # 运行时配置模板
├── 配置
│   ├── .env（从 resources/defaults/.env.example 复制）
│   ├── pyproject.toml
│   └── requirements.txt
│
├── send_lark_msg.py            # 飞书消息调试脚本
└── backup/                     # 归档（与项目无关的工具脚本）
```

## 安装流程

Remote Claude 支持多种安装方式：

### npm/pnpm 全局安装（推荐）

```bash
npm install -g remote-claude
# 或
pnpm add -g remote-claude
```

**安装过程：**
1. npm/pnpm 下载并解压包文件
2. `postinstall` 钩子自动执行 `scripts/install.sh --npm`：
   - 检查/安装 uv 包管理器
   - 创建 Python 虚拟环境（`.venv/`）
   - 使用 `uv sync --frozen` 安装依赖
   - 执行 `scripts/setup.sh` 完成初始化

**特点：**
- 安装后即可使用，无需额外初始化
- Python 环境完全隔离，不影响系统
- 使用 uv 管理的 Python 版本

### 本地克隆安装

```bash
git clone https://github.com/yyzybb537/remote_claude.git
cd remote_claude
./scripts/install.sh
```

**安装过程：**
1. 检查操作系统（macOS/Linux）
2. 检查/安装 uv
3. 创建虚拟环境并安装依赖
4. 执行完整初始化（创建目录、符号链接、配置补全）

### 依赖变更检测

首次运行命令时，`_lazy_init` 会检查：
- `.venv` 是否存在
- `pyproject.toml` 是否比 `.venv` 新
- `uv.lock` 是否比 `.venv` 新

如果检测到变更，会自动重新同步依赖。

### 卸载流程

```bash
npm uninstall -g remote-claude
```

卸载时会：
- 删除快捷命令符号链接
- 停止飞书客户端
- 清理虚拟环境
- 询问是否保留配置文件

---

## 常用命令

```bash
# 安装依赖（通过 uv 管理）
uv sync

# 快捷命令（需运行 init.sh 配置）
cla                    # 启动飞书客户端 + 以当前目录路径为会话名启动 Claude
cl                     # 同 cla，但跳过权限确认
cx                     # 启动飞书客户端 + 以当前目录路径为会话名启动 Codex（跳过权限确认）
cdx                    # 同 cx，但需要确认权限

# 启动会话
uv run python3 remote_claude.py start <会话名> [-- claude 参数]
uv run python3 remote_claude.py start mywork

# 连接/管理会话
uv run python3 remote_claude.py attach <会话名>
uv run python3 remote_claude.py list
uv run python3 remote_claude.py kill <会话名>
uv run python3 remote_claude.py status <会话名>

# 使用统计
uv run python3 remote_claude.py stats              # 查看今日统计
uv run python3 remote_claude.py stats --range 7d   # 查看近 7 天统计
uv run python3 remote_claude.py stats --detail     # 显示详细分类

# 更新
uv run python3 remote_claude.py update             # 更新到最新版本

# 飞书客户端管理（需配置 .env）
uv run python3 remote_claude.py lark start     # 启动（后台守护进程）
uv run python3 remote_claude.py lark stop      # 停止
uv run python3 remote_claude.py lark restart   # 重启
uv run python3 remote_claude.py lark status    # 查看状态和日志
```

```
## 远程连接

### 启动远程会话
```bash
remote-claude start <session> --remote [--remote-port 8765] [--remote-host 0.0.0.0]
```

### 连接远程会话
```bash
remote-claude connect <host> <session> --token <token>
remote-claude connect <host>:<port>/<session> --token <token>
```

### 远程控制
```bash
remote-claude remote shutdown <host> <session> --token <token>
remote-claude remote restart <host> <session> --token <token>
remote-claude remote update <host> <session> --token <token>
```

### Token 管理
```bash
remote-claude token <session>
remote-claude regenerate-token <session>
```

## 测试


> **详细测试计划见 [`tests/TEST_PLAN.md`](./tests/TEST_PLAN.md)**，包含测试分层、执行流程、特殊场景说明和回归防护清单。

测试分为三层：
1. **单元测试** — 纯本地，覆盖格式化逻辑，无需网络和服务
2. **集成测试** — 直连 socket，发送真实消息验证输出
3. **飞书视觉测试** — 验证实际渲染效果，偶尔进行

**核心单元测试（Docker CI 必跑）：**
```bash
uv run python3 tests/test_session_truncate.py   # 会话名称截断测试
uv run python3 tests/test_runtime_config.py     # 运行时配置测试
```

**其他可独立运行的单元测试：**
```bash
uv run python3 tests/test_format_unit.py        # 格式化逻辑单元测试
uv run python3 tests/test_stream_poller.py      # 流式卡片模型测试
uv run python3 tests/test_renderer.py           # 终端渲染器测试
uv run python3 tests/test_stats.py              # 统计功能测试
uv run python3 tests/test_log_level.py          # 日志级别测试
uv run python3 tests/test_list_display.py       # 列表显示测试
uv run python3 tests/test_disconnected_state.py # 断开状态测试
uv run python3 tests/test_card_interaction.py   # 卡片交互测试
uv run python3 tests/lark_client/test_mock_output.py   # lark_client 输出模拟测试
uv run python3 tests/lark_client/test_cjk_width.py     # CJK 字符宽度测试
uv run python3 tests/lark_client/test_full_simulation.py  # 完整模拟测试
```

**Codex 解析测试：**
```bash
uv run python3 tests/test_codex_parser_utils.py
uv run python3 tests/test_codex_split_regions.py
uv run python3 tests/test_codex_option_block.py
```

**需要活跃会话的集成测试：**
```bash
# 先启动会话：uv run python3 remote_claude.py start test
uv run python3 tests/test_integration.py       # 集成测试
uv run python3 tests/test_session.py           # 会话连接测试
uv run python3 tests/test_real.py              # 实时数据渲染测试
uv run python3 tests/test_e2e.py               # 端到端流程测试
uv run python3 tests/test_mock_conversation.py # 模拟多轮对话
```

**调试工具：**
```bash
uv run python3 lark_client/capture_output.py <会话名> [秒数]  # 捕获原始输出
```

无 pytest 配置，测试文件均为独立脚本，通过 `uv run python3` 运行。


## 变更同步规则

**每当做事规则或需求发生变更时，必须同步更新以下文件：**
- `CLAUDE.md` — 更新对应的架构说明、开发须知或规则描述
- `tests/TEST_PLAN.md` — 更新对应的测试场景或注意事项

变更范围包括但不限于：命令行为调整、卡片交互设计变更、新增功能需求、废弃旧需求、约束条件修改。

## 开发须知

- **系统要求：** macOS/Linux（依赖 PTY、termios），需已安装 `uv`、`tmux` 和 `claude` CLI
- **飞书配置：** 复制 `resources/defaults/.env.example` 为 `~/.remote-claude/.env`，填写 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
- **Socket 路径：** `/tmp/remote-claude/<name>.sock`，PID 文件同目录
- **tmux 会话前缀：** `rc-`，如会话名 `test` 对应 tmux 会话 `rc-test`
- **历史缓冲区：** 100KB 循环缓冲，重连时自动发送
- **输出延迟：** 飞书侧 2-3 秒等待动画稳定后再发送；完成检测基于状态行（~2s），非超时
- **语言：** 代码注释和用户交互均使用中文

### 循环依赖处理

`utils/session.py` 和 `utils/runtime_config.py` 之间存在循环依赖：

- `session.py` 的 `resolve_session_name()` 需要调用 `runtime_config.py` 的配置管理函数
- `runtime_config.py` 在模块级导入了 `session.py` 的 `USER_DATA_DIR` 常量

**解决方案**：`session.py` 中的 `resolve_session_name()` 使用**延迟导入**（函数内导入），避免模块级循环依赖：

```python
def resolve_session_name(original_path: str, config: "RuntimeConfig" = None) -> str:
    # 延迟导入避免循环依赖：session.py ← → runtime_config.py
    from utils.runtime_config import load_runtime_config, save_runtime_config
    ...
```

**注意**：新增代码应避免在这两个模块之间添加模块级导入。

### 配置文件架构

Remote Claude 使用两个配置文件，职责分离：

| 文件 | 用途 | 管理方式 |
|------|------|---------|
| `~/.remote-claude/config.json` | 用户可编辑配置 | 用户手动编辑 |
| `~/.remote-claude/runtime.json` | 程序运行时状态 | 程序自动管理 |

#### config.json（用户配置）

存储用户可自定义的 UI 设置：

```json
{
  "version": "1.0",
  "ui_settings": {
    "quick_commands": {
      "enabled": false,
      "commands": [
        {"label": "清空对话", "value": "/clear", "icon": "🗑️"},
        {"label": "压缩上下文", "value": "/consume", "icon": "📦"},
        {"label": "退出会话", "value": "/exit", "icon": "🚪"},
        {"label": "帮助", "value": "/help", "icon": "❓"}
      ]
    },
    "notify": {
      "ready_enabled": true,
      "urgent_enabled": false
    },
    "bypass_enabled": false
  }
}
```

**快捷命令配置说明**：
- `enabled`: 是否启用快捷命令选择器（默认 `false`）
- `commands`: 快捷命令列表，最多 20 条（超出静默截断）
- `label`: 显示名称，最长 20 字符
- `value`: 命令值，必须以 `/` 开头，最长 32 字符，不能包含空格
- `icon`: 图标 emoji（可选，为空时使用空白占位）

**CustomCommand 数据类** (`utils/runtime_config.py`)：
- `name`: 显示名称，如 "Claude"、"Aider"
- `cli_type`: CLI 类型（必须为 CliType 枚举值之一："claude" 或 "codex"）
- `command`: 实际执行的命令，如 "claude"、"aider --message-args"
- `description`: 可选描述

**CliType 枚举** (`server/biz_enum.py`)：
- `CLAUDE = "claude"`: Claude Code CLI
- `CODEX = "codex"`: OpenAI Codex CLI

**通知配置说明**：
- `notify.ready_enabled`: 就绪通知开关（默认 `true`），Claude 完成任务后群聊 @ 用户
- `notify.urgent_enabled`: 加急通知开关（默认 `false`），对上一条通知消息加急（需开通飞书加急权限）

**Bypass 配置说明**：
- `bypass_enabled`: 新会话跳过权限确认（默认 `false`），启动时自动添加 `--dangerously-skip-permissions`

#### runtime.json（运行时状态）

存储程序自动管理的状态：

```json
{
  "version": "1.0",
  "session_mappings": {
    "myapp_src": "/Users/dev/projects/myapp/src/components"
  },
  "lark_group_mappings": {
    "oc_xxx": "my-session"
  },
  "ready_notify_count": 0
}
```

- **session_mappings**：截断名称 ↔ 原始路径映射（解决超长路径问题），最多 500 条（软限制）
- **lark_group_mappings**：飞书群组 ID ↔ 会话名映射
- **ready_notify_count**：就绪通知累计次数（用于显示"这是第 N 次通知"）

**文件锁机制**：

配置文件写入使用 `fcntl.flock` 实现进程级互斥：

- 锁文件路径：`runtime.json.lock` / `config.json.lock`
- **持久化特性**：锁文件在写入前创建，写入完成后保留（不删除）
- **互斥原理**：对锁文件本身加排他锁（`LOCK_EX`），多个进程阻塞等待
- **异常处理**：程序崩溃后锁文件可能残留，但不会造成死锁（flock 随进程终止自动释放）

> **注意**：锁文件的存在不表示锁定状态，只是一个协调媒介。真正的锁定通过 flock 系统调用实现。

#### 备份文件清理策略

- 配置文件损坏时自动备份为 `.json.bak.<timestamp>`
- 最多保留最近 2 个备份文件
- 迁移/修改成功后自动删除 `.bak` 文件
- 启动时检测残留 `.bak` 文件，提示用户选择：覆盖（从备份恢复）或跳过（删除备份继续）

#### 配置重置命令

可通过 `remote-claude config reset` 命令重置配置文件：

```bash
remote-claude config reset          # 交互式选择重置范围
remote-claude config reset --all    # 重置全部配置文件（config.json + runtime.json）
remote-claude config reset --config # 仅重置用户配置（config.json）
remote-claude config reset --runtime # 仅重置运行时配置（runtime.json）
```

重置时会同步清理相关的锁文件（`.lock`）和备份文件（`.bak`）。配置模板位于 `resources/defaults/` 目录。

### 飞书卡片 API 参考

- **飞书卡片 JSON V2 结构文档：** https://open.larkoffice.com/document/feishu-cards/card-json-v2-structure

### 飞书客户端管理

飞书客户端作为后台守护进程运行，状态信息保存在：
- **PID 文件：** `/tmp/remote-claude/lark.pid`
- **状态文件：** `/tmp/remote-claude/lark.status` (JSON 格式，包含启动时间)
- **日志文件：**
  - `~/.remote-claude/lark_client.log` — 正常运行日志（INFO 及以上）
  - `~/.remote-claude/lark_client.debug.log` — 调试日志（需设置 `LARK_LOG_LEVEL=DEBUG`）

启动后客户端在后台运行，通过 `uv run python3 remote_claude.py lark status` 可查看：
- 进程 PID
- 启动时间（精确到秒）
- 运行时长（格式化为天/小时/分钟）
- 日志文件大小
- 最近 5 行日志

**日志级别配置**（通过 `~/.remote-claude/.env`）：
```bash
# lark_client 日志级别（可选，默认 WARNING）
LARK_LOG_LEVEL=WARNING  # 支持: DEBUG / INFO / WARNING / ERROR
```

**日志格式**（含毫秒级时间戳）：
```
2026-03-12 14:30:15.123 [LarkHandler] INFO 收到消息: ou_12345678... -> 帮我分析代码...
2026-03-12 14:30:15.456 [SharedMemoryPoller] DEBUG 读取 .mq 文件: size=12345
```
