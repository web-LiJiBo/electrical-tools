"""Offline protocol encoding for a server-owned preview. Never opens a socket.

Modbus: TCP ADU, FC05/06/16. IEC61850: Ed2 Operate over MMS Write,
with an ISO-on-TCP data envelope for an already negotiated association.
The small BER encoder is original; protocol structure is documented in the
Modbus specifications and IEC61850/MMS control service mappings.
"""
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import ipaddress
import math
import re
import struct


def integer(values, key, low, high):
    value = values.get(key)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{key}须为{low}至{high}的整数')
    return value


def boolean(values, key):
    if type(values.get(key)) is not bool:
        raise ValueError(f'{key}须为布尔值')
    return values[key]


def text(values, key, maximum=128):
    value = values.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{key}须为1至{maximum}个字符的文本')
    return value.strip()


def endpoint(values):
    host = text(values, 'host', 253)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
            raise ValueError('通信地址须为IP或主机名，不能包含URL、路径或端口')
        if any(not part or len(part) > 63 or part.startswith('-') or part.endswith('-') for part in host.split('.')):
            raise ValueError('主机名格式不正确')
    return {'host': host, 'port': integer(values, 'port', 1, 65535)}


def defaults(candidate, profile, action):
    payload = candidate['payload']
    template = profile['actions'][action]
    if template.get('wire_profile_missing_fields'):
        raise ValueError('动作协议配置不完整：' + '、'.join(template['wire_profile_missing_fields']))
    mapping = {**profile.get('mapping', {}), **template.get('mapping', {})}
    communication = profile.get('communication', {})
    common = {'host': communication.get('host', ''),
              'port': communication.get('port', 502 if candidate['protocol'] == 'Modbus' else 102)}
    if candidate['protocol'] == 'Modbus':
        return {**common, 'unit_id': mapping.get('slave_id'), 'transaction_id': 1,
                'address': mapping.get('address'), 'function_code': mapping.get('function_code'),
                'data_type': mapping.get('data_type'), 'scale': mapping.get('scale', 1),
                'byte_order': mapping.get('byte_order', 'big'), 'word_order': mapping.get('word_order', 'big')}
    if candidate['protocol'] != 'IEC61850':
        raise ValueError('当前仅支持Modbus TCP与IEC61850 MMS报文生成')
    association = communication.get('association', {})
    return {**common, 'domain_id': mapping.get('domain_id', ''), 'item_id': mapping.get('item_id', ''),
            'control_model': mapping.get('control_model'), 'data_type': mapping.get('data_type'),
            'value_shape': mapping.get('value_shape'), 'invoke_id': 1,
            'presentation_context_id': association.get('mms_context_id'),
            'max_tpdu_size': association.get('max_tpdu_size'),
            'origin_category': 3, 'origin_ident': 'electrical-tools-simulation', 'ctl_num': 1,
            'include_ctl_num': mapping.get('include_ctl_num'),
            'include_oper_time': mapping.get('include_oper_time'), 'oper_time_utc': '',
            'timestamp_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'time_quality': 32, 'test': True, 'synchro_check': True, 'interlock_check': True,
            'structure_confirmed': not bool(template.get('wire_profile_missing_fields')) and bool(mapping.get('domain_id')),
            'control_cancel_supported': mapping.get('control_cancel_supported', False),
            'selection_timeout_ms': mapping.get('selection_timeout_ms', 5000)}


def numeric(value, data_type, scale=1):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError('原指令不是有效数值，不能按寄存器或数值控制编码')
    if type(scale) not in (int, float) or not 0 < scale <= 1e12:
        raise ValueError('倍率须为有限正数且不超过1e12')
    try:
        raw = Decimal(str(value)) * Decimal(str(scale))
        formats = {'uint16': ('H', 0, 65535), 'int16': ('h', -32768, 32767),
                   'uint32': ('I', 0, 4294967295), 'int32': ('i', -2147483648, 2147483647)}
        if data_type in formats:
            code, lo, hi = formats[data_type]
            if raw != raw.to_integral_value() or not lo <= raw <= hi:
                raise ValueError('原目标值无法按所选倍率无损编码为该整数类型')
            return struct.pack('>' + code, int(raw)), int(raw)
        if data_type == 'float32':
            encoded = struct.pack('>f', float(raw))
            decoded = struct.unpack('>f', encoded)[0]
            if not math.isfinite(decoded):
                raise ValueError('目标值超出float32范围')
            return encoded, decoded
    except (OverflowError, struct.error, InvalidOperation) as exc:
        raise ValueError('数值无法按所选类型编码') from exc
    raise ValueError('不支持的数据类型')


