"""
全局唯一的 LLM 客户端。

■ 它在哪
    被 plan/turn_planner.py、plan/turn_plan_validator.py、
    task/response/response_render.py、knowledge/responder.py、
    clarify/clarify_response.py、chitchat/chit_chat.py 直接 import 使用。

■ ※ 为什么在模块级就创建好（import 时就执行）？
    1) init_chat_model 内部会建连接池、读环境，属于「重」操作，做一次就够；
    2) 全项目共用一个实例，便于统一换模型 / 统一加回调打日志；
    3) python 的模块只会被执行一次，天然就是单例，不需要自己写单例模式。

■ 参数含义
    model           模型名，来自 .env 的 LLM_MODEL（如 deepseek-chat / gpt-4o-mini）
    model_provider  固定写 "openai"：只要对方兼容 OpenAI 协议就都走这条分支
                    （DeepSeek、通义、vLLM、Ollama 的 /v1 接口都算）
    api_key         密钥，来自 .env 的 llm_api_key
    base_url        接口地址，来自 .env 的 llm_base_url
                    ※ 这一项是「换供应商不改代码」的关键：换模型只改 .env。

■ 注意
    返回类型标注为 BaseChatModel，调用方式是 llm.invoke(...) / await llm.ainvoke(...)。
    项目里几乎都用 ainvoke（异步），因为整条链路是 async 的，用同步 invoke 会阻塞事件循环。
"""
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from finassist.conf.config import settings

llm:BaseChatModel  = init_chat_model(
    model=settings.LLM_MODEL,
    model_provider="openai",
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
)

if __name__ == "__main__":
    print(llm.invoke("hello").content)