"""钉死的选股规则(单一事实源,plan §4.1)。

铁律(plan §4 / 任务书):技术面/选股不定死阈值,交给 LLM 判;这里**只硬编真二元项**
(黑名单代码段/ST/白酒行业、候选固定 CANDIDATE_LIMIT=20(v1.3.0 起,已删满仓闭门));
**v1.3.1 起高位线 ≥100% 不再硬排除**,只分级 warn(≥100% 红级/[50,100%) 琥珀级,见
high_position_verdict/high_warn_level);粗筛宽条件(主力净流入为正、量比、创 N 日新高/
站均线)给"宁松勿紧"经验默认值,**注释标"可复盘迭代、不卡生死"**,不当死阈值。

止损/止盈/D4/容差带常量仍只在 app.db.store 顶部,本模块需要时 import 复用,**禁止再写一份**。
MAX_HOLDINGS 单一事实源 = `app.db.store.constants.MAX_HOLDINGS`(v1.3.0 C1:本模块曾定义
一份同名常量供已删的 free_slots()/truncation_limit() 用,现两函数随满仓闭门一并删除,
本模块不再需要 MAX_HOLDINGS,不重复定义、不重复 import——双定义漂移已消)。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

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


# —— 高位分级(v1.3.1 A1 改:删硬排除,只标注 warn 分级)——————————————————
# 近 60 交易日累计涨幅 pct_60d:≥100% → 红级(high,极高位);[50,100%) → 琥珀级(warn)。
# 不再排除——组合效应(与 pos_health 奖励贴高点同向)是刻意的动量逻辑选择,见 plan §4.1。
HIGH_EXCLUDE_PCT = 100.0      # ≥ 此值 → 红级(high),仍是原名沿用,含义改为"红级阈"
HIGH_WARN_PCT = 50.0          # ≥ 此值(且 <100%)→ 琥珀级(amber)


def high_position_verdict(pct_60d: Optional[float]) -> str:
    """高位线判定。返回 'warn' / 'ok'(v1.3.1 起不再产 'exclude',见 plan §4.1)。

    pct_60d 为 None → 'ok'(无证据不杀)。≥100% 与 [50,100%) 都归 'warn'
    (级别细分见 high_warn_level,'warn' 只是"需要展示警示"的粗粒度判定)。
    """
    if pct_60d is None:
        return "ok"
    if pct_60d >= HIGH_WARN_PCT:
        return "warn"
    return "ok"


def high_warn_level(pct_60d: Optional[float]) -> Optional[str]:
    """高位 warn 级别:≥100% → 'high'(红级);[50,100%) → 'amber'(琥珀级);否则 None。"""
    if pct_60d is None:
        return None
    if pct_60d >= HIGH_EXCLUDE_PCT:
        return "high"
    if pct_60d >= HIGH_WARN_PCT:
        return "amber"
    return None


def high_warn_text(pct_60d: Optional[float]) -> Optional[str]:
    """warn 降级时的展示文案(对齐 Candidate.warn,非空触发琥珀/红降级)。

    v1.3.1 重要#6:≥100% 不再是 None(旧逻辑 ≥100% 已 exclude 轮不到产文案)——
    现在 ≥100% 票仍会出现在候选池(动量逻辑刻意选择),必须有红级文案配套 warnLevel=high。

    注:HIGH_EXCLUDE_PCT/HIGH_WARN_PCT(红/琥珀分级阈)本 Phase B 不进 SCREEN_CONFIG_SPEC
    (§4 config 形状表未列此二值,只列 9 权重 + 12 阈值),仍是 rules.py 常量单一源、不吃配置。
    """
    if pct_60d is None:
        return None
    if pct_60d >= HIGH_EXCLUDE_PCT:
        return f"60日累涨 {pct_60d:.0f}%,极高位,追高高危"
    if pct_60d >= HIGH_WARN_PCT:
        return f"60日累涨 {pct_60d:.0f}%,偏高位,谨慎"
    return None


# —— 候选条数上限(v1.3.0 C1,单一事实源)———————————————————————————————
# 固定 Top 20,任何持仓状态都不闭门(旧"5×free_slots 满仓闭门"截断公式已删,
# CANDIDATE_LIMIT 是唯一事实源,GET /candidates 端点 import 此常量,不散落硬编 20)。
CANDIDATE_LIMIT = 20


# —— 粗筛宽条件(经验默认值,非生死阈,可复盘迭代,不卡死生死)——————————————
# 铁律:这些是"宁松勿紧"的宽门槛,只用来粗筛掉明显不相关的票,把"值不值得进"
# 的判断留给 LLM 深判。任何一条都不是死阈值,后续可据复盘迭代调松/调紧。
#
#   · 放量:官方量比(daily_basic.volume_ratio)≥ VOL_RATIO_MIN(宽,1.5,v1.3.1 A1
#     改口径:旧"自算放量倍数"换成 Tushare 现成量比字段,排序也同步换用;展示侧
#     volMultiple/volPct 仍用自算放量倍数,解耦不变,见 plan §4.1 建议#10)。
#   · 主力资金:东财 moneyflow_dc 近 3 日主力净额(net_amount,万元)合计 > 0(还在流入,不强求大幅)。
#   · 当日非大幅净流出:当日主力净额 >= DAY_OUTFLOW_FLOOR(允许小幅流出,只挡崩盘出货)。
#   · 形态:创 NEW_HIGH_DAYS 日新高 或 站上 MA_DAYS 日均线,任一即可(宽,任一满足)。
VOL_MULTIPLE_MIN = 1.5            # 展示用自算放量倍数下限(历史沿用,展示口径不变)
VOL_RATIO_MIN = 1.5               # 粗筛/排序用官方量比下限(v1.3.1,经验默认,可迭代,不卡生死)
NEW_HIGH_DAYS = 20               # 创 N 日新高的 N(经验默认)
MA_DAYS = 20                     # 站上 N 日均线的 N(经验默认)
DAY_OUTFLOW_FLOOR = -5000.0      # 当日主力净流入下限(万元;允许小幅流出,挡大幅出货)
RECENT_FLOW_DAYS = 3             # 近 N 日主力净流入合计 > 0 的 N(经验默认)

# —— 阶段3.1 选股信号增强(6 类软信号,plan §4.0;经验默认值,可复盘迭代,不卡生死)——
# 全部为软信号(排序权重/warn 软闸),不新增硬排除;单一事实源就在此顶部,禁止在
# fetch/pipeline/form 里另写一份(Phase A 验收4 grep 断言)。
#
#   · 换手健康区间(信号3):v1.3.1 A1 改带 [7%, 15%](旧 [5,10]),过低(无共识)/
#     过高(筹码松动)线性衰减。
#   · 市值弹性(信号4):v1.3.1 A1 改带 [50, 500] 亿满分(旧 [20,200]);微盘 <30 亿
#     (旧 15)、超大盘 >500 亿衰减;缺失(<=0)中性。
#   · 近期活跃(信号5):近 ACTIVE_LOOKBACK_DAYS 日(排除今日)任一日涨停(>=LIMIT_UP_PCT)→ 加分。
#   · 单日强弩之末软闸(信号6):今日涨幅 >= DAY_SURGE_WARN_PCT → 罚分 + warn(不排除)。
#   · 横盘突破(信号7,v1.3.1 A1 新增):近24日(排除今日)振幅收窄 + 今日放量突破区间
#     上沿 → 加分,布尔 0/1。
#   · 打分展示(用户追加):当日候选池相对分归一到 [SCORE_FLOOR, 100],不跨天可比。
TURNOVER_HEALTHY_LO = 7.0        # 换手健康带下沿 %(v1.3.1 改,经验默认,可迭代,不卡生死)
TURNOVER_HEALTHY_HI = 15.0       # 换手健康带上沿 %(v1.3.1 改,经验默认,可迭代,不卡生死)
MV_MICRO_FLOOR = 30.0            # 微盘阈(亿元;v1.3.1 改,<此值流动性/操纵风险,衰减)(经验默认)
MV_SMALL_CAP_LO = 50.0           # 中小盘弹性带下沿(亿元;v1.3.1 改,满分带起点)(经验默认)
MV_SMALL_CAP_HI = 500.0          # 中小盘弹性带上沿(亿元;v1.3.1 改,满分带终点)(经验默认)
MV_MEGA_CEIL = 1500.0            # 超大盘衰减终点(亿元;>mv_hi 起线性衰减,到此值为 0,
                                  # 再高恒 0)(v1.3.1 审后修复:原 500 与 MV_SMALL_CAP_HI
                                  # 重合、衰减带 span=0 退化成硬台阶,与"平滑衰减"设计意图
                                  # 不符;改 1500 使 [500,1500] 成真正线性衰减带)(经验默认,
                                  # 可迭代,进 SCREEN_CONFIG_SPEC 可调)
ACTIVE_LOOKBACK_DAYS = 10        # 近期活跃回看 N 日(排除今日)(经验默认,可迭代)
LIMIT_UP_PCT = 9.8               # 涨停判定阈 %(主板宽阈,涵盖 9.8%+)(经验默认)
DAY_SURGE_WARN_PCT = 9.0         # 单日强弩之末软闸阈 %(经验默认,可迭代,不卡生死)
BREAKOUT_RANGE_MAX = 0.15        # 横盘突破:近24日(排除今日)振幅收窄阈(经验默认,可迭代,不卡生死)
BREAKOUT_VOL_RATIO_MIN = 1.5     # 横盘突破:今日量比配合下限(经验默认,可迭代,不卡生死)
SCORE_FLOOR = 10                 # 展示分归一下限(见 §4.0 打分展示;避免末位恒 0/两票 100vs0)


# —— 阶段3.1 评分函数(信号3/4/6;全部无副作用、纯函数、可单测,plan §4.1)————
# 这三个函数产 [0,1] 的因子分,直接进 rank_score(turnover/mv 不再走 min-max 归一,
# day_surge 走归一后乘负权)。函数内引用上面的经验常量,不硬编数字。

def turnover_health_score(t: float, cfg: Optional[Dict[str, Any]] = None) -> float:
    """换手健康区间评分(信号3)→ [0,1]。

    落 [turnover_lo, turnover_hi] 得满分 1.0;过低(无共识)按距下沿线性衰减(0 换手
    → 0 分),过高(筹码松动)按距上沿线性衰减(至 2×上沿 → 0 分,再高恒 0)。
    缺失/负值(<=0)→ 0(无成交无共识)。

    v1.3.1 Phase B:cfg 缺省(None)→ 直接回落【模块级常量】TURNOVER_HEALTHY_LO/HI(不是
    DEFAULT_SCREEN_CONFIG 快照 dict,与改前逐字节一致、且对常量的 monkeypatch 仍生效,
    保批1测试/旧调用不回归)。cfg 传入时取 cfg["turnover_lo"/"hi"]。
    """
    if cfg is not None:
        lo = cfg.get("turnover_lo", TURNOVER_HEALTHY_LO)
        hi = cfg.get("turnover_hi", TURNOVER_HEALTHY_HI)
    else:
        lo = TURNOVER_HEALTHY_LO
        hi = TURNOVER_HEALTHY_HI
    if t <= 0:
        return 0.0
    if t < lo:
        return t / lo if lo > 0 else 0.0          # 0→0, lo→1
    if t <= hi:
        return 1.0                               # 健康带满分
    # 过高衰减:hi→1, 2×hi 及以上→0(线性)
    span = hi                                     # 衰减跨度 = 一个健康带上沿宽
    if span <= 0:
        return 0.0
    frac = (t - hi) / span
    return max(0.0, 1.0 - frac)


def mv_elastic_score(mv_yi: float, cfg: Optional[Dict[str, Any]] = None) -> float:
    """市值弹性评分(信号4)→ [0,1]。mv_yi 单位亿元。

    中小盘弹性带 [mv_lo, mv_hi] 满分;上行至 mv_mega_ceil 线性衰减到 0(超大盘弹性弱,
    审后修复:mv_mega_ceil 已升级为 SCREEN_CONFIG_SPEC 第 22 键,可调,默认 1500);
    再大恒 0;下行到 mv_floor 及以下线性衰减到 0(微盘流动性/操纵风险)。**mv_yi<=0
    (缺失/未知市值)→ 中性 0.5**(不当微盘惩罚,无凭据不误伤,plan §4.1 🔵,与 _normalize
    全相等中性一致)。

    v1.3.1 Phase B:cfg 缺省(None)→ 直接回落模块级常量(行为与改前逐字节一致,对常量的
    monkeypatch 仍生效)。
    """
    if cfg is not None:
        mv_lo = cfg.get("mv_lo", MV_SMALL_CAP_LO)
        mv_hi = cfg.get("mv_hi", MV_SMALL_CAP_HI)
        mv_floor = cfg.get("mv_floor", MV_MICRO_FLOOR)
        mv_mega_ceil = cfg.get("mv_mega_ceil", MV_MEGA_CEIL)
    else:
        mv_lo = MV_SMALL_CAP_LO
        mv_hi = MV_SMALL_CAP_HI
        mv_floor = MV_MICRO_FLOOR
        mv_mega_ceil = MV_MEGA_CEIL
    if mv_yi <= 0:
        return 0.5                                # 缺失 → 中性,不误伤
    if mv_lo <= mv_yi <= mv_hi:
        return 1.0                                # 中小盘满分带
    if mv_yi > mv_hi:
        # 上行衰减:mv_hi→1, mv_mega_ceil 及以上→0
        span = mv_mega_ceil - mv_hi
        if span <= 0:
            return 0.0
        return max(0.0, 1.0 - (mv_yi - mv_hi) / span)
    # mv_yi < mv_lo:下行衰减,mv_floor 及以下→0, mv_lo→1
    span = mv_lo - mv_floor
    if span <= 0:
        return 0.0
    return max(0.0, (mv_yi - mv_floor) / span)


def day_surge_penalty_norm(pct_chg: float, cfg: Optional[Dict[str, Any]] = None) -> float:
    """单日强弩之末罚分归一(信号6)→ [0,1](越暴涨越接近 1,乘以负权成罚项)。

    今日涨幅 < day_surge_warn_pct → 0(不罚);>= 软闸阈 → 从 0 线性升,到涨停线
    (limit_up_pct)封顶 1.0(再高恒 1)。单调不减。负涨幅/缺失 → 0。

    v1.3.1 Phase B:cfg 缺省(None)→ 直接回落模块级常量(行为与改前逐字节一致,对常量的
    monkeypatch 仍生效)。
    """
    if cfg is not None:
        warn_pct = cfg.get("day_surge_warn_pct", DAY_SURGE_WARN_PCT)
        limit_pct = cfg.get("limit_up_pct", LIMIT_UP_PCT)
    else:
        warn_pct = DAY_SURGE_WARN_PCT
        limit_pct = LIMIT_UP_PCT
    if pct_chg < warn_pct:
        return 0.0
    span = limit_pct - warn_pct
    if span <= 0:
        return 1.0
    return min(1.0, (pct_chg - warn_pct) / span)


def day_surge_warn_text(pct_chg: float, cfg: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """单日暴涨软闸文案(信号6;对齐 high_warn_text 写法,非空触发琥珀降级)。

    今日涨幅 >= day_surge_warn_pct → 返回文案(与 60 日高位 warn 并列,不互斥);否则 None。
    v1.3.1 Phase B:cfg 缺省(None)→ 直接回落模块级常量(行为与改前逐字节一致)。
    """
    if pct_chg is None:
        return None
    warn_pct = cfg.get("day_surge_warn_pct", DAY_SURGE_WARN_PCT) if cfg is not None else DAY_SURGE_WARN_PCT
    if pct_chg >= warn_pct:
        return f"今日大涨 {pct_chg:.1f}%,单日强弩之末,谨慎追高"
    return None


# —— 排序加权(机械层,不卡生死,只定"先看谁",plan §4.1 v1.3.1 A1 换新因子集)————
# v1.3.1 九键方案(经验首版,可迭代,复盘后调):量比权重仍最大;`low_position` 系统性
# 偏好左侧下跌票(方向反了)已删,换 `pos_health`(距高点越近分越高);新增 `breakout`
# (横盘突破)。正权之和 = 1.00;day_surge 是罚项(负权,从总分里减)。
WEIGHTS: Dict[str, float] = {
    "vol_ratio": 0.30,     # 量比(官方 daily_basic.volume_ratio,权重最大)
    "pos_health": 0.16,    # 位置健康(距60日高点,今日收盘/近60日最高收盘,越近高点分越高)
    "turnover": 0.14,      # 换手【健康区间评分】(信号3,带 [7,15]%)
    "vwap": 0.10,          # 收盘站 VWAP(信号1,布尔 0/1)
    "breakout": 0.10,      # 横盘突破(新增,信号7,布尔 0/1)
    "mv_elastic": 0.08,    # 市值弹性(信号4,带 [50,500]亿/floor 30亿)
    "active": 0.06,        # 近期活跃(信号5,布尔 0/1)
    "fund": 0.06,          # 资金面(主力近3日净流入占成交额比例,相对口径,免大盘股偏置)
    "day_surge": -0.06,    # 单日强弩之末罚分(信号6,罚项,越暴涨扣越多)
}


# —— v1.3.1 Phase B:选股配置可调化(档 B,plan §4「Phase B」config 形状钉死段)——————
#
# **单一事实源仍是上面的 WEIGHTS/VOL_RATIO_MIN/TURNOVER_HEALTHY_LO 等常量**;
# SCREEN_CONFIG_SPEC/DEFAULT_SCREEN_CONFIG 只是把它们**收进一份扁平单层键注册表**,
# 供用户在 App 里调参(GET/PUT /api/v1/screen/config)、供 resolve/validate 校验用,
# **不手写第二份数字**(建议#8,防双写漂移;等值断言测试见 test_screen.py)。
#
# 键集 = 9 权重(WEIGHTS 原样) + 13 阈值(各自对应上面已存在的 rules 常量;
# mv_mega_ceil 为审后修复新增第 22 键,见下方注释)。
# HIGH_EXCLUDE_PCT/HIGH_WARN_PCT/VOL_MULTIPLE_MIN/NEW_HIGH_DAYS/MA_DAYS/
# RECENT_FLOW_DAYS/SCORE_FLOOR **不在此键集**(plan §4 config 形状表未列,仍是
# rules.py 常量单一源、不进配置/不可调)。
#
# **mv_mega_ceil(审后修复新增)**:市值弹性上行衰减带终点(亿元),原是不进配置的
# rules 常量(MV_MEGA_CEIL),因与 mv_hi 默认值重合(均 500)导致衰减带 span=0、
# 退化成硬台阶,不符合"平滑衰减"设计意图——现升级进 SCREEN_CONFIG_SPEC 成第 22 键,
# 默认值改 1500(与 mv_hi=500 拉开衰减带),用户可调。
SCREEN_CONFIG_SPEC: Dict[str, Dict[str, Any]] = {
    # —— 权重(category="weight",∈[0,1];day_surge 例外 ∈[-1,0])——
    "vol_ratio":  {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["vol_ratio"]},
    "pos_health": {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["pos_health"]},
    "turnover":   {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["turnover"]},
    "vwap":       {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["vwap"]},
    "breakout":   {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["breakout"]},
    "mv_elastic": {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["mv_elastic"]},
    "active":     {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["active"]},
    "fund":       {"type": float, "range": (0.0, 1.0), "category": "weight", "default": WEIGHTS["fund"]},
    "day_surge":  {"type": float, "range": (-1.0, 0.0), "category": "weight", "default": WEIGHTS["day_surge"]},
    # —— 阈值(category="threshold")——
    "vol_ratio_min":          {"type": float, "range": (1.0, 5.0), "category": "threshold", "default": VOL_RATIO_MIN},
    "turnover_lo":            {"type": float, "range": (0.0, 50.0), "category": "threshold", "default": TURNOVER_HEALTHY_LO},
    "turnover_hi":            {"type": float, "range": (0.0, 50.0), "category": "threshold", "default": TURNOVER_HEALTHY_HI},
    "mv_lo":                  {"type": float, "range": (0.0, 10000.0), "category": "threshold", "default": MV_SMALL_CAP_LO},
    "mv_hi":                  {"type": float, "range": (0.0, 10000.0), "category": "threshold", "default": MV_SMALL_CAP_HI},
    "mv_mega_ceil":           {"type": float, "range": (500.0, 5000.0), "category": "threshold", "default": MV_MEGA_CEIL},
    "mv_floor":               {"type": float, "range": (0.0, 10000.0), "category": "threshold", "default": MV_MICRO_FLOOR},
    "breakout_range_max":     {"type": float, "range": (0.0, 1.0), "category": "threshold", "default": BREAKOUT_RANGE_MAX},
    "breakout_vol_ratio_min": {"type": float, "range": (1.0, 5.0), "category": "threshold", "default": BREAKOUT_VOL_RATIO_MIN},
    "day_outflow_floor":      {"type": float, "range": (-100000.0, 0.0), "category": "threshold", "default": DAY_OUTFLOW_FLOOR},
    "day_surge_warn_pct":     {"type": float, "range": (0.0, 20.0), "category": "threshold", "default": DAY_SURGE_WARN_PCT},
    "active_lookback_days":   {"type": int, "range": (1, 60), "category": "threshold", "default": ACTIVE_LOOKBACK_DAYS},
    "limit_up_pct":           {"type": float, "range": (0.0, 20.0), "category": "threshold", "default": LIMIT_UP_PCT},
}

# 默认配置 = 由上面 SPEC 的 default 字段(引用常量/WEIGHTS 构造)展开,不手写第二份数字
# (建议#8);等值断言测试见 test_screen.py(各键 == 对应 rules 常量)。
DEFAULT_SCREEN_CONFIG: Dict[str, Any] = {k: v["default"] for k, v in SCREEN_CONFIG_SPEC.items()}


def _is_finite_number(x: Any) -> bool:
    """类型是 int/float 且非有限值(nan/inf)返回 False(重要#4:非有限值必须回退默认)。"""
    if isinstance(x, bool):   # bool 是 int 子类,配置里不允许权重/阈值传 bool
        return False
    if not isinstance(x, (int, float)):
        return False
    return math.isfinite(x)


def _clamp_field(key: str, value: Any) -> float:
    """按 SCREEN_CONFIG_SPEC[key] 单字段夹紧:类型不符/非有限值 → 默认值;否则夹到 range。"""
    spec = SCREEN_CONFIG_SPEC[key]
    if not _is_finite_number(value):
        return spec["default"]
    lo, hi = spec["range"]
    v = max(lo, min(hi, float(value)))
    if spec["type"] is int:
        v = int(round(v))
    return v


def _enforce_band_consistency(out: Dict[str, Any]) -> None:
    """带内一致性收口(审后修复 🟡#1):逐键独立夹紧不拦"反转带"——用户能存进
    turnover_lo>=turnover_hi 或 mv 带乱序,评分函数因 span<=0 守卫不崩、不产 NaN,
    但因子单调性畸形、排序静默失真。此函数在逐键夹紧之后、返回之前对每条"带"做
    序约束检查,违反则**该带相关键整组回退默认**(最稳:结果恒合法,不做"抬高/
    压低到边界"这类局部修补,避免和用户其余设定产生新的隐式耦合)。

    只检查 out 里**实际存在**的键(PUT 可能只提交带的一部分,band 键都在场才有
    "反转"可言;缺键场景由 resolve 用默认补全后再次校验,不受此函数影响)。
    """
    # 换手带:turnover_lo < turnover_hi
    if "turnover_lo" in out and "turnover_hi" in out:
        if not (out["turnover_lo"] < out["turnover_hi"]):
            out["turnover_lo"] = DEFAULT_SCREEN_CONFIG["turnover_lo"]
            out["turnover_hi"] = DEFAULT_SCREEN_CONFIG["turnover_hi"]

    # 市值带:mv_floor < mv_lo < mv_hi < mv_mega_ceil(四键都在场才检查该序)
    mv_keys = ("mv_floor", "mv_lo", "mv_hi", "mv_mega_ceil")
    if all(k in out for k in mv_keys):
        if not (out["mv_floor"] < out["mv_lo"] < out["mv_hi"] < out["mv_mega_ceil"]):
            for k in mv_keys:
                out[k] = DEFAULT_SCREEN_CONFIG[k]


def validate_screen_config(cfg: Dict[str, Any], *, normalize_weights: bool = False) -> Dict[str, Any]:
    """按 SCREEN_CONFIG_SPEC 逐字段校验/夹紧(plan §4 Phase B2,plan-critic 重点)。

    ① 类型不符/缺失/非有限值(math.isfinite)→ 用默认值;
    ② 阈值越界 → 夹到 SPEC range;
    ③ **带内一致性收口(审后修复 🟡#1)**:逐键夹紧后,对"换手带"(lo<hi)、"市值带"
       (floor<lo<hi<mega_ceil)做序约束检查,违反 → 该带相关键整组回退默认(见
       `_enforce_band_consistency`);与 normalize_weights 无关,PUT/resolve 两条
       路径都跑(反转带无论哪条路径存入都不该生效)。
    ④ **权重归一只在 normalize_weights=True 时做**(钉死:归一只在 resolve 合并出全量后
       发生,PUT 逐键夹紧路径**显式**不传 normalize_weights,不靠"是否凑齐全部权重键"
       这种隐式判断——即便 PUT 一次性提交了全部 9 权重键,只要不是走 resolve,也不归一,
       严格对应 plan"PUT 时逐键按范围夹紧但不归一")。
    非法/异常配置 → 逐字段回退默认,绝不崩、绝不产空候选。
    """
    out: Dict[str, Any] = {}
    for key in SCREEN_CONFIG_SPEC:
        if key in cfg:
            out[key] = _clamp_field(key, cfg[key])
    # 未知键忽略(不进 out,不报错)。

    _enforce_band_consistency(out)

    if normalize_weights:
        positive_weight_keys = [k for k, v in SCREEN_CONFIG_SPEC.items()
                                if v["category"] == "weight" and k != "day_surge"]
        # 归一只在全量场景发生(resolve 已用 DEFAULT 补全所有键),缺键用默认兜底。
        weight_vals = {k: out.get(k, DEFAULT_SCREEN_CONFIG[k]) for k in positive_weight_keys}
        total = sum(weight_vals.values())
        if total <= 1e-9:
            # 全 0(或数值上退化为 0)→ 退回默认权重
            for k in positive_weight_keys:
                out[k] = DEFAULT_SCREEN_CONFIG[k]
        elif abs(total - 1.0) > 1e-9:
            # 按比例归一到和 = 1.0
            for k in positive_weight_keys:
                out[k] = weight_vals[k] / total
        else:
            for k in positive_weight_keys:
                out[k] = weight_vals[k]
        # day_surge(负权,已在上面按 range 夹到 [-1,0])不参与归一。

    return out


def resolve_screen_config(user_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """DEFAULT_SCREEN_CONFIG 基底 浅合并 用户增量 → 全量 → 校验 + 权重归一(plan §4 Phase B2)。

    user_cfg 缺省(None)→ 视为空增量(全默认)。缺键用默认、未知键忽略。
    返回全量已夹紧配置(供刷新链路显式穿参 / GET 端点 config 字段)。
    """
    merged = dict(DEFAULT_SCREEN_CONFIG)
    merged.update(user_cfg or {})
    return validate_screen_config(merged, normalize_weights=True)


def _normalize(values: List[float]) -> List[float]:
    """min-max 归一到 [0,1];全相等 → 全 0.5(无区分度,中性)。"""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def rank_score(
    vol_ratios: List[float],
    fund_3d: List[float],
    turnovers: List[float],
    pos_healths: List[float],
    vwap_oks: List[bool],
    breakout_oks: List[bool],
    total_mv_yis: List[float],
    actives: List[bool],
    day_pcts: List[float],
    cfg: Optional[Dict[str, Any]] = None,
) -> List[float]:
    """对一批候选算机械排序分(越大越靠前;v1.3.1 九因子,plan §4.1)。

    · vol_ratio/fund 走 min-max 相对归一(全相等 → 全 0.5 中性)。
    · pos_health 已是 [0,1] 绝对刻度,**直接进分,不走 min-max**(plan §4.1)。
    · turnover 调 turnover_health_score(信号3,函数已产 [0,1],不再 min-max)。
    · vwap/breakout/active 布尔转 0/1(信号1/7/5)。
    · mv_elastic 调 mv_elastic_score(信号4;缺失市值中性 0.5)。
    · day_surge 调 day_surge_penalty_norm 后乘负权(信号6,罚项)。
    九个入参列表等长、同序;返回同序的分数列表(理论范围约 [-0.06, 1.0])。
    fund_3d 传相对口径(占成交额比例合计,fetch.StockRow.net_mf_rate_3d),不要传绝对
    万元金额——否则大盘股天然靠体量堆高分,失真。pct_60d 不再传入排序(只留给 warn 分级)。

    v1.3.1 Phase B:cfg 缺省(None)→ 回落 WEIGHTS/DEFAULT_SCREEN_CONFIG(行为与改前逐字节
    一致,保批1测试/旧调用不回归)。cfg 传入时权重取 cfg 对应键(resolve 后已归一全量),
    阈值类因子函数(turnover/mv/day_surge)也一并穿参 cfg(生效机制显式穿参,禁 monkeypatch)。
    """
    n = len(vol_ratios)
    if n == 0:
        return []
    c = cfg if cfg is not None else DEFAULT_SCREEN_CONFIG
    w = {k: c.get(k, WEIGHTS[k]) for k in WEIGHTS}
    nv = _normalize(vol_ratios)
    nf = _normalize(fund_3d)
    out: List[float] = []
    for i in range(n):
        turnover_f = turnover_health_score(turnovers[i], cfg)
        vwap_f = 1.0 if vwap_oks[i] else 0.0
        breakout_f = 1.0 if breakout_oks[i] else 0.0
        mv_f = mv_elastic_score(total_mv_yis[i], cfg)
        active_f = 1.0 if actives[i] else 0.0
        surge_f = day_surge_penalty_norm(day_pcts[i], cfg)
        score = (
            w["vol_ratio"] * nv[i]
            + w["pos_health"] * pos_healths[i]   # 已是 [0,1] 绝对刻度,不 min-max
            + w["turnover"] * turnover_f
            + w["vwap"] * vwap_f
            + w["breakout"] * breakout_f
            + w["mv_elastic"] * mv_f
            + w["active"] * active_f
            + w["fund"] * nf[i]
            + w["day_surge"] * surge_f   # 负权,罚项
        )
        out.append(round(score, 6))
    return out
