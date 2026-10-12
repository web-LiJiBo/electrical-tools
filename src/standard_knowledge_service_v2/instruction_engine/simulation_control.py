"""Read-only simulated inputs and source-bound generation. No execution."""
from copy import deepcopy
from dataclasses import asdict
import re
from threading import RLock
from .simulation import SimulationInstructionService
from .models import CandidateInstruction


class SimulationControlSession:
    def __init__(self):
        self.lock = RLock()
        self.service = SimulationInstructionService()
        from .template_editor import load_custom
        load_custom(self.service)
        self.facts = {key: deepcopy(d.get('runtime_facts', {})) for key, d in self.service.devices.items()}

    def snapshot(self):
        with self.lock:
            return {'simulation_only': True, 'devices': [
                {'device_id': key, 'protocol': device['protocol'], 'device_type': device['device_type'],
                 'state': deepcopy(self.service.states[key]), 'runtime_facts': deepcopy(self.facts[key])}
                for key, device in self.service.devices.items()], 'generation_only': True}

    @staticmethod
    def is_status_question(query):
        return bool(re.search(r'是否正常|正不正常|状态.*(?:正常|异常)|运行正常', query))

    def generate_grounded(self, snapshot, semantic, parameters):
        with self.lock:
            key = snapshot['device_id']
            state, facts = deepcopy(self.service.states[key]), deepcopy(self.facts[key])
            decision = self.service.preconditions.evaluate(semantic.condition, facts, semantic.constraints)
            candidate = CandidateInstruction(target=key, evidence=semantic.evidence,
                precondition_status=decision.status.value, precondition_trace=decision.to_dict()['trace'])
            template = self.service.devices[key].get('actions', {}).get(semantic.action, {})
            expected = {template['parameter']} if template.get('parameter') else set()
            if state != snapshot['state'] or facts != snapshot['runtime_facts']:
                candidate.explanation = '生成期间设备输入变化，请重新分析'
            elif semantic.source_rule_id not in template.get('source_rule_ids', []):
                candidate.explanation = '模板没有绑定该来源动作条款'
            elif set(parameters) != expected:
                candidate.explanation = '参数字段不符合动作模板'
            elif decision.status.value != 'pass':
                candidate.explanation = '来源条款前置条件不满足或无法计算，未生成指令'
            else:
                candidate = self.service.generate(key, semantic.action, facts, parameters)
                candidate.evidence = semantic.evidence
                candidate.precondition_trace += decision.to_dict()['trace']
            return {'generation_only': True, 'status': 'generated' if candidate.payload else 'blocked',
                'candidate': asdict(candidate), 'device_id': key, 'action': semantic.action,
                'action_parameters': deepcopy(parameters), 'device_snapshot': deepcopy(snapshot),
                'basis': 'source_bound_model_advice'}
