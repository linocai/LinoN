"""舆情(消息面)best-effort 抓取 + 降级(阶段2 Phase D3)。

plan §4.0:best-effort 抓东财股吧标题页(免费),低频、仅对选中候选;超时 4s;
失败/无数据 → news 轴 neutral 占位"未获取到舆情,仅技术+资金判定";**绝不阻塞深判**。

抓取仅取标题文本(不碰新闻 NLP),交给 DeepSeek 感知情绪/排雷。可注入 fetch_fn 免单测联网。
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_TIMEOUT = 4.0
_GUBA_URL = "https://guba.eastmoney.com/list,{code}.html"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
}

# 东财股吧标题大致出现在 .articleh .l3 a 的 title/文本里;用宽松正则抓 a 标签 title。
_TITLE_RE = re.compile(r'<a[^>]*title="([^"]{4,80})"', re.IGNORECASE)

_DEGRADE_NOTE = "未获取到舆情,仅技术+资金判定"


def _default_fetch(code: str) -> List[str]:
    """真抓东财股吧标题(best-effort)。任何异常 → 返回空列表(降级,不抛)。"""
    try:
        import requests
    except ImportError:
        return []
    bare = re.sub(r"\D", "", code or "")[:6]
    if not bare:
        return []
    try:
        resp = requests.get(_GUBA_URL.format(code=bare), headers=_HEADERS, timeout=_TIMEOUT)
        resp.encoding = "utf-8"
        text = resp.text
    except Exception:
        return []
    titles = _TITLE_RE.findall(text)
    # 去重保序 + 过滤纯导航词
    seen = set()
    out: List[str] = []
    for t in titles:
        t = t.strip()
        if t and t not in seen and not t.startswith("东方财富"):
            seen.add(t)
            out.append(t)
        if len(out) >= 10:
            break
    return out


def fetch_sentiment(
    code: str, *, fetch_fn: Optional[Callable[[str], List[str]]] = None
) -> Dict[str, object]:
    """抓某票舆情标题。返回 news 上下文 {titles: [...], note: str, degraded: bool}。

    失败/无数据 → {titles: [], note: "未获取到舆情…", degraded: True}(不阻塞深判)。
    fetch_fn 可注入(测试免联网)。
    """
    fetch_fn = fetch_fn or _default_fetch
    try:
        titles = fetch_fn(code)
    except Exception as e:   # 抓取替身异常也兜住
        logger.warning("舆情抓取异常(降级): %s", e)
        titles = []
    if not titles:
        return {"titles": [], "note": _DEGRADE_NOTE, "degraded": True}
    return {"titles": titles, "note": "", "degraded": False}
