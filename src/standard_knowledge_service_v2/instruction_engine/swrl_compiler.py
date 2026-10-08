from __future__ import annotations

from .models import SemanticTuple


class SwrlCompiler:
    """将语义元组映射到受控SWRL模板，不允许模型自由生成谓词结构。"""

    _OPERATORS = {
        "<": "swrlb:lessThan",
        "<=": "swrlb:lessThanOrEqual",
        "=": "swrlb:equal",
        ">=": "swrlb:greaterThanOrEqual",
        ">": "swrlb:greaterThan",
        "!=": "swrlb:notEqual",
    }

    @staticmethod
    def _symbol(value: object, fallback: str) -> str:
        text = str(value or fallback).strip().replace(" ", "_")
        return "".join(char if char.isalnum() or char in "_-" else "_" for char in text)

    def compile(self, semantic: SemanticTuple) -> str:
        subject = self._symbol(semantic.subject, "Subject")
        target = self._symbol(semantic.target, "Target")
        action = self._symbol(semantic.action, "RequiredAction")
        antecedents = [f"StandardSubject(?x, {subject})"]
        if semantic.condition:
            antecedents.append(f"ConditionText(?x, {self._symbol(semantic.condition, 'Condition')})")
        for index, item in enumerate(semantic.constraints):
            parameter = self._symbol(item.get("parameter"), f"parameter_{index}")
            value = self._symbol(item.get("value"), f"value_{index}")
            variable = f"?v{index}"
            antecedents.append(f"hasParameter(?x, {parameter}, {variable})")
            operator = self._OPERATORS.get(str(item.get("operator", "")).strip())
            if operator:
                antecedents.append(f"{operator}({variable}, {value})")
            else:
                antecedents.append(f"ConstraintText(?x, {value})")
        return f"{' ^ '.join(antecedents)} -> RequiresAction(?x, {action}, {target})"

    def compile_if_then(self, semantic: SemanticTuple) -> str:
        condition = semantic.condition or "前置条件满足"
        constraints = "; ".join(
            f"{item.get('parameter') or '参数'} {item.get('operator') or ''} {item.get('value')} {item.get('unit') or ''}".strip()
            for item in semantic.constraints
        )
        premise = " AND ".join(item for item in (condition, constraints) if item)
        return f"IF {premise} THEN {semantic.subject} {semantic.action} {semantic.target}"
