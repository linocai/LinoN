"""Tushare 薄封装(plan §4 Phase 0.3)。

四接口,统一带状态返回,token 缺失 / 初始化失败 / 限频 / 网络异常
→ 一律 ok=False, data=None, reason 可读,【绝不抛异常】:

    TushareResult = { ok: bool, data: DataFrame | None, reason: str }
    ts_moneyflow(code, start, end)     # 主力/小单净额(原始源,保留供 LLM 深判层)
    ts_moneyflow_dc(code, start, end)  # 个股资金流向·东财源(net_amount=主力净额万元)
    ts_daily_basic(code, trade_date)   # 换手率/涨跌幅/PE-PB
    ts_daily(code, start, end)         # 日线·形态
    ts_trade_cal(start, end)           # 交易日历
    ts_stock_basic()                   # 全市场代码→行业映射(阶段2 第 5 接口)

token 取自 app.config.settings(读 .env)。本期 token 未到,只验证无 token
优雅降级路径;有 token 联调待后续(报告已注明)。

代码归一:Tushare 用 `600000.SH` 风格的 ts_code;本封装入参接受裸 6 位代码或
带前缀,内部统一转 ts_code。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Optional

from app.config import settings

# pandas / tushare 是重依赖,延迟到首次真正需要时再 import,
# 这样无 token 降级路径在依赖未装时也不崩(直接走 reason 返回)。
_TS_PRO: Any = None
_TS_INIT_DONE = False
_TS_INIT_REASON = ""
_INIT_LOCK = threading.Lock()


@dataclass
class TushareResult:
    ok: bool
    data: Optional[Any]   # pandas.DataFrame | None(避免顶层强依赖 pandas 做类型标注)
    reason: str

    @classmethod
    def fail(cls, reason: str) -> "TushareResult":
        return cls(ok=False, data=None, reason=reason)

    @classmethod
    def success(cls, data: Any) -> "TushareResult":
        return cls(ok=True, data=data, reason="ok")


def to_ts_code(code: str) -> str:
    """裸代码 / 带前缀 → Tushare ts_code(如 '600000.SH')。"""
    c = code.strip().upper()
    if re.match(r"^\d{6}\.(SH|SZ|BJ)$", c):
        return c
    digits = re.sub(r"\D", "", c)
    if len(digits) != 6:
        return c  # 交给上游,Tushare 会自行报错(已被 try 包住)
    if digits.startswith("6"):
        return f"{digits}.SH"
    if digits.startswith(("0", "3")):
        return f"{digits}.SZ"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SH"


def _get_pro() -> tuple[Optional[Any], str]:
    """惰性初始化 Tushare pro 客户端。

    返回 (pro_or_None, reason)。无 token / tushare 未装 / 初始化异常 → (None, reason)。
    成功 → (pro, "ok")。结果缓存(token 在进程生命周期内不变)。
    """
    global _TS_PRO, _TS_INIT_DONE, _TS_INIT_REASON
    if _TS_INIT_DONE:
        return _TS_PRO, _TS_INIT_REASON
    with _INIT_LOCK:
        if _TS_INIT_DONE:
            return _TS_PRO, _TS_INIT_REASON
        token = settings.TUSHARE_TOKEN
        if not token or not token.strip():
            _TS_PRO, _TS_INIT_REASON, _TS_INIT_DONE = None, "token 缺失", True
            return _TS_PRO, _TS_INIT_REASON
        try:
            import tushare as ts  # 延迟导入

            # token 直传 pro_api,【不调 ts.set_token】——set_token 会往用户家目录
            # (`~/...`)写 token 缓存文件;nologin 系统服务用户(如 ECS 上的 linon)
            # 无可写家目录,会 `[Errno 13] Permission denied: '/home/linon'` 致整条
            # Tushare 初始化崩、全市场拉取静默降级。pro_api(token) 直传不碰家目录。
            _TS_PRO = ts.pro_api(token.strip())
            _TS_INIT_REASON = "ok"
        except ImportError:
            _TS_PRO, _TS_INIT_REASON = None, "tushare 包未安装"
        except Exception as e:  # 初始化失败(无效 token / 网络)
            _TS_PRO, _TS_INIT_REASON = None, f"Tushare 初始化失败: {e}"
        finally:
            _TS_INIT_DONE = True
        return _TS_PRO, _TS_INIT_REASON


def reset_client_cache() -> None:
    """清初始化缓存(测试 / token 录入后热切换用)。"""
    global _TS_PRO, _TS_INIT_DONE, _TS_INIT_REASON
    with _INIT_LOCK:
        _TS_PRO, _TS_INIT_DONE, _TS_INIT_REASON = None, False, ""


def _call(api_name: str, **kwargs: Any) -> TushareResult:
    """统一调用包装:拿 pro → 调 api → 捕获一切异常转 reason。"""
    pro, reason = _get_pro()
    if pro is None:
        return TushareResult.fail(reason)
    try:
        method = getattr(pro, api_name)
        df = method(**kwargs)
    except Exception as e:
        # 限频 / 网络 / 权限不足等 Tushare 抛的异常,统一收敛
        msg = str(e)
        if "每分钟" in msg or "频率" in msg or "limit" in msg.lower():
            return TushareResult.fail(f"限频: {msg}")
        return TushareResult.fail(f"网络/接口异常: {msg}")
    if df is None:
        return TushareResult.fail("接口返回空")
    return TushareResult.success(df)


# —— 四接口 ————————————————————————————————————————————————————————

def ts_moneyflow(code: str, start: str, end: str) -> TushareResult:
    """主力/小单净额(原始 moneyflow,同花顺式口径)。start/end 格式 'YYYYMMDD'。

    注:原始 moneyflow 偶发"几天到约一周"的发布延迟、会逐步补齐;选股数据层已
    切到东财源 `ts_moneyflow_dc`(当日数据、6000 积分解锁)。本接口保留供 LLM 深判层用。
    """
    return _call(
        "moneyflow",
        ts_code=to_ts_code(code),
        start_date=start,
        end_date=end,
    )


def ts_moneyflow_dc(code: str, start: str, end: str) -> TushareResult:
    """个股资金流向·东财源(moneyflow_dc)。start/end 格式 'YYYYMMDD'。

    东财口径:`net_amount`=主力净额(万元,= buy_elg_amount 超大单 + buy_lg_amount 大单)。
    6000 积分解锁、全市场给到上一交易日(比原始 moneyflow 的发布延迟更优)。
    与原始 moneyflow 数值有口径差(东财主力 vs 同花顺式),属预期非 bug——这正是用户在
    东财/同花顺 App 里看到的那套主力净额。沿四接口降级模式:无 token/无权限/限频/网络
    异常 → ok=False,data=None,reason 可读,**绝不抛异常**。
    """
    return _call(
        "moneyflow_dc",
        ts_code=to_ts_code(code),
        start_date=start,
        end_date=end,
    )


def ts_daily_basic(code: str, trade_date: str) -> TushareResult:
    """换手率/涨跌幅/PE-PB。trade_date 格式 'YYYYMMDD'。"""
    return _call(
        "daily_basic",
        ts_code=to_ts_code(code),
        trade_date=trade_date,
    )


def ts_daily(code: str, start: str, end: str) -> TushareResult:
    """日线·形态。start/end 格式 'YYYYMMDD'。"""
    return _call(
        "daily",
        ts_code=to_ts_code(code),
        start_date=start,
        end_date=end,
    )


def ts_trade_cal(start: str, end: str) -> TushareResult:
    """交易日历(SSE 沪市)。start/end 格式 'YYYYMMDD'。"""
    return _call(
        "trade_cal",
        exchange="SSE",
        start_date=start,
        end_date=end,
    )


# —— 第 5 接口(阶段2):全市场代码→行业映射 ————————————————————————————

def ts_stock_basic() -> TushareResult:
    """全市场上市股票基础信息(ts_code/symbol/name/industry/list_status)。

    用于白酒/酿酒行业黑名单(精确用 industry 字段归类,Review 拍板)。
    进程内缓存全市场代码→行业映射,启动/EOD 拉一次(缓存逻辑在 screen.fetch)。
    沿四接口降级模式:无 token / 接口失败 → ok=False,data=None,不抛异常。
    """
    return _call(
        "stock_basic",
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,industry,list_status",
    )


# —— 全市场 EOD 批量(阶段2 D1:按 trade_date 单次返回全市场 ~5400 行)——————

def ts_daily_basic_all(trade_date: str) -> TushareResult:
    """全市场当日 daily_basic(换手率/总市值等)。trade_date 'YYYYMMDD'。

    不带 ts_code → Tushare 按 trade_date 一次返回全市场。无 token/失败优雅降级。
    """
    return _call("daily_basic", trade_date=trade_date)


def ts_moneyflow_all(trade_date: str) -> TushareResult:
    """全市场当日 moneyflow(原始源,主力/小单净额)。trade_date 'YYYYMMDD'。

    保留备用;选股数据层已切到 `ts_moneyflow_dc_all`(东财源,当日数据)。
    """
    return _call("moneyflow", trade_date=trade_date)


def ts_moneyflow_dc_all(trade_date: str) -> TushareResult:
    """全市场当日 moneyflow_dc(东财源,主力净额)。trade_date 'YYYYMMDD'。

    不带 ts_code → Tushare 按 trade_date 一次返回全市场(6000 积分给到上一交易日)。
    字段:`net_amount`=主力净额(万元,= 超大单 buy_elg + 大单 buy_lg)。选股资金面唯一信号。
    无 token/无权限(2000 积分跑会落此)/失败 → 优雅降级,绝不抛异常。
    """
    return _call("moneyflow_dc", trade_date=trade_date)


def ts_daily_all(trade_date: str) -> TushareResult:
    """全市场当日 daily(开高低收/量额)。trade_date 'YYYYMMDD'。

    近 N 日形态(放量/新高/均线/60日涨幅)= 逐交易日拉一次再内存拼接。
    """
    return _call("daily", trade_date=trade_date)
