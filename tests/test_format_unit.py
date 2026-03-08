"""
格式化逻辑单元测试 - 无需网络和服务，直接测试 session_bridge._format_plain_output

运行：python3 test_format_unit.py
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lark_client.session_bridge import SessionBridge

bridge = SessionBridge.__new__(SessionBridge)
fmt = bridge._format_plain_output

PASS = 0
FAIL = 0
ERRORS = []


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  ✓ {name}")
        PASS += 1
    except AssertionError as e:
        print(f"  ✗ {name}: {e}")
        FAIL += 1
        ERRORS.append((name, str(e)))
    except Exception as e:
        print(f"  ✗ {name}: {type(e).__name__}: {e}")
        FAIL += 1
        ERRORS.append((name, traceback.format_exc()))


def in_code_block(result, text):
    """检查 text 是否在代码块内"""
    lines = result.split('\n')
    in_block = False
    for line in lines:
        if line.startswith('```'):
            in_block = not in_block
        elif in_block and text in line:
            return True
    return False


def not_in_code_block(result, text):
    return not in_code_block(result, text)


# ─── 分隔线 ───────────────────────────────────────────────
SEP = '─' * 80

# ── 场景1：Python 单函数，⏺ 直接跟代码 ──────────────────
print("\n[场景1] Python 单函数（⏺ 直接跟代码）")


def s1_has_python_block():
    r = fmt("""❯ 写一个二分查找
⏺ def binary_search(arr, target):
      left, right = 0, len(arr) - 1
      while left <= right:
          mid = (left + right) // 2
          if arr[mid] == target:
              return mid
          elif arr[mid] < target:
              left = mid + 1
          else:
              right = mid - 1
      return -1
  用法：
  >>> binary_search([1,3,5], 3)
  1
""" + SEP)
    assert '```python' in r, f'应有 python 代码块，实际:\n{r}'


def s1_indentation():
    r = fmt("""❯ 写一个二分查找
⏺ def binary_search(arr, target):
      left, right = 0, len(arr) - 1
      while left <= right:
          mid = (left + right) // 2
          return mid
      return -1
""" + SEP)
    assert '    left, right = 0, len(arr) - 1' in r, f'4空格缩进不对:\n{r}'
    assert '        mid = (left + right) // 2' in r, f'8空格缩进不对:\n{r}'


def s1_usage_outside_block():
    r = fmt("""❯ test
⏺ def foo():
      pass
  用法：
  >>> foo()
""" + SEP)
    assert not_in_code_block(r, '用法：'), f'用法: 不应在代码块内:\n{r}'


test("有 python 代码块", s1_has_python_block)
test("缩进正确", s1_indentation)
test("用法在代码块外", s1_usage_outside_block)

# ── 场景2：Python 多函数，⏺ 跟文字 ──────────────────────
print("\n[场景2] Python 多函数（⏺ 跟文字说明）")


def s2_def_in_block():
    r = fmt("""❯ 写一个冒泡排序
⏺ 这是冒泡排序的实现：
  def bubble_sort(arr):
      n = len(arr)
      for i in range(n):
          for j in range(0, n-i-1):
              if arr[j] > arr[j+1]:
                  arr[j], arr[j+1] = arr[j+1], arr[j]
      return arr
""" + SEP)
    assert in_code_block(r, 'def bubble_sort'), f'def 应在代码块内:\n{r}'


def s2_intro_outside():
    r = fmt("""❯ test
⏺ 这是冒泡排序的实现：
  def bubble_sort(arr):
      pass
""" + SEP)
    assert '⏺ 这是冒泡排序的实现：' in r, f'⏺ 文字应保留:\n{r}'


test("def 在代码块内", s2_def_in_block)
test("⏺ 文字在代码块外", s2_intro_outside)

# ── 场景3：Go 完整程序 ────────────────────────────────────
print("\n[场景3] Go 完整程序（package + import + func）")


def s3_all_in_one_block():
    r = fmt("""❯ Go HTTP 服务器
