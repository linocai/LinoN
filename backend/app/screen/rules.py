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

# —— 阶段3.1 选股信号增强(6 类软信号,plan §4.0;经验默认值,可复盘迭代,不卡生死)——
# 全部为软信号(排序权重/warn 软闸),不新增硬排除;单一事实源就在此顶部,禁止在
# fetch/pipeline/form 里另写一份(Phase A 验收4 grep 断言)。
#
#   · 换手健康区间(信号3):落 [5%, 10%] 得满分,过低(无共识)/过高(筹码松动)线性衰减。
#   · 市值弹性(信号4):中小盘 [20, 200] 亿满分;微盘 <15 亿、超大盘 >500 亿衰减;缺失(<=0)中性。
#   · 近期活跃(信号5):近 ACTIVE_LOOKBACK_DAYS 日(排除今日)任一日涨停(>=LIMIT_UP_PCT)→ 加分。
#   · 单日强弩之末软闸(信号6):今日涨幅 >= DAY_SURGE_WARN_PCT → 罚分 + warn(不排除)。
#   · 打分展示(用户追加):当日候选池相对分归一到 [SCORE_FLOOR, 100],不跨天可比。
TURNOVER_HEALTHY_LO = 5.0        # 换手健康带下沿 %(经验默认,可迭代,不卡生死)
TURNOVER_HEALTHY_HI = 10.0       # 换手健康带上沿 %(经验默认,可迭代,不卡生死)
MV_MICRO_FLOOR = 15.0            # 微盘阈(亿元;<此值流动性/操纵风险,衰减)(经验默认)
MV_SMALL_CAP_LO = 20.0           # 中小盘弹性带下沿(亿元;满分带起点)(经验默认)
MV_SMALL_CAP_HI = 200.0          # 中小盘弹性带上沿(亿元;满分带终点)(经验默认)
MV_MEGA_CEIL = 500.0             # 超大盘阈(亿元;>此值弹性弱,衰减到 0)(经验默认)
ACTIVE_LOOKBACK_DAYS = 10        # 近期活跃回看 N 日(排除今日)(经验默认,可迭代)
LIMIT_UP_PCT = 9.8               # 涨停判定阈 %(主板宽阈,涵盖 9.8%+)(经验默认)
DAY_SURGE_WARN_PCT = 9.0         # 单日强弩之末软闸阈 %(经验默认,可迭代,不卡生死)
SCORE_FLOOR = 10                 # 展示分归一下限(见 §4.0 打分展示;避免末位恒 0/两票 100vs0)


# —— 阶段3.1 评分函数(信号3/4/6;全部无副作用、纯函数、可单测,plan §4.1)————
# 这三个函数产 [0,1] 的因子分,直接进 rank_score(turnover/mv 不再走 min-max 归一,
# day_surge 走归一后乘负权)。函数内引用上面的经验常量,不硬编数字。

def turnover_health_score(t: float) -> float:
    """换手健康区间评分(信号3)→ [0,1]。

    落 [TURNOVER_HEALTHY_LO, TURNOVER_HEALTHY_HI] 得满分 1.0;过低(无共识)按距下沿
    线性衰减(0 换手 → 0 分),过高(筹码松动)按距上沿线性衰减(至 2×上沿 → 0 分,
    再高恒 0)。缺失/负值(<=0)→ 0(无成交无共识)。
    """
    if t <= 0:
        return 0.0
    if t < TURNOVER_HEALTHY_LO:
        return t / TURNOVER_HEALTHY_LO           # 0→0, LO→1
    if t <= TURNOVER_HEALTHY_HI:
        return 1.0                               # 健康带满分
    # 过高衰减:HI→1, 2×HI 及以上→0(线性)
    span = TURNOVER_HEALTHY_HI                    # 衰减跨度 = 一个健康带上沿宽
    frac = (t - TURNOVER_HEALTHY_HI) / span
    return max(0.0, 1.0 - frac)


def mv_elastic_score(mv_yi: float) -> float:
    """市值弹性评分(信号4)→ [0,1]。mv_yi 单位亿元。

    中小盘弹性带 [MV_SMALL_CAP_LO, MV_SMALL_CAP_HI] 满分;上行至 MV_MEGA_CEIL 线性衰减
    到 0(超大盘弹性弱),再大恒 0;下行到 MV_MICRO_FLOOR 及以下线性衰减到 0(微盘
    流动性/操纵风险)。**mv_yi<=0(缺失/未知市值)→ 中性 0.5**(不当微盘惩罚,无凭据不误伤,
    plan §4.1 🔵,与 _normalize 全相等中性一致)。
    """
    if mv_yi <= 0:
        return 0.5                                # 缺失 → 中性,不误伤
    if MV_SMALL_CAP_LO <= mv_yi <= MV_SMALL_CAP_HI:
        return 1.0                                # 中小盘满分带
    if mv_yi > MV_SMALL_CAP_HI:
        # 上行衰减:SMALL_CAP_HI→1, MEGA_CEIL 及以上→0
        span = MV_MEGA_CEIL - MV_SMALL_CAP_HI
        if span <= 0:
            return 0.0
        return max(0.0, 1.0 - (mv_yi - MV_SMALL_CAP_HI) / span)
    # mv_yi < SMALL_CAP_LO:下行衰减,MICRO_FLOOR 及以下→0, SMALL_CAP_LO→1
    span = MV_SMALL_CAP_LO - MV_MICRO_FLOOR
    if span <= 0:
        return 0.0
    return max(0.0, (mv_yi - MV_MICRO_FLOOR) / span)


