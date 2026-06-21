# LinoN — 项目专属规范与坑(builder/reviewer 必读)

> 全局规范见 `~/.claude/CLAUDE.md`;权威施工件 `PROJECT_PLAN.md`。本文件只记 LinoN 专属。

## 仓库布局

- monorepo:`backend/`(Python 数据层/部署/冒烟)+ `client/`(SwiftUI 契约,本期仅两个 .swift)+ `archive/`(历史 plan/审查报告)。
- `backend/app/` 子包:`config / data / db / calendar / smoke`。
- 跑后端:`cd backend && source .venv/bin/activate`。建环境:`bash scripts/setup.sh`(幂等)。冒烟:`python scripts/smoke.py [code]`。测试:`python -m pytest`。

## 钉死的领域常量(单一事实源,禁止各处漂移)

- 止损线 = `buy_price×0.95`,**纯派生不落库**(`positions` 无 stop_line 列);止盈 ×1.15;D4 强平。
- 触发线口径**定死 -5.0**;展示侧 -4.9 仅显示阈(见 `Models.swift` 的 `hitStop`)。
- `kept_stop` 容差带 **[-6%, -4%]**(滑点不误判破纪律),常量在 `app/db/store.py` 顶部。
- 持仓交易日计数:**买入日=D1**,`count==4 ⟺ should_force_close`(D4 强平,可卖 D2/D3)。改这个语义=改契约,必须回 planner。
- 绿涨红跌(用户明确选择,与 A 股本地相反),**勿"纠正"**。

## 数据源坑(已验证)

- 新浪 `hq.sinajs.cn`:**必须带 `Referer: https://finance.sina.com.cn`**,否则返回 `Kinsoku jikou desu!` 无数据。GBK 解码。字段:volume=**股**(÷100→手)、amount=**元**;bid/ask 块「量先价后」。
- 腾讯 `qt.gtimg.cn`:GBK;index0=市场标记;volume(idx6)=**手**、amount(idx37)=**万元**(×1e4→元);bid/ask 块「价先量后」(**与新浪相反,易写反**)。ts(idx30)=`YYYYMMDDHHMMSS`。
- 归一目标(plan):`Quote.volume` 单位**手**、`Quote.amount` 单位**元**。两源已对齐(实测 603986 价/量/涨跌停完全一致)。

## 交易日历

- 静态兜底表 `app/calendar/static_holidays.py` = 官方 2025/2026 休市日 + **调休补班周末(股市仍休)**;来源已查证(国务院通知 + 上交所公告),注释在文件头。trade_cal 到位后用 `verify_against_trade_cal` 比对告警,**不自动改静态表**。
- `app/calendar` 包名与**标准库 calendar 同名**:包内一律绝对导入,**禁止 `import calendar`**(会拿到本包)。本模块只依赖 `datetime`。
- 静态表覆盖 2025–2026;超出年份 `is_trading_day` 退化为"工作日近似"并打 warning(本期不走到,待 trade_cal)。

## 配置

- `app/config/settings.py` 主路径用 pydantic-settings;另有**标准库 fallback**(仅当 pydantic-settings 未装时启用,供未 setup 前的 import 不崩)。装了依赖后 `_BACKEND == "pydantic-settings"`。
- pydantic v2 的 BaseSettings 实例**不能直接 setattr**;测试里要换 settings 用替身对象 monkeypatch 模块级 `settings` 名字 + `reset_client_cache()`。
- `.env` 不提交;`setup.sh` 首次会从 `.env.example` 拷一份占位。

## 依赖/环境

- 开发机 Python 3.9.6(系统自带);`requirements.txt` 钉死版本兼容 3.9(pandas 2.2.3 是支持 3.9 末版,pydantic-settings 2.7.1)。ECS Python 版本待定,这些版本 3.9~3.12 通吃。
- macOS 上 urllib3 报 `NotOpenSSLWarning`(LibreSSL)无害,ECS(OpenSSL)不出现,**勿当 bug 追**。
- `timeout` 命令 macOS 默认无;脚本验证用 `bash -n` 语法检查。

## 部署 / ECS(hz 杭州云)

- 目标 `deploy@118.178.122.194:/opt/linon`(阿里云 ECS,代号 hz;事实源 `~/Lino/hz_info.md`,**任何 hz 运维动作后必须更新它**)。SSH 仅公钥登录、用户 `deploy`。三要素已填 `backend/.env`(gitignored)。
- 这台机已跑 lf/lw/主页/xiaoran + nginx + postgres,**内存仅 1.6G + 2G swap,很紧**;阶段1 上 FastAPI 要挑没占的本地端口(已用 8000/8787/5432/80/443)。
- **坑1 pip 镜像**:ECS 直连公网 PyPI 超时卡死(hz_info 两次重申),`setup.sh` 已默认 `PIP_INDEX_URL=阿里云镜像` + `TIMEOUT=60`,可覆盖。
- **坑2 rsync**:本机 Mac 是 openrsync,与 `--delete` 不兼容;`sync.sh` 已加 GNU-rsync 守卫,需先 `brew install rsync`。
- **坑3 /opt 权限**:`/opt/linon` 未建,按惯例 `deploy:linon` setgid + 阶段1 建 nologin 系统用户;rsync `-a` 会带错 Mac 目录权限,远端需 chown/chmod 复原(同 lw/lf 旧坑)。
- **阶段0 不部署**(无服务);阶段1 接 FastAPI + systemd 后才真 rsync。

## 待联调(token/SSH/真机就绪后)

- Tushare 有 token 真拉一条 daily/moneyflow(本期只验证无 token 降级)。
- 实时价真源**联网+盘中**复测(本期用收盘快照 + 样例报文单测;盘后源仍返回上一交易日快照)。
- `sync.sh` 填 host/user/path 后真 rsync 到 ECS,远端 `setup.sh` 跑通。
- `deploy/linon.service` 阶段1 接 FastAPI 后才 enable/start(本期注释态)。
