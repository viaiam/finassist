"""金融知识取数：查询已有产品和银行卡数据；规则只返回可核实的说明。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from finassist.finance_client import get_finance, customer_path, FinanceQueryError


@dataclass
class KnowledgeChunk:
    content: str = ''


class KnowledgeError(Exception):
    """知识检索的可读错误。"""


class KnowledgeProvider(ABC):
    provider_id = ''

    @abstractmethod
    async def execute(self, state, user_message):
        pass


async def retrieve(path, params=None):
    try:
        data = await get_finance(path, params)
    except FinanceQueryError as exc:
        raise KnowledgeError(str(exc)) from exc
    return [KnowledgeChunk(json.dumps(data, ensure_ascii=False))]


class LoanProductProvider(KnowledgeProvider):
    provider_id = 'api.loan_product'

    async def execute(self, state, user_message):
        params = {'kind': 'loan'}
        obj = state.shared.focused_object
        if obj and obj.type == 'loan_product':
            params['code'] = obj.id
        return await retrieve('/finance/products', params)


class WealthProductProvider(KnowledgeProvider):
    provider_id = 'api.wealth_product'

    async def execute(self, state, user_message):
        params = {'kind': 'wealth'}
        obj = state.shared.focused_object
        if obj and obj.type == 'wealth_product':
            params['code'] = obj.id
        return await retrieve('/finance/products', params)


class BankCardProvider(KnowledgeProvider):
    provider_id = 'api.bank_card'

    async def execute(self, state, user_message):
        try:
            data = await get_finance(customer_path(state.sender_id) + '/objects')
        except FinanceQueryError as exc:
            raise KnowledgeError(str(exc)) from exc
        return [KnowledgeChunk(json.dumps({'cards': data['cards'],
            'notice': '仅展示当前样例客户名下银行卡信息，不代表已接通信用卡账单或挂失服务。'}, ensure_ascii=False))]


class FAQProvider(KnowledgeProvider):
    provider_id = 'faq.finance'

    async def execute(self, state, user_message):
        # 没有正式业务规则文档时，不用常识冒充本行政策。
        return [KnowledgeChunk('''融知金融客服能力说明：
当前可查询账户余额及冻结金额、银行卡列表、按自然日或最近交易流水、贷款状态和还款计划；
可咨询样例库中的贷款、理财产品。所有产品和客户均为合成样例。
贷款申请、信用卡挂失和支付转账尚未接入，不得声称已办理或已转人工。投诉请走 complaint_ticket 流程。
未接入基金、信用卡账单和独立存款产品数据，不能编造这些产品信息。
账户产品不等于存款产品。银行卡表不等于独立信用卡授信和账单系统。
提前还款、手续费、审核时效等规则未接入正式文档，应说明需要以实际合同及机构规则为准。
产品利率来自查询数据，小数 0.03 对应 3%；理财预期收益不是承诺收益，不保证本金或收益。
不索取登录密码、支付密码、短信验证码。仅提供资料说明，不做个人适当性判断或个性化投资建议。
目前是本地演示，没有登录鉴权，客户编号仅用于样例数据隔离，不可用于真实金融客户服务。''')]
