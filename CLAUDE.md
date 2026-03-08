# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Remote Claude 是一个双端共享 Claude CLI 工具。通过 PTY + Unix Socket 架构，支持多个终端客户端和飞书客户端并发连接同一个 Claude 会话，实现协作式 AI 对话。

## 架构

```
Claude CLI (PTY)
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
- `remote_claude.py` — CLI 入口，子命令：start / attach / list / kill / lark
- `server/server.py` — PTY 代理服务器，`pty.fork()` 启动 Claude，asyncio Unix Socket 广播输出
- `server/component_parser.py` — 终端输出解析（区域切分、Block 分类、执行状态判断）
- `server/shared_state.py` — 共享内存写入（`.mq` 文件）
- `client/client.py` — 终端客户端，raw mode 输入转发
- `utils/protocol.py` — 消息协议（JSON + `\n` 分隔，二进制数据 base64 编码）。7 种消息类型：INPUT / OUTPUT / CONTROL / STATUS / HISTORY / ERROR / RESIZE
- `utils/session.py` — socket 路径管理、会话生命周期
- `utils/components.py` — 控制权状态机，SHARED（默认，所有人可输入）和 EXCLUSIVE（独占）两种模式

**飞书客户端 (`lark_client/`)：**
- `main.py` — WebSocket 入口，事件分发
- `lark_handler.py` — 命令路由，以 `chat_id` 为 key 统一管理群聊/私聊的 bridge 和绑定
- `session_bridge.py` — 连接 Unix Socket，**仅负责输入发送**（send_input/send_key）和连接管理
- `shared_memory_poller.py` — **流式滚动卡片轮询器**：每秒轮询 `.mq` 共享内存，通过 hash diff 驱动 `CardSlice`/`StreamTracker` 就地更新或冻结+开新卡
- `card_builder.py` — **`build_stream_card(blocks, status_line, bottom_bar, is_frozen, agent_panel, option_block)`**：四层结构卡片构建（内容区/状态区/交互区/菜单）+ 辅助卡片（session_list/menu/help/dir 等）
- `card_service.py` — 飞书卡片 API 服务（create/update/send）
- `rich_text_renderer.py` — 持久化 pyte Screen 封装（server 端实时喂入）

**Server 端数据流（全量快照架构）：**
```
PTY data → self._renderer.feed(data) → pyte.Screen(220,2000) 持久化实时更新
                                            ↓（flush 触发）
                                    ScreenParser.parse(screen)
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
                                 ┌── 累积列表合并 ──┐
                                 │ _accumulated_blocks │
                                 │ 首行匹配 + 滑动合并  │
                                 └────────┬──────────┘
                                          ↓
                                    ClaudeWindow 快照
                                          ↓
                                ├→ _messages.log (debug)
                                └→ .mq 共享内存 (全量覆写)
```

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
- **持久化绑定**：`/tmp/remote-claude/lark_chat_bindings.json`（chat_id → session_name）

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
| **第一层：内容区** | 累积型 blocks | blocks 列表中的 OutputBlock / UserInput | `_ansi_to_lark_md()` 解析 ANSI 着色为 `<font color>` markdown |
| **第二层：状态区** | 状态型组件 | status_line + bottom_bar + **agent_panel** + **option_block** 问题文本 | `column_set` grey 背景；status_line/bottom_bar 用 ANSI 着色；option_block 问题/标题文本 |
| **第三层：交互区** | 按钮 | **option_block** 的 options（降级搜索 blocks 中旧 OptionBlock/PermissionBlock） | 每个选项一个独立按钮 |
| **第四层：菜单** | 菜单入口 | 固定 | ⚡菜单按钮 |

**各 block 类型渲染规则（`_render_block_colored`）：**
- **OutputBlock** → `{prefix}{ansi_indicator_md} {ansi_content_md}`（ANSI → `<font color>` 着色，streaming 时 prefix=⏳，无 ANSI 时回退 `_escape_md`）
- **UserInput** → `{ansi_indicator_md} {ansi_text_md}`（同上）
- **OptionBlock(sub_type="option")** → `🤔 {_escape_md(question)}`（向后兼容：blocks 中的旧 OptionBlock 也按此渲染）
- **OptionBlock(sub_type="permission")** → `🔐 {_escape_md(title)}\n{_escape_md(content)}`（向后兼容：blocks 中的旧 PermissionBlock 也按此渲染）

**AgentPanelBlock 渲染规则（column_set grey 状态区内）：**
- **AgentPanelBlock(summary)** → `🤖 {agent_count} 个后台 agent`（纯文本，灰色背景已区分）
- **AgentPanelBlock(list)** → ` ```\n🤖 后台任务 ({count})\n{每行: ❯/空格 name (status)}\n``` `（代码块）
- **AgentPanelBlock(detail)** → ` ```\n🤖 {type} › {name}\n{stats}\nProgress: {progress}\nPrompt: {prompt}\n``` `（代码块）

**Card Header 逻辑：**

| 状态 | Header | 颜色 |
|------|--------|------|
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

设计动机：废弃旧的增量 MessageQueue（push_new/update_tail/complete_tail 状态机）。Claude CLI 终端偶尔出现内容错乱帧，增量状态被永久污染。改为持久化 pyte Screen（`self._renderer`），PTY 数据直接实时喂入；flush 时 screen 已是最新状态，直接 parse → 平滑 → 合并 → 生成 `ClaudeWindow` 快照。`_raw_buffer` 已废弃，resize 后历史随 renderer 重建而丢失（可接受）。

**组件两大分类：**

解析产出的组件分为两类，ClaudeWindow 中分别存储：

| 分类 | 特点 | 类型 | ClaudeWindow 字段 |
|------|------|------|-------------------|
| **累积型 Block** | 随对话推进不断增长，历史保留 | OutputBlock, UserInput | `blocks: list` |
| **状态型组件** | 全局唯一，不累积，反映当前瞬时状态 | StatusLine, BottomBar, AgentPanelBlock, OptionBlock | 各自独立字段 |

- **累积型 Block**：出现在输出区，每个 Block 都有 `block_id` 标识，新 Block 追加到列表末尾，旧 Block 保留不动。是对话的"历史记录"。
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

**累积列表合并**（`_merge_blocks`）：每次 flush 解析出 `visible_blocks`（当前屏幕可见），与 `_accumulated_blocks`（历史累积）合并：
```
_accumulated = [A, B, C, D]    ← 上一帧累积
visible      = [C', D', E]    ← 当前屏幕可见（C'=C的更新版）

