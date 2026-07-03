"""交易成本计算(v1.3.0 Phase B1)。

费率常量单一源在 `app/config/settings.py`(可配),公式在 `app/trade/costs.py` 纯函数。
**与离场铁律常量(-5.0/+15/D4/容差带,在 app/db/store/constants.py)严格分离**——
费用是另一套单一源,不塞进 store/constants.py(CLAUDE.md 红线)。
"""
