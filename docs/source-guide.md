> 本文为迁移后的引擎源码导读；启动与配置以根目录 README 为准。

# 业务智能客服 · 源码导读

> 这份文档配合源码一起看：先读本文建立全局印象，再按「第 6 节 阅读顺序」逐层钻进代码。
> 每个源文件的顶部也写了模块级注释（职责 / 在调用链中的位置 / 关键概念），两边对照着看印象最深。

---

## 1. 这个项目在做什么

一个**带业务办理能力的业务客服机器人**。用户发一句话，系统要判断他到底想干什么，然后分三条路走：

| 用户说的话 | 系统走哪条路 | 干什么 |
| --- | --- | --- |
| 我要查订单状态 / 我要退款 / 推荐个椅子 | **任务流程**（task） | 启动一条 YAML 定义的多步流程，逐步收集槽位、调用接口、渲染话术 |
| 这个商品多少钱 / 你们的退货政策 | **知识检索**（knowledge） | 命中意图 → 找对应 provider 取数 → 交给 LLM 组织成一句话 |
| 你好呀 / 谢谢 | **闲聊**（chitchat） | 带着最近几轮历史直接让 LLM 回一句 |

关键难点不在「调 LLM」，而在**怎么把 LLM 的不确定输出，塞进一个确定的状态机里**。
整个项目的骨架就是围绕这件事搭的：

- LLM 只负责**判断意图、产出命令/意图 id**（结构化 JSON）
- 代码负责**校验 → 改状态 → 推流程 → 生成回复**（纯确定性逻辑）

---

## 2. 技术栈

| 层次 | 选型 |
| --- | --- |
| Web 框架 | FastAPI（async）+ uvicorn |
| LLM 接入 | LangChain 的 `init_chat_model`，OpenAI 兼容协议 |
| 数据持久化 | MySQL + SQLAlchemy 2.0 async（aiomysql 驱动） |
| 状态序列化 | pydantic `TypeAdapter` 把 dataclass 树互转 JSON |
| 模板渲染 | Jinja2（流程话术模板 + 提示词模板） |
| 配置 | pydantic-settings 读 `.env`；流程配置用 YAML |

启动只有三个异步资源，都在 `api/app.py` 的 lifespan 里初始化：
数据库引擎 → HTTP 客户端 → 对话引擎。前两个是 IO 资源，最后一个是纯内存装配。

---

## 3. 目录结构（每个文件一句话）

