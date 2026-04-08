"""
统计追踪辅助模块

统一管理 stats 模块的导入和安全调用。
"""

import logging

logger = logging.getLogger('StatsHelper')

try:
    from stats import track as _track_stats
except ImportError:
    _track_stats = None
except OSError as e:
    logger.warning(f"stats 模块加载失败（系统错误），统计功能将禁用: {e}")
    _track_stats = None
except Exception as e:
    logger.warning(f"stats 模块加载异常: {e}")
    _track_stats = None


def safe_track_stats(*args, **kwargs):
    """安全调用统计追踪函数，模块未加载时静默跳过"""
    if _track_stats is not None:
        try:
            _track_stats(*args, **kwargs)
        except (ConnectionError, TimeoutError) as e:
            logger.debug(f"统计追踪失败（网络错误）: {e}")
        except Exception as e:
            logger.debug(f"统计追踪失败: {e}")
