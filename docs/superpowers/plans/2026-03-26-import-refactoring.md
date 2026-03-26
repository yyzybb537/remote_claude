# Import 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Python 代码中不必要的临时 import 改为全局 import，提升代码一致性和可读性

**Architecture:** 静态代码重构，不改变运行时行为。保留可选依赖延迟加载和一次性迁移代码，仅移动标准库 import 到模块顶部

**Tech Stack:** Python 3.12，uv 包管理

---

## 变更范围

| 文件 | 变更内容 |
|------|----------|
| `stats/collector.py` | 移动 base64/json/urllib.request/datetime 到顶部 |
| `utils/runtime_config.py` | 移动 os 到顶部 |
| `client/local_client.py` | 移动 argparse/sys 到顶部 |
| `client/remote_client.py` | 移动 argparse 到顶部 |
| `tests/test_codex_option_block.py` | 移动 re 到顶部 |

**不修改的场景：**
- `stats/collector.py:97` — `import mixpanel`（可选依赖延迟加载）
- `stats/collector.py:32` — `import shutil`（一次性迁移块）

---

### Task 1: 重构 stats/collector.py

**Files:**
- Modify: `stats/collector.py:1-20`（添加全局 import）
- Modify: `stats/collector.py:335-370`（移除函数内 import）

**当前状态分析：**
- 第 337-339 行：`import base64/json/urllib.request` 在 `_send()` 内
- 第 359 行：`import datetime` 在 `_send()` 内
- 这些都是标准库，应移到模块顶部

- [ ] **Step 1: 添加全局 import**

在文件顶部（第 10-17 行附近）添加：

```python
import asyncio
import base64
import datetime
import json
import logging
import os
import sqlite3
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Optional
```

注意：保持原有 import 顺序，按标准库 → 第三方库 → 本地模块分组。

- [ ] **Step 2: 移除 report_install 内的 import**

删除第 337-339 行和第 359 行的 import 语句：

```python
# 删除这些行：
# import base64
# import json
# import urllib.request
# import datetime
```

- [ ] **Step 3: 验证语法正确**

Run: `uv run python3 -m py_compile stats/collector.py`
Expected: 无输出（编译成功）

- [ ] **Step 4: 提交变更**

```bash
git add stats/collector.py
git commit -m "refactor(stats): move stdlib imports to module level in collector.py"
```

---

### Task 2: 重构 utils/runtime_config.py

**Files:**
- Modify: `utils/runtime_config.py:1-20`（添加全局 import）
- Modify: `utils/runtime_config.py:817`（移除函数内 import）

**当前状态分析：**
- 第 817 行：`import os` 在 `validate_uv_path()` 函数内
- os 是标准库，应移到模块顶部

- [ ] **Step 1: 检查现有全局 import**

读取文件顶部，确认 os 是否已全局导入。如果已存在，跳过 Step 2。

- [ ] **Step 2: 添加全局 import（如需要）**

如果 os 未在全局导入，在顶部 import 区域添加：

```python
import os
```

- [ ] **Step 3: 移除函数内 import**

删除第 817 行的 `import os`

- [ ] **Step 4: 验证语法正确**

Run: `uv run python3 -m py_compile utils/runtime_config.py`
Expected: 无输出（编译成功）

- [ ] **Step 5: 提交变更**

```bash
git add utils/runtime_config.py
git commit -m "refactor(utils): move os import to module level in runtime_config.py"
```

---

### Task 3: 重构 client/local_client.py

**Files:**
- Modify: `client/local_client.py:1-20`（添加全局 import）
- Modify: `client/local_client.py:189-196`（移除 if __name__ 内 import）

**当前状态分析：**
- 第 190 行：`import argparse` 在 `if __name__` 块内
- 第 195 行：`import sys` 在 `if __name__` 块内
- sys 已在第 12 行全局导入，argparse 需要添加

- [ ] **Step 1: 添加全局 import**

在文件顶部 import 区域添加 argparse：

```python
import argparse
import asyncio
from typing import Optional
```

- [ ] **Step 2: 移除 if __name__ 内的 import**

删除第 190 行的 `import argparse` 和第 195 行的 `import sys`：

修改前：
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Remote Claude Local Client")
    parser.add_argument("session_name", help="会话名称")
    args = parser.parse_args()

    import sys
    sys.exit(run_client(args.session_name))
```

修改后：
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Claude Local Client")
    parser.add_argument("session_name", help="会话名称")
    args = parser.parse_args()
    sys.exit(run_client(args.session_name))
```

