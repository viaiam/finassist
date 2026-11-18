# 融知 FinAssist

金融智能客服平台，基于既有对话引擎完成最小金融适配。
已接入账户余额、交易流水、银行卡、贷款状态、还款计划以及贷款/理财产品咨询。
所有数据均为合成样例；尚未实现贷款申请、挂失、投诉等写入业务。
完整评估见 docs/finance-requirements-assessment.md。

## 工程结构

- `finassist/`：Python 客服服务，API、会话编排、对话引擎、任务流程和持久化。
- `flow_config/`：四条金融查询 YAML 流程。
- `finassist-web/`：Vue 客户端，包含聊天、历史消息及对象卡片。
- `finassist-business/`：FastAPI 业务中台 API；原资料未包含独立运营后台页面。
- `scripts/`：本地验证及可选桩服务。
- `docs/`：迁移记录、源码导读和金融需求。

## 本地启动（PowerShell，三个终端）

在本项目根目录同步客服依赖并配置模型与数据库：

```powershell
uv sync --locked
# 仅首次配置；已有 .env 时不要覆盖。
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 编辑 .env，填写模型、密钥和独立数据库连接；不要提交 .env。
uv run python -m finassist.main
```

中台使用独立 uv 环境：

```powershell
cd finassist-business
uv sync --locked
# 仅首次配置；已有 .env 时不要覆盖。
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 编辑中台 .env 后启动。
uv run uvicorn app.app:app --env-file .env --host 127.0.0.1 --port 18081
```

前端：

```powershell
cd finassist-web
npm ci
npm run dev
```

访问 http://127.0.0.1:5173 。客服接口文档位于 http://127.0.0.1:18082/docs。
Vite 将 `/api` 转发至客服，将 `/business` 转发至中台，保留后端原有接口结构。

## 数据库说明

客服默认使用 `finassist`，中台默认使用 `finassist_business`，需要 MySQL。
客服建表 SQL 见 scripts/init_dialogue.sql；金融查询使用独立 `finassist_finance` 库，中台 .env 配置 `FINASSIST_FINANCE_DATABASE_URL`。本机样例已生成，不要重复运行会清表的生成器。
迁移不会自动修改或复制原数据库。仅导入代码或生成 OpenAPI 不能证明数据库、模型端到端联通。

## 开发约定

代码、目录和配置标识使用英文；模块职责、关键分支和运行说明使用中文。
保留现有分层，优先做小步可验证改动，不混入金融新功能或无关重构。
提交前运行 `uv run python scripts/verify_migration.py`，前端运行 `npm run build`。
本机 `.venv`、`.idea`、`.env`、`node_modules` 和构建产物不应提交。

## 来源记录

本工程基于用户既有学习工程和用户提供的配套资料迁移，并非声称全部从零编写。
`docs/migration-manifest.json` 记录迁移前文件的 SHA-256，便于对照原始资料。

中台数据库 `finassist_business` 创建后，在中台目录执行 `uv run python init_db.py` 显式建表；该命令不生成样例数据。

配置完成后，也可在三个终端分别使用统一入口：

```powershell
.\scripts\start.ps1 server
.\scripts\start.ps1 business
.\scripts\start.ps1 web
```

## 金融版运行与验收

本次代码修改后重启客服（18082）和中台（18081），刷新前端（5173）。
页面自动读取有账户、贷款和还款计划的真实样例客户，不再使用电商样例用户编号。
先点击“账户”卡片，再问“查这个账户的余额”；贷款卡片同理。
详细测试问题见 docs/finance-test-questions.md。

```powershell
# 根目录运行，金融接口测试（含样例投诉写入，使用中台依赖环境）
.\finassist-business\.venv\Scripts\python.exe -B tests/integration/test_finance_api.py
# 根目录运行，独立临时中台 + 真实数据库 + 确定性流程，不调用模型
uv run python tests/integration/test_finance_dialogue.py
# 可选真实模型与会话落库验收：会调用配置中的模型并新增样例聊天历史
uv run python tests/integration/test_finance_dialogue.py --live-model
```

`sender_id` 目前只是可输入的演示客户编号，不是登录认证，仅可用于合成数据演示。
四条查询结果采用代码模板返回，产品咨询由模型基于中台资料组织语言。
原订单接口仍保留在中台，页面和规划器默认只提供金融能力。
