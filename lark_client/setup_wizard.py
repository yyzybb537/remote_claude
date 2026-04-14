"""
飞书机器人配置向导

自动创建飞书应用（通过 OAuth 设备流扫码），并引导用户完成机器人能力配置。

用法：
    python3 -m lark_client.setup_wizard          # 交互式向导
    python3 -m lark_client.setup_wizard --check  # 仅检查现有配置
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

# 将项目根目录加入 sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.session import USER_DATA_DIR, get_env_file

# ── ANSI 颜色 ──────────────────────────────────────────────────────────────
GREEN  = "\033[32m"
YELLOW = "\033[33m"
BLUE   = "\033[34m"
CYAN   = "\033[36m"
RED    = "\033[31m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ── 飞书 API 端点 ──────────────────────────────────────────────────────────
FEISHU_ACCOUNTS_URL = "https://accounts.feishu.cn"
LARK_ACCOUNTS_URL   = "https://accounts.larksuite.com"
FEISHU_OPEN_URL     = "https://open.feishu.cn"
LARK_OPEN_URL       = "https://open.larksuite.com"


def _post_form(url: str, data: dict, timeout: int = 10) -> dict:
    """发送 application/x-www-form-urlencoded POST 请求，返回 JSON 响应。"""
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, data: dict, timeout: int = 10) -> dict:
    """发送 application/json POST 请求，返回 JSON 响应。"""
    encoded = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _read_input(prompt: str, default: str = "") -> str:
    """读取用户输入，支持默认值。"""
    if default:
        full_prompt = f"{prompt} [{DIM}{default}{RESET}]: "
    else:
        full_prompt = f"{prompt}: "
    try:
        val = input(full_prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return val if val else default


def _read_secret(prompt: str) -> str:
    """读取密钥输入（不回显）。"""
    import getpass
    try:
        return getpass.getpass(f"{prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise


def _print_header():
    print(f"\n{CYAN}{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"{CYAN}{BOLD}  飞书机器人配置向导{RESET}")
    print(f"{CYAN}{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n")


def _print_step(n: int, title: str):
    print(f"\n{BLUE}{BOLD}[{n}] {title}{RESET}")


def _ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str):
    print(f"  {YELLOW}⚠{RESET} {msg}")


def _err(msg: str):
    print(f"  {RED}✗{RESET} {msg}")


def _info(msg: str):
    print(f"  {DIM}{msg}{RESET}")


# ── lark-cli 配置读取 ───────────────────────────────────────────────────────

# ── OAuth 设备流：创建应用 ──────────────────────────────────────────────────

def request_app_registration(accounts_base: str = FEISHU_ACCOUNTS_URL) -> dict:
    """
    调用飞书 OAuth 设备流 API，发起应用注册请求。

    返回包含 device_code, user_code, verification_url, expires_in, interval 的字典。
    """
    url = f"{accounts_base}/oauth/v1/app/registration"
    resp = _post_form(url, {
        "action": "begin",
        "archetype": "PersonalAgent",
        "auth_method": "client_secret",
        "request_user_info": "open_id tenant_brand",
    })

    # 构建完整验证 URL
    verification_url = resp.get("verification_uri_complete") or resp.get("verification_uri", "")
    user_code = resp.get("user_code", "")

    # 追加 CLI 参数（与 lark-cli 行为一致）
    if verification_url and "?" not in verification_url:
        verification_url = f"{verification_url}?from=remote-claude"
    elif verification_url:
        verification_url = f"{verification_url}&from=remote-claude"

    return {
        "device_code": resp["device_code"],
        "user_code": user_code,
        "verification_url": verification_url,
        "expires_in": resp.get("expires_in", 300),
        "interval": resp.get("interval", 5),
    }


def poll_app_registration(device_code: str, expires_in: int, interval: int,
                          accounts_base: str = FEISHU_ACCOUNTS_URL) -> dict:
    """
    轮询应用注册结果，直到用户完成扫码授权或超时。

    成功时返回包含 client_id, client_secret, user_info 的字典。
    """
    url = f"{accounts_base}/oauth/v1/app/registration"
    deadline = time.time() + expires_in
    attempt = 0
    max_attempts = 200

    print(f"  {DIM}等待扫码...{RESET}", end="", flush=True)

    while time.time() < deadline and attempt < max_attempts:
        attempt += 1
        time.sleep(3)
        print(".", end="", flush=True)

        try:
            resp = _post_form(url, {
                "action": "poll",
                "device_code": device_code,
            })
        except Exception:
            continue

        error = resp.get("error", "")

        if not error:
            # 成功
            if resp.get("client_id"):
                print(f" {GREEN}✓{RESET}")
                return resp
            # 可能还在处理，继续轮询
            continue
        elif error == "authorization_pending":
            continue
        elif error == "slow_down":
            pass
        elif error == "access_denied":
            print()
            raise RuntimeError("用户拒绝了授权请求")
        elif error in ("expired_token", "invalid_grant"):
            print()
            raise RuntimeError("二维码已过期，请重新运行向导")
        else:
            print()
            raise RuntimeError(f"注册失败：{error} - {resp.get('error_description', '')}")

    print()
    raise RuntimeError("等待超时，请重新运行向导")


def create_app_via_scan(brand: str = "feishu") -> tuple[str, str]:
    """
    通过扫码创建飞书应用。

    返回 (app_id, app_secret) 元组。
    """
    accounts_base = LARK_ACCOUNTS_URL if brand == "lark" else FEISHU_ACCOUNTS_URL

    # 发起注册请求
    reg = request_app_registration(accounts_base)

    print(f"\n  {CYAN}请在浏览器中打开以下链接，扫码创建应用：{RESET}")
    print(f"\n  {BOLD}{reg['verification_url']}{RESET}\n")

    # 尝试自动打开浏览器（纯命令行环境跳过，避免文字浏览器接管终端）
    if _open_browser(reg["verification_url"]):
        _info("已尝试自动在浏览器中打开（如未打开请手动复制上方链接）")

    # 尝试显示终端二维码
    _try_print_qrcode(reg["verification_url"])

    # 轮询结果
    result = poll_app_registration(
        reg["device_code"],
        reg["expires_in"],
        reg["interval"],
        accounts_base,
    )

    # DEBUG: 打印 user_info 原始内容，用于调试企业检测逻辑（测试完删除）
    import json as _json
    print(f"\n  [DEBUG] user_info: {_json.dumps(result.get('user_info', {}), ensure_ascii=False, indent=2)}\n")

    # 处理 Lark 双端特殊情况（feishu 端点可能不返回 lark 租户的 secret）
    tenant_brand = result.get("user_info", {}).get("tenant_brand", "feishu")
    if tenant_brand == "lark" and not result.get("client_secret"):
        _info("检测到 Lark 租户，从 Lark 端点重新获取凭证...")
        result = poll_app_registration(
            reg["device_code"],
            reg["expires_in"],
            reg["interval"],
            LARK_ACCOUNTS_URL,
        )

    app_id = result.get("client_id", "")
    app_secret = result.get("client_secret", "")

    if not app_id or not app_secret:
        raise RuntimeError(f"创建成功但未获取到凭证，响应：{result}")

    return app_id, app_secret


def _has_gui() -> bool:
    """
    判断当前环境是否有 GUI 可用（能安全调用系统 open/xdg-open）。

    - macOS：用 `open` 命令，始终非阻塞，安全。
    - Linux：需要 DISPLAY 或 WAYLAND_DISPLAY 环境变量，否则 webbrowser
      会找到 lynx/w3m/elinks 等文字浏览器并接管终端。
    - 其他：保守返回 False。
    """
    import platform
    if platform.system() == "Darwin":
        return True
    if platform.system() == "Linux":
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return False


def _open_browser(url: str) -> bool:
    """
    安全地打开浏览器。仅在有 GUI 环境时才尝试，避免文字浏览器接管终端。

    返回 True 表示已触发打开，False 表示跳过。
    """
    if not _has_gui():
        return False
    try:
        import subprocess
        import platform
        if platform.system() == "Darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _try_print_qrcode(url: str):
    """尝试在终端打印二维码（需要 qrcode 库）。"""
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print()
        qr.print_ascii(invert=True)
        print()
    except ImportError:
        pass  # 没有 qrcode 库，跳过
    except Exception:
        pass


# ── OAuth 设备流：权限授权 ─────────────────────────────────────────────────

# remote_claude 机器人所需的最小权限 scope 集合
# 格式：飞书 OAuth scope（空格分隔）
REMOTE_CLAUDE_SCOPES = " ".join([
    # 卡片
    "cardkit:card:write",
    # 通讯录
    "contact:contact.base:readonly",
    "contact:user.base:readonly",
    "contact:user.employee_id:readonly",
    "contact:user.id:readonly",
    # 群聊管理
    "im:chat.managers:write_only",
    "im:chat.members:read",
    "im:chat.members:write_only",
    "im:chat.tabs:read",
    "im:chat.tabs:write_only",
    "im:chat.top_notice:write_only",
    "im:chat:create",
    "im:chat:delete",
    "im:chat:operate_as_owner",
    "im:chat:read",
    "im:chat:update",
    # 消息收发
    "im:message.group_at_msg:readonly",
    "im:message.group_msg",
    "im:message.p2p_msg:readonly",
    "im:message.reactions:read",
    "im:message.reactions:write_only",
    "im:message.urgent",
    "im:message.urgent.status:write",
    "im:message:readonly",
    "im:message:recall",
    "im:message:send_as_bot",
    "im:message:update",
    "im:resource",
    # 离线访问（refresh token）
    "offline_access",
])


# 应用身份权限（tenant scope）列表，与 README.md tenant 部分保持一致
# 仅保留 Remote Claude 实际使用的权限（消息收发、卡片、群聊管理、加急通知）
TENANT_SCOPES = [
    # 卡片
    "cardkit:card:write",
    # 通讯录
    "contact:contact.base:readonly",
    "contact:user.employee_id:readonly",
    "contact:user.id:readonly",
    # 群聊管理
    "im:chat.members:read",
    "im:chat.members:write_only",
    "im:chat.tabs:read",
    "im:chat.tabs:write_only",
    "im:chat.top_notice:write_only",
    "im:chat:create",
    "im:chat:delete",
    "im:chat:operate_as_owner",
    "im:chat:read",
    "im:chat:update",
    # 消息收发
    "im:message.group_at_msg:readonly",
    "im:message.group_msg",
    "im:message.p2p_msg:readonly",
    "im:message.reactions:read",
    "im:message.reactions:write_only",
    "im:message.urgent",
    "im:message.urgent.status:write",
    "im:message:readonly",
    "im:message:recall",
    "im:message:send_as_bot",
    "im:message:update",
    "im:message:urgent_app",
    "im:resource",
]


def authorize_tenant_scopes(app_id: str, brand: str = "feishu") -> None:
    """
    打开飞书开发者后台权限申请页，引导用户开通应用身份权限（tenant scope）。

    飞书支持快捷权限申请 URL 格式，点击后自动列出所有待开通权限，用户全选确认即可。
    """
    base = "https://open.feishu.cn" if brand == "feishu" else "https://open.larksuite.com"
    scopes_str = ",".join(TENANT_SCOPES)
    url = f"{base}/app/{app_id}/auth?q={scopes_str}&token_type=tenant"

    print(f"\n  {CYAN}请打开以下链接，在开发者后台开通应用身份权限：{RESET}")
    print(f"  {DIM}（页面加载后，点击「全选」，再点击「确认开通权限」）{RESET}")
    print(f"\n  {BOLD}{url}{RESET}\n")

    if _open_browser(url):
        _info("已尝试自动在浏览器中打开")

    _try_print_qrcode(url)

    try:
        input(f"  {DIM}完成后按 Enter 继续...{RESET}")
    except (KeyboardInterrupt, EOFError):
        print()


def request_device_authorization(app_id: str, app_secret: str,
                                  scope: str,
                                  brand: str = "feishu") -> dict:
    """
    发起 OAuth device flow 权限授权请求（与 lark-cli auth login 相同机制）。

    scope 参数传给飞书后，返回的 verification_uri_complete URL 中会预带 scope 参数，
    用户打开链接后飞书授权页会自动勾选这些权限，用户一键确认即可。

    返回包含 device_code, verification_url, expires_in, interval 的字典。
    """
    import base64
    accounts_base = LARK_ACCOUNTS_URL if brand == "lark" else FEISHU_ACCOUNTS_URL
    url = f"{accounts_base}/oauth/v1/device_authorization"

    # Authorization: Basic base64(appId:appSecret)
    basic = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()

    encoded = urllib.parse.urlencode({
        "client_id": app_id,
        "scope": scope,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    verification_url = data.get("verification_uri_complete") or data.get("verification_uri", "")
    return {
        "device_code": data["device_code"],
        "verification_url": verification_url,
        "expires_in": data.get("expires_in", 300),
        "interval": data.get("interval", 5),
    }


def poll_device_token(app_id: str, app_secret: str,
                      device_code: str, expires_in: int, interval: int,
                      brand: str = "feishu") -> dict:
    """轮询 OAuth device token，直到用户完成授权或超时。"""
    open_base = LARK_OPEN_URL if brand == "lark" else FEISHU_OPEN_URL
    url = f"{open_base}/open-apis/authen/v2/oauth/token"

    deadline = time.time() + expires_in
    attempt = 0

    print(f"  {DIM}等待授权确认...{RESET}", end="", flush=True)

    while time.time() < deadline and attempt < 200:
        attempt += 1
        time.sleep(3)
        print(".", end="", flush=True)

        try:
            resp = _post_form(url, {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": app_id,
                "client_secret": app_secret,
            })
        except Exception:
            continue

        error = resp.get("error", "")
        if not error and resp.get("access_token"):
            print(f" {GREEN}✓{RESET}")
            return resp
        elif error == "authorization_pending":
            continue
        elif error == "slow_down":
            pass
        elif error == "access_denied":
            print()
            raise RuntimeError("用户拒绝了授权")
        elif error in ("expired_token", "invalid_grant"):
            print()
            raise RuntimeError("授权链接已过期")
        else:
            print()
            raise RuntimeError(f"授权失败：{error}")

    print()
    raise RuntimeError("等待超时")


def authorize_app_scopes(app_id: str, app_secret: str,
                          brand: str = "feishu") -> bool:
    """
    通过 OAuth device flow 引导用户为应用授权所需权限。

    与 lark-cli auth login --recommend 相同机制：
    - scope 在请求中传给飞书
    - 飞书返回带 scope 参数的验证 URL
    - 用户打开链接，授权页自动预选这些权限，一键确认即可

    返回 True 表示授权成功，False 表示跳过或失败。
    """
    try:
        auth = request_device_authorization(app_id, app_secret, REMOTE_CLAUDE_SCOPES, brand)
    except Exception as e:
        _warn(f"无法生成授权链接：{e}")
        return False

    print(f"\n  {CYAN}请打开以下链接，确认授予应用所需权限：{RESET}")
    print(f"  {DIM}（页面中的权限已自动预选，直接点击确认即可）{RESET}")
    print(f"\n  {BOLD}{auth['verification_url']}{RESET}\n")

    if _open_browser(auth["verification_url"]):
        _info("已尝试自动在浏览器中打开")

    _try_print_qrcode(auth["verification_url"])

    try:
        poll_device_token(app_id, app_secret,
                          auth["device_code"], auth["expires_in"], auth["interval"],
                          brand)
        return True
    except RuntimeError as e:
        _warn(f"授权未完成：{e}")
        return False
    except Exception as e:
        _warn(f"授权出错：{e}")
        return False


# ── 凭证验证 ───────────────────────────────────────────────────────────────

def verify_credentials(app_id: str, app_secret: str) -> tuple[bool, str]:
    """
    验证飞书应用凭证是否有效。

    返回 (成功, 错误信息或 tenant_access_token)。
    """
    try:
        resp = _post_json(
            f"{FEISHU_OPEN_URL}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret},
        )
        if resp.get("code") == 0:
            return True, resp.get("tenant_access_token", "")
        return False, f"code={resp.get('code')}, msg={resp.get('msg', '未知错误')}"
    except Exception as e:
        return False, str(e)


# ── .env 文件读写 ──────────────────────────────────────────────────────────

def _read_env_file(path: Path) -> list[str]:
    """读取 .env 文件的所有行。"""
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    return []


def write_env_file(app_id: str, app_secret: str) -> Path:
    """
    写入 app_id 和 app_secret 到 ~/.remote-claude/.env。

    如果文件已存在，只更新 FEISHU_APP_ID 和 FEISHU_APP_SECRET 两行，保留其他配置。
    如果文件不存在，从 .env.example 生成。
    """
    env_path = get_env_file()
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    lines = _read_env_file(env_path)

    if not lines:
        # 从 .env.example 生成
        example_path = Path(_PROJECT_ROOT) / ".env.example"
        if example_path.exists():
            lines = example_path.read_text(encoding="utf-8").splitlines()
        else:
            lines = [
                "# Remote Claude 飞书客户端配置",
                "FEISHU_APP_ID=",
                "FEISHU_APP_SECRET=",
            ]

    # 更新或追加 FEISHU_APP_ID / FEISHU_APP_SECRET
    updated_id = False
    updated_secret = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FEISHU_APP_ID=") and not stripped.startswith("#"):
            new_lines.append(f"FEISHU_APP_ID={app_id}")
            updated_id = True
        elif stripped.startswith("FEISHU_APP_SECRET=") and not stripped.startswith("#"):
            new_lines.append(f"FEISHU_APP_SECRET={app_secret}")
            updated_secret = True
        else:
            new_lines.append(line)

    if not updated_id:
        new_lines.append(f"FEISHU_APP_ID={app_id}")
    if not updated_secret:
        new_lines.append(f"FEISHU_APP_SECRET={app_secret}")

    content = "\n".join(new_lines) + "\n"

    # 写入（权限 0600）
    fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)

    return env_path


def _read_current_config() -> tuple[str, str]:
    """读取当前 .env 中的 app_id 和 app_secret。"""
    env_path = get_env_file()
    if not env_path.exists():
        return "", ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("FEISHU_APP_ID=") and not stripped.startswith("#"):
            _, _, val = stripped.partition("=")
            app_id = val.strip()
        elif stripped.startswith("FEISHU_APP_SECRET=") and not stripped.startswith("#"):
            _, _, val = stripped.partition("=")
            app_secret = val.strip()
    return locals().get("app_id", ""), locals().get("app_secret", "")


# ── 应用配置 Checklist ─────────────────────────────────────────────────────

# remote_claude 需要的最小权限集
REQUIRED_PERMISSIONS = [
    ("base:app:read", "读取多维表格应用信息"),
    ("base:field:read", "读取多维表格字段"),
    ("base:form:read", "读取多维表格表单"),
    ("base:record:read", "读取多维表格记录"),
    ("base:record:retrieve", "检索多维表格记录"),
    ("base:table:read", "读取多维表格表格"),
    ("board:whiteboard:node:read", "读取白板节点"),
    ("calendar:calendar.event:create", "创建日历事件"),
    ("calendar:calendar.event:delete", "删除日历事件"),
    ("calendar:calendar.event:read", "读取日历事件"),
    ("calendar:calendar.event:reply", "回复日历事件"),
    ("calendar:calendar.event:update", "更新日历事件"),
    ("calendar:calendar.free_busy:read", "读取日历忙闲状态"),
    ("calendar:calendar:read", "读取日历信息"),
    ("cardkit:card:write", "写入卡片内容"),
    ("contact:contact.base:readonly", "读取通讯录基本信息"),
    ("contact:user.base:readonly", "读取用户基本信息"),
    ("contact:user.employee_id:readonly", "读取用户工号"),
    ("contact:user.id:readonly", "读取用户 ID"),
    ("docs:document.comment:read", "读取文档评论"),
    ("docs:document.content:read", "读取文档内容"),
    ("docs:document.media:download", "下载文档媒体"),
    ("docs:document.media:upload", "上传文档媒体"),
    ("docs:document:import", "导入文档"),
    ("docs:permission.member:auth", "校验文档成员权限"),
    ("docs:permission.member:create", "创建文档成员"),
    ("docs:permission.member:transfer", "转让文档所有者"),
    ("docx:document.block:convert", "转换文档块"),
    ("docx:document:create", "创建 Docx 文档"),
    ("docx:document:readonly", "只读 Docx 文档"),
    ("docx:document:write_only", "写入 Docx 文档"),
    ("drive:drive.metadata:readonly", "读取云空间元数据"),
    ("drive:drive.search:readonly", "搜索云空间文件"),
    ("drive:drive:version:readonly", "读取云空间版本"),
    ("drive:file:download", "下载云空间文件"),
    ("drive:file:upload", "上传云空间文件"),
    ("im:chat.managers:write_only", "管理群聊管理员"),
    ("im:chat.members:read", "读取群成员"),
    ("im:chat.members:write_only", "管理群成员"),
    ("im:chat.tabs:read", "读取群标签页"),
    ("im:chat.tabs:write_only", "管理群标签页"),
    ("im:chat.top_notice:write_only", "设置群置顶公告"),
    ("im:chat:create", "创建群聊"),
    ("im:chat:delete", "删除群聊"),
    ("im:chat:operate_as_owner", "以群主身份操作"),
    ("im:chat:read", "读取群聊信息"),
    ("im:chat:update", "更新群聊信息"),
    ("im:message.group_at_msg:readonly", "读取群 @ 消息"),
    ("im:message.group_msg", "发送群消息"),
    ("im:message.p2p_msg:readonly", "读取私聊消息"),
    ("im:message.reactions:read", "读取消息表情回应"),
    ("im:message.reactions:write_only", "管理消息表情回应"),
    ("im:message.urgent", "发送加急消息"),
    ("im:message.urgent.status:write", "更新加急消息状态"),
    ("im:message:readonly", "只读消息"),
    ("im:message:recall", "撤回消息"),
    ("im:message:send_as_bot", "以机器人身份发消息"),
    ("im:message:update", "更新消息"),
    ("im:resource", "上传/下载消息资源"),
    ("search:docs:read", "搜索文档"),
    ("sheets:spreadsheet.meta:read", "读取电子表格元数据"),
    ("sheets:spreadsheet.meta:write_only", "写入电子表格元数据"),
    ("sheets:spreadsheet:create", "创建电子表格"),
    ("sheets:spreadsheet:read", "读取电子表格"),
    ("sheets:spreadsheet:write_only", "写入电子表格"),
    ("space:document:delete", "删除知识空间文档"),
    ("space:document:retrieve", "检索知识空间文档"),
    ("task:task:read", "读取任务"),
    ("task:task:readonly", "只读任务"),
    ("task:task:write", "写入任务"),
    ("task:task:writeonly", "只写任务"),
    ("task:tasklist:read", "读取任务列表"),
    ("wiki:wiki:readonly", "只读知识库"),
]

REQUIRED_EVENTS = [
    ("im.message.receive_v1", "接收消息事件"),
    ("card.action.trigger", "卡片交互回调"),
]


def print_checklist(app_id: str):
    """打印需要手动完成的飞书开放平台配置步骤。"""
    base = f"https://open.feishu.cn/app/{app_id}"

    print(f"\n{YELLOW}{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"{YELLOW}{BOLD}  还需在飞书开放平台完成以下配置{RESET}")
    print(f"{YELLOW}{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")

    print(f"""
{BOLD}1. 启用「机器人」能力{RESET}
   → {CYAN}{base}/bot{RESET}
   勾选「机器人」，保存

