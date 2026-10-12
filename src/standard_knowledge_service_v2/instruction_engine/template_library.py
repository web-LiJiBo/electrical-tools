from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstructionTemplate:
    scenario: str
    action: str
    device_type: str
    protocol: str
    required_fields: tuple[str, ...]
    safety_level: str = "high"


class TemplateLibrary:
    """场景/动作/协议检索目录；不存具体点位，也不授予条款来源或下发权限。"""

    def __init__(self) -> None:
        iec_fields = ("device_id", "logical_node", "data_object")
        modbus_fields = ("device_id", "slave_id", "coil_address")
        mappings = {
            "offshore_wind": ["trip", "close", "isolate", "alarm", "limit_power"],
            "substation_maintenance": ["alarm", "isolate", "trip", "close", "lockout", "reset"],
            "grid_fault_isolation": ["alarm", "trip", "isolate", "lockout", "close", "reset", "restore_power"],
            "renewable_grid_integration": [
                "synchronize", "connect_grid", "disconnect_grid", "limit_power", "adjust_active_power",
                "adjust_reactive_power", "regulate_voltage", "alarm", "trip",
            ],
            "power_grid_operation": [
                "issue_dispatch_order", "adjust_active_power", "adjust_reactive_power", "regulate_voltage",
                "start", "stop", "load_shedding", "restore_load", "alarm",
            ],
        }
        self._templates = [
            InstructionTemplate(scenario, action, "", protocol, fields)
            for scenario, actions in mappings.items()
            for action in actions
            for protocol, fields in (("IEC61850", iec_fields), ("Modbus", modbus_fields))
        ]
        self._templates.append(InstructionTemplate('power_grid_operation', 'runback_power', '极控系统', 'IEC61850', iec_fields))
        for device_type in ('cooling_fan', 'oil_pump'):
            for action in ('start', 'stop'):
                for protocol, fields in (('IEC61850', iec_fields), ('Modbus', modbus_fields)):
                    self._templates.append(InstructionTemplate('substation_maintenance', action, device_type, protocol, fields))
        # 启停补足新设备场景；其余动作复用场景通用目录，具体条件/点位由模拟配置提供。
        for scenario, device_type in (('renewable_grid_integration', 'battery_pcs'), ('substation_maintenance', 'capacitor_bank'), ('substation_maintenance', 'ventilation_fan')):
            for action in ('start', 'stop'):
                for protocol, fields in (('IEC61850', iec_fields), ('Modbus', modbus_fields)):
                    self._templates.append(InstructionTemplate(scenario, action, device_type, protocol, fields))

    def find(self, scenario: str, action: str, device_type: str = "", protocol: str = "") -> list[InstructionTemplate]:
        return [item for item in self._templates if item.scenario == scenario and item.action == action and (not protocol or item.protocol.lower() == protocol.lower()) and (not item.device_type or item.device_type == device_type)]