⏺ 简单的 Go HTTP 服务器：
  package main

  import (
      "fmt"
      "net/http"
  )

  func main() {
      http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
          fmt.Fprintln(w, "Hello")
      })
      http.ListenAndServe(":8080", nil)
  }
  运行：
  go run main.go
""" + SEP)
    assert '```go' in r, f'应有 go 代码块:\n{r}'
    assert in_code_block(r, 'package main'), f'package 应在块内:\n{r}'
    assert in_code_block(r, 'import ('), f'import 应在块内:\n{r}'
    assert in_code_block(r, 'func main()'), f'func 应在块内:\n{r}'


def s3_run_outside():
    r = fmt("""❯ test
⏺ Go 服务器：
  package main
  func main() {}
  运行：
  go run main.go
""" + SEP)
    assert not_in_code_block(r, '运行：'), f'运行: 不应在块内:\n{r}'


def s3_single_block():
    r = fmt("""❯ test
⏺ Go 服务器：
  package main

  import "fmt"

  func main() {
      fmt.Println("Hello")
  }
""" + SEP)
    blocks = r.count('```go')
    assert blocks == 1, f'应只有1个 go 代码块，实际{blocks}个:\n{r}'


test("package/import/func 在同一代码块", s3_all_in_one_block)
test("运行说明在代码块外", s3_run_outside)
test("整个程序只有一个代码块", s3_single_block)

# ── 场景4：JavaScript ─────────────────────────────────────
print("\n[场景4] JavaScript")


def s4_js_block():
    r = fmt("""❯ JS 函数
⏺ function fetchData(url) {
      return fetch(url)
          .then(res => res.json())
          .catch(err => console.error(err));
  }
""" + SEP)
    assert '```javascript' in r or '```' in r, f'应有代码块:\n{r}'
    assert in_code_block(r, 'function fetchData'), f'function 应在块内:\n{r}'


def s4_const_arrow():
    r = fmt("""❯ 箭头函数
⏺ 用箭头函数写：
  const add = (a, b) => a + b;
  const multiply = (a, b) => {
      return a * b;
  };
""" + SEP)
    assert in_code_block(r, 'const add'), f'const 应在块内:\n{r}'


test("function 声明", s4_js_block)
test("const 箭头函数", s4_const_arrow)

# ── 场景5：Rust ───────────────────────────────────────────
print("\n[场景5] Rust")


def s5_rust_fn():
    r = fmt("""❯ Rust 函数
⏺ fn fibonacci(n: u64) -> u64 {
      if n <= 1 {
          return n;
      }
      fibonacci(n - 1) + fibonacci(n - 2)
  }
""" + SEP)
    assert in_code_block(r, 'fn fibonacci'), f'fn 应在块内:\n{r}'


def s5_rust_struct():
    r = fmt("""❯ Rust struct
⏺ use std::collections::HashMap;

  struct Cache {
      data: HashMap<String, i32>,
  }

  impl Cache {
      fn new() -> Self {
          Cache { data: HashMap::new() }
      }
  }
""" + SEP)
    assert in_code_block(r, 'use std'), f'use 应在块内:\n{r}'
    assert in_code_block(r, 'struct Cache'), f'struct 应在块内:\n{r}'
    assert in_code_block(r, 'impl Cache'), f'impl 应在块内:\n{r}'


test("fn 函数", s5_rust_fn)
test("use + struct + impl", s5_rust_struct)

# ── 场景6：SQL ────────────────────────────────────────────
print("\n[场景6] SQL")


def s6_sql():
    r = fmt("""❯ SQL 查询
⏺ 查询最近7天的用户：
  SELECT user_id, name, created_at
  FROM users
  WHERE created_at >= NOW() - INTERVAL '7 days'
  ORDER BY created_at DESC
  LIMIT 100;
""" + SEP)
    assert in_code_block(r, 'SELECT'), f'SELECT 应在块内:\n{r}'


test("SQL 查询", s6_sql)

# ── 场景7：Bash 脚本 ──────────────────────────────────────
print("\n[场景7] Bash 脚本")


def s7_bash():
    r = fmt("""❯ Bash 脚本
