#!/usr/bin/env python3
"""
便携式 Python 环境验证测试

测试项目：
1. pyproject.toml 的 requires-python 配置
2. uv 可用性
3. 虚拟环境创建
4. 核心模块导入

注意：Python 版本由 uv 自动管理，无需 .python-version 文件
"""

import sys
import os
import subprocess
from pathlib import Path

# 测试结果
PASSED = 0
FAILED = 0

def test(name, fn):
    global PASSED, FAILED
    try:
        fn()
        print(f"✓ {name}")
        PASSED += 1
    except AssertionError as e:
        print(f"✗ {name}: {e}")
        FAILED += 1
    except Exception as e:
        print(f"✗ {name}: {e}")
        FAILED += 1


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


def test_requires_python():
    """测试 pyproject.toml 中的 requires-python 配置"""
    import tomllib

    pyproject = PROJECT_ROOT / "pyproject.toml"
    assert pyproject.exists(), "pyproject.toml 不存在"

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    requires_python = data.get("project", {}).get("requires-python", "")
    assert requires_python, "requires-python 未配置"
    assert "3.11" in requires_python, f"预期 requires-python 包含 3.11，实际 {requires_python}"


def test_uv_available():
    """测试 uv 可用性"""
    result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
    assert result.returncode == 0, f"uv 不可用: {result.stderr}"


def test_venv_creation():
    """测试虚拟环境创建"""
    venv_dir = PROJECT_ROOT / ".venv"

    # 检查 .venv 是否存在（可能需要先运行 install.sh）
    if not venv_dir.exists():
        print("  ℹ .venv 不存在，尝试运行 install.sh 创建...")
        # 运行 install.sh
        result = subprocess.run(
            ["bash", str(PROJECT_ROOT / "scripts/install.sh")],
            capture_output=True,
            text=True,
        )
        # install.sh 应该成功
        print(f"  install.sh 退出码: {result.returncode}")

    assert venv_dir.exists(), "install.sh 运行后 .venv 仍不存在"


def test_core_imports():
    """测试核心模块导入"""
    # 切换到项目目录
    os.chdir(PROJECT_ROOT)

    # 测试核心模块导入
    result = subprocess.run(
        ["python3", "-c",
             "from utils.session import resolve_session_name, _safe_filename; "
             "from utils.runtime_config import load_runtime_config; "
             "print('核心模块导入成功')"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"核心模块导入失败: {result.stderr}"
    assert "核心模块导入成功" in result.stdout


def main():
    print("=" * 60)
    print("便携式 Python 环境验证测试")
    print("=" * 60)
    print()

    # 运行测试
    test("requires-python 配置", test_requires_python)
    test("uv 可用性", test_uv_available)
    test("虚拟环境创建", test_venv_creation)
    test("核心模块导入", test_core_imports)

    print()
    print("=" * 60)
    print(f"测试结果: {PASSED} 通过, {FAILED} 失败")
    print("=" * 60)

    sys.exit(0 if FAILED == 0 else 1)


if __name__ == "__main__":
    main()
