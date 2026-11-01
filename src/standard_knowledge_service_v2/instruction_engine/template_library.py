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
    """动作/设备/协议检索目录；场景仅保留为兼容提示，不授予下发权限。"""

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
        self._reusable_types = {
            'transformer': (), 'breaker': ('trip', 'close', 'alarm'),
            'disconnector': ('open', 'close'), 'earthing_switch': ('open', 'close'),
            'cooling_fan': ('start', 'stop'), 'oil_pump': ('start', 'stop'),
            'tap_changer': ('raise', 'lower', 'set_tap'),
            'inverter': ('adjust_active_power', 'adjust_reactive_power', 'regulate_voltage'),
            'battery_pcs': ('start', 'stop', 'alarm', 'adjust_active_power', 'limit_power'),
            'capacitor_bank': ('start', 'stop', 'alarm'),
            'ventilation_fan': ('start', 'stop', 'alarm'),
            'pole_controller': ('runback_power',),
        }
        for device_type, actions in self._reusable_types.items():
            for action in actions:
                for protocol, fields in (('IEC61850', iec_fields), ('Modbus', modbus_fields)):
                    if not any(t.action == action and t.device_type == device_type and t.protocol == protocol for t in self._templates):
                        self._templates.append(InstructionTemplate('', action, device_type, protocol, fields))

    def find(self, scenario: str, action: str, device_type: str = "", protocol: str = "") -> list[InstructionTemplate]:
        return [item for item in self._templates if item.action == action
                and (not protocol or item.protocol.lower() == protocol.lower())
                and (item.device_type == device_type if device_type in self._reusable_types
                     else not item.device_type or item.device_type == device_type)]
