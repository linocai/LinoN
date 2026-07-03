"""交易成本 + 净收益纯函数(v1.3.0 Phase B1,🔴高危区·金额计算)。

**沪深口径**:佣金(买卖双边、万2.8、最低 5 元/笔)+ 印花税(仅卖出、0.05%)+
过户费(买卖双边、0.001%)。过户费/印花税对北交所口径不同;北交所已被选股黑名单
排除(rules.py `^(30|688|689|8|4|920)`),手录基本不碰,故本模块按沪深口径实现(🔵8)。

费率常量单一源 = `app/config/settings.py`(可配 4 字段),本模块**引用 settings 常量、
不硬编数字**。所有结果 `round(…, 2)`(元,两位小数,逐项四舍五入)。

公式(定死,plan §4 B1):
    总费用 = max(买额×0.00028, 5) + max(卖额×0.00028, 5) + 卖额×0.0005 + (买额+卖额)×0.00001
    net_pnl_amount = (卖价−买价)×qty − 总费用
其中 买额 = 买价×qty、卖额 = 卖价×qty。
"""

from __future__ import annotations

from app.config.settings import settings


def buy_commission(buy_amount: float) -> float:
    """买入佣金 = max(买额 × 佣金率, 最低佣金)。元,两位小数。"""
    return round(max(buy_amount * settings.COMMISSION_RATE, settings.COMMISSION_MIN), 2)


def sell_commission(sell_amount: float) -> float:
    """卖出佣金 = max(卖额 × 佣金率, 最低佣金)。元,两位小数。"""
    return round(max(sell_amount * settings.COMMISSION_RATE, settings.COMMISSION_MIN), 2)


def stamp_tax(sell_amount: float) -> float:
    """印花税 = 卖额 × 印花税率(**仅卖出单边**)。元,两位小数。"""
    return round(sell_amount * settings.STAMP_TAX_RATE, 2)


def transfer_fee(buy_amount: float, sell_amount: float) -> float:
    """过户费 = (买额 + 卖额) × 过户费率(**沪深买卖双边**)。元,两位小数。"""
    return round((buy_amount + sell_amount) * settings.TRANSFER_FEE_RATE, 2)


def total_fee(buy_amount: float, sell_amount: float) -> float:
    """总费用 = 买佣 + 卖佣 + 印花税 + 过户费(逐项已 round 到分再相加)。元,两位小数。"""
    return round(
        buy_commission(buy_amount)
        + sell_commission(sell_amount)
        + stamp_tax(sell_amount)
        + transfer_fee(buy_amount, sell_amount),
        2,
    )


def net_pnl_amount(buy_price: float, sell_price: float, qty: int) -> float:
    """净收益金额 = (卖价 − 买价) × qty − 总费用。元,两位小数。

    买额 = 买价 × qty、卖额 = 卖价 × qty。总费用逐项 round 到分。
    """
    buy_amount = buy_price * qty
    sell_amount = sell_price * qty
    gross = (sell_price - buy_price) * qty
    return round(gross - total_fee(buy_amount, sell_amount), 2)
