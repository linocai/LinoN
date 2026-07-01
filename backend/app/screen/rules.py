"""钉死的选股规则(单一事实源,plan §4.1)。

铁律(plan §4 / 任务书):技术面/选股不定死阈值,交给 LLM 判;这里**只硬编真二元项**
(黑名单代码段/ST/白酒行业、高位线 ≥100% 排除·≥50% 警告降级、截断 5×free_slots、
排序放量权重最大首版 0.4/0.25/0.2/0.15);粗筛宽条件(主力净流入为正、放量倍数、
创 N 日新高/站均线)给"宁松勿紧"经验默认值,**注释标"可复盘迭代、不卡生死"**,不当死阈值。

止损/止盈/D4/容差带常量仍只在 app.db.store 顶部,本模块需要时 import 复用,**禁止再写一份**。
(本选股层不直接用那几个常量,但保留这条纪律说明,提醒后续 builder 别在此另起常量。)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# —— 黑名单硬排除(二元,plan §4.1)——————————————————————————————————
# 按【板块前缀】排除(用板块整段、非枚举精确段——防交易所新增子段漏挡):
#   创业板 30*(覆盖 300/301/302 全段)/ 科创板 688* + 689*(含 CDR,如九号 689009)/
#   北交所 8*(83/87/88) + 4*(43/40) + 920*(2024+ 新发段)。
# 只做沪深主板短线,创业/科创/北交所一律不碰(流动性/涨跌幅规则不同)。
# 历史漏挡:旧 `300` 漏创业板 301/302(信濠光电 301051)、旧无 920 漏北交所——均已收为板块整段。
# 用正则前缀匹配裸 6 位代码。
_BLACKLIST_PREFIX_RE = re.compile(r"^(30|688|689|8|4|920)")

# 名称含 ST / *ST(风险警示)→ 排除。
def _is_st_name(name: str) -> bool:
    n = (name or "").upper().replace(" ", "")
    return "ST" in n

# 行业属白酒/酿酒 → 排除(Review 拍板:用 Tushare stock_basic.industry 精确归类,
# 比名称关键词覆盖更全)。这里是"行业字符串命中即排除"的判定集合。
# 茅台/五粮液等 Tushare industry 字段标"白酒"。同时容错"酿酒/黄酒/啤酒"等酒类
# (宁可多排一点酒,短线投机不碰高位抱团白酒板块——与画像一致)。
BAIJIU_INDUSTRY_KEYWORDS = ("白酒", "酿酒", "黄酒", "啤酒", "葡萄酒", "其他酒")


def is_baijiu_industry(industry: Optional[str]) -> bool:
    """行业字符串是否命中酒类黑名单(白酒为主)。industry 为 None/空 → False(不误杀)。"""
    if not industry:
        return False
    s = str(industry)
    return any(k in s for k in BAIJIU_INDUSTRY_KEYWORDS)


def is_blacklisted(code: str, name: str, industry: Optional[str]) -> bool:
    """黑名单硬排除(二元):代码段 / ST / 白酒行业 任一命中即排除。"""
    bare = re.sub(r"\D", "", code or "")
    if _BLACKLIST_PREFIX_RE.match(bare):
        return True
    if _is_st_name(name):
        return True
    if is_baijiu_industry(industry):
        return True
    return False


# —— 高位排除(二元,plan §4.1)————————————————————————————————————
# 近 60 交易日累计涨幅 pct_60d:≥100% → 排除;≥50% → 不排除但 warn 降级(对齐 Candidate.warn)。
HIGH_EXCLUDE_PCT = 100.0      # ≥ 此值排除
HIGH_WARN_PCT = 50.0          # ≥ 此值(且 <100%)warn 降级


def high_position_verdict(pct_60d: Optional[float]) -> str:
    """高位线判定。返回 'exclude' / 'warn' / 'ok'。pct_60d 为 None → 'ok'(无证据不杀)。"""
    if pct_60d is None:
        return "ok"
    if pct_60d >= HIGH_EXCLUDE_PCT:
        return "exclude"
    if pct_60d >= HIGH_WARN_PCT:
        return "warn"
    return "ok"


def high_warn_text(pct_60d: Optional[float]) -> Optional[str]:
    """warn 降级时的展示文案(对齐 Candidate.warn,非空触发琥珀降级)。"""
    if pct_60d is None:
        return None
    if HIGH_WARN_PCT <= pct_60d < HIGH_EXCLUDE_PCT:
        return f"60日累涨 {pct_60d:.0f}%,偏高位,谨慎"
    return None


# —— 截断公式(二元,plan §4.1)————————————————————————————————————
# limit = 5 × free_slots;free_slots = max(0, 3 - holding_count);满仓 → 0(闭门)。
SLOTS_PER_CANDIDATE = 5
MAX_HOLDINGS = 3              # 与 store.MAX_HOLDINGS 一致(画像:同时最多 3 票)


def free_slots(holding_count: int) -> int:
    """空仓位 = max(0, 3 - 在持票数)。"""
    return max(0, MAX_HOLDINGS - max(0, int(holding_count)))


def truncation_limit(holding_count: int) -> int:
    """候选截断上限 = 5 × free_slots;满仓 → 0(闭门)。"""
    return SLOTS_PER_CANDIDATE * free_slots(holding_count)


# —— 粗筛宽条件(经验默认值,非生死阈,可复盘迭代,不卡死生死)——————————————
# 铁律:这些是"宁松勿紧"的宽门槛,只用来粗筛掉明显不相关的票,把"值不值得进"
# 的判断留给 LLM 深判。任何一条都不是死阈值,后续可据复盘迭代调松/调紧。
#
#   · 放量:当日量 / 5 日均量 ≥ VOL_MULTIPLE_MIN(宽,1.5)——温和放量即可,不要求爆量。
#   · 主力资金:东财 moneyflow_dc 近 3 日主力净额(net_amount,万元)合计 > 0(还在流入,不强求大幅)。
#   · 当日非大幅净流出:当日主力净额 >= DAY_OUTFLOW_FLOOR(允许小幅流出,只挡崩盘出货)。
#   · 形态:创 NEW_HIGH_DAYS 日新高 或 站上 MA_DAYS 日均线,任一即可(宽,任一满足)。
VOL_MULTIPLE_MIN = 1.5            # 放量倍数下限(经验默认,可迭代,不卡生死)
NEW_HIGH_DAYS = 20               # 创 N 日新高的 N(经验默认)
MA_DAYS = 20                     # 站上 N 日均线的 N(经验默认)
DAY_OUTFLOW_FLOOR = -5000.0      # 当日主力净流入下限(万元;允许小幅流出,挡大幅出货)
RECENT_FLOW_DAYS = 3             # 近 N 日主力净流入合计 > 0 的 N(经验默认)


# —— 排序加权(机械层,不卡生死,只定"先看谁",plan §4.1)————————————————
# 四因子归一打分加权,放量强度权重最大;其余 资金面 > 换手 > 低位程度。
# 首版经验值,注明可迭代(复盘后调权重)。
WEIGHTS: Dict[str, float] = {
    "vol": 0.40,        # 放量强度(权重最大)
    "fund": 0.25,       # 资金面(主力近 3 日净流入占成交额比例,相对口径,免大盘股偏置)
    "turnover": 0.20,   # 换手
    "low_position": 0.15,  # 低位程度(pct_60d 越低越好)
}


def _normalize(values: List[float]) -> List[float]:
    """min-max 归一到 [0,1];全相等 → 全 0.5(无区分度,中性)。"""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def rank_score(
    vol_multiples: List[float],
    fund_3d: List[float],
    turnovers: List[float],
    pct_60ds: List[float],
) -> List[float]:
    """对一批候选算机械排序分(越大越靠前)。

    四因子各自 min-max 归一后加权:放量强度最大权,其余 资金 > 换手 > 低位程度。
    低位程度 = 1 - 归一(pct_60d)(涨幅越低分越高,偏好相对低位)。
    入参四个列表等长、同序;返回同序的分数列表。
    fund_3d 传入相对口径(占成交额比例合计,fetch.StockRow.net_mf_rate_3d),
    不要传绝对万元金额——否则大盘股天然靠体量堆高分,失真。
    """
    n = len(vol_multiples)
    if n == 0:
        return []
    nv = _normalize(vol_multiples)
    nf = _normalize(fund_3d)
    nt = _normalize(turnovers)
    np_ = _normalize(pct_60ds)
    low = [1.0 - x for x in np_]   # 涨幅越低 → 低位分越高
    out: List[float] = []
    for i in range(n):
        score = (
            WEIGHTS["vol"] * nv[i]
            + WEIGHTS["fund"] * nf[i]
            + WEIGHTS["turnover"] * nt[i]
            + WEIGHTS["low_position"] * low[i]
        )
        out.append(round(score, 6))
    return out