1. 取 visible[0] 的 block_id，在 accumulated 中从后往前搜索匹配
2. 找到 C 在位置 i=2
3. 合并 = accumulated[:2] + visible = [A, B, C', D', E]
```
- 匹配点之前 = 已滚出的历史，保留不动
- 匹配点及之后 = 用 visible 整体替换（自动完成 streaming→complete 更新）
- 无匹配 → 尝试匹配后续 visible block；仍无匹配 → 追加全部
- 上限 MAX_ACCUMULATED=500 blocks，超出从头部裁剪

**时序窗口平滑**（WINDOW_SECONDS=1.0）：
- 每帧记录 `_FrameObs(ts, status_line, block_blink)` 到 deque，清理过期帧
- **status_line 平滑**：窗口内最新非 None 值（防间歇消失导致闪烁）
- **block blink 平滑**：窗口内任意帧有 blink=True → 最后一个 OutputBlock 标记 is_streaming=True
- 平滑**先于**合并执行（确保累积列表存储的是平滑后的值）

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

**Block ID 前缀：** `U:` UserInput / `O:` OutputBlock / `Q:` OptionBlock(option) / `P:` OptionBlock(permission) / `AP:` AgentPanelBlock

**调试文件**：
- `/tmp/remote-claude/<name>_messages.log` — ClaudeWindow 快照（每个 block 含 block_id）
- `/tmp/remote-claude/<name>_screen.log` — pyte 屏幕快照（含 blink 标记，`--debug-screen` 开启时写入）
- `/tmp/remote-claude/<name>_flush.log` — flush 各阶段耗时（`screen_log / parse / msg_log / snapshot / total`）

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

### 第三步：Block 分类

解析产出的组件分为**累积型 Block**（进入 `blocks` 列表，历史保留）和**状态型组件**（全局唯一，每帧覆盖）。

#### 累积型 Block（输出区，随对话增长）

**输出 Block（OutputBlock）：**
- 文本回复、工具调用块、Agent/Plan 块，**三者视为同一种 OutputBlock**
- 无需识别具体工具名称，无需区分工具调用还是文本回复
- 首行首列是圆点字符（`●` `⏺` 等）

**用户输入行（UserInput）：**
- 位于**输出区**中，首列字符为 `❯`，后跟用户已提交的历史文本

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

## 文件结构

```
remote_claude/
├── remote_claude.py            # CLI 入口
│
├── server/                     # PTY 代理服务器
│   ├── server.py               # 主服务，管理 PTY 进程/控制权/广播
│   ├── component_parser.py     # 终端输出解析（区域切分/Block 分类）
│   ├── shared_state.py         # 共享内存写入（.mq 文件）
│   └── rich_text_renderer.py   # 历史文件（暂保留）
│
├── client/                     # 终端客户端
│   └── client.py               # raw mode 输入转发
│
├── utils/                      # 公共工具
│   ├── protocol.py             # 消息协议（JSON + \n，7 种消息类型）
│   ├── session.py              # socket 路径管理、会话生命周期
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
│   ├── test_format_unit.py     # 格式化单元测试
│   ├── test_component_parser.py
│   ├── test_stream_poller.py   # 流式卡片模型单元测试（card_builder + poller）
│   ├── test_integration.py     # 集成测试
│   ├── test_attach_dedup.py
│   ├── test_message_queue.py
│   ├── test_option_block.py
│   ├── test_e2e.py
│   ├── test_mock_conversation.py
│   ├── test_output_clean.py
│   ├── test_real.py
│   ├── test_renderer.py
│   ├── test_session.py
│   └── lark_client/            # lark_client 内部测试
│       ├── test_mock_output.py
│       ├── test_cjk_width.py
│       └── test_full_simulation.py
│
├── 文档
│   ├── CLAUDE.md
│   ├── TEST_PLAN.md
│   ├── CHANGELOG.md
│   ├── CONTRIBUTING.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   ├── LARK_CLIENT_GUIDE.md
│   └── QUICKSTART.md
│
├── 配置
│   ├── .env / .env.example
│   ├── pyproject.toml
│   └── requirements.txt
│
├── send_lark_msg.py            # 飞书消息调试脚本
└── backup/                     # 归档（与项目无关的工具脚本）
```

## 常用命令

```bash
# 安装依赖（通过 uv 管理）
uv sync

