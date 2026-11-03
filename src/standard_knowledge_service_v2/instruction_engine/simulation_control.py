"""Legacy read-only simulated inputs. Conversion lives in SimulationRuntime."""
from copy import deepcopy
import re
from threading import RLock
from .simulation import SimulationInstructionService


class SimulationControlSession:
    def __init__(self):
        self.lock = RLock()
        self.service = SimulationInstructionService()
        from .template_editor import load_custom
        # A damaged/obsolete user row is quarantined and reported; it must not
        # make the whole built-in simulation catalogue unavailable.
        load_custom(self.service, strict=False)
        self.template_load_errors = list(getattr(self.service, 'template_load_errors', []))
        self.facts = {key: deepcopy(d.get('runtime_facts', {})) for key, d in self.service.devices.items()}

    def snapshot(self):
        with self.lock:
            return {'simulation_only': True, 'devices': [
                {'device_id': key, 'protocol': device['protocol'], 'device_type': device['device_type'],
                 'state': deepcopy(self.service.states[key]), 'runtime_facts': deepcopy(self.facts[key])}
                for key, device in self.service.devices.items()], 'generation_only': True,
                'template_load_errors': list(self.template_load_errors)}

    @staticmethod
    def is_status_question(query):
        return bool(re.search(r'是否正常|正不正常|状态.*(?:正常|异常)|运行正常', query))
