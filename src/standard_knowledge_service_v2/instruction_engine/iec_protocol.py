"""Offline IEC 61850 Ed2 MMS control requests and ISO-on-TCP association.

This module generates a *conditional* request plan, never a connected client.
An executor must inspect the indicated peer responses and negotiated limits
before sending the next request.  Concatenated TPKTs inside one request are
COTP segments of that request, not permission to send the whole plan at once.

Wire structures follow the ISO session/presentation and ACSE/MMS mappings
used by libiec61850 (iso_session.c, iso_presentation.c, acse.c and the MMS
Initiate/Read/Write ASN.1 definitions).  BER encoding primitives are shared
with protocol_messages; session lengths deliberately use their own encoding.
"""

import re

from .protocol_messages import (
    boolean, integer, numeric, signed_integer, text, tlv, utc_time,
)


_MODELS = (
    'direct-with-normal-security', 'direct-with-enhanced-security',
    'sbo-with-normal-security', 'sbo-with-enhanced-security',
)
_TPDU_SIZES = (128, 256, 512, 1024, 2048, 4096, 8192)
_APPLICATION_CONTEXT = bytes.fromhex('28ca220203')  # 1.0.9506.2.3
_ACSE_ABSTRACT = bytes.fromhex('52010001')         # 2.2.1.0.1
_MMS_ABSTRACT = bytes.fromhex('28ca220201')         # 1.0.9506.2.1
_BER_TRANSFER = bytes.fromhex('5101')              # 2.1.1
_SERVICE_BITS = {
    'getNameList': 1, 'read': 4, 'write': 5,
    'getVariableAccessAttributes': 6, 'informationReport': 79,
}


def encode_iec_data(value, data_type, value_shape='primitive'):
    """Encode ctlVal according to the declared engineering type, not Python's.

    AnalogueValue is a one-member MMS structure containing i or f.  Primitive
    signed/unsigned values retain their declared type even at positive values.
    """
    if data_type == 'bool':
        if type(value) is not bool:
            raise ValueError('原指令不是布尔值，不能按布尔控制编码')
        encoded = tlv(0x83, b'\xff' if value else b'\x00')
    else:
        raw, scalar = numeric(value, data_type)
        if data_type == 'float32':
            encoded = tlv(0x87, b'\x08' + raw)
        else:
            encoded = tlv(0x86 if data_type.startswith('u') else 0x85,
                          signed_integer(scalar))
    if value_shape == 'analogue':
        if data_type not in ('int16', 'int32', 'float32'):
            raise ValueError('AnalogueValue只允许有符号整数或float32')
        return tlv(0xa2, encoded)
    if value_shape != 'primitive':
        raise ValueError('控制值结构须为primitive或analogue')
    return encoded


def _selector(config, key, maximum):
    value = text(config, key, maximum * 2)
    if len(value) % 2 or not re.fullmatch(r'[0-9a-fA-F]+', value):
        raise ValueError(f'{key}须为连续的十六进制字节')
    raw = bytes.fromhex(value)
    if len(raw) > maximum:
        raise ValueError(f'{key}超出{maximum}字节')
    return raw


def _association(config, values):
    if not isinstance(config, dict):
        raise ValueError('缺少IEC模拟关联配置')
    result = dict(config)
    for key, maximum in (
            ('calling_tsel', 16), ('called_tsel', 16),
            ('calling_ssel', 16), ('called_ssel', 16),
            ('calling_psel', 16), ('called_psel', 16)):
        result[key] = _selector(config, key, maximum)
    for key in ('acse_context_id', 'mms_context_id'):
        result[key] = integer(config, key, 1, 127)
        if result[key] % 2 != 1:
            raise ValueError('表示层上下文标识必须是奇数')
    if result['acse_context_id'] == result['mms_context_id']:
        raise ValueError('ACSE与MMS必须使用不同的表示层上下文')
    result['max_tpdu_size'] = integer(config, 'max_tpdu_size', 128, 8192)
    if result['max_tpdu_size'] not in _TPDU_SIZES:
        raise ValueError('最大TPDU须为128至8192的2次幂')
    result['max_mms_pdu'] = integer(config, 'max_mms_pdu', 64, 2147483647)
    for key in ('outstanding_calling', 'outstanding_called'):
        result[key] = integer(config, key, 1, 32767)
    result['nesting'] = integer(config, 'nesting', 1, 127)
    if integer(values, 'presentation_context_id', 1, 127) != result['mms_context_id']:
        raise ValueError('控制报文上下文必须与关联提议的MMS上下文一致')
    if integer(values, 'max_tpdu_size', 128, 8192) != result['max_tpdu_size']:
        raise ValueError('控制报文最大TPDU必须与关联提议一致')
    services = config.get('services_supported', list(_SERVICE_BITS))
    if not isinstance(services, list) or any(s not in _SERVICE_BITS for s in services):
        raise ValueError('services_supported只能包含已实现的MMS服务')
    if not {'read', 'write'}.issubset(services):
        raise ValueError('控制及读回必须声明read与write服务')
    result['services_supported'] = list(dict.fromkeys(services))
    return result


