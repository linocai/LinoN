"""复权 + 共享形态计算(阶段2.5 F1,plan §4.0/§4.3)。

抽出 `fetch.py`(全市场批量)与 `analyze.py`(单票深判)两处重复的近 N 日形态计算,
统一在此一处实现,两处改为调用共享函数(一处修、两处生效)。复权在共享函数内部
统一做。

【复权序列方向契约,钉死不得反,见 plan §4.0】:
  `qfq_closes` 入参 raw_closes / adj_factors 均为【新→旧】排序(与 fetch.py/analyze.py
  现有序列一致——下标 0 = 最新交易日 = 今天)。基准 = adj_factors[0](新→旧的第 0 个 =
  最新日)。公式 qfq_close[i] = raw_close[i] × adj_factors[i] / adj_factors[0]。
  ⇒ 最新日(i=0)close 恒不变(factor 约成 1),更早日按各自因子相对最新日缩放。
  【禁止用 [-1] 当基准】——那是最早日 = 后复权,历史价整体错位、new_high/ma/pct_60d
  全线偏且无除权票测不出这个方向错误。

只复权 close 序列(new_high/ma20/pct_60d/当日 pct_chg 依赖价格连续性);vol 不动
(adj_factor 是价格因子,不改成交量;vol_multiple 用原始量在除权日仍可比)。

缺 adj_factor(None / 0 / 长度不齐)→ 该处 factor=1.0(退化为原始价,即当前行为),
不崩、不阻塞。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.screen import rules


@dataclass
class FormResult:
    """近 N 日形态计算结果(复权后)。"""
    pct_chg: float = 0.0              # 当日涨跌幅 %(从复权后 closes[0]/closes[1] 派生)
    vol_multiple: float = 0.0         # 当日量 / 前 5 日均量(vol 不复权)
    new_high_20d: bool = False        # 创 20 日新高(复权后价)
    above_ma20: bool = False          # 站上 20 日均线(复权后价)
    pct_60d: Optional[float] = None   # 近 60 交易日累计涨幅 %(复权后价)
    vwap_ok: bool = False             # 收盘站当日 VWAP(信号1;缺 amount → 保守 False)
    had_limit_up: bool = False        # 近 N 日(排除今日)有涨停(信号5;数据不足 → False)
    pos_health: float = 0.0           # 位置健康(距60日高点,v1.3.1 A1;数据不足<20日 → 0.0)
    breakout_ok: bool = False         # 横盘突破(v1.3.1 A1 新增;缺 volume_ratio/数据不足 → False)


def qfq_closes(raw_closes: List[float], adj_factors: List[Optional[float]]) -> List[float]:
    """前复权收盘价序列。入参【新→旧】,基准 = adj_factors[0](最新日)。

    qfq_close[i] = raw_close[i] × adj_factors[i] / adj_factors[0]。
    缺因子(None/0/长度与 raw_closes 不齐)→ 该处退化 factor=1.0(即该日用原始价)。
    adj_factors[0] 本身缺失/为 0 → 全体退化为 1.0(等价不复权,不崩)。
    """
    n = len(raw_closes)
    if n == 0:
        return []
    base = adj_factors[0] if adj_factors else None
    if not base:  # None 或 0 → 无法建立基准,整体退化不复权
        return list(raw_closes)
    out: List[float] = []
    for i in range(n):
        factor = adj_factors[i] if i < len(adj_factors) else None
        if not factor:
            factor = base  # 缺该日因子 → 退化为该日不缩放(等同 factor=1.0 相对基准)
        out.append(raw_closes[i] * factor / base)
    return out


def compute_form(
    closes_new_to_old: List[float],
    vols_new_to_old: List[float],
    amounts_new_to_old: Optional[List[float]] = None,
    volume_ratio: Optional[float] = None,
    cfg: Optional[dict] = None,
) -> FormResult:
    """从近 N 日【已复权】收盘价序列 + 原始成交量序列(均新→旧)算形态。

    口径逐字对齐现有 _enrich_form/_fetch_form:
      · 当日涨跌幅 = (closes[0]-closes[1])/closes[1]×100(不再用原始 pre_close 字段,
        复权后 today_close 变了而 raw pre_close 没变,除权当天会算出假突变)。
      · 放量倍数 = 当日量 / 前 5 日均量(vols[1:6],vol 不复权)。
      · 创 20 日新高:今日收盘 >= 近 20 日(不含今日,closes[1:21])最高收盘(含等号)。
      · 站上 N 日均线:ma_window = closes[:rules.MA_DAYS](引用常量,不硬编 20)。
      · 60 日基准:base_idx = min(60, len(closes)-1)。
    数据不足 → 各字段保守退化(vol_multiple=0/new_high=False/pct_60d=None),不崩。

    阶段3.1 新增(plan §4.0/§4.1,只新增一个可选入参 amounts_new_to_old):
      · vwap_ok(信号1):仅当 amounts 传入且 vols[0]>0(除零守卫,停牌/异常行退化 False)
        才算;vwap = amounts[0]×1000 / (vols[0]×100)(千元→元、手→股),vwap_ok =
        closes[0] >= vwap(用复权后 close;amount/vol 是当日绝对量、不复权不受影响)。
        缺 amounts(None)→ vwap_ok 恒 False(向后兼容旧调用点)。
      · had_limit_up(信号5):从【已复权】closes 逐日内部派生 pct 序列(不新增入参、
        不用原始 daily.pct_chg——复权序列消除除权跳变、不产假涨停,plan §4.0 🟡#2),
        扫【排除今日】的 pct[1 : 1+ACTIVE_LOOKBACK_DAYS](🟡#1;index 0 是今天),
        任一 >= rules.LIMIT_UP_PCT → True。数据不足 → False。

    v1.3.1 A1 新增(plan §4.1,只新增一个可选入参 volume_ratio):
      · pos_health(位置健康,距60日高点)= closes[0] / max(closes[:min(60,len)])。
        分母 <=0 → 0.0。**数据不足 len<20 → 0.0**(建议#9:次新股只几天数据会贴短命
        高点白拿满权,压掉,保守压分不误抬)。范围 (0,1]。
      · breakout_ok(横盘突破)= 满足全部三条才 True:
          ① 近24日(**排除今日**,closes[1:25])振幅收窄:
             (max(closes[1:25])-min(closes[1:25])) / min(closes[1:25]) < BREAKOUT_RANGE_MAX;
          ② 今日突破区间上沿:closes[0] > max(closes[1:25]);
          ③ 量比配合:volume_ratio >= BREAKOUT_VOL_RATIO_MIN。
        **振幅窗口必须排除今日(重要#5)**——若把今日纳入振幅窗口,而突破条又令今日=
        最高,振幅会退化为 (今日-最低)/最低、越有力突破越判 False(把窄横盘+大阳线
        突破自己掐灭);故振幅与突破都在 closes[1:25](过去24日,不含今日)上算。
        volume_ratio 缺失(None,向后兼容旧调用点)→ 条③视为不满足 → breakout_ok=False。
        数据不足 25 日(closes[1:25] 拿不满)→ False。

    v1.3.1 Phase B(plan §4 Phase B2,新增可选入参 cfg):had_limit_up/breakout_ok 用到的
    ACTIVE_LOOKBACK_DAYS/LIMIT_UP_PCT/BREAKOUT_RANGE_MAX/BREAKOUT_VOL_RATIO_MIN 改从
    cfg 读(缺省 None → 回落 rules.DEFAULT_SCREEN_CONFIG,行为与改前逐字节一致,保批1
    测试/旧调用点[analyze.py 的 3 参调用]不回归)。**深判层 analyze.py 不传 cfg**——
    继续吃 rules 默认常量,不读用户配置(plan §4 Phase B2 深判层边界,钉死)。
    """
    # cfg 缺省(None,批1旧调用点/深判层 analyze.py)→ 直接回落【模块级常量】(不是
    # DEFAULT_SCREEN_CONFIG 快照 dict)——旧测试对 rules.ACTIVE_LOOKBACK_DAYS 等常量的
    # monkeypatch 仍需生效(test_form.py test_had_limit_up_respects_lookback_window),
    # 若回落一份"构造时快照"的 dict,monkeypatch 常量不会反映到该 dict 里,会假性回归。
    if cfg is not None:
        active_lookback_days = int(cfg.get("active_lookback_days", rules.ACTIVE_LOOKBACK_DAYS))
        limit_up_pct = cfg.get("limit_up_pct", rules.LIMIT_UP_PCT)
        breakout_range_max = cfg.get("breakout_range_max", rules.BREAKOUT_RANGE_MAX)
        breakout_vol_ratio_min = cfg.get("breakout_vol_ratio_min", rules.BREAKOUT_VOL_RATIO_MIN)
    else:
        active_lookback_days = rules.ACTIVE_LOOKBACK_DAYS
        limit_up_pct = rules.LIMIT_UP_PCT
        breakout_range_max = rules.BREAKOUT_RANGE_MAX
        breakout_vol_ratio_min = rules.BREAKOUT_VOL_RATIO_MIN

    result = FormResult()
    if not closes_new_to_old:
        return result

    today_close = closes_new_to_old[0]

    # 当日涨跌幅:从复权后 closes[0]/closes[1] 派生
    if len(closes_new_to_old) >= 2 and closes_new_to_old[1] > 0:
        result.pct_chg = round(
            (today_close - closes_new_to_old[1]) / closes_new_to_old[1] * 100, 2
        )

    # 放量倍数(vol 不复权)
    if vols_new_to_old:
        today_vol = vols_new_to_old[0]
        prev5 = [v for v in vols_new_to_old[1:6] if v > 0]
        if prev5:
            avg5 = sum(prev5) / len(prev5)
            if avg5 > 0:
                result.vol_multiple = round(today_vol / avg5, 2)

    # 创 20 日新高(复权后价,不含今日)
    prev20 = [c for c in closes_new_to_old[1:21] if c > 0]
    if prev20 and today_close > 0:
        result.new_high_20d = today_close >= max(prev20)

    # 站上 N 日均线(引用 rules.MA_DAYS,不硬编)
    ma_window = closes_new_to_old[: rules.MA_DAYS]
    if ma_window:
        ma = sum(ma_window) / len(ma_window)
        result.above_ma20 = today_close >= ma

    # 近 60 交易日累计涨幅
    if len(closes_new_to_old) >= 2:
        base_idx = min(60, len(closes_new_to_old) - 1)
        base = closes_new_to_old[base_idx]
        if base > 0:
            result.pct_60d = round((today_close - base) / base * 100, 2)

    # 收盘站 VWAP(信号1):仅当 amounts 传入且当日 vol>0(除零守卫)才算,否则保守 False
    if amounts_new_to_old and vols_new_to_old and vols_new_to_old[0] > 0:
        today_amount = amounts_new_to_old[0]  # 千元
        today_vol = vols_new_to_old[0]         # 手
        vwap = (today_amount * 1000.0) / (today_vol * 100.0)  # 元/股
        if vwap > 0:
            result.vwap_ok = today_close >= vwap

    # 近期活跃 had_limit_up(信号5):从复权 closes 逐日派生 pct,扫排除今日的窗口
    # pct[i] = (closes[i]-closes[i+1])/closes[i+1];窗口 = pct[1 : 1+N](排除今日 index0,
    # 上界 1+N 不含端点 → i 取 1..N;每个 i 需 closes[i+1] 存在,即 i+1 <= n_close-1)。
    n_close = len(closes_new_to_old)
    lookback_end = 1 + active_lookback_days  # slice 上界(不含),i ∈ [1, lookback_end)
    for i in range(1, lookback_end):
        if i + 1 > n_close - 1:      # closes[i+1] 不存在 → 数据不足,停
            break
        prev = closes_new_to_old[i + 1]
        if prev <= 0:
            continue
        pct = (closes_new_to_old[i] - prev) / prev * 100.0
        if pct >= limit_up_pct:
            result.had_limit_up = True
            break

    # 位置健康 pos_health(v1.3.1 A1):距60日高点,今日收盘/近60日最高收盘。
    # 数据不足 len<20 → 0.0(建议#9:次新股短命高点白拿满权,保守压分)。
    if n_close >= 20:
        window60 = closes_new_to_old[: min(60, n_close)]
        peak = max(window60) if window60 else 0.0
        if peak > 0:
            result.pos_health = today_close / peak

    # 横盘突破 breakout_ok(v1.3.1 A1 新增):近24日(排除今日,closes[1:25])振幅收窄 +
    # 今日突破区间上沿 + 量比配合,三条全满足才 True。数据不足 25 日 → False。
    window24 = closes_new_to_old[1:25]
    if len(window24) == 24 and volume_ratio is not None:
        lo24, hi24 = min(window24), max(window24)
        if lo24 > 0:
            range_pct = (hi24 - lo24) / lo24
            narrow = range_pct < breakout_range_max
            breaks_out = today_close > hi24
            vol_ok = volume_ratio >= breakout_vol_ratio_min
            result.breakout_ok = narrow and breaks_out and vol_ok

    return result
