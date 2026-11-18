"""
prompts/loader.py —— 按名字读取提示词模板文件

■ 它是什么
    一行代码的「模板读取器」：给一个名字，返回 prompts/jinja2/名字.jinja2 的内容。

■ 在调用链中的位置
    plan/turn_planner.py        load_prompt('turn_plan')
    clarify/clarify_response.py  load_prompt('clarify_respond')
    knowledge/responder.py       load_prompt('knowledge_respond')
    chitchat/chit_chat.py        load_prompt('chitchat_respond')

■ 两种加载方式别混了（初学者常混）
    · 提示词（本文件）：整段文本**只渲染一次**，用 jinja2.Template(text).render(...) 或
      直接 .format 风格拼接，产物是发给 LLM 的字符串；
    · 流程话术（task/response/response_render.py）：来自 YAML 而不是这里的文件，
      同样是 jinja2，但每轮都可能按新 slots 重渲染。

■ 注意
    这里没有缓存：每次调用都读盘。模板文件很小、调用频率也低（一轮一次），
    所以没做缓存；若要优化，可以加个 lru_cache 或启动时预加载。
"""
from pathlib import Path


def load_prompt(name: str) -> str:
    file = Path(__file__).parent / 'jinja2' / f'{name}.jinja2'
    return file.read_text(encoding='utf-8')