```text
finassist/
├── flow_config/user_flows.yml       ★ 业务流程配置：5 条流程、9 个槽位的全部定义
├── mock_business_server.py          ★ 模拟业务中台（18081 端口），订单/物流/商品假数据
├── pyproject.toml / uv.lock            依赖清单（uv 管理）
└── finassist/
    ├── main.py                         进程入口：uvicorn.run(app)
    ├── api/                            ── 接入层：只做 HTTP ↔ 业务模型转换
    │   ├── app.py                       创建 FastAPI 对象 + lifespan 管理全局资源
    │   ├── chat_router.py               POST /api/chat 路由 + 两个模型转换函数
    │   ├── dependencies.py              依赖注入：把单例引擎塞给路由
    │   └── schemas.py                   对外的请求/响应 Pydantic 模型
    ├── service/                        ── 业务编排层（薄）
    │   └── dialogue_service.py          读状态 → 交给引擎 → 写状态，三步
    ├── engine/                         ── 核心引擎
    │   ├── dialogue_engine.py           ★★★ 总入口：会话维护 + 三分支分派
    │   └── builder.py                   ★★ 依赖装配：把十几个组件 new 好并互相关联
    ├── domain/                         ── 领域模型（不依赖任何框架）
    │   ├── state.py                     ★★★ DialogueState：全部记忆都在这里
    │   └── message.py                   消息模型：文本/对象、用户/机器人
    ├── lifecycle/models.py              任务事件：Started/Switched/Resumed/Canceled
    ├── plan/                           ── 意图识别（LLM 第一跳）
    │   ├── turn_planner.py              拼提示词 → 调 LLM → 解析 JSON 成 TurnPlan
    │   ├── turn_plan_validator.py       ★★ 校验模型给的命令/意图是否合法
    │   └── command.py                   命令模型：start_flow / set_slots / ...
    ├── prompts/                        ── 提示词资产
    │   ├── jinja2/*.jinja2              4 个提示词模板
    │   ├── loader.py                    按名字读模板文件
    │   ├── models.py                    TurnPlan 家族 + ClarifyReason + 校验结果
    │   └── history_builder.py           把历史对话渲染成 USER:/BOT: 文本块
    ├── task/                           ── 任务流程（最重的一块）
    │   ├── task_handler.py              ★★ 任务方向的门面：命令→事件→话术→推流程
    │   ├── command/command_processor.py ★★ 按命令改 state，产出 TaskEvent 列表
    │   ├── tasklifecycle/task_lifecycle.py  事件 → 中文提示语
    │   ├── flow/                        流程的静态定义（YAML 的内存模型）
    │   │   ├── steps.py                 5 种步骤类型 + 从 dict 构造
    │   │   ├── links.py                 步骤间的连线（静态/条件/兜底）
    │   │   ├── models.py                Flow / FlowSlot / FlowCatalog
    │   │   └── loader.py                解析 YAML → FlowCatalog
    │   ├── flowexecutor/flow_executor.py ★★★ 流程执行器：while 循环推步骤
    │   ├── response/                    ── 话术渲染
    │   │   ├── models.py                ResponseMode(static/rephrase/generate) + 模板模型
    │   │   └── response_render.py       jinja2 渲染 + 按模式决定是否让 LLM 改写
    │   └── action/                      ── 业务动作（真正调外部接口的地方）
    │       ├── base.py                  Action 基类 + ActionCall/ActionResult
    │       ├── registry.py              名字 → Action 对象的注册表
    │       ├── builder.py               自动扫描 custom/ 包并注册
    │       ├── action_runner.py         执行入口（FlowExecutor 只认它）
    │       └── custom/                  三个具体动作：查订单 / 查物流 / 推荐
    ├── knowledge/                      ── 知识检索
    │   ├── intents.py                   ★ 意图字典：意图 id → 用哪些 provider
    │   ├── registry.py                  provider 注册表
    │   ├── provider.py                  各种取数实现（API / FAQ / RAG 占位）
    │   ├── knowledge_handler.py         ★ 五步：取意图→取数→合并→组织→回复
    │   └── responder.py                 把 chunk 列表交给 LLM 组织成人话
    ├── clarify/clarify_response.py      校验失败时的反问话术
    ├── chitchat/chit_chat.py            闲聊回复
    ├── repository/                     ── 持久化
    │   ├── dialogue_repository.py       ★ load_state / save_state（upsert）
    │   └── orm/                         Base + 单表 dialogue_states
    ├── conf/config.py                   Settings：读 .env
    └── utils/                           llm / db / httpx_client 三个全局资源工厂
```

带 ★ 的是主干，先读它们；其余是主干上挂的零件。

---

## 4. 整体架构（一张图）

```text
                    ┌──────────────────────────────┐
   HTTP 请求 ──────► │ api/        接入层（薄）      │  schemas + 模型转换
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │ service/    编排层（薄）      │  load → engine → save
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │ engine/     核心引擎          │
                    │  · 会话过期判定（60 分钟）    │
                    │  · 文本 / 对象 两条入口       │
                    │  · 意图识别 → 校验 → 三分支   │
                    └───┬──────────┬───────────┬───┘
                        ▼          ▼           ▼
                  ┌─────────┐ ┌──────────┐ ┌────────┐
                  │ task/   │ │knowledge/│ │chitchat│
                  │ 流程引擎│ │ 知识检索 │ │ 闲聊   │
                  └────┬────┘ └────┬─────┘ └───┬────┘
                       ▼           ▼           ▼
                  ┌─────────────────────────────────┐
                  │ action/custom · provider        │  ← 调外部中台/知识库
                  └─────────────────────────────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │ repository/  MySQL 单表持久化   │
                  └─────────────────────────────────┘
```

**一句话记住分层原则**：越往下越稳定，越往上越易变。
domain（数据形状）几乎不动；api（对前端）随时改；中间的 engine 靠依赖注入隔离变化。

---

## 5. 一次请求的完整生命周期

以「我要退款」为例，从按下发送到看到回复：

