"""验证迁移后的导入、动态动作注册和接口契约，不调用真实模型或数据库。"""
import ast
import importlib
import os
from pathlib import Path
import pkgutil
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # 独立进程内使用虚拟配置，避免验证脚本接触本机密钥或连接生产资源。
    os.environ.update({
        'FINASSIST_LLM_MODEL': 'migration-check',
        'FINASSIST_LLM_API_KEY': 'migration-check',
        'FINASSIST_LLM_BASE_URL': 'http://127.0.0.1:1/v1',
        'FINASSIST_DATABASE_URL': 'mysql+aiomysql://check:check@127.0.0.1:1/finassist',
        'FINASSIST_BUSINESS_API_BASE_URL': 'http://127.0.0.1:1',
    })
    ignored = {'.git', '.venv', '.idea', '__pycache__', 'node_modules', 'dist'}
    # 分段构造旧标识，避免检查规则自身被误认为遗留品牌。
    legacy = re.compile('|'.join(['at' + 'guigu', 'dian_shang_' + 'xiao_er',
                                 'dianshang' + 'xiaoer', 'e' + 'commerce']), re.I)
    count = 0
    for path in ROOT.rglob('*'):
        if not path.is_file() or any(p in ignored for p in path.relative_to(ROOT).parts):
            continue
        if path.name == '.env' or path.name == 'migration-manifest.json':
            continue
        if path.suffix in {'.py', '.js', '.vue', '.html', '.json', '.toml', '.lock', '.yml', '.jinja2', '.md'}:
            content = path.read_text(encoding='utf-8-sig')
            assert not legacy.search(content), f'旧标识残留：{path}'
            assert not legacy.search(path.name), f'旧文件名残留：{path}'
            if path.suffix == '.py':
                ast.parse(content, filename=str(path))
                count += 1

    import finassist
    # 扫描导入可以发现普通 import 及动态注册字符串改名不完整的问题。
    modules = list(pkgutil.walk_packages(finassist.__path__, 'finassist.'))
    for module in modules:
        importlib.import_module(module.name)
    from finassist.engine.builder import build_engine
    from finassist.api.app import app
    from finassist.task.flow.loader import FlowLoader
    from finassist.task.action.builder import register_custom_action
    from finassist.task.action.registry import ActionRegistry
    catalog = FlowLoader().load(ROOT / 'flow_config/user_flows.yml')
    assert catalog.flows and catalog.slots
    registry = ActionRegistry()
    register_custom_action(registry)
    # YAML 中的每个动作必须能从新包名下找到实现。
    from finassist.task.flow.steps import ActionFlowStep
    for flow in catalog.flows.values():
        for step in flow.steps:
            if isinstance(step, ActionFlowStep):
                registry.get_action(step.action)
    assert build_engine() is not None
    schema = app.openapi()
    assert schema['info']['title'] == '融知 FinAssist 客服服务'
    assert '/api/chat' in schema['paths']
    assert '/api/chat/history' in schema['paths']
    # 通过依赖替身验证真实 HTTP 路由和消息转换，不访问模型及数据库。
    from fastapi.testclient import TestClient
    from finassist.api.dependencies import get_dialogue_service, get_repository
    from finassist.domain.message import ProcessResult, BotMessage, MessageType
    from finassist.domain.state import DialogueState

    class FakeService:
        async def run(self, message):
            assert message.sender_id == 'migration-user'
            if message.type == MessageType.OBJECT:
                assert message.object.id == 'A1001'
            return ProcessResult(message.sender_id, message.message_id,
                                 [BotMessage(text='融知迁移验证')])

    class FakeRepository:
        async def load_state(self, sender_id):
            return DialogueState(sender_id=sender_id)

    app.dependency_overrides[get_dialogue_service] = lambda: FakeService()
    app.dependency_overrides[get_repository] = lambda: FakeRepository()
    try:
        # 不进入 lifespan，避免创建真实外部资源；仅检查路由及转换契约。
        client = TestClient(app)
        for payload in ({'text': '你好'}, {'object': {'type': 'order', 'id': 'A1001'}}):
            response = client.post('/api/chat', json={
                'sender_id': 'migration-user', 'message_id': 'migration-message', **payload})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body['message_id'] == 'migration-message'
            assert body['messages'][0]['text'] == '融知迁移验证'
        history = client.get('/api/chat/history', params={'sender_id': 'migration-user'})
        assert history.status_code == 200
        assert history.json()['messages'] == []
    finally:
        app.dependency_overrides.clear()
    print('PASS：文本消息、对象卡片及历史接口契约（使用依赖替身）')
    print(f'PASS：{count} 个 Python 文件语法、{len(modules)} 个模块导入、旧标识检查')
    print(f'PASS：{len(catalog.flows)} 条流程、动态动作注册、引擎装配与接口文档')


if __name__ == '__main__':
    main()