- [ ] **Step 3: 验证语法正确**

Run: `uv run python3 -m py_compile client/local_client.py`
Expected: 无输出（编译成功）

- [ ] **Step 4: 提交变更**

```bash
git add client/local_client.py
git commit -m "refactor(client): move argparse/sys imports to module level in local_client.py"
```

---

### Task 4: 重构 client/remote_client.py

**Files:**
- Modify: `client/remote_client.py:1-20`（添加全局 import）
- Modify: `client/remote_client.py:132-141`（移除 if __name__ 内 import）

**当前状态分析：**
- 第 12 行：`import sys` 已全局导入
- 第 133 行：`import argparse` 在 `if __name__` 块内
- 只需添加 argparse

- [ ] **Step 1: 添加全局 import**

在文件顶部 import 区域添加 argparse：

```python
import argparse
import asyncio
import sys
from typing import Optional
```

- [ ] **Step 2: 移除 if __name__ 内的 import**

删除第 133 行的 `import argparse`：

修改前：
```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Remote Claude WebSocket Client")
```

修改后：
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Claude WebSocket Client")
```

- [ ] **Step 3: 验证语法正确**

Run: `uv run python3 -m py_compile client/remote_client.py`
Expected: 无输出（编译成功）

- [ ] **Step 4: 提交变更**

```bash
git add client/remote_client.py
git commit -m "refactor(client): move argparse import to module level in remote_client.py"
```

---

### Task 5: 重构 tests/test_codex_option_block.py

**Files:**
- Modify: `tests/test_codex_option_block.py:1-30`（合并 import）
- Modify: `tests/test_codex_option_block.py:103`（移除中间的 import）

**当前状态分析：**
- 第 13-28 行：顶部已有 import
- 第 103 行：`import re` 在测试函数定义之间
- re 应移到顶部与其他 import 合并

- [ ] **Step 1: 在顶部添加 re import**

在第 13 行附近添加：

```python
import re
import sys
from pathlib import Path
```

- [ ] **Step 2: 移除中间的 import re**

删除第 103 行的 `import re`

- [ ] **Step 3: 验证语法正确**

Run: `uv run python3 -m py_compile tests/test_codex_option_block.py`
Expected: 无输出（编译成功）

- [ ] **Step 4: 运行测试确保功能正常**

Run: `uv run python3 tests/test_codex_option_block.py`
Expected: 所有测试通过

- [ ] **Step 5: 提交变更**

```bash
git add tests/test_codex_option_block.py
git commit -m "refactor(tests): move re import to module level in test_codex_option_block.py"
```

---

### Task 6: 最终验证

**Files:**
- 所有修改的文件

- [ ] **Step 1: 运行完整测试套件**

Run: `uv run python3 -m pytest tests/ -v --tb=short`
Expected: 所有测试通过

- [ ] **Step 2: 检查 import 规范**

Run: `uv run python3 -c "
import ast
import sys
from pathlib import Path

def check_imports_in_file(filepath):
    with open(filepath) as f:
        tree = ast.parse(f.read())
    imports_in_functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    imports_in_functions.append((filepath.name, node.name, child.lineno))
    return imports_in_functions

files = [
    Path('stats/collector.py'),
    Path('utils/runtime_config.py'),
    Path('client/local_client.py'),
    Path('client/remote_client.py'),
    Path('tests/test_codex_option_block.py'),
]

all_issues = []
for f in files:
    if f.exists():
        issues = check_imports_in_file(f)
        # 过滤掉允许的延迟加载（mixpanel, shutil 迁移块等）
        for fname, func, lineno in issues:
            if 'mixpanel' in str(issues) or 'shutil' in str(issues):
                continue
            all_issues.append(f'{fname}:{func}():{lineno}')

if all_issues:
    print('Found imports in functions:')
    for i in all_issues:
        print(f'  {i}')
    sys.exit(1)
else:
    print('All imports are at module level (except allowed delayed imports)')
    sys.exit(0)
"`
Expected: "All imports are at module level (except allowed delayed imports)"

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 移动 import 可能改变加载顺序 | 低 | 标准库 import 无副作用 |
| 测试未覆盖的边界情况 | 低 | 纯重构，不改变逻辑 |
| 遗漏其他需要重构的文件 | 低 | 已完整扫描项目 |

---

## 预期结果

- 5 个文件的 import 结构更清晰
- 代码风格一致性提升
- 无功能变更
- 所有测试通过