def day_surge_penalty_norm(pct_chg: float) -> float:
    """单日强弩之末罚分归一(信号6)→ [0,1](越暴涨越接近 1,乘以负权成罚项)。

    今日涨幅 < DAY_SURGE_WARN_PCT → 0(不罚);>= 软闸阈 → 从 0 线性升,到涨停线
    (LIMIT_UP_PCT)封顶 1.0(再高恒 1)。单调不减。负涨幅/缺失 → 0。
    """
    if pct_chg < DAY_SURGE_WARN_PCT:
        return 0.0
    span = LIMIT_UP_PCT - DAY_SURGE_WARN_PCT
    if span <= 0:
        return 1.0
    return min(1.0, (pct_chg - DAY_SURGE_WARN_PCT) / span)


def day_surge_warn_text(pct_chg: float) -> Optional[str]:
    """单日暴涨软闸文案(信号6;对齐 high_warn_text 写法,非空触发琥珀降级)。

    今日涨幅 >= DAY_SURGE_WARN_PCT → 返回文案(与 60 日高位 warn 并列,不互斥);否则 None。
    """
    if pct_chg is None:
        return None
    if pct_chg >= DAY_SURGE_WARN_PCT:
        return f"今日大涨 {pct_chg:.1f}%,单日强弩之末,谨慎追高"
    return None


# —— 排序加权(机械层,不卡生死,只定"先看谁",plan §4.0/§4.1)——————————————
# 阶段3.1 八键方案(经验首版,可迭代,复盘后调):放量权重仍最大(略降腾空间给新因子),
# 其余 资金面 > 换手健康 > 低位 = VWAP = 市值弹性 > 近期活跃 > 单日软闸罚项。
# 正权之和 = 1.0;day_surge 是罚项(负权,从总分里减)。
WEIGHTS: Dict[str, float] = {
    "vol": 0.28,          # 放量强度(权重仍最大,略降为新因子腾空间)
    "fund": 0.20,         # 资金面(主力近 3 日净流入占成交额比例,相对口径,免大盘股偏置)
    "turnover": 0.14,     # 换手【健康区间评分】(信号3,不再 min-max)
    "low_position": 0.10, # 低位程度(pct_60d 越低越好)
    "vwap": 0.10,         # 收盘站 VWAP(信号1,布尔 0/1)
    "mv_elastic": 0.10,   # 市值弹性(信号4)
    "active": 0.08,       # 近期活跃(信号5,布尔 0/1)
    "day_surge": -0.06,   # 单日强弩之末罚分(信号6,罚项,越暴涨扣越多)
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
    vwap_oks: List[bool],
    total_mv_yis: List[float],
    actives: List[bool],
    day_pcts: List[float],
) -> List[float]:
    """对一批候选算机械排序分(越大越靠前;阶段3.1 八因子)。

    · vol/fund/low_position 沿用 min-max 相对归一(全相等 → 全 0.5 中性)。
    · turnover 改调 turnover_health_score(信号3,函数已产 [0,1],不再 min-max)。
    · vwap/active 布尔转 0/1(信号1/5)。
    · mv_elastic 调 mv_elastic_score(信号4;缺失市值中性 0.5)。
    · day_surge 调 day_surge_penalty_norm 后乘负权(信号6,罚项)。
    低位程度 = 1 - 归一(pct_60d)(涨幅越低分越高,偏好相对低位)。
    八个入参列表等长、同序;返回同序的分数列表(理论范围约 [-0.06, 1.0])。
    fund_3d 传相对口径(占成交额比例合计,fetch.StockRow.net_mf_rate_3d),不要传绝对
    万元金额——否则大盘股天然靠体量堆高分,失真。
    """
    n = len(vol_multiples)
    if n == 0:
        return []
    nv = _normalize(vol_multiples)
    nf = _normalize(fund_3d)
    np_ = _normalize(pct_60ds)
    low = [1.0 - x for x in np_]   # 涨幅越低 → 低位分越高
    out: List[float] = []
    for i in range(n):
        turnover_f = turnover_health_score(turnovers[i])
        vwap_f = 1.0 if vwap_oks[i] else 0.0
        mv_f = mv_elastic_score(total_mv_yis[i])
        active_f = 1.0 if actives[i] else 0.0
        surge_f = day_surge_penalty_norm(day_pcts[i])
        score = (
            WEIGHTS["vol"] * nv[i]
            + WEIGHTS["fund"] * nf[i]
            + WEIGHTS["turnover"] * turnover_f
            + WEIGHTS["low_position"] * low[i]
            + WEIGHTS["vwap"] * vwap_f
            + WEIGHTS["mv_elastic"] * mv_f
            + WEIGHTS["active"] * active_f
            + WEIGHTS["day_surge"] * surge_f   # 负权,罚项
        )
        out.append(round(score, 6))
    return out
