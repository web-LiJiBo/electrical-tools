"""Check a current observation's literal number/unit before session mutation."""
import re
import unicodedata

from ..decomposition.evidence import CHINESE, NUMBER_PATTERN, number_text


def verify_fact_value(fact, profile, spec, normalize_value, devices=()):
    exact = lambda text: re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text)))
    source = exact(fact['source_text'])
    value_text = exact(fact.get('value_text', ''))
    unit_text = exact(fact.get('unit_text', fact.get('unit', '')))
    # Remove device identities before looking for numeric observations. A device
    # suffix is never evidence that its fault flag or measurement equals 1.
    evidence = source
    aliases = [alias for device in (devices or [profile]) for alias in
               [device['device_id'], device.get('display_name', ''), *device.get('aliases', [])]]
    for alias in sorted(aliases, key=len, reverse=True):
        if alias:
            evidence = re.sub(re.escape(exact(alias)), '', evidence, flags=re.I)
    evidence = re.sub(r'SIM-[A-Z0-9-]+', '', evidence, flags=re.I)
    numeric = spec['type'] in ('integer', 'number')
    literal_boolean = spec['type'] == 'boolean' and value_text in ('0', '1')
    numeric = numeric or literal_boolean
    if not numeric:
        if value_text and value_text not in source:
            raise ValueError('当前状态取值缺少对应原文')
        return {'method': 'typed_semantic', 'value_text': value_text, 'source_text': fact['source_text']}
    if not value_text:
        values = list(re.finditer(NUMBER_PATTERN, evidence))
        if len(values) == 1:
            value_text = values[0][0]
    try:
        raw = number_text(value_text)
        if not value_text or not re.fullmatch(NUMBER_PATTERN, raw):
            raise ValueError('not a numeric observation')
    except ValueError:
        # Existing 0/1 status flags also have ordinary verbal descriptions, such
        # as "没有故障". Keep those on the model's typed semantic path; do not
        # mistake a missing measurement literal for a verbal status flag.
        if (spec['type'] == 'integer' and not spec.get('unit') and not fact.get('unit')
                and type(fact['value']) is int and fact['value'] in (0, 1)
                and (not value_text or value_text in source)
                and not re.search(r'\d', evidence)):
            return {'method': 'typed_status', 'value_text': value_text or evidence,
                    'source_text': fact['source_text']}
        raise ValueError('当前数值须有唯一的原始数字依据，请明确该字段的当前值')
    boundary = r'\d+\-−－＋负正eE' + CHINESE
    suffix = ('(?=' + re.escape(unit_text) + ')') if unit_text else '(?![' + boundary + r'])(?![.,]\d)'
    pattern = '(?<![' + boundary + '])(?<!\\d[.,])' + re.escape(value_text) + suffix
    matches = list(re.finditer(pattern, evidence))
    if not matches:
        raise ValueError('当前数值的原文数字不匹配，设备编号不能作为测量值')
    complete_unit = re.compile(re.escape(unit_text) + r'(?![A-Za-z\dΩ%/^·²³]|小时|时|每)')
    if unit_text and not any(complete_unit.match(evidence[m.end():]) for m in matches):
        raise ValueError('当前数值单位须紧随对应原始数字，不能借用其他值的单位')
    # A written unit cannot be omitted to reinterpret MW as kW. Only fields
    # whose original number has no unit may use their configured default unit.
    from ..application.action_parameters import UNITS
    units = sorted({*UNITS, spec.get('unit', ''), 'A', 'kA', 'mA', 'Ω', '℃', '%'}, key=len, reverse=True)
    if not unit_text and spec.get('unit') and any(
            re.match(r'[A-Za-zΩ℃%]', evidence[m.end():])
            or any(evidence[m.end():].startswith(unit) for unit in units if unit) for m in matches):
        raise ValueError('当前数值包含单位，须保留原始单位进行换算')
    from ..application.action_parameters import _number
    parsed = _number(raw)
    value = int(parsed) if parsed == parsed.to_integral_value() else float(parsed)
    normalized = normalize_value(value, fact.get('unit_text', fact.get('unit', '')), spec)
    supplied = normalize_value(fact['value'], fact.get('unit', ''), spec)
    if supplied != normalized:
        raise ValueError('当前数值与原文数字或单位换算不一致；未更新模拟状态')
    return {'method': 'literal_numeric', 'value_text': value_text, 'unit_text': unit_text,
            'normalized_value': normalized, 'normalized_unit': spec.get('unit', ''),
            'source_text': fact['source_text']}