⏺ 批量重命名脚本：
  #!/bin/bash
  for file in *.txt; do
      mv "$file" "${file%.txt}.md"
  done
  echo "完成"
""" + SEP)
    assert '```' in r, f'应有代码块:\n{r}'


test("Bash 脚本", s7_bash)

# ── 场景8：纯文本，不产生代码块 ──────────────────────────
print("\n[场景8] 纯文本（不应产生代码块）")


def s8_plain_text():
    r = fmt("""❯ 你好
⏺ 你好！我是 Claude Code，Anthropic 开发的 CLI 编程助手。
  我可以帮你：
  • 读写代码 — 编辑文件、创建项目
  • 调试排查 — 分析错误、定位问题
  • 回答问题 — 算法、架构设计、技术方案
""" + SEP)
    assert '```' not in r, f'纯文本不应有代码块:\n{r}'
    assert '我是 Claude' in r, f'内容丢失:\n{r}'


def s8_chinese_only():
    r = fmt("""❯ 什么是递归
⏺ 递归是一种编程技术，函数调用自身。
  它有两个要素：
  1. 基本情况（base case）：终止条件
  2. 递归情况（recursive case）：调用自身
  举例：计算阶乘 n! = n × (n-1)!
""" + SEP)
    assert '```' not in r, f'纯文本不应有代码块:\n{r}'


test("包含列表的纯文本", s8_plain_text)
test("纯中文说明", s8_chinese_only)

# ── 场景9：混合内容（文字 + 代码 + 文字）────────────────
print("\n[场景9] 混合内容")


def s9_mixed():
    r = fmt("""❯ 解释冒泡排序
⏺ 冒泡排序是最简单的排序算法之一。
  时间复杂度 O(n²)，空间复杂度 O(1)。
  def bubble_sort(arr):
      n = len(arr)
      for i in range(n):
          for j in range(n-i-1):
              if arr[j] > arr[j+1]:
                  arr[j], arr[j+1] = arr[j+1], arr[j]
      return arr
  优化版本可以加 swapped 标志提前退出。
""" + SEP)
    assert '```' in r, f'应有代码块:\n{r}'
    assert in_code_block(r, 'def bubble_sort'), f'def 应在块内:\n{r}'
    assert '冒泡排序是最简单' in r, f'前导文字应保留:\n{r}'
    assert not_in_code_block(r, '优化版本'), f'后续文字不应在块内:\n{r}'


test("文字+代码+文字", s9_mixed)

# ── 场景10：代码内有中文注释 ──────────────────────────────
print("\n[场景10] 代码内有中文注释")


def s10_chinese_comment():
    r = fmt("""❯ 写带注释的函数
⏺ def factorial(n):
      # 计算阶乘，递归实现
      if n <= 1:
          return 1  # 基本情况
      return n * factorial(n - 1)  # 递归调用
""" + SEP)
    assert in_code_block(r, '# 计算阶乘'), f'中文注释应在块内:\n{r}'


test("中文注释在代码块内", s10_chinese_comment)

# ── 场景11：多个代码块（不同语言）──────────────────────
print("\n[场景11] 多个代码块")


def s11_multi_block():
    r = fmt("""❯ 对比 Python 和 Go 实现
⏺ Python 实现：
  def add(a, b):
      return a + b
  Go 实现：
  func add(a, b int) int {
      return a + b
  }
""" + SEP)
    assert r.count('```') >= 4, f'应有至少2个代码块(4个```标记):\n{r}'


test("多个代码块", s11_multi_block)

# ── 场景12：UI 装饰过滤 ───────────────────────────────────
print("\n[场景12] UI 装饰过滤")


def s12_no_shortcuts():
    r = fmt("""❯ test
⏺ 回复内容
  ? for shortcuts
  esc to interrupt
  plugins failed to load
""" + SEP)
    assert 'shortcuts' not in r, f'应过滤 shortcuts:\n{r}'
    assert 'esc to' not in r, f'应过滤 esc to:\n{r}'
    assert 'plugins failed' not in r, f'应过滤 plugins failed:\n{r}'


def s12_no_box_drawing():
    r = fmt("""╭────────────╮
