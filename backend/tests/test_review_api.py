"""阶段3 G2:复盘 + 记忆端点(GET /review + POST /review/{week}/note + GET /memory)单测。

不联网:DB 临时;token 临时;ENABLE_MONITOR=False。
覆盖 plan §4.4 G2 验收:
  ① GET /review 无 week 返本周实时聚合;带 week 返历史周;
  ② POST note 用 SELECT-then-UPDATE/INSERT(SQL 不含 ON CONFLICT(week),grep),
     写入后 GET 读回 nextWeekNote、二次覆盖同 week 不新增行;
  ③ GET /memory 返 memory 条目 + closedTrades 守线徽章字段、name=NULL 兜底回 code;
  ④ 缺 token 401;⑤ 空库各端点返空态不 500。
"""

import importlib
import inspect
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import settings as settings_singleton
from app.db import store

TEST_TOKEN = "t" * 64
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    db_path = str(tmp_path / "review_api.db")
    monkeypatch.setattr(settings_singleton, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(settings_singleton, "API_TOKEN", TEST_TOKEN, raising=False)
    app_mod = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_mod, "ENABLE_MONITOR", False)
    monkeypatch.setattr(app_mod, "_quotes_fn", lambda codes: {}, raising=False)
    with TestClient(app_mod.app) as c:
        yield c, db_path


def _seed_closed_trade(db_path, code, name, close_price, close_time, htd, buy_price=100.0):
    pid = store.open_position(code, name, buy_price, 100, "x", "2026-06-22", db_path=db_path)
    return store.close_position(
        pid, close_price, close_time=close_time, holding_trade_days=htd, db_path=db_path
    )


# —— ④:鉴权 ——
def test_review_requires_auth(ctx):
    c, _ = ctx
    assert c.get("/api/v1/review").status_code == 401
    assert c.post("/api/v1/review/2026-W27/note", json={"note": "x"}).status_code == 401
    assert c.get("/api/v1/memory").status_code == 401


