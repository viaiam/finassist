# FinAssist Business

融知业务中台，初版保留订单、商品、物流、退款及催发货接口。
此目录是中台 API，不是独立的运营后台页面。

```powershell
uv sync --locked
Copy-Item .env.example .env
# 填好独立数据库连接后启动，数据库需提前建表和准备样例数据。
uv run uvicorn app.app:app --env-file .env --host 127.0.0.1 --port 18081
```

接口文档：http://127.0.0.1:18081/docs 。已增加 `/finance` 只读金融接口，连接独立金融样例库。

中台数据库 `finassist_business` 创建后，在中台目录执行 `uv run python init_db.py` 显式建表；该命令不生成样例数据。

金融连接需要 .env 的 FINASSIST_FINANCE_DATABASE_URL；原有 DATABASE_URL 对应的中台库与金融样例库相互独立。
