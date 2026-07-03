"""v1.3.0 Phase B(🔴高危区·金额计算 + 第三次真 schema migration)单测。

覆盖 plan §4「B 验收标准」①–⑦:
  ① _ensure_v130_columns 连跑幂等 / 缺列自动补 / 异常吞不拖垮 startup;
  ② costs.py 公式(佣金触底 5 元、印花税仅卖出、过户费双边、净额=毛−费、精确到分);
  ③ 清仓落 qty/fee/net_pnl_amount 三列 + close 响应带 fee/net_pnl_amount(真实 HTTP);
  ④ 复盘/记忆端点:新行返实值、旧 NULL 行返 null(非 0.0)、netPnlTotal 只 sum 非空行、读旧行不 500;
  ⑤ 纪律打分 discipline_rate/kept_* 与改动前一字不差(回归);
  ⑥ 🔵4 迁移失败(列缺失)时 open/close 行为确认(录入路径 try/except 兜底,不硬阻断契约层);
  ⑦ pytest 全绿(整套跑)。

不联网:DB 临时、token 临时、ENABLE_MONITOR=False、_quotes_fn 替身。
"""

from __future__ import annotations

import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import settings as settings_singleton
from app.db import store
from app.db.store.schema import _ensure_v130_columns
from app.trade import costs

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _cols(db_path, table):
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


# ============================================================================
# ① migration:连跑幂等 / 缺列自动补 / 异常吞不拖垮 startup
# ============================================================================

def test_v130_columns_added_by_init_db(tmp_path):
    """init_db 建库后 positions.industry + trades.qty/fee/net_pnl_amount 均在。"""
    db = str(tmp_path / "fresh.db")
    store.init_db(db)
    assert "industry" in _cols(db, "positions")
    for col in ("qty", "fee", "net_pnl_amount"):
        assert col in _cols(db, "trades"), f"trades 缺 {col}"


def test_v130_migration_idempotent(tmp_path):
    """连跑 init_db 三次(模拟服务反复重启)不抛 duplicate column、不重复列、数据无损。"""
    db = str(tmp_path / "idem.db")
    store.init_db(db)
    pid = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-22", db_path=db)
    store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    before = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")]
    conn.close()

    store.init_db(db)
    store.init_db(db)   # 反复重启

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    after = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")]
    conn.close()
    assert len(after) == len(before) == 1
    assert after[0] == before[0]              # 列值不变
    # 每列只一份(无重复)
    for col in ("qty", "fee", "net_pnl_amount"):
        assert _cols(db, "trades").count(col) == 1
    assert _cols(db, "positions").count("industry") == 1


