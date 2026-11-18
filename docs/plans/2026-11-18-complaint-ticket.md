# 金融投诉工单最小版

沿用现有流程执行器，增加 complaint_ticket 流程，收集投诉类型、关联交易流水号（可答“无”）和问题描述。客户编号取当前会话 sender_id。

1. 先增加工单提交、重复请求及归属校验集成测试，确认原路由缺失导致失败。
2. 中台增加创建与详情接口，复用金融样例库 support_ticket、workflow_instance、workflow_task，在一个事务内写入。
3. 添加客服动作、输入槽位和金融提示词；沿用自动动作注册机制。
4. 运行接口与对话集成测试，验证原查询和多轮投诉流程。

本版不实现人工处理台、自动结案和短信通知。与资料接口一致，幂等缓存仅在当前进程生效，重启后不能保证旧请求去重；后续企业化时再改为数据库持久化。当前客户编号仍是样例身份，不是生产登录认证。

测试命令：`.venv/Scripts/python.exe tests/integration/test_finance_api.py`、`.venv/Scripts/python.exe tests/integration/test_finance_dialogue.py`。
