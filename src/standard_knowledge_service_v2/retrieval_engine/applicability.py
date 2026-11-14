"""Conservative topic/device mismatch filters, never a grant of applicability.

These filters only remove explicit conflicts. Surviving candidates still need
source and semantic review, especially for capacity, voltage and operating state.
"""
import re


_DEVICE_PATTERNS = {
    'tap_changer': re.compile(r'有载分接开关|分接开关|分接头'),
    'cable': re.compile(r'电缆'),
    'transformer': re.compile(r'变压器|主变'),
    'breaker': re.compile(r'断路器'),
    'reactor': re.compile(r'电抗器'),
    'fan': re.compile(r'冷却风机|风机'),
    'pump': re.compile(r'冷却水泵|水泵|油泵'),
    'motor': re.compile(r'电动机|电机'),
}
_TOPIC_PATTERNS = {
    'insulation_resistance': re.compile(r'绝缘电阻'),
    'dc_resistance': re.compile(r'直流电阻|绕组电阻'),
    'insulating_oil': re.compile(r'绝缘油|油试验|油质|油中溶解气体|色谱|击穿电压'),
}
_MAINTENANCE = re.compile(r'检修后|检修.*(?:恢复|送电)|恢复送电')
_FACTORY = re.compile(r'出厂前|出厂试验|出厂检验|制造厂内|新安装|新装时|安装交接')


def _families(text):
    return {name for name, pattern in _DEVICE_PATTERNS.items()
            if pattern.search(text) or re.search(r'(?<![A-Za-z_])' + name + r'(?![A-Za-z_])', text, re.IGNORECASE)}


def query_applicability(query, parsed):
    # Prefer the explicit target from structured data. An owner mentioned in
    # "transformer cooling fan" does not turn a fan question into transformer QA.
    entities = [str(item.get('name', '')) for item in parsed.get('entities', [])
                if isinstance(item, dict) and ('设备' in str(item.get('type', ''))
                    or str(item.get('type', '')).lower() in _DEVICE_PATTERNS)]
    target = ' '.join(entities) or str(parsed.get('context_device_type') or query)
    families = _families(target)
    if families & {'fan', 'pump', 'tap_changer'}:
        families.discard('transformer')
    topics = {name for name, pattern in _TOPIC_PATTERNS.items()
              if pattern.search(query + ' ' + ' '.join(str(x) for x in parsed.get('keywords', [])))}
    return families, topics, bool(_MAINTENANCE.search(query))


def source_applicability(rule, unit):
    # Rule subject is stronger than an incidental mention/whole-unit entity.
    subject_families = _families(rule.subject)
    source = str(unit.metadata.get('source', {}).get('source_text') or rule.content)
    content_families = _families(rule.content)
    if subject_families & {'fan', 'pump', 'tap_changer'}:
        subject_families.discard('transformer')
    if not subject_families and content_families & {'tap_changer'}:
        content_families.discard('transformer')
    return (subject_families or content_families,
            {name for name, pattern in _TOPIC_PATTERNS.items() if pattern.search(rule.content)},
            bool(_FACTORY.search(rule.content + ' ' + rule.condition + ' ' + source))
            and not bool(_MAINTENANCE.search(source)))


def rejection_reason(query_scope, source_scope):
    requested_devices, requested_topics, maintenance = query_scope
    devices, topics, factory_only = source_scope
    if requested_devices and devices and requested_devices.isdisjoint(devices):
        return 'device_mismatch'
    if requested_devices and requested_topics and not devices:
        return 'device_scope_unverified'
    if requested_topics and requested_topics.isdisjoint(topics):
        return 'topic_mismatch'
    if maintenance and factory_only:
        return 'operating_context_mismatch'
    return ''
