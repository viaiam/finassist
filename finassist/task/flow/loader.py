"""
流程加载器：把 flow_config/user_flows.yml 翻译成内存里的对象。

■ 它在哪
    engine/builder.py 在启动时调用一次 FlowLoader().load(FLOW_CONFIG_PATH)，
    产出的 FlowCatalog 被塞进 FlowExecutor。之后整个进程都复用这一份。

■ 三步走
    1) read_text 读成字符串 → yaml.safe_load 变成嵌套 dict（此时全是 dict/list，没有类型）
    2) _load_slots：把 dict 的槽位变成 FlowSlot 对象
    3) _load_flows：把 dict 的流程变成 Flow 对象，其中每个 step 靠
       task/flow/steps.py 的 FlowStep.from_dict 按 type 字段挑具体子类

■ ※ 为什么第 3 步要把 slots 传进去？
    YAML 里 collect 步骤只写 slot_name: order_number，
    而告诉 LLM「order_number 是什么」需要 FlowSlot 的 label / description。
    所以在加载期就把 slot 对象塞进步骤里，运行期就不用再查表了。

■ ※ 为什么用 safe_load 而不是 load？
    yaml.load 能构造任意 python 对象（可以执行代码），是安全漏洞；
    safe_load 只认基础类型（dict/list/str/int/bool），配置文件用它才对。

■ 注意
    这里没有任何异常处理，YAML 里少写 slots 或 flows 键会直接 KeyError，
    进程启动就崩。※ 这其实是「快速失败」：配置错了别让它带病上线。
"""
from pathlib import Path
import yaml
from finassist.task.flow.steps import  FlowStep
from finassist.task.flow.models import Flow, FlowCatalog, FlowSlot


class FlowLoader:
    def load(self,path:Path)->FlowCatalog:
        #read_text读取的是字符串
        yaml_text = path.read_text(encoding='utf-8')
        #safe_load将字符串转换为字典
        flow_dict = yaml.safe_load(yaml_text)
        #加载所有槽位数据
        slots:dict[str,FlowSlot] = self._load_slots(flow_dict['slots'])


        #加载所有流程数据
        #_load_flows需要传入所有槽位数据
        flows:dict[str,Flow] = self._load_flows(flow_dict['flows'],slots)


        return FlowCatalog(flows=flows,slots=slots)


    #加载所有槽位数据
    def _load_slots(self,slot_list: dict[str,dict]) -> dict[str,FlowSlot]:
        slots:dict[str,FlowSlot] = {}
        #遍历传入字典
        for slot_name,slot_data in slot_list.items():
            slots[slot_name] = FlowSlot(name=slot_name,**slot_data)
        return slots

    #加载所有流程数据
    def _load_flows(self,flows_data: dict[str,dict],slots:dict[str,FlowSlot]) -> dict[str,Flow]:
        flows:dict[str,Flow] = {}
        #遍历所有流程字典
        for flow_id,flow_data in flows_data.items():
            #封装每个流程槽位数据
            flow_slots:list[FlowSlot] = [slots[step['slot_name']]
                                        for step in flow_data['steps']
                                        if step['type']=='collect']

            #封装每个流程步骤数据
            steps:list[FlowStep] = [FlowStep.from_dict(step) for step in flow_data['steps']]


            flow = Flow(id=flow_id,
                        name=flow_data['name'],
                        description=flow_data['description'],
                        slots=flow_slots,
                        steps=steps)
            flows[flow_id] = flow


        return flows

if __name__ == '__main__':
    loader = FlowLoader()
    path = Path(__file__).parents[3]/"flow_config"/'user_flows.yml'
    print(loader.load(path))