{BOLD}2. 配置事件订阅{RESET}（选择「使用长连接接收事件」模式）
   → {CYAN}{base}/event{RESET}
   添加以下事件：""")
    for event, desc in REQUIRED_EVENTS:
        print(f"   - {GREEN}{event}{RESET}  {DIM}({desc}){RESET}")

    print(f"""
{BOLD}3. 添加 API 权限{RESET}
   → {CYAN}{base}/permission{RESET}
   申请以下权限：""")
    for perm, desc in REQUIRED_PERMISSIONS:
        print(f"   - {GREEN}{perm}{RESET}  {DIM}({desc}){RESET}")

    print(f"""
{BOLD}4. 创建版本并发布应用{RESET}
   → {CYAN}{base}/version{RESET}
   点击「创建版本」→ 填写版本信息 → 提交审核（或直接发布）

{DIM}提示：如果是个人开发者测试，可以在审批流程中选择「无需审批直接启用」{RESET}
""")

    print(f"完成以上步骤后，运行以下命令验证配置：")
    print(f"  {CYAN}remote-claude lark init --check{RESET}\n")


# ── Check 模式 ─────────────────────────────────────────────────────────────

def run_check():
    """检查当前配置状态，验证凭证有效性。"""
    _print_header()
    print(f"{BOLD}配置检查模式{RESET}\n")

    env_path = get_env_file()

    # 检查 .env 文件
    if not env_path.exists():
        _err(f"配置文件不存在：{env_path}")
        print(f"\n运行 {CYAN}remote-claude lark init{RESET} 开始配置")
        return 1

    _ok(f"配置文件：{env_path}")

    app_id, app_secret = _read_current_config()

    if not app_id or app_id in ("cli_xxxxx", ""):
        _err("FEISHU_APP_ID 未配置")
        return 1
    _ok(f"App ID：{app_id}")

    if not app_secret or app_secret in ("xxxxx", ""):
        _err("FEISHU_APP_SECRET 未配置")
        return 1
    _ok(f"App Secret：{'*' * 8}{app_secret[-4:] if len(app_secret) > 4 else '****'}")

    # 验证凭证
    print(f"\n  验证凭证...", end="", flush=True)
    ok, result = verify_credentials(app_id, app_secret)
    if ok:
        print(f" {GREEN}✓ 有效{RESET}")
    else:
        print(f" {RED}✗ 无效{RESET}")
        _err(f"凭证验证失败：{result}")
        return 1

    # 尝试 WebSocket 连接检测
    print(f"\n  尝试 WebSocket 连接...", end="", flush=True)
    ws_ok, ws_msg = _check_websocket(app_id, app_secret)
    if ws_ok:
        print(f" {GREEN}✓ 成功{RESET}")
        print(f"\n{GREEN}{BOLD}✅ 配置完整，飞书机器人已就绪！{RESET}")
        print(f"\n现在可以启动：{CYAN}remote-claude lark start{RESET}\n")
    else:
        print(f" {YELLOW}⚠{RESET}")
        _warn(f"WebSocket 连接失败：{ws_msg}")
        _warn("可能原因：未启用机器人能力、未配置事件订阅或应用未发布")
        print()
        print_checklist(app_id)
        return 1

    return 0


def _check_websocket(app_id: str, app_secret: str) -> tuple[bool, str]:
    """尝试建立 WebSocket 连接测试机器人能力是否就绪。"""
    try:
        import lark_oapi as lark
        # 仅测试能否获取 WS endpoint，不真正建立持久连接
        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
        # 调用一个轻量级 API 测试 bot 权限：获取机器人信息
        from lark_oapi.api.bot.v3 import GetBotInfoRequest
        req = GetBotInfoRequest.builder().build()
        resp = client.bot.v3.bot.get(req)
        if resp.success():
            return True, ""
        return False, f"code={resp.code}, msg={resp.msg}"
    except ImportError:
        # 没有 lark_oapi，退化为 API 检查
        return _check_bot_api(app_id, app_secret)
    except Exception as e:
        return False, str(e)


def _check_bot_api(app_id: str, app_secret: str) -> tuple[bool, str]:
    """使用飞书 REST API 检查机器人能力。"""
    try:
        # 获取 tenant token
        ok, token = verify_credentials(app_id, app_secret)
        if not ok:
            return False, token

        # 调用获取机器人信息 API
        req = urllib.request.Request(
            f"{FEISHU_OPEN_URL}/open-apis/bot/v3/info",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("code") == 0:
            bot = data.get("bot", {})
            bot_name = bot.get("app_name", "未知")
            _ok(f"机器人名称：{bot_name}")
            return True, ""
        elif data.get("code") == 230013:
            return False, "应用未启用机器人能力（需在开放平台启用）"
        else:
            return False, f"code={data.get('code')}, msg={data.get('msg', '')}"
    except Exception as e:
        return False, str(e)


# ── 主向导流程 ─────────────────────────────────────────────────────────────

class SetupWizard:
    """飞书机器人配置向导。"""

    def __init__(self, check_only: bool = False, new_only: bool = False):
        self.check_only = check_only
        self.new_only = new_only

    def run(self) -> int:
        if self.check_only:
            return run_check()

        try:
            return self._run_wizard(new_mode=self.new_only)
        except KeyboardInterrupt:
            print(f"\n\n{YELLOW}已取消配置{RESET}\n")
            return 1

    def _run_wizard(self, new_mode: bool = False) -> int:
        _print_header()

        if new_mode:
            print(f"{BOLD}创建新飞书应用{RESET}  {DIM}（不会修改现有配置）{RESET}\n")
        else:
            # ── 阶段 0：检查已有配置 ─────────────────────────────────────
            _print_step(0, "检查现有配置")

            env_path = get_env_file()
            existing_id, existing_secret = _read_current_config()

            if existing_id and existing_id not in ("cli_xxxxx", ""):
                masked_id = existing_id
                masked_secret = ('*' * 8 + existing_secret[-4:]) if len(existing_secret) > 4 else "****"
                _ok(f"已有配置：{masked_id} / {masked_secret}")
                ans = _read_input(f"  是否重新配置？(y/N)", default="n")
                if ans.lower() not in ("y", "yes"):
                    print(f"\n保持现有配置。运行 {CYAN}remote-claude lark init --check{RESET} 可验证配置状态。\n")
                    return 0

        # ── 阶段 1：获取凭证 ───────────────────────────────────────────────
        _print_step(1, "扫码创建飞书应用")

        app_id, app_secret = self._get_credentials_via_scan()

        if not app_id or not app_secret:
            _err("凭证获取失败")
            return 1

        # ── 阶段 2：验证凭证 ───────────────────────────────────────────────
        _print_step(2, "验证凭证")

        print(f"  验证中...", end="", flush=True)
        ok, result = verify_credentials(app_id, app_secret)
        if ok:
            print(f" {GREEN}✓ 有效{RESET}")
        else:
            print(f" {RED}✗{RESET}")
            _err(f"凭证无效：{result}")
            return 1

        # ── 阶段 3：应用身份权限开通（tenant scope）──────────────────────
        _print_step(3, "开通应用身份权限")
        authorize_tenant_scopes(app_id)
        _ok("应用身份权限配置完成")

        # ── 阶段 4：用户身份权限授权（预选权限，一键确认）──────────────
        _print_step(4, "授权用户身份权限")
        print(f"  {DIM}页面中的权限已自动预选，直接点击确认即可{RESET}")
        scope_ok = authorize_app_scopes(app_id, app_secret)
        if scope_ok:
            _ok("用户身份权限授权完成")
        else:
            _warn("用户身份权限授权跳过，稍后可手动在开放平台配置")

        # ── 阶段 5：发布应用 ───────────────────────────────────────────────
        _print_step(5, "发布应用（必须完成，否则无法使用）")

        publish_url = f"https://open.feishu.cn/app/{app_id}/version/create"
        print(f"  {DIM}未发布的应用无法被飞书用户搜索和使用。{RESET}")
        print(f"  正在打开发布页面：{CYAN}{publish_url}{RESET}\n")
        _open_browser(publish_url)

        print(f"  请在浏览器中按以下步骤操作：")
        print(f"  1. 填写版本号")
        print(f"  2. 填写更新说明（随便填）")
        print(f"  3. 点击「保存」")
        print(f"  4. 点击「确认发布」\n")
        input(f"  {DIM}完成发布后按 Enter 继续...{RESET}")

        # ── 阶段 6：保存凭证 ───────────────────────────────────────────────
        _print_step(6, "保存凭证")

        if new_mode:
            print(f"""
{CYAN}{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}
  {BOLD}应用凭证（请妥善保存）{RESET}
{CYAN}{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}

  {BOLD}FEISHU_APP_ID{RESET}     = {GREEN}{app_id}{RESET}
  {BOLD}FEISHU_APP_SECRET{RESET} = {GREEN}{app_secret}{RESET}
""")
        else:
            saved_path = write_env_file(app_id, app_secret)
            _ok(f"已写入：{saved_path}")

        print()
        _ok("配置全部完成！")
        if not new_mode:
            print(f"\n  运行以下命令验证配置：")
            print(f"  {CYAN}remote-claude lark init --check{RESET}\n")

        return 0

    def _get_credentials_via_scan(self) -> tuple[str, str]:
        """通过扫码创建应用获取凭证。"""
        print()
        try:
            app_id, app_secret = create_app_via_scan("feishu")
            _ok(f"应用已创建：{app_id}")
            return app_id, app_secret
        except RuntimeError as e:
            _err(str(e))
            return "", ""
        except Exception as e:
            _err(f"创建失败：{e}")
            return "", ""

def main():
    """命令行入口。"""
    import argparse
    parser = argparse.ArgumentParser(description="飞书机器人配置向导")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="仅检查现有配置状态")
    group.add_argument("--new", action="store_true", help="扫码创建新应用（不修改已有配置）")
    args = parser.parse_args()

    wizard = SetupWizard(check_only=args.check, new_only=args.new)
    sys.exit(wizard.run())


if __name__ == "__main__":
    main()
