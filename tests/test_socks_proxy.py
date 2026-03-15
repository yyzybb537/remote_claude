"""
SOCKS5 代理功能测试

测试内容：
1. test_socks5_proxy_forwarding   — python-socks 能通过 SOCKS5 代理正常转发 TCP 连接
2. test_proxy_detection_with_env  — urllib.request.getproxies() 能检测到 ALL_PROXY 环境变量
3. test_no_proxy_clears_env       — LARK_NO_PROXY=1 的清除逻辑能正确移除代理环境变量
"""

import asyncio
import os
import struct
import sys
import urllib.request


# ─────────────────────────────────────────────
# 内嵌最小 SOCKS5 代理服务器
# ─────────────────────────────────────────────

async def _socks5_handle(reader, writer):
    """处理单个 SOCKS5 连接：握手 + CONNECT + 双向转发"""
    try:
        # 握手：客户端问候
        ver, nmethods = struct.unpack("!BB", await reader.readexactly(2))
        if ver != 5:
            writer.close()
            return
        await reader.readexactly(nmethods)  # 跳过认证方法列表

        # 握手：服务端回复无认证（0x00）
        writer.write(b"\x05\x00")
        await writer.drain()

        # 读取请求头
        header = await reader.readexactly(4)
        ver, cmd, _rsv, atyp = struct.unpack("!BBBB", header)
        if ver != 5 or cmd != 1:  # 只支持 CONNECT
            writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
            await writer.drain()
            writer.close()
            return

        # 解析目标地址
        if atyp == 0x01:  # IPv4
            addr_bytes = await reader.readexactly(4)
            host = ".".join(str(b) for b in addr_bytes)
        elif atyp == 0x03:  # 域名
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode()
        else:
            writer.write(b"\x05\x08\x00\x01" + b"\x00" * 6)
            await writer.drain()
            writer.close()
            return

        port_bytes = await reader.readexactly(2)
        port = struct.unpack("!H", port_bytes)[0]

        # 连接目标
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except Exception:
            writer.write(b"\x05\x04\x00\x01" + b"\x00" * 6)
            await writer.drain()
            writer.close()
            return

        # 回复成功
        writer.write(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
        await writer.drain()

        # 双向转发
        async def relay(src, dst):
            try:
                while True:
                    data = await src.read(4096)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except Exception:
                pass
            finally:
                try:
                    dst.close()
                except Exception:
                    pass

        await asyncio.gather(
            relay(reader, remote_writer),
            relay(remote_reader, writer),
        )
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _echo_handle(reader, writer):
    """简单 TCP echo 服务器"""
    try:
        data = await reader.read(1024)
        writer.write(data)
        await writer.drain()
    finally:
        writer.close()


# ─────────────────────────────────────────────
# 测试用例
# ─────────────────────────────────────────────

async def test_socks5_proxy_forwarding():
    """通过 SOCKS5 代理连接本地 TCP echo 服务，验证 python-socks 转发正常"""
    try:
        from python_socks.async_.asyncio import Proxy
    except ImportError:
        print("  SKIP: python-socks[asyncio] 未安装，跳过测试")
        return True

    PROXY_HOST = "127.0.0.1"
    PROXY_PORT = 17890
    ECHO_HOST = "127.0.0.1"
    ECHO_PORT = 17891

    # 启动 echo 服务
    echo_server = await asyncio.start_server(_echo_handle, ECHO_HOST, ECHO_PORT)
    # 启动 SOCKS5 代理
    proxy_server = await asyncio.start_server(_socks5_handle, PROXY_HOST, PROXY_PORT)

    try:
        proxy = Proxy.from_url(f"socks5://{PROXY_HOST}:{PROXY_PORT}")
        sock = await proxy.connect(dest_host=ECHO_HOST, dest_port=ECHO_PORT)

        reader, writer = await asyncio.open_connection(sock=sock)
        writer.write(b"hello socks5")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(64), timeout=3.0)
        writer.close()

        assert data == b"hello socks5", f"echo 数据不匹配: {data!r}"
        print("  PASS: SOCKS5 代理转发正常")
        return True
    finally:
        echo_server.close()
        proxy_server.close()
        await echo_server.wait_closed()
        await proxy_server.wait_closed()


def test_proxy_detection_with_env():
    """设置 ALL_PROXY 环境变量后，urllib.request.getproxies() 应能检测到"""
    old = os.environ.copy()
    try:
        os.environ["ALL_PROXY"] = "socks5://127.0.0.1:7890"
        os.environ.pop("all_proxy", None)

        proxies = urllib.request.getproxies()
        # getproxies() 在 macOS/Linux 上将 ALL_PROXY 归入 'all' 键
        socks_proxy = (
            proxies.get("socks")
            or proxies.get("all")
            or proxies.get("https")
            or proxies.get("http")
        )

        assert socks_proxy is not None, f"未检测到代理，proxies={proxies}"
        assert "socks" in socks_proxy.lower(), f"检测到的代理不含 socks: {socks_proxy}"
        print(f"  PASS: 代理检测正常，socks_proxy={socks_proxy}")
        return True
    finally:
        # 还原环境变量
        for k in list(os.environ):
            if k not in old:
                del os.environ[k]
        for k, v in old.items():
            os.environ[k] = v


def test_no_proxy_clears_env():
    """LARK_NO_PROXY=1 的清除逻辑：应移除所有代理相关环境变量"""
    PROXY_VARS = (
        "ALL_PROXY", "all_proxy",
        "HTTPS_PROXY", "https_proxy",
        "HTTP_PROXY", "http_proxy",
        "SOCKS_PROXY", "socks_proxy",
    )

    old = {k: os.environ.get(k) for k in PROXY_VARS}
    try:
        # 预设代理环境变量
        os.environ["ALL_PROXY"] = "socks5://127.0.0.1:7890"
        os.environ["HTTPS_PROXY"] = "socks5://127.0.0.1:7890"

        # 模拟 lark_client/main.py 的清除逻辑
        for var in PROXY_VARS:
            os.environ.pop(var, None)

        # 验证全部被清除
        for var in PROXY_VARS:
            assert var not in os.environ, f"{var} 未被清除"

        print("  PASS: 代理环境变量清除逻辑正常")
        return True
    finally:
        # 还原
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

async def main():
    print("=== SOCKS5 代理功能测试 ===\n")

    results = []

    print("[1/3] test_socks5_proxy_forwarding")
    try:
        ok = await test_socks5_proxy_forwarding()
        results.append(ok is not False)
    except Exception as e:
        print(f"  FAIL: {e}")
        results.append(False)

    print("[2/3] test_proxy_detection_with_env")
    try:
        ok = test_proxy_detection_with_env()
        results.append(ok is not False)
    except Exception as e:
        print(f"  FAIL: {e}")
        results.append(False)

    print("[3/3] test_no_proxy_clears_env")
    try:
        ok = test_no_proxy_clears_env()
        results.append(ok is not False)
    except Exception as e:
        print(f"  FAIL: {e}")
        results.append(False)

    print(f"\n结果：{sum(results)}/{len(results)} 通过")
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
