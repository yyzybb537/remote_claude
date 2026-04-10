"""
init_install 上报脚本

每次 init.sh 执行时调用（npm 安装和源码安装均覆盖），发送 init_install 事件到 Mixpanel。
仅依赖标准库，不需要 mixpanel 包，失败静默。
"""

import base64
import json
import platform
import urllib.request
import uuid
from pathlib import Path

_TOKEN = 'c4d804fc1fe4337132e4da90fdb690c9'
_USER_DIR = Path.home() / '.remote-claude'
_ID_FILE = _USER_DIR / 'machine-id'
_REPORTED_VERSION_FILE = _USER_DIR / 'init_install_version'


def _get_machine_id() -> str:
    if _ID_FILE.exists():
        try:
            mid = _ID_FILE.read_text().strip()
            if mid:
                return mid
        except Exception:
            pass
    mid = str(uuid.uuid4())
    try:
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        _ID_FILE.write_text(mid)
    except Exception:
        pass
    return mid


def _resolve_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _get_version() -> str:
    try:
        pkg = _resolve_project_root() / 'package.json'
        return json.loads(pkg.read_text()).get('version', 'unknown')
    except Exception:
        return 'unknown'


def main() -> None:
    machine_id = _get_machine_id()
    version = _get_version()

    # 每个版本只上报一次
    try:
        if _REPORTED_VERSION_FILE.exists() and _REPORTED_VERSION_FILE.read_text().strip() == version:
            return
    except Exception:
        pass
    props = {
        'token': _TOKEN,
        'distinct_id': machine_id,
        'version': version,
        'hostname': platform.node(),
        'os': f'{platform.system()} {platform.release()}',
        'python': platform.python_version(),
    }
    data = base64.b64encode(json.dumps([{
        'event': 'init_install',
        'properties': props,
    }]).encode()).decode()
    req = urllib.request.Request(
        'https://api.mixpanel.com/track',
        data=f'data={data}'.encode(),
        method='POST',
    )
    urllib.request.urlopen(req, timeout=10)

    # 记录已上报版本
    try:
        _REPORTED_VERSION_FILE.write_text(version)
    except Exception:
        pass


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
