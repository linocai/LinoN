"""实时价(免费多源:新浪主 → 腾讯降级)。

接口契约(plan §4 Phase 0.2):
    get_realtime_quote(code) -> Quote | None        # 全失败返回 None,不抛崩
    get_realtime_quotes(codes) -> dict[str, Quote]
    Quote = {code, name, price, pre_close, open, high, low,
             limit_up, limit_down, volume(手), amount(元),
             bid1..5/ask1..5(可选), ts, source}

关键归一(两源字段口径不同,务必对齐到统一 Quote):
  · 新浪:逗号分隔,GBK;volume 单位=股(÷100→手),amount 单位=元(原样)。
         bid/ask 块为「量先价后」。需 Referer 头否则被拒(返回 Kinsoku jikou desu)。
  · 腾讯:~ 分隔,GBK;index0=市场标记;volume 单位=手(原样),amount(field37)=万元(×1e4→元)。
         bid/ask 块为「价先量后」(与新浪相反)。
  · 涨跌停由 pre_close 算:主板 ±10%、名称含 ST/*ST → ±5%;
    300/688 已黑名单不处理(不涉 ±20%);按 A 股最小变动价 0.01 四舍五入。

源全挂 → 单票返回 None,整体不崩。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

try:
    import requests  # 主路径
except ImportError:  # pragma: no cover - 依赖未装时
    requests = None  # type: ignore

# 网络请求超时(秒)。免费源偶发慢,给足但不卡死轮询。
_TIMEOUT = 4.0
# 新浪 2022 后强制校验 Referer,缺失返回 "Kinsoku jikou desu!"
_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
}
_TENCENT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
}

_SINA_URL = "https://hq.sinajs.cn/list={symbols}"
_TENCENT_URL = "https://qt.gtimg.cn/q={symbols}"


# —— Quote 数据结构 ————————————————————————————————————————————————

@dataclass
class Quote:
    code: str
    name: str
    price: float
    pre_close: float
    open: float
    high: float
    low: float
    limit_up: float
    limit_down: float
    volume: float          # 手
    amount: float          # 元
    ts: str                # 数据时间
    source: str            # "sina" | "tencent"
    bid: List[float] = field(default_factory=list)   # bid1..5 价(可选)
    ask: List[float] = field(default_factory=list)   # ask1..5 价(可选)

    def to_dict(self) -> dict:
        return asdict(self)


# —— 工具:代码 → 市场前缀 ——————————————————————————————————————————

def to_symbol(code: str) -> str:
    """归一为带市场前缀的符号。6*→sh、0*/3*→sz。已带前缀则原样小写。"""
    c = code.strip().lower()
    if c.startswith(("sh", "sz")):
        return c
    digits = re.sub(r"\D", "", c)
    if not digits:
        return c
    if digits.startswith("6"):
        return "sh" + digits
    if digits.startswith(("0", "3")):
        return "sz" + digits
    # 其它(如 8/4 北交所)阶段0 不涉,默认 sh 占位
    return "sh" + digits


def _bare_code(symbol_or_code: str) -> str:
    """剥掉市场前缀,返回 6 位数字代码。"""
    return re.sub(r"\D", "", symbol_or_code)


# —— 涨跌停计算 ————————————————————————————————————————————————————

def _is_st(name: str) -> bool:
    n = (name or "").upper().replace(" ", "")
    return "ST" in n  # 含 ST / *ST 均命中


def compute_limits(pre_close: float, code: str, name: str) -> tuple[float, float]:
    """由 pre_close 算涨跌停价。

    主板 ±10%;名称含 ST/*ST → ±5%;300/688(创业/科创)已黑名单,
    阶段0 不处理 ±20%(返回 ±10% 占位,反正这些票不进系统)。
    按 A 股最小变动价 0.01 四舍五入。
    """
    if pre_close <= 0:
        return 0.0, 0.0
    ratio = 0.05 if _is_st(name) else 0.10
    up = round(pre_close * (1 + ratio), 2)
    down = round(pre_close * (1 - ratio), 2)
    return up, down


def _f(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# —— 新浪源 ————————————————————————————————————————————————————————

_SINA_RE = re.compile(r'hq_str_([a-z]{2}\d+)="([^"]*)"')


def _fetch_sina(symbols: List[str]) -> Dict[str, str]:
    """返回 {symbol: 引号内原始字符串}。网络/HTTP 异常 → 空 dict,不抛。"""
    if requests is None or not symbols:
        return {}
    url = _SINA_URL.format(symbols=",".join(symbols))
    try:
        resp = requests.get(url, headers=_SINA_HEADERS, timeout=_TIMEOUT)
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for sym, body in _SINA_RE.findall(text):
        out[sym] = body
    return out


def _parse_sina(symbol: str, body: str) -> Optional[Quote]:
    """解析新浪单票字符串(逗号分隔,32 字段)。停牌/非法 → None。"""
    parts = body.split(",")
    if len(parts) < 32 or not parts[0]:
        return None
    name = parts[0]
    open_ = _f(parts[1])
    pre_close = _f(parts[2])
    price = _f(parts[3])
    high = _f(parts[4])
    low = _f(parts[5])
    volume_shares = _f(parts[8])     # 股
    amount_yuan = _f(parts[9])       # 元
    if pre_close <= 0 and price <= 0:
        return None
    # bid 块 10..19(量先价后),ask 块 20..29(量先价后)
    bid = [_f(parts[11 + i * 2]) for i in range(5)]
    ask = [_f(parts[21 + i * 2]) for i in range(5)]
    date = parts[30] if len(parts) > 30 else ""
    time = parts[31] if len(parts) > 31 else ""
    ts = f"{date} {time}".strip()
    code = _bare_code(symbol)
    up, down = compute_limits(pre_close, code, name)
    return Quote(
        code=code,
        name=name,
        price=price if price > 0 else pre_close,
        pre_close=pre_close,
        open=open_,
        high=high,
        low=low,
        limit_up=up,
        limit_down=down,
        volume=round(volume_shares / 100, 2),   # 股 → 手
        amount=amount_yuan,                      # 元(原样)
        ts=ts,
        source="sina",
        bid=bid,
        ask=ask,
    )


# —— 腾讯源(降级)——————————————————————————————————————————————————

_TENCENT_RE = re.compile(r'v_([a-z]{2}\d+)="([^"]*)"')


def _fetch_tencent(symbols: List[str]) -> Dict[str, str]:
    if requests is None or not symbols:
        return {}
    url = _TENCENT_URL.format(symbols=",".join(symbols))
    try:
        resp = requests.get(url, headers=_TENCENT_HEADERS, timeout=_TIMEOUT)
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for sym, body in _TENCENT_RE.findall(text):
        out[sym] = body
    return out


def _parse_tencent(symbol: str, body: str) -> Optional[Quote]:
    """解析腾讯单票字符串(~ 分隔)。停牌/非法 → None。

    单位:volume(field6)=手(原样);amount(field37)=万元(×1e4→元)。
    bid/ask 为「价先量后」(与新浪相反)。
    """
    parts = body.split("~")
    if len(parts) < 35 or not parts[1]:
        return None
    name = parts[1]
    price = _f(parts[3])
    pre_close = _f(parts[4])
    open_ = _f(parts[5])
    volume_lots = _f(parts[6])       # 手(原样)
    # bid 块 9..18(价先量后):价在 9,11,13,15,17
    bid = [_f(parts[9 + i * 2]) for i in range(5)]
    # ask 块 19..28(价先量后):价在 19,21,23,25,27
    ask = [_f(parts[19 + i * 2]) for i in range(5)]
    high = _f(parts[33]) if len(parts) > 33 else 0.0
    low = _f(parts[34]) if len(parts) > 34 else 0.0
    ts_raw = parts[30] if len(parts) > 30 else ""   # YYYYMMDDHHMMSS
    ts = _fmt_tencent_ts(ts_raw)
    amount_wan = _f(parts[37]) if len(parts) > 37 else 0.0   # 万元
    if pre_close <= 0 and price <= 0:
        return None
    code = _bare_code(symbol)
    up, down = compute_limits(pre_close, code, name)
    return Quote(
        code=code,
        name=name,
        price=price if price > 0 else pre_close,
        pre_close=pre_close,
        open=open_,
        high=high,
        low=low,
        limit_up=up,
        limit_down=down,
        volume=volume_lots,                # 手(原样)
        amount=round(amount_wan * 10000, 2),  # 万元 → 元
        ts=ts,
        source="tencent",
        bid=bid,
        ask=ask,
    )


def _fmt_tencent_ts(raw: str) -> str:
    """YYYYMMDDHHMMSS → 'YYYY-MM-DD HH:MM:SS';非法原样返回。"""
    raw = (raw or "").strip()
    if len(raw) == 14 and raw.isdigit():
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]} {raw[8:10]}:{raw[10:12]}:{raw[12:14]}"
    return raw


# —— 对外 API ——————————————————————————————————————————————————————

def get_realtime_quotes(codes: List[str]) -> Dict[str, Quote]:
    """批量拉。新浪主源拿到的票优先;主源缺的票逐一用腾讯补。

    返回 {原始 code: Quote}。任一源全挂或单票解析失败 → 该票不在结果里(跳过),整体不崩。
    """
    if not codes:
        return {}
    # 原始 code ↔ symbol 双向映射(结果用原始 code 作 key)
    sym_to_code: Dict[str, str] = {}
    symbols: List[str] = []
    for c in codes:
        sym = to_symbol(c)
        sym_to_code[sym] = c
        symbols.append(sym)

    result: Dict[str, Quote] = {}

    # 1) 新浪主源
    sina_raw = _fetch_sina(symbols)
    for sym in symbols:
        body = sina_raw.get(sym)
        if body is None:
            continue
        q = _parse_sina(sym, body)
        if q is not None:
            result[sym_to_code[sym]] = q

    # 2) 腾讯降级:补齐主源没拿到的票
    missing_syms = [s for s in symbols if sym_to_code[s] not in result]
    if missing_syms:
        tencent_raw = _fetch_tencent(missing_syms)
        for sym in missing_syms:
            body = tencent_raw.get(sym)
            if body is None:
                continue
            q = _parse_tencent(sym, body)
            if q is not None:
                result[sym_to_code[sym]] = q

    return result


def get_realtime_quote(code: str) -> Optional[Quote]:
    """单票。全失败返回 None,不抛崩。"""
    return get_realtime_quotes([code]).get(code)