```text
1. POST /api/chat  {sender_id, message_id, text}
   └ api/chat_router.py::chat()
       └ _build_user_message()  把 HTTP 模型转成 UserMessage(type=TEXT)

2. service/dialogue_service.py::run()
   ├ repository.load_state(sender_id)      读库；没有就 new 一个空的 DialogueState
   ├ engine.process_message(state, message)
   └ repository.save_state(state)          整棵树序列化回写（upsert）

3. engine/dialogue_engine.py::process_message()
   ├ _prepare_current_session()   60 分钟没动过？关会话 + 清任务 + 开新会话
   └ 文本 → _execute_text_message()
       ├ TurnPlanner.plan()        拼提示词 → LLM → JSON → TurnPlan
       ├ TurnPlanValidator.validate()
       │    ├ 不合法 → ClarifyResponse.response() → 「您是想办理什么业务呢？」
       │    └ 合法   → 下一步
       └ 按 plan 分支：task → TaskHandler.handle()

4. task/task_handler.py::handle()      ← 三件事串起来
   ├ CommandProcessor.process()      改 state（active/paused/slots）→ 产出 list[TaskEvent]
   ├ TaskLifecycleResponder          事件 → 「好的，现在开始执行退款申请」
   └ FlowExecutor.execute()          从当前 step 往下推，直到要用户输入或流程结束

5. task/flowexecutor/flow_executor.py::execute()
   └ for _ in range(100):            最多推 100 步，防死循环
       ├ StartFlowStep   → 挪到下一步
       ├ CollectSlotStep → 槽位空？停在这里问用户；有值？往下走
       ├ ActionStep      → ActionRunner.run() 调中台，结果塞回 slots
       ├ ResponseStep    → ResponseRender 渲染模板成 BotMessage
       └ EndFlowStep     → 清空 active，结束

6. 结果回传：ProcessResult → api 层转 ChatResponse → JSON 给前端
```

---

## 6. 推荐阅读顺序（五遍法）

不要从 `main.py` 顺着往下读——那是执行顺序，不是理解顺序。
建议按「**数据结构 → 静态配置 → 主干链路 → 两大分支 → 边角料**」五遍走，每遍目标单一。

### 第一遍：把「记忆」搞清楚（约 1 小时）

| 顺序 | 文件 | 读的时候问自己 |
| --- | --- | --- |
| 1 | `finassist/domain/message.py` | 一条消息有几个字段？文本和对象怎么区分？ |
| 2 | `finassist/domain/state.py` | DialogueState 这棵树长什么样？shared 和 tasks 为什么要分开？ |
| 3 | `finassist/lifecycle/models.py` | 为什么改状态要「产出事件」而不是直接拼话术？ |

> 这一遍只求能画出那张树形图。画不出来就别往下读，后面全是它的增删改查。

### 第二遍：静态配置长什么样（约 1 小时）

| 顺序 | 文件 | 读的时候问自己 |
| --- | --- | --- |
| 4 | `flow_config/user_flows.yml` | 一条流程由几个步骤组成？槽位在哪定义？next 怎么写条件跳转？ |
| 5 | `finassist/task/flow/steps.py` | 5 种步骤类型各自带哪些字段？from_dict 怎么按 type 分派？ |
| 6 | `finassist/task/flow/links.py` | 静态/条件/兜底三种连线有什么区别？ |
| 7 | `finassist/task/flow/models.py` | Flow 怎么按 id 找步骤？FlowCatalog 为什么要在启动时缓存？ |
| 8 | `finassist/task/flow/loader.py` | YAML 的键怎么映射成对象字段？ |

> 这一遍要能「把 YAML 翻译成步骤列表」在纸上写出来。

### 第三遍：主干链路（2~3 小时，最重要）

| 顺序 | 文件 | 读的时候问自己 |
| --- | --- | --- |
| 9 | `finassist/api/schemas.py` → `chat_router.py` | 对外字段怎么变成对内模型？ |
| 10 | `finassist/service/dialogue_service.py` | 为什么它只有三步？ |
| 11 | `finassist/engine/dialogue_engine.py` | 会话过期怎么判？文本和对象两条入口差在哪？ |
| 12 | `finassist/plan/turn_planner.py` | 提示词怎么拼？LLM 返回的 JSON 怎么变对象？ |
| 13 | `finassist/plan/turn_plan_validator.py` | 校验哪几件事？为什么必须校验？ |
| 14 | `finassist/task/task_handler.py` | 三个组件为什么是这种顺序？ |
| 15 | `finassist/task/command/command_processor.py` | 命令怎么变成状态变化？set_slots 为什么不产事件？ |
| 16 | `finassist/task/flowexecutor/flow_executor.py` | 五个 isinstance 分支分别做什么？什么时候停下来等用户？ |
| 17 | `finassist/engine/builder.py` | 谁依赖谁？为什么全在这一处 new？ |

