"""Source provenance is separate from lexical relevance and semantic extraction QA.

No standard identity, version, current validity, or numerical threshold is inferred.
"""
import re


def audit_source_quality(unit, rule) -> dict:
    metadata = unit.metadata
    source = metadata.get('source', {})
    provenance = metadata.get('standard_metadata', {})
    audit = metadata.get('audit', {})
    identifier = str(unit.standard_id or '').strip()
    missing = identifier in ('', '未标注标准', '未知标准', '（无）', '(无)')
    opaque = bool(re.fullmatch(r'[A-Za-z]?\d+', identifier))
    confirmed = provenance.get('identity_status') in ('filename_confirmed', 'official_code_change', 'identity_confirmed')
    identity = 'missing' if missing else 'unverified' if opaque or not confirmed else 'source_confirmed'
    version_status = 'present' if unit.version else 'missing'
    source_text = str(source.get('source_text') or '')
    issues = []
    if identity != 'source_confirmed':
        issues.append('standard_identity_' + identity)
    if not unit.version:
        issues.append('version_missing')
    if not source_text:
        issues.append('original_source_text_missing')
    elif re.sub(r'\s+', '', source_text) != re.sub(r'\s+', '', rule.content):
        # A short extracted rule may omit capacity, voltage or table qualifications.
        # Keep the whole original source visible without inventing those qualifiers.
        issues.append('source_scope_requires_review')
    if audit.get('manual_review_required') is True:
        issues.append('semantic_manual_review_required')
    if provenance.get('identity_status') == 'identity_conflict':
        issues.append('source_identity_conflict')
    return {'standard_identity': identity, 'version_status': version_status,
            'current_validity': provenance.get('current_validity', 'unverified'),
            'review_required': bool(issues), 'formal_citation_ready': not issues,
            'issues': issues, 'source_text': source_text,
            'source_location': source or metadata.get('source_location', {}),
            'notice': '原文可追溯不代表标准编号、版本、现行性或设备适用范围已经确认'}