def modbus(values, value):
    transaction = integer(values, 'transaction_id', 0, 65535)
    unit = integer(values, 'unit_id', 0, 255)
    address = integer(values, 'address', 0, 65535)
    code = integer(values, 'function_code', 1, 127)
    data_type = text(values, 'data_type')
    for key in ('byte_order', 'word_order'):
        if values[key] not in ('big', 'little'):
            raise ValueError('字节序和字序只能为big或little')
    if code == 5:
        if data_type != 'bool' or type(value) is not bool or type(values['scale']) not in (int, float) or values['scale'] != 1:
            raise ValueError('功能码05仅支持原指令的布尔值，倍率须为1')
        encoded_value = 0xff00 if value else 0
        pdu = struct.pack('>BHH', code, address, encoded_value)
    elif code in (6, 16):
        raw, encoded_value = numeric(value, data_type, values['scale'])
        if code == 6 and len(raw) != 2:
            raise ValueError('功能码06只支持一个16位寄存器，32位类型须使用16')
        words = [raw[i:i+2] for i in range(0, len(raw), 2)]
        if values['byte_order'] == 'little':
            words = [word[::-1] for word in words]
        if values['word_order'] == 'little':
            words.reverse()
        raw = b''.join(words)
        if address + len(words) > 65536:
            raise ValueError('寄存器范围超出协议地址空间')
        pdu = (struct.pack('>BH', code, address) + raw if code == 6
               else struct.pack('>BHHB', code, address, len(words), len(raw)) + raw)
    else:
        raise ValueError('首期仅支持Modbus写单线圈05、单寄存器06和多寄存器16')
    adu = struct.pack('>HHHB', transaction, 0, len(pdu) + 1, unit) + pdu
    warnings = ['单元标识0可能被网关解释为广播；请按实际设备和网关定义核对。'] if unit == 0 else []
    return adu, {'pdu_hex': pdu.hex(' '), 'encoded_value': encoded_value,
                 'scope': 'Modbus TCP完整应用层请求（ADU），不含IP/TCP网络头'}, warnings