# 快捷命令（需运行 init.sh 配置）
cla                    # 启动飞书客户端 + 以当前目录路径为会话名启动 Claude
cl                     # 同 cla，但跳过权限确认

# 启动会话
uv run python3 remote_claude.py start <会话名> [-- claude 参数]
uv run python3 remote_claude.py start mywork

# 连接/管理会话
uv run python3 remote_claude.py attach <会话名>
uv run python3 remote_claude.py list
uv run python3 remote_claude.py kill <会话名>

# 飞书客户端管理（需配置 .env）
uv run python3 remote_claude.py lark start     # 启动（后台守护进程）
uv run python3 remote_claude.py lark stop      # 停止
uv run python3 remote_claude.py lark restart   # 重启
uv run python3 remote_claude.py lark status    # 查看状态和日志
```

## 测试

> **详细测试计划见 [`TEST_PLAN.md`](./TEST_PLAN.md)**，包含测试分层、执行流程、特殊场景说明和回归防护清单。

测试分为三层：
1. **单元测试**（`test_format_unit.py`）— 纯本地，覆盖格式化逻辑，无需网络和服务
2. **集成测试**（`test_integration.py`）— 直连 socket，发送真实消息验证输出
3. **飞书视觉测试** — 验证实际渲染效果，偶尔进行

**可独立运行的单元测试：**
```bash
uv run python3 tests/test_format_unit.py                  # 格式化逻辑单元测试（见 TEST_PLAN.md 层1）
uv run python3 tests/test_stream_poller.py                # 流式卡片模型测试（card_builder + poller）
uv run python3 tests/test_renderer.py                     # 终端渲染器测试
uv run python3 tests/test_output_clean.py                 # 输出清理器测试
uv run python3 lark_client/output_cleaner.py              # output_cleaner 自带测试
uv run python3 tests/lark_client/test_mock_output.py      # lark_client 输出模拟测试
uv run python3 tests/lark_client/test_cjk_width.py        # CJK 字符宽度测试
uv run python3 tests/lark_client/test_full_simulation.py  # 完整模拟测试
```

**需要活跃会话的集成测试：**
```bash
# 先启动会话：uv run python3 remote_claude.py start test
uv run python3 tests/test_integration.py       # 集成测试（见 TEST_PLAN.md 层2）
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
- `TEST_PLAN.md` — 更新对应的测试场景或注意事项

变更范围包括但不限于：命令行为调整、卡片交互设计变更、新增功能需求、废弃旧需求、约束条件修改。

## 开发须知

- **系统要求：** macOS/Linux（依赖 PTY、termios），需已安装 `uv`、`tmux` 和 `claude` CLI
- **飞书配置：** 复制 `.env.example` 为 `.env`，填写 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
- **Socket 路径：** `/tmp/remote-claude/<name>.sock`，PID 文件同目录
- **tmux 会话前缀：** `rc-`，如会话名 `test` 对应 tmux 会话 `rc-test`
- **历史缓冲区：** 100KB 循环缓冲，重连时自动发送
- **输出延迟：** 飞书侧 2-3 秒等待动画稳定后再发送；完成检测基于状态行（~2s），非超时
- **语言：** 代码注释和用户交互均使用中文

### 飞书客户端管理

飞书客户端作为后台守护进程运行，状态信息保存在：
- **PID 文件：** `/tmp/remote-claude/lark.pid`
- **状态文件：** `/tmp/remote-claude/lark.status` (JSON 格式，包含启动时间)
- **日志文件：** `lark_client.log`（项目根目录）

启动后客户端在后台运行，通过 `uv run python3 remote_claude.py lark status` 可查看：
- 进程 PID
- 启动时间（精确到秒）
- 运行时长（格式化为天/小时/分钟）
- 日志文件大小
- 最近 5 行日志