│ Welcome    │
╰────────────╯
❯ test
⏺ 正常回复
""" + SEP)
    assert '╭' not in r, f'应过滤框绘字符:\n{r}'
    assert '正常回复' in r, f'正常内容应保留:\n{r}'


test("过滤快捷键提示", s12_no_shortcuts)
test("过滤欢迎框", s12_no_box_drawing)

# ── 场景13：REPL 示例 ─────────────────────────────────────
print("\n[场景13] REPL 示例（>>> 开头）")


def s13_repl():
    r = fmt("""❯ 演示用法
⏺ def square(n):
      return n * n
  用法：
  >>> square(4)
  16
  >>> square(5)
  25
""" + SEP)
    # REPL 行在代码块外，但不应被过滤掉
    assert 'square(4)' in r or in_code_block(r, 'square(4)'), f'REPL 示例应出现:\n{r}'


test("REPL 示例保留", s13_repl)

# ── 场景14：TypeScript ────────────────────────────────────
print("\n[场景14] TypeScript")


def s14_ts():
    r = fmt("""❯ TS 接口
⏺ TypeScript 示例：
  interface User {
      id: number;
      name: string;
      email?: string;
  }

  function getUser(id: number): Promise<User> {
      return fetch(`/api/users/${id}`).then(r => r.json());
  }
""" + SEP)
    assert '```' in r, f'应有代码块:\n{r}'
    assert in_code_block(r, 'interface User'), f'interface 应在块内:\n{r}'


test("TypeScript interface + function", s14_ts)

# ── 场景15：代码块内有空行 ───────────────────────────────
print("\n[场景15] 代码块内有空行")


def s15_empty_lines_in_block():
    r = fmt("""❯ 带空行的代码
⏺ def process():
      # 第一步
      step1()

      # 第二步
      step2()

      return True
""" + SEP)
    # 函数体内的空行应保留在代码块内
    lines = r.split('\n')
    in_block = False
    empty_in_block = False
    for line in lines:
        if line.startswith('```'):
            in_block = not in_block
        elif in_block and line.strip() == '':
            empty_in_block = True
    assert empty_in_block, f'代码块内应有空行:\n{r}'


test("代码块内保留空行", s15_empty_lines_in_block)

# ── 场景16：❯ 用户输入行过滤 ─────────────────────────────
print("\n[场景16] ❯ 用户输入行过滤")


def s16_filter_user_input():
    r = fmt("""❯ 用户的消息
⏺ Claude 的回复
""" + SEP)
    lines = [l for l in r.split('\n') if l.strip()]
    for line in lines:
        assert not line.strip().startswith('❯'), f'应过滤 ❯ 行:\n{r}'


test("❯ 用户输入行被过滤", s16_filter_user_input)

# ── 场景17：_detect_language 覆盖 ────────────────────────
print("\n[场景17] 语言检测")


def s17_lang():
    detect = SessionBridge._detect_language
    cases = [
        ('def foo():', 'python'),
        ('class Foo:', 'python'),
        ('package main', 'go'),
        ('func main() {', 'go'),
        ('function foo() {', 'javascript'),
        ('const x = 1', 'javascript'),
        ('pub fn main()', 'rust'),
        ('fn foo()', 'rust'),
        ('SELECT * FROM', 'sql'),
        ('CREATE TABLE', 'sql'),
        ('FROM ubuntu:20.04', 'dockerfile'),
        ('apiVersion: apps/v1', 'yaml'),
        ('{"key": "value"}', 'json'),  # starts with {
        ('#!/bin/bash', 'bash'),
        ('for i in range', ''),  # ambiguous → no label
    ]
    for code, expected in cases:
        result = detect(code)
        if expected:
            assert result == expected, f'"{code}" → 期望 {expected}，实际 {result}'


test("语言检测覆盖", s17_lang)

# ── 汇总 ─────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"结果：{PASS} 通过，{FAIL} 失败")
if ERRORS:
    print("\n失败详情：")
    for name, err in ERRORS:
        print(f"\n  [{name}]\n  {err}")
print('='*50)
sys.exit(0 if FAIL == 0 else 1)
