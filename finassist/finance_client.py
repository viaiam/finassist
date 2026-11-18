"""客服访问金融中台的统一入口：超时、失败和空数据统一转为可读提示。"""
from urllib.parse import quote
import httpx
from finassist.conf.config import settings
from finassist.utils import httpx_client


class FinanceQueryError(Exception):
    """可直接反馈给用户的金融查询错误。"""


def customer_path(customer_no):
    return '/finance/customers/' + quote(str(customer_no), safe='')


async def get_finance(path, params=None):
    for attempt in range(2):
        try:
            response = await httpx_client.http_client.get(
                settings.business_api_base_url + path, params=params, timeout=10)
            if response.status_code >= 500 and attempt == 0:
                continue
            if response.is_error:
                try:
                    detail = response.json().get('detail')
                except ValueError:
                    detail = None
                if response.status_code == 404 and isinstance(detail, str):
                    raise FinanceQueryError(detail)
                if response.status_code == 422:
                    raise FinanceQueryError('查询条件格式不正确，请使用完整业务编号和 YYYY-MM-DD 日期。')
                raise FinanceQueryError('金融数据服务暂不可用，请稍后重试。')
            payload = response.json()
            if payload.get('code') != 0 or payload.get('data') is None:
                raise FinanceQueryError('金融数据返回异常，请稍后重试。')
            return payload['data']
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt:
                raise FinanceQueryError('金融服务连接超时，请稍后重试。') from exc
        except ValueError as exc:
            raise FinanceQueryError('金融数据返回格式异常，请稍后重试。') from exc


async def post_finance(path, payload):
    """提交金融写操作；业务校验错误转换为安全提示，不自动重复提交。"""
    try:
        response = await httpx_client.http_client.post(
            settings.business_api_base_url + path, json=payload, timeout=10)
        if response.is_error:
            try:
                detail = response.json().get('detail')
            except ValueError:
                detail = None
            if response.status_code in (404, 409) and isinstance(detail, str):
                raise FinanceQueryError(detail)
            if response.status_code == 422:
                raise FinanceQueryError('投诉信息不完整或格式不正确，请重新提供。')
            raise FinanceQueryError('工单服务暂不可用，请稍后重试。')
        payload = response.json()
        if payload.get('code') != 0 or payload.get('data') is None:
            raise FinanceQueryError('工单提交结果异常，请稍后查询工单状态。')
        return payload['data']
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise FinanceQueryError('工单服务连接超时，请稍后重试；请勿重复提交新的投诉。') from exc
    except ValueError as exc:
        raise FinanceQueryError('工单服务返回格式异常，请稍后查询工单状态。') from exc
