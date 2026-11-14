from test_retrieval_applicability import unit


def test_source_quality_does_not_upgrade_verified_text_into_known_standard():
    from standard_knowledge_service_v2.knowledge.source_quality import audit_source_quality
    source = unit('unlabelled', '变压器', '应提供变压器绝缘电阻实测值')
    source.standard_id = '未标注标准'
    source.version = ''
    source.metadata['audit'] = {'status': 'passed_source_grounding', 'manual_review_required': False}
    quality = audit_source_quality(source, source.rules[0])
    assert quality['standard_identity'] == 'missing'
    assert quality['version_status'] == 'missing'
    assert quality['review_required'] is True
    assert quality['formal_citation_ready'] is False


def test_source_quality_retains_raw_qualifications_and_marks_opaque_ids_pending():
    from standard_knowledge_service_v2.knowledge.source_quality import audit_source_quality
    source = unit('scoped', '三相变压器', '三相变压器直流电阻应符合原文要求')
    source.standard_id = 'M33'
    source.metadata['source']['source_text'] += '；适用容量范围见原始表格'
    source.metadata['audit'] = {'manual_review_required': True}
    quality = audit_source_quality(source, source.rules[0])
    assert quality['standard_identity'] == 'unverified'
    assert quality['formal_citation_ready'] is False
    assert quality['source_text'] == source.metadata['source']['source_text']
    assert 'source_scope_requires_review' in quality['issues']
