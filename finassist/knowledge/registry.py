"""
    @Aythor:Bee
    @Time:2026/11/16
    @Desc:provider 注册表。yaml / intents 里写的是字符串，运行时得换成对象。
          和 ActionRegistry 一个套路：构造时一次性建好字典，运行时只查不改。
"""
from finassist.knowledge.provider import KnowledgeProvider


class KnowledgeProviderRegistry:

    def __init__(self, provider_objects: list[KnowledgeProvider]):
        self.providers_dict: dict[str, KnowledgeProvider] = {
            provider.provider_id: provider
            for provider in provider_objects
        }

    def get_provider(self, provider_id: str) -> KnowledgeProvider:
        # 课程代码用 dict.get，取不到返回 None，后面 provider.execute() 直接
        # AttributeError: 'NoneType' 报得莫名其妙。这里直接说清楚"谁没注册"。
        provider = self.providers_dict.get(provider_id)
        if provider is None:
            raise ValueError(
                f"没有注册 provider_id={provider_id} 的 Provider，"
                f"已注册：{sorted(self.providers_dict)}"
            )
        return provider