def _tpkt(tpdu):
    if len(tpdu) + 4 > 65535:
        raise ValueError('TPKT超出65535字节')
    return b'\x03\x00' + (len(tpdu) + 4).to_bytes(2, 'big') + tpdu


def _transport(tsdu, maximum):
    """Segment one TSDU; the TPDU limit includes its three-byte DT header."""
    capacity = maximum - 3
    chunks = [tsdu[n:n + capacity] for n in range(0, len(tsdu), capacity)]
    return b''.join(_tpkt(b'\x02\xf0' + (b'\x80' if n == len(chunks) - 1 else b'\x00') + chunk)
                    for n, chunk in enumerate(chunks)), len(chunks)


def _session_length(size):
    # ISO 8327 LI: 0..254 is one byte; 255 is followed by a uint16.
    if not 0 <= size <= 65535:
        raise ValueError('会话用户数据超出65535字节')
    return bytes([size]) if size < 255 else b'\xff' + size.to_bytes(2, 'big')


def _session_parameter(code, content):
    return bytes([code]) + _session_length(len(content)) + content


def _pdv(context, payload):
    return tlv(0x61, tlv(0x30, tlv(0x02, signed_integer(context)) + tlv(0xa0, payload)))


def _initiate(config):
    bits = bytearray(11)  # ISO 9506 ServicesSupported is 85 bits.
    for service in config['services_supported']:
        bit = _SERVICE_BITS[service]
        bits[bit // 8] |= 0x80 >> (bit % 8)
    detail = (tlv(0x80, b'\x01')       # proposedVersionNumber
              + tlv(0x81, b'\x05\xf1\x00')  # 11-bit ParameterSupportOptions
              + tlv(0x82, b'\x03' + bytes(bits)))
    return tlv(0xa8,
               tlv(0x80, signed_integer(config['max_mms_pdu']))
               + tlv(0x81, signed_integer(config['outstanding_calling']))
               + tlv(0x82, signed_integer(config['outstanding_called']))
               + tlv(0x83, signed_integer(config['nesting'])) + tlv(0xa4, detail))


def _connect(config):
    exponent = config['max_tpdu_size'].bit_length() - 1
    # Source reference 1, destination reference 0 (not known before CC).
    body = (b'\xe0\x00\x00\x00\x01\x00'
            + b'\xc0\x01' + bytes([exponent])
            + bytes([0xc2, len(config['called_tsel'])]) + config['called_tsel']
            + bytes([0xc1, len(config['calling_tsel'])]) + config['calling_tsel'])
    cotp = _tpkt(bytes([len(body)]) + body)
    initiate = _initiate(config)
    # Association-information is an EXTERNAL, not an OCTET STRING.
    aarq = tlv(0x60,
               tlv(0xa1, tlv(0x06, _APPLICATION_CONTEXT))
               + tlv(0xbe, tlv(0x28,
                     tlv(0x02, signed_integer(config['mms_context_id'])) + tlv(0xa0, initiate))))
    contexts = b''
    for context, abstract in ((config['acse_context_id'], _ACSE_ABSTRACT),
                              (config['mms_context_id'], _MMS_ABSTRACT)):
        contexts += tlv(0x30, tlv(0x02, signed_integer(context))
                        + tlv(0x06, abstract) + tlv(0x30, tlv(0x06, _BER_TRANSFER)))
    cp = tlv(0x31,
             tlv(0xa0, tlv(0x80, b'\x01'))
             + tlv(0xa2, tlv(0x81, config['calling_psel'])
                   + tlv(0x82, config['called_psel']) + tlv(0xa4, contexts)
                   + _pdv(config['acse_context_id'], aarq)))
    session = (bytes.fromhex('050613010016010214020002')
               + _session_parameter(0x33, config['calling_ssel'])
               + _session_parameter(0x34, config['called_ssel'])
               + _session_parameter(0xc1, cp))
    cn = b'\x0d' + _session_length(len(session)) + session
    connection, segments = _transport(cn, config['max_tpdu_size'])
    return cotp, connection, segments, initiate


def _object_name(domain, item):
    return tlv(0xa1, tlv(0x1a, domain.encode('ascii')) + tlv(0x1a, item.encode('ascii')))


def _variables(domain, item):
    return tlv(0xa0, tlv(0x30, tlv(0xa0, _object_name(domain, item))))


def _write(invoke, domain, item, data):
    service = tlv(0xa5, _variables(domain, item) + tlv(0xa0, data))
    return tlv(0xa0, tlv(0x02, signed_integer(invoke)) + service)


def _read(invoke, domain, item):
    # Read.variableAccessSpecification is [1] EXPLICIT because its type is
    # CHOICE.  Omitting this A1 wrapper produces an invalid MMS Read request.
    service = tlv(0xa4, tlv(0xa1, _variables(domain, item)))
    return tlv(0xa0, tlv(0x02, signed_integer(invoke)) + service)


def _location(mapping, control=False):
    domain = text(mapping, 'domain_id', 64)
    item = text(mapping, 'item_id', 128)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', domain):
        raise ValueError('MMS domain_id格式不正确')
    if not re.fullmatch(r'[A-Za-z0-9_$]+', item) or '$' not in item:
        raise ValueError('MMS item_id须为LN$FC$对象的完整点位')
    if control and not re.fullmatch(r'[A-Za-z0-9_]+\$CO\$[A-Za-z0-9_$]+\$Oper', item):
        raise ValueError('控制点位须为LN$CO$对象$Oper')
    return domain, item


def _control_data(values, value):
    ctl_value = encode_iec_data(value, text(values, 'data_type'), text(values, 'value_shape'))
    quality = integer(values, 'time_quality', 0, 255)
    if not boolean(values, 'include_oper_time') and values.get('oper_time_utc'):
        raise ValueError('当前控制对象不包含operTm，不能填写计划操作时间')
    if boolean(values, 'include_oper_time'):
        # A declared operTm field stays present even for an immediate command.
        stamp = values.get('oper_time_utc')
        ctl_value += tlv(0x91, b'\x00' * 8 if stamp == '' else utc_time(stamp, quality))
    origin_ident = values.get('origin_ident')
    if not isinstance(origin_ident, str):
        raise ValueError('origin_ident须为文本，可为空')
    try:
        origin = origin_ident.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError('来源标识必须为有效UTF8文本') from exc
    if len(origin) > 64:
        raise ValueError('来源标识UTF8编码不得超过64字节')
    ctl_value += tlv(0xa2,
                     tlv(0x85, signed_integer(integer(values, 'origin_category', 0, 8)))
                     + tlv(0x89, origin))
    if not boolean(values, 'include_ctl_num'):
        raise ValueError('IEC61850 Ed2控制结构必须包含ctlNum')
    ctl_value += tlv(0x86, signed_integer(integer(values, 'ctl_num', 0, 255)))
    ctl_value += tlv(0x91, utc_time(values.get('timestamp_utc'), quality))
    ctl_value += tlv(0x83, b'\xff' if boolean(values, 'test') else b'\x00')
    checks = ((128 if boolean(values, 'synchro_check') else 0)
              | (64 if boolean(values, 'interlock_check') else 0))
    return tlv(0xa2, ctl_value + tlv(0x84, bytes([6, checks]))), tlv(0xa2, ctl_value)


def encode_iec_bundle(values, value, association, feedback_mapping):
    """Build all phases for a configured direct/SBO normal/enhanced control.

    ``bytes`` are actual TPKT/COTP messages. ``requires`` reference request IDs
    whose response gates must succeed first; ``on_cancel`` and ``release``
    are alternative/optional branches. No server response is fabricated.
    """
    if not isinstance(values, dict) or not isinstance(feedback_mapping, dict):
        raise ValueError('缺少IEC控制或反馈映射')
    if not boolean(values, 'structure_confirmed'):
        raise ValueError('控制结构须由明确的设备工程或模拟配置提供')
    model = text(values, 'control_model')
    if model not in _MODELS:
        raise ValueError('不支持的IEC61850控制模型')
    config = _association(association, values)
    domain, item = _location(values, control=True)
    feedback_domain, feedback_item = _location(feedback_mapping)
    invoke = integer(values, 'invoke_id', 0, 4294967295)
    sbo = model.startswith('sbo-')
    enhanced = model.endswith('enhanced-security')
    if enhanced and 'informationReport' not in config['services_supported']:
        raise ValueError('增强安全控制必须声明informationReport以接收命令终结')
    cancel_supported = boolean(values, 'control_cancel_supported')
    count = 2 + int(sbo) + int(cancel_supported)
    if invoke + count - 1 > 4294967295:
        raise ValueError('请求包的invoke_id序列超出MMS Unsigned32范围')
    selection_timeout = integer(values, 'selection_timeout_ms', 1, 2147483647) if sbo else None
    oper_data, cancel_data = _control_data(values, value)
    cotp, connection, segments, initiate = _connect(config)
    public_association = {
        **association, 'services_supported': config['services_supported'],
        'mode': 'simulated-proposal', 'established': False,
        'negotiated': False, 'requires_peer_acceptance': True,
    }
    requests = [{
        'id': 'cotp_connect', 'title': 'COTP连接请求（CR）', 'bytes': cotp,
        'requires': [], 'branch': 'main', 'service': 'COTP CR',
        'expected_response': {
            'service': 'COTP CC', 'tpdu_type': 0xd0, 'destination_reference': 1,
            'require_matching_selectors': True, 'require_class': 0,
            'max_tpdu_size_at_most': config['max_tpdu_size'],
            'on_reject_or_timeout': 'abort',
        },
    }, {
        'id': 'association', 'title': 'Session CN / CP / AARQ / MMS Initiate',
        'bytes': connection, 'segment_count': segments, 'mms_hex': initiate.hex(' '),
        'requires': ['cotp_connect'], 'branch': 'main', 'service': 'MMS Initiate',
        'expected_response': {
            'service': 'Session ACCEPT / CPA / AARE / MMS InitiateResponse',
            'association_established': False,
            'require_session_accept': True, 'require_cpa': True,
            'presentation_context_results': [
                {'context_id': config['acse_context_id'], 'result': 0,
                 'abstract_syntax': '2.2.1.0.1', 'transfer_syntax': '2.1.1'},
                {'context_id': config['mms_context_id'], 'result': 0,
                 'abstract_syntax': '1.0.9506.2.1', 'transfer_syntax': '2.1.1'},
            ],
            'aare_result': 0, 'application_context': '1.0.9506.2.3',
            'require_mms_initiate_response': True, 'mms_version': 1,
            'negotiated_limits_required': ['max_mms_pdu', 'outstanding_calling',
                                           'outstanding_called', 'nesting'],
            'require_read_write_services': True,
            'require_regeneration_if_limits_exceeded': True,
            'on_reject_or_timeout': 'abort',
        },
    }]

    def append_request(request_id, title, mms, requires, expected, branch='main', **extra):
        if len(mms) > config['max_mms_pdu']:
            raise ValueError('生成的MMS PDU超出关联提议的最大长度')
        frame, segment_count = _transport(
            b'\x01\x00\x01\x00' + _pdv(config['mms_context_id'], mms),
            config['max_tpdu_size'])
        request = {
            'id': request_id, 'title': title, 'bytes': frame,
            'requires': requires, 'branch': branch, 'mms_hex': mms.hex(' '),
            'segment_count': segment_count, 'expected_response': expected,
            'presentation_context_id': config['mms_context_id'], **extra,
        }
        requests.append(request)
        return frame

    def response(service, invoke_id):
        return {'service': service, 'invoke_id': invoke_id,
                'require_confirmed_response': True,
                'reject_confirmed_error_or_data_access_error': True,
                'on_reject_or_timeout': 'abort'}

    predecessor = 'association'
    if sbo:
        selector = item[:-4] + ('SBOw' if enhanced else 'SBO')
        expected = response('MMS WriteResponse' if enhanced else 'MMS ReadResponse', invoke)
        expected.update({'selection_must_match_domain': domain,
                         'selection_must_match_item': item[:-5],
                         'selection_must_match_ctl_num': values['ctl_num'],
                         'selection_timeout_ms': selection_timeout})
        if enhanced:
            select_mms = _write(invoke, domain, selector, oper_data)
            expected['access_result'] = 'success'
            expected['require_same_ctlVal_origin_ctlNum_T_Test_Check'] = True
        else:
            select_mms = _read(invoke, domain, selector)
            expected['access_result_type'] = 'visible-string'
            expected['require_nonempty_visible_string'] = True
        append_request('select', 'SBO选择（' + ('SBOw写入' if enhanced else 'SBO读取') + '）',
                       select_mms, ['association'], expected,
                       service='MMS Write / SBOw' if enhanced else 'MMS Read / SBO',
                       domain_id=domain, item_id=selector, invoke_id=invoke)
        invoke += 1
        predecessor = 'select'
    expected_operate = response('MMS WriteResponse', invoke)
    expected_operate.update({'access_result': 'success',
                             'control_model': model, 'execution_confirmed_by_write_alone': False})
    if enhanced:
        expected_operate['require_command_termination'] = {
            'service': 'MMS InformationReport', 'must_match_control_object': item[:-5],
            'must_match_origin_and_ctl_num': True,
            'reject_negative_last_application_error': True,
            'must_receive_positive_termination_before_readback': True,
        }
    else:
        expected_operate['require_status_readback'] = True
    operate = append_request('operate', 'IEC61850 Operate操作',
                             _write(invoke, domain, item, oper_data), [predecessor],
                             expected_operate, service='MMS Write / Oper',
                             domain_id=domain, item_id=item, invoke_id=invoke)
    invoke += 1
    expected_read = response('MMS ReadResponse', invoke)
    expected_read.update({'access_result': 'success', 'data_type': text(feedback_mapping, 'data_type'),
                          'feedback_mapping': dict(feedback_mapping),
                          'compare_using_feedback_semantics': True})
    append_request('readback', '状态或测量值读回', _read(invoke, feedback_domain, feedback_item),
                   ['operate'], expected_read, service='MMS Read',
                   domain_id=feedback_domain, item_id=feedback_item, invoke_id=invoke)
    invoke += 1
    if cancel_supported:
        cancel_item = item[:-4] + 'Cancel'
        expected_cancel = response('MMS WriteResponse', invoke)
        expected_cancel['access_result'] = 'success'
        append_request('cancel', '取消选择或待执行控制',
                       _write(invoke, domain, cancel_item, cancel_data),
                       ['select'] if sbo else ['association'], expected_cancel,
                       branch='on_cancel', service='MMS Write / Cancel',
                       domain_id=domain, item_id=cancel_item, invoke_id=invoke,
                       condition='only_when_selection_or_time_activated_control_is_pending',
                       not_after_command_termination=True)
    append_request('mms_conclude', 'MMS关联结束请求', b'\x8b\x00', ['readback'],
                   {'service': 'MMS ConcludeResponse', 'pdu_tag': 0x8c,
                    'on_conclude_error_or_timeout': 'abort_transport'},
                   branch='release', service='MMS Conclude')
    # ACSE RLRQ(reason=normal) in a Session FINISH.  Transport ownership is
    # released after the peer's Session DISCONNECT/ACSE RLRE response.
    release_data = _pdv(config['acse_context_id'], tlv(0x62, tlv(0x80, b'\x00')))
    finish_body = _session_parameter(0x11, b'\x01') + _session_parameter(0xc1, release_data)
    finish = b'\x09' + _session_length(len(finish_body)) + finish_body
    release_frame, release_segments = _transport(finish, config['max_tpdu_size'])
    requests.append({
        'id': 'association_release', 'title': 'ACSE释放及Session FINISH',
        'bytes': release_frame, 'requires': ['mms_conclude'], 'branch': 'release',
        'service': 'ACSE RLRQ / Session FINISH', 'segment_count': release_segments,
        'expected_response': {'service': 'Session DISCONNECT / ACSE RLRE',
                              'require_orderly_release': True,
                              'then': 'close_transport'},
    })
    return {'requests': requests, 'operate': operate, 'model': model,
            'association': public_association, 'domain_id': domain, 'item_id': item,
            'feedback_mapping': dict(feedback_mapping),
            'scope': 'TPKT/COTP/Session/Presentation/ACSE/MMS完整阶段请求；须按成功响应推进',
            'sent': False, 'established': False}