def tlv(tag, content):
    size = len(content)
    if size < 128:
        length = bytes([size])
    else:
        raw = size.to_bytes((size.bit_length() + 7) // 8, 'big')
        length = bytes([128 + len(raw)]) + raw
    return bytes([tag]) + length + content


def signed_integer(value):
    size = max(1, (value.bit_length() + 8) // 8)
    raw = value.to_bytes(size, 'big', signed=True)
    while len(raw) > 1 and ((raw[0] == 0 and raw[1] < 128) or (raw[0] == 255 and raw[1] >= 128)):
        raw = raw[1:]
    return raw


def utc_time(value, quality):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('时间须为带时区的ISO8601时间')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('时间缺少时区')
        seconds = stamp.timestamp()
        if not 0 <= seconds < 4294967296:
            raise ValueError('时间超出IEC UTC范围')
        whole = int(seconds)
        fraction = min(16777215, round((seconds-whole) * 16777216))
        return whole.to_bytes(4, 'big') + fraction.to_bytes(3, 'big') + bytes([quality])
    except (ValueError, OverflowError) as exc:
        raise ValueError('时间无效，须包含时区并在IEC UTC范围内') from exc


def modbus_readback(values, mapping):
    code = integer(mapping, 'function_code', 1, 4)
    address = integer(mapping, 'address', 0, 65535)
    unit = integer(mapping, 'slave_id', 0, 255)
    if mapping.get('data_type') == 'bool':
        if code not in (1, 2):
            raise ValueError('布尔读回须使用线圈或离散输入读取服务')
        count = 1
    else:
        if code not in (3, 4):
            raise ValueError('数值读回须使用寄存器读取服务')
        raw, _ = numeric(0, mapping.get('data_type'), mapping.get('scale', 1))
        count = len(raw) // 2
    if address + count > 65536:
        raise ValueError('读回寄存器范围越界')
    transaction = integer(values, 'transaction_id', 0, 65534) + 1
    pdu = struct.pack('>BHH', code, address, count)
    return struct.pack('>HHHB', transaction, 0, len(pdu)+1, unit) + pdu


def _packet(row):
    frame = row['bytes']
    return {**{k: v for k, v in row.items() if k != 'bytes'},
            'hex': frame.hex(' '), 'base64': base64.b64encode(frame).decode('ascii'),
            'byte_length': len(frame)}


def build_message(candidate, profile, action, options):
    """Generate complete staged application requests; never connect or send."""
    expected = defaults(candidate, profile, action)
    if not isinstance(options, dict) or set(options) - set(expected):
        raise ValueError('报文参数包含不支持的字段，不能修改原设备、动作或目标值')
    values = {**expected, **options}
    destination = endpoint(values)
    value = candidate['payload']['engineering_value']
    protocol = candidate['protocol']
    communication = profile.get('communication', {})
    feedback = profile['actions'][action]['feedback_mapping']
    if protocol == 'Modbus':
        frame, details, warnings = modbus(values, value)
        readback = modbus_readback(values, feedback)
        requests = [
            {'id': 'operate', 'title': '写入控制请求', 'bytes': frame, 'branch': 'main',
             'requires': ['tcp_connected'], 'expected_response': {
                 'type': 'modbus_write_ack', 'transaction_id': values['transaction_id'],
                 'unit_id': values['unit_id'], 'function_code': values['function_code'],
                 'address': values['address'], 'reject_exception': True}},
            {'id': 'readback', 'title': '读取独立反馈点', 'bytes': readback, 'branch': 'main',
             'requires': ['operate_response_success'], 'expected_response': {
                 'type': 'modbus_read_response', 'transaction_id': values['transaction_id']+1,
                 'unit_id': feedback['slave_id'], 'function_code': feedback['function_code'],
                 'data_type': feedback['data_type'], 'field': feedback.get('field'),
                 'reject_exception': True}}]
        context = {'transport': 'Modbus TCP', 'tcp_connection_required': True}
    else:
        from .iec_protocol import encode_iec_bundle
        bundle = encode_iec_bundle(values, value, communication.get('association', {}), feedback)
        requests, frame, context = bundle['requests'], bundle['operate'], bundle['association']
        details = {'service': 'IEC61850 MMS控制请求包', 'control_model': values['control_model'],
                   'domain_id': values['domain_id'], 'item_id': values['item_id'],
                   'scope': '完整连接建立、控制和读回请求；后续阶段须核验对端响应后才能发送'}
        warnings = ['关联参数来自明确的模拟配置，尚未与真实设备协商。',
                    '增强安全模型须取得CommandTermination；写入确认不代表最终动作完成。']
    if values['data_type'] == 'float32':
        warnings.append('float32按IEEE754舍入，可能存在微小表示误差。')
    packets = [_packet(row) for row in requests]
    result = {'status': 'generated', 'protocol': protocol, 'endpoint': destination,
            'device_id': candidate['target'], 'action': action, 'engineering_value': value,
            'unit': candidate['payload'].get('unit', ''), 'parameters': values,
            'hex': frame.hex(' '), 'base64': base64.b64encode(frame).decode('ascii'),
            'byte_length': len(frame), 'details': details, 'warnings': warnings,
            'requests': packets, 'request_count': len(packets), 'connection_profile': context,
            'feedback_mapping': feedback, 'configuration_source': 'explicit_simulation_profile',
            'profile_id': communication.get('profile_id'), 'sent': False, 'dispatch_allowed': False,
            'notice': '已生成完整分阶段请求；未连接、未发送、未执行。主hex字段为操作请求，完整内容见请求包。'}
    return result


def archive_message(result):
    """Archive after the runtime has attached its command/version provenance."""
    import io
    import json
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(result, ensure_ascii=False, indent=2))
        for index, packet in enumerate(result['requests'], 1):
            archive.writestr(f'{index:02d}-{packet["id"]}.bin', base64.b64decode(packet['base64']))
    result['bundle_base64'] = base64.b64encode(buffer.getvalue()).decode('ascii')
    result['bundle_byte_length'] = len(buffer.getvalue())
    return result


