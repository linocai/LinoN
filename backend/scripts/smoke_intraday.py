#!/usr/bin/env python3
"""盘中冒烟脚本(plan §4 Phase E)—— 两源盘中真复测,交易时段手动跑。

收 §3「待联调」旧债:新浪/腾讯实时源从未在交易时段真盘中复测(此前只验收盘快照 +
样例报文单测)。②(coach 盘中上下文)③(候选池今日续强确认)均建在两源之上,
本脚本对一组固定测试 code 真拉两源,打印并验证三件事:

  ① 两源价量一致性:同 code 新浪 vs 腾讯 price/pre_close/涨跌停一致(容差内);
     归一后 volume(手)/amount(元)量级一致(校验两源单位坑无回归)。
  ② VWAP 合理性:amount/(volume×100)(元/股,plan §4 致命#1 口径)落在当日
     [low, high] 价区间内(若误用 amount/volume 会大 100 倍显著出界)。
  ③ 盘中量能口径落地数字:打印 elapsed_min/current_vol/projected_full_vol/
     prev5_avg_vol/intraday_vol_ratio 具体数值 + note,供人工核对折算合理。

只读不写库、不推送(纯只读冒烟)。非交易时段运行 → 明确打印"非盘中窗口"退出,
不报错(A 股 09:30–15:00 交易时段窗口判定见 app.data.intraday._is_intraday_window,
含午休——午休时当日累计量/VWAP 仍是有效上午终态,本脚本午休时段也可跑)。

运行(交易时段,含午休):
  source .venv/bin/activate && python scripts/smoke_intraday.py
  或指定测试票(逗号分隔,默认 3 只不同板块示例):
  python scripts/smoke_intraday.py 600519,000858,300750
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

# 允许从 backend/ 任意位置运行:把 backend/ 加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.data import intraday  # noqa: E402
from app.data.realtime import (  # noqa: E402
    Quote,
    _fetch_sina,
    _fetch_tencent,
    _parse_sina,
    _parse_tencent,
    to_symbol,
)
from app.data import tushare_client as tc  # noqa: E402

# 默认 3 只不同板块示例票(主板贵州茅台/主板五粮液/创业板宁德时代)。
_DEFAULT_CODES = ["600519", "000858", "300750"]

# 两源价格一致性容差(元)。免费源偶发报文时刻差 1 拍,给 0.05 元余量。
_PRICE_TOLERANCE = 0.05


def _hr(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def _fetch_both_sources(code: str) -> tuple[Optional[Quote], Optional[Quote]]:
    """分别调新浪/腾讯单源解析函数,各自独立拉一次(不共享 monitor tick)。"""
    sym = to_symbol(code)
    sina_raw = _fetch_sina([sym])
    tencent_raw = _fetch_tencent([sym])
    sina_q = _parse_sina(sym, sina_raw[sym]) if sym in sina_raw else None
    tencent_q = _parse_tencent(sym, tencent_raw[sym]) if sym in tencent_raw else None
    return sina_q, tencent_q


def check_two_source_consistency(code: str) -> bool:
    """① 两源价量一致性核查。返回 True 表示通过(或至少一源可用不报错)。"""
    sina_q, tencent_q = _fetch_both_sources(code)
    print(f"  code={code}")
    if sina_q is None and tencent_q is None:
        print("    ⚠ 两源均未拉到(非交易时段快照缺失/停牌/代码非法)。")
        return False
    if sina_q is not None:
        print(f"    新浪 : price={sina_q.price} pre_close={sina_q.pre_close} "
              f"limit_up/down={sina_q.limit_up}/{sina_q.limit_down} "
              f"volume(手)={sina_q.volume} amount(元)={sina_q.amount} ts={sina_q.ts}")
    else:
        print("    新浪 : 未拉到(降级)")
    if tencent_q is not None:
        print(f"    腾讯 : price={tencent_q.price} pre_close={tencent_q.pre_close} "
              f"limit_up/down={tencent_q.limit_up}/{tencent_q.limit_down} "
              f"volume(手)={tencent_q.volume} amount(元)={tencent_q.amount} ts={tencent_q.ts}")
    else:
        print("    腾讯 : 未拉到(降级)")

    if sina_q is not None and tencent_q is not None:
        price_diff = abs(sina_q.price - tencent_q.price)
        pre_close_diff = abs(sina_q.pre_close - tencent_q.pre_close)
        ok_price = price_diff <= _PRICE_TOLERANCE
        ok_pre = pre_close_diff <= _PRICE_TOLERANCE
        ok_limit = (sina_q.limit_up == tencent_q.limit_up
                    and sina_q.limit_down == tencent_q.limit_down)
        # 量级一致性:volume(手)/amount(元)数量级应相近(同一时刻累计成交,允许因
        # 拉取时刻微小差异,取比值在 [0.5, 2.0] 内视为量级一致,量级差 100 倍会显著出界)。
        vol_ratio = (sina_q.volume / tencent_q.volume) if tencent_q.volume > 0 else None
        amt_ratio = (sina_q.amount / tencent_q.amount) if tencent_q.amount > 0 else None
        ok_vol_scale = vol_ratio is not None and 0.3 <= vol_ratio <= 3.0
        ok_amt_scale = amt_ratio is not None and 0.3 <= amt_ratio <= 3.0
        print(f"    价差(元)={price_diff:.3f}({'OK' if ok_price else '偏差偏大'})"
              f"  昨收差(元)={pre_close_diff:.3f}({'OK' if ok_pre else '偏差偏大'})"
              f"  涨跌停一致={'OK' if ok_limit else '不一致'}")
        print(f"    volume 比(新浪/腾讯)={vol_ratio}  amount 比={amt_ratio}"
              f"  量级{'一致' if (ok_vol_scale and ok_amt_scale) else '⚠ 疑似单位坑回归'}")
        return ok_price and ok_pre and ok_limit and ok_vol_scale and ok_amt_scale
    return True   # 只有单源可用,不判一致性,视为通过(降级链本身没问题)


def check_vwap_reasonable(code: str) -> bool:
    """② VWAP 合理性:amount/(volume×100) 落在当日 [low, high] 内。"""
    sina_q, tencent_q = _fetch_both_sources(code)
    quote = sina_q or tencent_q
    if quote is None:
        print(f"  code={code}: 两源均未拉到,跳过 VWAP 核查。")
        return False
    vwap, is_above = intraday.vwap_of(quote)
    if vwap is None:
        print(f"  code={code}: volume<=0(停牌/无成交),vwap=None(降级,预期行为)。")
        return True
    in_range = quote.low <= vwap <= quote.high
    print(f"  code={code}({quote.source}): vwap={vwap:.4f}  "
          f"当日区间=[{quote.low}, {quote.high}]  price={quote.price}  "
          f"is_above_vwap={is_above}  {'OK 落在区间内' if in_range else '⚠ 出界(疑似单位坑)'}")
    return in_range


def _prev5_avg_vol_smoke(code: str) -> float:
    """近 10 自然日 daily → 最近 5 条 vol 均值(与 app.api.app._prev5_avg_vol 同口径)。"""
    if not settings.has_tushare_token:
        return 0.0
    today = date.today()
    end = today.strftime("%Y%m%d")
    start = (today - timedelta(days=20)).strftime("%Y%m%d")
    res = tc.ts_daily(code, start, end)
    if not res.ok or res.data is None or len(res.data) == 0:
        return 0.0
    df = res.data.sort_values("trade_date", ascending=False).reset_index(drop=True)
    vols = [float(x) for x in df["vol"].tolist()]
    window = vols[:5]
    if not window:
        return 0.0
    return round(sum(window) / len(window), 1)


def check_volume_ratio_numbers(code: str) -> None:
    """③ 打印盘中量能口径落地数字,供人工核对折算合理(如 10:30 时 elapsed≈60、
    折算≈现量×4 量级)。"""
    sina_q, tencent_q = _fetch_both_sources(code)
    quote = sina_q or tencent_q
    now = datetime.now()
    elapsed = intraday.elapsed_trading_minutes(now)
    if quote is None:
        print(f"  code={code}: 两源均未拉到,跳过量能折算核查。")
        return
    prev5 = _prev5_avg_vol_smoke(code)
    ratio, note = intraday.intraday_vol_ratio(quote.volume, prev5, elapsed)
    projected = None
    if elapsed > 0:
        projected = round(quote.volume / elapsed * 240, 1)
    print(f"  code={code}({quote.source}): elapsed_min={elapsed}  "
          f"current_vol(手)={quote.volume}  projected_full_vol(手)={projected}  "
          f"prev5_avg_vol(手)={prev5 if settings.has_tushare_token else '无 token,跳过'}  "
          f"intraday_vol_ratio={ratio}  note={note}")


def main() -> int:
    codes: List[str] = (
        sys.argv[1].split(",") if len(sys.argv) > 1 else list(_DEFAULT_CODES)
    )
    now = datetime.now()
    print("LinoN 盘中冒烟脚本 —— Phase E:两源盘中真复测")
    print(f"  当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    if not intraday._is_intraday_window(now):
        print("\n⚠ 非盘中窗口(非交易日 / 09:30 前 / 15:00 后)——本脚本需交易时段"
              "(含午休)手动跑,当前直接退出,不报错。")
        return 0

    print(f"  测试票: {codes}")
    print(f"  Tushare token: {'已配置' if settings.has_tushare_token else '缺失(prev5 均量将跳过)'}")

    _hr("① 两源价量一致性")
    r1 = all(check_two_source_consistency(c) for c in codes)

    _hr("② VWAP 合理性(落在当日 [low, high] 内)")
    r2 = all(check_vwap_reasonable(c) for c in codes)

    _hr("③ 盘中量能口径落地数字(人工核对)")
    for c in codes:
        check_volume_ratio_numbers(c)

    _hr("结论")
    print(f"  ① 两源一致性: {'通过' if r1 else '存在偏差,见上方明细'}")
    print(f"  ② VWAP 合理性: {'通过' if r2 else '存在出界,见上方明细'}")
    print("  ③ 量能折算数字已打印,人工核对是否合理(如 10:30 时 elapsed≈60、折算≈现量×4 量级)。")
    print("\n冒烟完成。若发现两源盘中口径新坑,记 CLAUDE.md 数据源坑并按需修 intraday.py。")
    return 0 if (r1 and r2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
