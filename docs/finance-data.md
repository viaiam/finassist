> 更新：金融查询与基础投诉工单已接入，当前能力见 finance-requirements-assessment.md，验收见 finance-verification.md。下文为数据生成时的记录。

# 金融数据生成验证记录

日期：2026-11-18。

数据源复制到 `tools/finassist-finance-data`，使用独立库 `finassist_finance`，执行 `uv run --locked --no-dev python -m generate.main --profile smoke`。

共有 92 张金融业务表，已核对以下实际行数：

- `customer`：1200 条
- `bank_account`：1646 条
- `bank_card`：1396 条
- `account_transaction`：8896 条
- `wealth_order`：900 条
- `loan_contract`：300 条
- `support_ticket`：160 条

原始初始化器会删库，本次仅使用其 SQL 导入方法初始化新库，未删除已有数据库。

客服 `finassist` 会话表和现有中台 `finassist_business` 的表结构也已初始化，本地配置已修正。新进程中台数据库健康检查通过。

现有前端及中台仍采用订单、商品接口，尚未适配金融数据。金融数据生成完成不表示原页面已能展示金融账户。正在运行的旧服务需要重启后才能载入新连接。
