"""金融咨询意图，供规划器识别并映射到已实现的数据源。"""
from dataclasses import dataclass, field


@dataclass
class KnowledgeIntent:
    id: str
    description: str
    provider_ids: list[str] = field(default_factory=list)
    requires_object: str | None = None


KNOWLEDGE_INTENTS = {
    'loan_product_info': KnowledgeIntent('loan_product_info', '贷款产品、利率、额度范围、期限和还款方式咨询（不是查个人贷款）', ['api.loan_product']),
    'wealth_product_info': KnowledgeIntent('wealth_product_info', '理财产品、风险等级、起购金额与预期收益信息咨询', ['api.wealth_product']),
    'bank_card_info': KnowledgeIntent('bank_card_info', '查询当前客户名下的银行卡类型与状态', ['api.bank_card']),
    'finance_rules': KnowledgeIntent('finance_rules', '风险提示、提前还款、手续费、客服能力介绍，以及尚未支持的贷款申请、基金、信用卡、存款产品或挂失', ['faq.finance']),
}