> 这一遍读完，你应该能闭着眼睛走完「我要退款」的六步。

### 第四遍：两大分支各自的套路（2 小时）

**任务分支的剩余零件**

- `task/tasklifecycle/task_lifecycle.py`：事件 → 中文，注意它不碰 state
- `task/response/models.py` + `response_render.py`：三种渲染模式的区别
- `task/action/*`：注册表 + 自动扫描 + 三个 custom 实现

**知识分支**

- `knowledge/intents.py`：意图字典（这是整条分支的配置中心）
- `knowledge/registry.py` + `provider.py`：字符串 → 对象 → 取数
- `knowledge/knowledge_handler.py`：五步流程 + 去重
- `knowledge/responder.py`：chunk → 人话

### 第五遍：边角与存疑处（1 小时）

- `clarify/clarify_response.py`、 `chitchat/chit_chat.py`：两个兜底出口
- `repository/` + `utils/` + `conf/`：基础设施
- `mock_business_server.py`：跑起来看真实返回长什么样

---

## 7. 核心概念词典

| 术语 | 含义 | 在哪定义 |
| --- | --- | --- |
| sender_id | 用户唯一标识，一个用户一条状态记录 | `domain/message.py` |
| Turn | 一轮对话：一问 + 一至多答 | `domain/state.py` |
| Session | 会话，60 分钟不活跃就换新的 | `domain/state.py` |
| FocusedObject | 用户当前「指着」的订单/商品，「我这一单」靠它落地 | `domain/state.py` |
| TaskInstance | 一条正在跑的流程实例：flow_id + step_id + slots | `domain/state.py` |
| TaskRef | 任务的轻量引用，只有 id + flow_id | `lifecycle/models.py` |
| TaskEvent | 状态变化的四种说法 | `lifecycle/models.py` |
| Flow | 一条业务流程（YAML 里的一节） | `task/flow/models.py` |
| FlowStep | 流程中的一步，有 5 种类型 | `task/flow/steps.py` |
| Slot | 槽位：流程要收集的一个变量声明；值是存在 TaskInstance.slots 里的 | `task/flow/models.py` |
| Link | 步骤之间的跳转关系 | `task/flow/links.py` |
| Command | LLM 产出的一条业务指令（start_flow 等） | `plan/command.py` |
| TurnPlan | 一轮的完整计划：task / knowledge / chitchat 三选一 | `prompts/models.py` |
| ClarifyReason | 校验失败原因，决定反问话术 | `prompts/models.py` |
| Action | 一个可执行的外部动作（查订单/查物流） | `task/action/base.py` |
| Provider | 一个知识数据源 | `knowledge/provider.py` |
| chunk | 检索回来的一小段数据（dict 或文本） | `knowledge/provider.py` |

---

## 8. 三条贯穿全项目的设计套路

读代码时反复会撞见这三个模式，认出来就一通百通：

### 套路一：命令 / 事件分离

```text
命令(Command)  ──►  CommandProcessor  ──►  改 state  ──►  事件(TaskEvent)
                                                             │
                                                             ▼
                                                   TaskLifecycleResponder
                                                             │
                                                             ▼
                                                        中文提示语
```

好处：状态机可以脱离话术单测；改文案不会碰坏状态。

### 套路二：字符串 → 对象的注册表

YAML 和 LLM 只能给字符串（`action_lookup_order_status`、`product_info`）。
运行时需要一个字典把它们换成对象：

- `task/action/registry.py` + `builder.py`（还会自动扫描 custom/ 包）
- `knowledge/registry.py`（构造时一次性建好）

### 套路三：模板 + 三种渲染模式

流程话术不写死在代码里，全在 YAML：

- `static`：模板渲染完直接用（快、稳定）
- `rephrase`：渲染完交给 LLM 换个说法（自然、但慢且不可控）
- `generate`：完全让 LLM 自由发挥

---