# —— ⑤:空库不 500 ——
def test_review_empty_db_no_500(ctx):
    c, _ = ctx
    r = c.get("/api/v1/review", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["disciplineRate"] == 0 and b["score"] == 0
    assert b["redFlags"] == [] and b["trades"] == []
    assert b["sampleNote"] == "本周 0 笔闭合"
    assert len(b["trend"]) == 6


def test_memory_empty_db_no_500(ctx):
    c, _ = ctx
    r = c.get("/api/v1/memory", headers=AUTH)
    assert r.status_code == 200
    b = r.json()
    assert b["items"] == [] and b["closedTrades"] == []


# —— ①:GET /review 无 week 本周 / 带 week 历史周 ——
def test_review_default_current_week(ctx):
    c, db_path = ctx
    # 本周 = 2026-W27(2026-06-29~07-05):种 1 守 + 1 破止损
    _seed_closed_trade(db_path, "603986", "兆易创新", 116.0, "2026-06-30 10:00:00", 2)  # +16% 守
    _seed_closed_trade(db_path, "002463", "沪电股份", 90.0, "2026-07-01 10:00:00", 2)   # -10% 破止损
    from app.review.score import iso_week
    from datetime import date
    # 只在本 ISO 周确实是 W27 时断言具体 week;否则退化验证结构
    r = c.get("/api/v1/review", headers=AUTH).json()
    assert r["week"] == iso_week(date.today())
    # 带明确 week 查历史周
    r27 = c.get("/api/v1/review?week=2026-W27", headers=AUTH).json()
    assert r27["week"] == "2026-W27"
    assert r27["disciplineRate"] == 50   # 2 笔 1 守
    assert r27["redFlags"] == ["沪电股份 破止损:-10.0% 未在 -5% 走"]
    tags = {t["code"]: t["tag"] for t in r27["trades"]}
    assert tags["603986"] == "good" and tags["002463"] == "red"


# —— ②:POST note upsert(SELECT-then-UPDATE/INSERT,不 ON CONFLICT)——
def test_upsert_review_note_no_on_conflict_in_sql():
    """源码检查:upsert_review_note 的 SQL 不用 ON CONFLICT(reviews 无 UNIQUE(week))。

    只看真 SQL 语句(排除 docstring/注释里的解释性词)。
    """
    src = inspect.getsource(store.upsert_review_note)
    # 取三引号 docstring 之外的函数体:粗略地把 docstring 段剔掉再检查
    body = src
    if '"""' in body:
        parts = body.split('"""')
        # parts[0]=def 行, parts[1]=docstring, parts[2:]=真正函数体
        body = parts[0] + "".join(parts[2:]) if len(parts) >= 3 else body
    assert "ON CONFLICT" not in body.upper(), \
        "upsert_review_note 函数体 SQL 不应用 ON CONFLICT(reviews 无 UNIQUE(week))"


def test_save_note_then_read_back_and_overwrite(ctx):
    c, db_path = ctx
    # 写入
    r = c.post("/api/v1/review/2026-W27/note", json={"note": "只做 D 型,-5% 必走"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True
    # GET 读回
    got = c.get("/api/v1/review?week=2026-W27", headers=AUTH).json()
    assert got["nextWeekNote"] == "只做 D 型,-5% 必走"
    # reviews 表只 1 行
    conn = sqlite3.connect(db_path)
    n1 = conn.execute("SELECT COUNT(*) FROM reviews WHERE week='2026-W27'").fetchone()[0]
    conn.close()
    assert n1 == 1
    # 二次覆盖同 week → 不新增行,内容更新
    c.post("/api/v1/review/2026-W27/note", json={"note": "改一版"}, headers=AUTH)
    got2 = c.get("/api/v1/review?week=2026-W27", headers=AUTH).json()
    assert got2["nextWeekNote"] == "改一版"
    conn = sqlite3.connect(db_path)
    n2 = conn.execute("SELECT COUNT(*) FROM reviews WHERE week='2026-W27'").fetchone()[0]
    conn.close()
    assert n2 == 1   # 仍 1 行


def test_note_snapshots_discipline_rate(ctx):
    c, db_path = ctx
    # W27 种 2 笔 1 守 → discipline_rate=50 快照
    _seed_closed_trade(db_path, "603986", "兆易创新", 116.0, "2026-06-30 10:00:00", 2)
    _seed_closed_trade(db_path, "002463", "沪电股份", 90.0, "2026-07-01 10:00:00", 2)
    c.post("/api/v1/review/2026-W27/note", json={"note": "x"}, headers=AUTH)
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM reviews WHERE week='2026-W27'").fetchone()
    conn.close()
    assert row["discipline_rate"] == 50


# —— ③:GET /memory 返 memory 条目 + closedTrades 守线徽章 + name 兜底 ——
def test_memory_lists_items_and_closed_trades(ctx):
    c, db_path = ctx
    store.insert_memory("闭环结论", "追高硬扛那笔亏 40%", db_path=db_path)
    _seed_closed_trade(db_path, "603986", "兆易创新", 116.0, "2026-06-30 10:00:00", 2)   # 守(不沉淀)
    _seed_closed_trade(db_path, "002463", "沪电股份", 90.0, "2026-07-01 10:00:00", 5)    # 破止损+破时间(G3 自动沉淀 1 条)

    b = c.get("/api/v1/memory", headers=AUTH).json()
    # 手工 1 条 + G3 破线笔自动沉淀 1 条 = 2 条(守线笔不沉淀)
    assert len(b["items"]) == 2
    contents = [it["content"] for it in b["items"]]
    assert any("追高" in ct for ct in contents)
    assert any("沪电股份" in ct and "破" in ct for ct in contents)
    assert all(it["kind"] == "闭环结论" for it in b["items"])
    assert all(it["date"].startswith("2026-") for it in b["items"])

    assert len(b["closedTrades"]) == 2
    by_code = {t["code"]: t for t in b["closedTrades"]}
    kept = by_code["603986"]
    # +16% 止盈:kept_take True、kept_time True、broke_rule False
    # (kept_stop 对盈利笔天然 False——止损带 [-6%,-4%] 未触发,非破纪律)
    assert kept["keptTake"] is True and kept["keptTime"] is True and kept["brokeRule"] is False
    assert kept["pnl"] == "+16.0%"
    broke = by_code["002463"]
    assert broke["keptTime"] is False and broke["brokeRule"] is True


def test_memory_closed_trade_name_null_falls_back_to_code(ctx):
    c, db_path = ctx
    # 写一条 name/note 为 NULL 的历史 trade(模拟存量库;name/note 列 G3 补,这里全列名写入)
    store.init_db(db_path)   # 确保 name/note 列存在(G3 _ensure_trades_columns)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trades
           (code, open_price, close_price, open_time, close_time,
            kept_stop, kept_take, kept_time, pnl, broke_rule, created_at, name, note)
           VALUES ('600519', 100.0, 120.0, '2026-06-22', '2026-06-30 10:00:00',
                   1, 1, 1, 20.0, 0, '2026-06-30 10:00:00', NULL, NULL)"""
    )
    conn.commit(); conn.close()
    b = c.get("/api/v1/memory", headers=AUTH).json()
    t = b["closedTrades"][0]
    assert t["name"] == "600519"   # name=NULL 兜底回 code
    assert t["note"] == ""         # note=NULL 兜底空串
