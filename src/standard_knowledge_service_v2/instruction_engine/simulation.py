"""隔离的协议字段模拟：没有网络客户端，不接入真实数据或设备。

配置中的对象、点号和阈值全部是测试预设，不构成现场控制依据。
IEC输出为服务参数示意；Modbus PDU示例不包含RTU/TCP传输封装。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path

from .models import CandidateInstruction
from .preconditions import ActionPreconditionEvaluator


DEFAULT_PROFILES = Path(__file__).resolve().parents[3] / "configs" / "simulation_devices.json"

class SimulationInstructionService:
    """预置设备的确定性载荷生成器，不读取用户模板或执行设备动作。

    默认配置合并原库与补充库；应用会话另由load_custom加载用户动作。
    显式非默认配置独立使用，便于隔离实验，不静默掺入额外设备。
    """

    def __init__(self, profile_path: str | Path = DEFAULT_PROFILES) -> None:
        paths = [Path(profile_path)]
        if Path(profile_path).resolve() == DEFAULT_PROFILES.resolve():
            # 补充文件随默认部署提供；缺失或设备ID冲突时拒绝启动，而非覆盖原库。
            paths.append(DEFAULT_PROFILES.with_name('simulation_devices_supplement.json'))
        self.devices = {}
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("simulation_only") is not True:
                raise ValueError("只允许加载simulation_only=true的模拟配置")
            for device in data["devices"]:
                identifier = device["device_id"]
                if not identifier.startswith("SIM-") or identifier in self.devices:
                    raise ValueError("模拟设备ID必须唯一且以SIM-开头")
                self.devices[identifier] = device
        self.states = {key: deepcopy(value["initial_state"]) for key, value in self.devices.items()}
        self.preconditions = ActionPreconditionEvaluator()

    def generate(self, device_id: str, action: str, facts: dict | None = None,
                 parameters: dict | None = None, *, scenario: str | None = None) -> CandidateInstruction:
        """用显式事实测试模板，返回解释对象；只有非空payload表示生成成功。

        此直接测试入口不核验条款授权；条款建议链由generate_grounded另行
        验证来源绑定。本方法只生成字段，从不修改states。
        """
        candidate = CandidateInstruction(target=device_id, dispatch_allowed=False)
        device = self.devices.get(device_id)
        if not device:
            candidate.missing_fields = ["simulation_device"]
            candidate.explanation = "未知模拟设备；不接受真实设备标识"
            return candidate
        candidate.protocol = device["protocol"]
        template = device["actions"].get(action)
        if not template or (scenario is not None and scenario != device["scenario"]):
            candidate.missing_fields = ["simulation_template"]
            candidate.explanation = "场景或动作与模拟设备模板不匹配"
            return candidate
        decision = self.preconditions.evaluate(template["condition"], facts, template.get('constraints'))
        candidate.precondition_status = decision.status.value
        candidate.precondition_trace = decision.to_dict()["trace"]
        if candidate.precondition_status != "pass":
            candidate.explanation = "测试前置条件不满足或事实不完整；不生成载荷"
            return candidate
        parameters = parameters or {}
        parameter = template.get("parameter")
        if set(parameters) != ({parameter} if parameter else set()):
            candidate.missing_fields = ["template_parameter_fields"]
            candidate.explanation = "参数字段与动作模板不一致"
            return candidate
        value = parameters.get(parameter) if parameter else template.get("value")
        if parameter and (isinstance(value, bool) or not isinstance(value, (int, float))
                          or not math.isfinite(value)
                          or not template["minimum"] <= value <= template["maximum"]):
            candidate.missing_fields = [f"valid_parameter:{parameter}"]
            candidate.explanation = "动作参数缺失、类型无效或超出模拟范围"
            return candidate
        configured_fact = template.get('configured_parameter_fact')
        if configured_fact and (not facts or type(facts.get(configured_fact)) not in (int, float)
                                or not math.isfinite(facts[configured_fact]) or value != facts[configured_fact]):
            candidate.explanation = '参数不等于已配置的模拟回降定值，禁止模型另造数值'
            return candidate
        if template.get('decrease_only'):
            current = self.states[device_id].get(template['current_state_key'])
            if type(current) not in (int, float) or not math.isfinite(current) or not value < current:
                candidate.explanation = '功率回降目标必须低于当前模拟功率'
                return candidate
        mapping = {**device["mapping"], **template.get("mapping", {})}
        common = {"simulation_only": True, "template_version": "1.1",
                  "template_id": f"{device_id}:{action}", "unit": template.get("unit", ""),
                  "source": "synthetic_test_fixture", "scenario": device["scenario"],
                  "function": template["function"], "device_type": device["device_type"],
                  "requested_action": action, "engineering_value": value,
                  "source_rule_ids": template.get("source_rule_ids", []),
                  "source_scope": template.get("source_scope", "synthetic_test_fixture")}
        if device["protocol"] == "IEC61850":
            required = ("object_reference", "control_model", "service")
            candidate.missing_fields = [key for key in required if not mapping.get(key)]
            if candidate.missing_fields:
                candidate.explanation = "模拟IEC配置缺失；不生成载荷"
                return candidate
            payload = {**common, **{key: mapping[key] for key in required}, "ctlVal": value}
        elif device["protocol"] == "Modbus":
            slave, address, code = (mapping.get(key) for key in ("slave_id", "address", "function_code"))
            if (type(slave) is not int or not 1 <= slave <= 247 or type(address) is not int
                    or not 0 <= address <= 65535 or type(code) is not int or code not in (5, 6)):
                candidate.missing_fields = ["valid_modbus_mapping"]
                candidate.explanation = "模拟Modbus映射无效或功能码未支持"
                return candidate
            if code == 5:
                if mapping.get("data_type") != "bool" or type(value) is not bool:
                    candidate.missing_fields = ["boolean_coil_value"]
                    return candidate
                encoded = 0xFF00 if value else 0
            else:
                scale = mapping.get("scale")
                if (mapping.get("data_type") != "uint16" or type(scale) not in (int, float)
                        or not math.isfinite(scale) or scale <= 0 or type(value) not in (int, float)):
                    candidate.missing_fields = ["uint16_encoding"]
                    return candidate
                raw = value * scale
                if not math.isfinite(raw) or not 0 <= raw <= 65535 or not math.isclose(raw, round(raw), abs_tol=1e-8, rel_tol=0):
                    candidate.missing_fields = ["exact_uint16_value"]
                    candidate.explanation = "参数无法按模拟倍率无损编码为uint16"
                    return candidate
                encoded = round(raw)
            pdu = bytes([code]) + address.to_bytes(2, "big") + encoded.to_bytes(2, "big")
            payload = {**common, "transport": "SIMULATED", "slave_id": slave,
                       "function_code": code, "address": address, "encoded_value": encoded,
                       "pdu_hex": pdu.hex(" ")}
        else:
            candidate.missing_fields = ["supported_simulation_protocol"]
            return candidate
        candidate.payload = payload
        candidate.explanation = "仅生成协议字段示例，不执行或改变设备状态"
        return candidate



def main():
    service = SimulationInstructionService()
    candidate = service.generate('SIM-IEC-VALVE-01', 'runback_power', service.devices['SIM-IEC-VALVE-01']['runtime_facts'], {'target_power_mw': 80})
    print(json.dumps(asdict(candidate), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