def test_old_db_without_v130_columns_gets_migrated(tmp_path):
    """旧库(positions 无 industry、trades 无 qty/fee/net_pnl_amount)跑 init_db 自动补列、历史数据无损、新列 NULL。"""
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    # 旧版 positions(无 industry)+ 旧版 trades(无 qty/fee/net_pnl_amount,含阶段3 的 name/note)
    conn.execute("""
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, name TEXT NOT NULL,
            buy_price REAL NOT NULL, qty INTEGER NOT NULL, entry_reason TEXT NOT NULL,
            entry_snapshot TEXT, buy_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'holding', created_at TEXT NOT NULL)
    """)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
            open_price REAL NOT NULL, close_price REAL NOT NULL,
            open_time TEXT NOT NULL, close_time TEXT NOT NULL,
            kept_stop INTEGER NOT NULL, kept_take INTEGER NOT NULL,
            kept_time INTEGER NOT NULL, pnl REAL NOT NULL,
            broke_rule INTEGER NOT NULL, created_at TEXT NOT NULL,
            name TEXT, note TEXT)
    """)
    conn.execute(
        """INSERT INTO trades
           (code, open_price, close_price, open_time, close_time,
            kept_stop, kept_take, kept_time, pnl, broke_rule, created_at, name, note)
           VALUES ('600519', 100.0, 120.0, '2026-06-22', '2026-06-30 10:00:00',
                   1, 1, 1, 20.0, 0, '2026-06-30 10:00:00', '贵州茅台', '守住铁律')"""
    )
    conn.execute(
        """INSERT INTO positions
           (code, name, buy_price, qty, entry_reason, buy_date, status, created_at)
           VALUES ('000858', '五粮液', 150.0, 100, 'x', '2026-06-22', 'holding', '2026-06-22 09:30:00')"""
    )
    conn.commit(); conn.close()
    assert "industry" not in _cols(db, "positions")
    assert "net_pnl_amount" not in _cols(db, "trades")

    store.init_db(db)   # 自动补列

    assert "industry" in _cols(db, "positions")
    for col in ("qty", "fee", "net_pnl_amount"):
        assert col in _cols(db, "trades")

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades WHERE code='600519'").fetchone()
    p = conn.execute("SELECT * FROM positions WHERE code='000858'").fetchone()
    conn.close()
    # 历史数据无损;trades 新列(qty/fee/net_pnl_amount)与 positions.industry 均 NULL
    assert t["code"] == "600519" and t["pnl"] == 20.0 and t["name"] == "贵州茅台"
    assert t["qty"] is None and t["fee"] is None and t["net_pnl_amount"] is None
    assert p["code"] == "000858" and p["qty"] == 100    # 旧 qty 列(positions 本就有)不受影响
    assert p["industry"] is None


def test_v130_migration_swallows_exception_no_reraise(monkeypatch, caplog):
    """ALTER 意外失败 → 只 log.error 不 re-raise(不拖垮 startup)。传入被关闭的连接强制抛异常。"""
    conn = sqlite3.connect(":memory:")
    conn.close()   # 关闭后再 execute 会抛 ProgrammingError
    # 不抛出到调用方(init_db lifespan 路径),整段吞掉
    _ensure_v130_columns(conn)   # 不 raise 即通过


def test_init_db_survives_v130_migration_failure(tmp_path):
    """畸形库(trades 是 view,ALTER 必失败)跑 init_db → v130 迁移的 ALTER 抛
    OperationalError('Cannot add a column to a view'),被 _ensure_v130_columns 自身
    try/except 吞掉,init_db 不 re-raise、不拖垮 startup(高危区既有姿势)。

    注:_SCHEMA 的 `CREATE TABLE IF NOT EXISTS trades` 遇同名 view 是 no-op(IF NOT EXISTS
    按名字判存在,不管类型),故 executescript 不抛;真正被测的是三处 _ensure_* 对坏表的容错。
    """
    db = str(tmp_path / "survive.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE _t (x INTEGER)")
    conn.execute("CREATE VIEW trades AS SELECT x FROM _t")  # trades 是 view → ALTER 失败
    conn.commit(); conn.close()
    store.init_db(db)   # 不抛即通过(startup 不被拖垮)


# ============================================================================
# ② costs.py 公式(纯函数,精确到分)
# ============================================================================

def test_commission_floor_5_yuan_small_trade():
    """小仓位:买卖两边佣金都触底 5 元(万2.8 × 小额 < 5)。"""
    # 买额 10000 → 10000×0.00028 = 2.8 < 5 → 触底 5
    assert costs.buy_commission(10000.0) == 5.0
    assert costs.sell_commission(10000.0) == 5.0


def test_commission_above_floor_large_trade():
    """大仓位:佣金 = 额 × 万2.8(超过 5 元底)。"""
    # 买额 100000 → 100000×0.00028 = 28.0 > 5
    assert costs.buy_commission(100000.0) == 28.0
    assert costs.sell_commission(100000.0) == 28.0


def test_stamp_tax_sell_only():
    """印花税仅卖出:stamp_tax(卖额) = 卖额 × 0.0005;买入无印花税(公式只对卖额收)。"""
    assert costs.stamp_tax(10000.0) == 5.0     # 10000×0.0005
    assert costs.stamp_tax(0.0) == 0.0


def test_transfer_fee_double_sided():
    """过户费双边:(买额 + 卖额) × 0.00001。"""
    assert costs.transfer_fee(10000.0, 11000.0) == round(21000 * 0.00001, 2)   # 0.21


def test_total_fee_composition():
    """总费用 = 买佣 + 卖佣 + 印花税(仅卖) + 过户费(双边),逐项 round 到分。

    买额=卖额=10000:买佣 5 + 卖佣 5 + 印花 5 + 过户 (20000×1e-5=0.2) = 15.2
    """
    assert costs.total_fee(10000.0, 10000.0) == 15.2


def test_net_pnl_amount_gross_minus_fee():
    """净额 = 毛收益 − 总费用,精确到分。

    买 10 卖 11 × 1000 股:毛 = 1000;买额 10000/卖额 11000。
    买佣 max(2.8,5)=5、卖佣 max(3.08,5)=5、印花 11000×0.0005=5.5、过户 21000×1e-5=0.21 → 费 15.71
    净 = 1000 − 15.71 = 984.29
    """
    assert costs.net_pnl_amount(10.0, 11.0, 1000) == 984.29


def test_net_pnl_amount_loss_case():
    """亏损也算净额(毛为负,费仍双边扣)。买 10 卖 9 × 1000:毛 −1000,费再吃一口。"""
    # 买额 10000/卖额 9000:买佣 5、卖佣 max(2.52,5)=5、印花 9000×0.0005=4.5、过户 19000×1e-5=0.19 → 费 14.69
    assert costs.net_pnl_amount(10.0, 9.0, 1000) == round(-1000 - 14.69, 2)   # -1014.69


def test_costs_reference_settings_not_hardcoded(monkeypatch):
    """公式引用 settings 常量(非硬编):改费率 → 结果随动。"""
    monkeypatch.setattr(settings_singleton, "COMMISSION_MIN", 0.0, raising=False)
    monkeypatch.setattr(settings_singleton, "STAMP_TAX_RATE", 0.0, raising=False)
    monkeypatch.setattr(settings_singleton, "TRANSFER_FEE_RATE", 0.0, raising=False)
    # 只剩佣金(万2.8,无底、无印花、无过户):买额=卖额=10000 → 佣 2.8×2 = 5.6
    assert costs.total_fee(10000.0, 10000.0) == 5.6


# ============================================================================
# ③ 清仓落三列 + close 响应带 fee/net_pnl_amount(store 层 + 真实 HTTP)
# ============================================================================

def test_close_position_writes_qty_fee_net(tmp_path):
    """store.close_position 落 qty/fee/net_pnl_amount 三列(实值,与 costs 一致)。"""
    db = str(tmp_path / "close.db")
    store.init_db(db)
    pid = store.open_position("603986", "兆易创新", 100.0, 200, "x", "2026-06-22", db_path=db)
    tid = store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)
    assert isinstance(tid, int)   # 返回值仍是 trade_id(int,契约不变)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT qty, fee, net_pnl_amount FROM trades WHERE id=?", (tid,)).fetchone()
    conn.close()
    assert t["qty"] == 200
    assert t["fee"] == costs.total_fee(100.0 * 200, 116.0 * 200)
    assert t["net_pnl_amount"] == costs.net_pnl_amount(100.0, 116.0, 200)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_singleton, "DB_PATH", str(tmp_path / "api.db"), raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)
    with TestClient(app_mod.app) as c:
        yield c


def test_close_endpoint_returns_fee_and_net(client):
    """真实 HTTP:POST /positions/{id}/close 响应带 fee/net_pnl_amount 实值。"""
    r = client.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 100.0, "qty": 300,
        "entry_reason": "x", "name": "兆易创新",
    }, headers=AUTH)
    assert r.status_code == 200
    pid = r.json()["position_id"]

    rc = client.post(f"/api/v1/positions/{pid}/close", json={"sell_price": 116.0}, headers=AUTH)
    assert rc.status_code == 200
    b = rc.json()
    assert b["ok"] is True
    assert b["fee"] == costs.total_fee(100.0 * 300, 116.0 * 300)
    assert b["net_pnl_amount"] == costs.net_pnl_amount(100.0, 116.0, 300)
    # pnl 百分比列不动(仍在)
    assert "pnl" in b and b["broke_rule"] is False


# ============================================================================
# ④ 复盘/记忆端点:新行实值、旧 NULL 行 null(非 0.0)、netPnlTotal 只 sum 非空、不 500
# ============================================================================

def _seed_old_null_trade(db_path, code, name, close_time, pnl):
    """直接 INSERT 一条 net_pnl_amount=NULL 的旧行(模拟迁移前存量)。"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trades
           (code, open_price, close_price, open_time, close_time,
            kept_stop, kept_take, kept_time, pnl, broke_rule, created_at, name, note)
           VALUES (?, 100.0, ?, '2026-06-22', ?, 1, 1, 1, ?, 0, ?, ?, '守住铁律')""",
        (code, 100.0 + pnl, close_time, pnl, close_time, name),
    )   # qty/fee/net_pnl_amount 不写 → NULL
    conn.commit(); conn.close()


def test_review_null_row_returns_null_not_zero(client, tmp_path):
    """旧 NULL 行:GET /review 的 trades[].netPnlAmount 返 null(非 0.0);netPnlTotal 只 sum 非空行。"""
    db = str(tmp_path / "api.db")
    # 同一周:一条新行(有净额)+ 一条旧 NULL 行
    # 新行经 open→close(net 实值)
    r = client.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 100.0, "qty": 200,
        "entry_reason": "x", "name": "兆易创新",
    }, headers=AUTH)
    pid = r.json()["position_id"]
    client.post(f"/api/v1/positions/{pid}/close",
                json={"sell_price": 116.0, "sell_time": "2026-06-30 10:00:00"}, headers=AUTH)
    # 旧 NULL 行(同 ISO 周 2026-W27:6/30 属该周)
    _seed_old_null_trade(db, "600519", "贵州茅台", "2026-07-01 10:00:00", 20.0)

    from app.review.score import iso_week
    wk = iso_week("2026-06-30")
    rr = client.get(f"/api/v1/review?week={wk}", headers=AUTH)
    assert rr.status_code == 200
    body = rr.json()
    trades = {t["code"]: t for t in body["trades"]}
    # 新行:实值(与 costs 一致)
    assert trades["603986"]["netPnlAmount"] == costs.net_pnl_amount(100.0, 116.0, 200)
    # 旧 NULL 行:netPnlAmount 为 null,不是 0.0
    assert trades["600519"]["netPnlAmount"] is None
    # netPnlTotal 只 sum 非空行(= 新行净额),不因旧行缺数据把整周合计假成 0/漏加
    assert body["netPnlTotal"] == costs.net_pnl_amount(100.0, 116.0, 200)


def test_review_all_null_rows_nettotal_is_none(client, tmp_path):
    """整周全是旧 NULL 行 → netPnlTotal 为 None(D 端显"—"),不 500、不显假 0。"""
    db = str(tmp_path / "api.db")
    _seed_old_null_trade(db, "600519", "贵州茅台", "2026-07-01 10:00:00", 20.0)
    _seed_old_null_trade(db, "000858", "五粮液", "2026-07-02 10:00:00", -8.0)

    from app.review.score import iso_week
    wk = iso_week("2026-07-01")
    rr = client.get(f"/api/v1/review?week={wk}", headers=AUTH)
    assert rr.status_code == 200
    body = rr.json()
    assert body["netPnlTotal"] is None
    for t in body["trades"]:
        assert t["netPnlAmount"] is None


def test_memory_null_row_returns_null_not_zero(client, tmp_path):
    """GET /memory 的 closedTrades[].netPnlAmount:新行实值、旧 NULL 行 null,读旧行不 500。"""
    db = str(tmp_path / "api.db")
    r = client.post("/api/v1/positions/open", json={
        "code": "603986", "buy_price": 100.0, "qty": 200,
        "entry_reason": "x", "name": "兆易创新",
    }, headers=AUTH)
    pid = r.json()["position_id"]
    client.post(f"/api/v1/positions/{pid}/close",
                json={"sell_price": 116.0, "sell_time": "2026-06-30 10:00:00"}, headers=AUTH)
    _seed_old_null_trade(db, "600519", "贵州茅台", "2026-07-01 10:00:00", 20.0)

    rm = client.get("/api/v1/memory", headers=AUTH)
    assert rm.status_code == 200
    rows = {t["code"]: t for t in rm.json()["closedTrades"]}
    assert rows["603986"]["netPnlAmount"] == costs.net_pnl_amount(100.0, 116.0, 200)
    assert rows["600519"]["netPnlAmount"] is None   # 旧行 null 非 0.0


def test_review_true_zero_net_stays_zero_not_null(tmp_path):
    """区分'没数据'vs'真 0 元':net_pnl_amount==0.0 的行必须原样返 0.0,不被误判 None。"""
    from app.review.score import aggregate_week, iso_week
    wk = iso_week("2026-06-30")
    trades = [{
        "code": "603986", "name": "兆易创新", "close_time": "2026-06-30 10:00:00",
        "kept_stop": 1, "kept_take": 1, "kept_time": 1, "pnl": 0.0, "broke_rule": 0,
        "net_pnl_amount": 0.0,   # 真 0 元
    }]
    review = aggregate_week(wk, trades_fn=lambda: trades, holdings_fn=lambda: [])
    assert review["trades"][0]["netPnlAmount"] == 0.0   # 原样 0.0,不是 None
    assert review["netPnlTotal"] == 0.0                 # 有非空行(0.0),合计 0.0 非 None


# ============================================================================
# ⑤ 纪律打分回归:discipline_rate / kept_* / score / redFlags 与本版前一字不差
# ============================================================================

def test_discipline_scoring_unchanged_regression(tmp_path):
    """经典组合(1 守 + 1 破止损)聚合:discipline_rate/score/kept_*/redFlags 口径不变。

    这些断言值是 v1.3.0 改动前 aggregate_week 的既有口径(仅新增净额维度,不动纪律口径)。
    """
    from app.review.score import aggregate_week, iso_week

    wk = iso_week("2026-06-30")
    trades = [
        {   # 守线笔(+16%,全绿)
            "code": "603986", "name": "兆易创新", "close_time": "2026-06-30 10:00:00",
            "kept_stop": 0, "kept_take": 1, "kept_time": 1, "pnl": 16.0, "broke_rule": 0,
            "net_pnl_amount": 3100.0,
        },
        {   # 破止损笔(-10%,跌穿容差未走)
            "code": "600519", "name": "贵州茅台", "close_time": "2026-07-01 10:00:00",
            "kept_stop": 0, "kept_take": 0, "kept_time": 1, "pnl": -10.0, "broke_rule": 1,
            "net_pnl_amount": -2050.0,
        },
    ]
    review = aggregate_week(wk, trades_fn=lambda: trades, holdings_fn=lambda: [])
    # 2 笔中 1 笔破 → discipline_rate = round(1/2*100) = 50;score 一比一
    assert review["disciplineRate"] == 50
    assert review["score"] == 50
    # redFlags:仅破线笔一条(带股票名 + 破止损明细)
    assert len(review["redFlags"]) == 1
    assert "贵州茅台" in review["redFlags"][0] and "破止损" in review["redFlags"][0]
    # 每笔 tag/comment 口径不变
    tmap = {t["code"]: t for t in review["trades"]}
    assert tmap["603986"]["tag"] == "good" and tmap["603986"]["comment"] == "守住铁律"
    assert tmap["600519"]["tag"] == "red" and "破止损" in tmap["600519"]["comment"]
    # 新增净额维度(不干扰纪律口径)
    assert tmap["603986"]["netPnlAmount"] == 3100.0
    assert review["netPnlTotal"] == round(3100.0 - 2050.0, 2)   # 1050.0


def test_close_position_kept_flags_unchanged_regression(tmp_path):
    """close_position 落库的 kept_*/broke_rule/pnl 口径不因新增净额列而变。"""
    db = str(tmp_path / "reg.db")
    store.init_db(db)
    # 守止盈(+16%)
    pid = store.open_position("603986", "兆易创新", 100.0, 100, "x", "2026-06-22", db_path=db)
    tid = store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    conn.close()
    assert t["kept_take"] == 1 and t["broke_rule"] == 0
    assert round(t["pnl"], 2) == 16.0
    assert t["note"] == "守住铁律"

    # 破止损(-10%,持到 D2)
    pid2 = store.open_position("600519", "贵州茅台", 100.0, 100, "x", "2026-06-22", db_path=db)
    tid2 = store.close_position(pid2, 90.0, holding_trade_days=2, db_path=db)
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    t2 = conn.execute("SELECT * FROM trades WHERE id=?", (tid2,)).fetchone()
    conn.close()
    assert t2["broke_rule"] == 1 and t2["note"] == "破止损:跌穿 -5% 未走"


# ============================================================================
# ⑥ 🔵4 迁移失败(列缺失)时 open/close 契约层行为确认
# ============================================================================

def test_close_on_db_missing_net_columns_raises_operationalerror(tmp_path):
    """迁移静默失败(trades 缺 net 列)→ close_position INSERT 抛 OperationalError(no such column)。

    契约:录入路径本就有 try/except ValueError→404 兜底,但 no such column 是
    OperationalError(非 ValueError)→ 端点会 500;plan §4「🔵4」明确接受此后果差异
    (迁移失败=录不了仓,比阶段3'少个展示列'重),仍用只 log 不 re-raise 的既有迁移姿势。
    此测试固化该后果(迁移失败时 close 确实抛,不会静默写坏数据)。
    """
    db = str(tmp_path / "nocol.db")
    # 建一个只有阶段3 列(无 v130 三列)的 trades + 正常 positions,种一个 holding
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, name TEXT NOT NULL,
            buy_price REAL NOT NULL, qty INTEGER NOT NULL, entry_reason TEXT NOT NULL,
            entry_snapshot TEXT, buy_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'holding', created_at TEXT NOT NULL)
    """)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
            open_price REAL NOT NULL, close_price REAL NOT NULL,
            open_time TEXT NOT NULL, close_time TEXT NOT NULL,
            kept_stop INTEGER NOT NULL, kept_take INTEGER NOT NULL,
            kept_time INTEGER NOT NULL, pnl REAL NOT NULL,
            broke_rule INTEGER NOT NULL, created_at TEXT NOT NULL, name TEXT, note TEXT)
    """)
    conn.execute("CREATE TABLE memory (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute(
        """INSERT INTO positions (code, name, buy_price, qty, entry_reason, buy_date, status, created_at)
           VALUES ('603986', '兆易创新', 100.0, 100, 'x', '2026-06-22', 'holding', '2026-06-22 09:30:00')"""
    )
    conn.commit()
    pid = conn.execute("SELECT id FROM positions WHERE code='603986'").fetchone()[0]
    conn.close()

    # trades 缺 qty/fee/net_pnl_amount → INSERT 抛 OperationalError(no such column)
    with pytest.raises(sqlite3.OperationalError):
        store.close_position(pid, 116.0, holding_trade_days=2, db_path=db)

    # position 未被归档(INSERT 抛在 UPDATE 之前,同事务回滚)——不产生幽灵闭合
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    p = conn.execute("SELECT status FROM positions WHERE id=?", (pid,)).fetchone()
    conn.close()
    assert p["status"] == "holding"
