"""Local business classifications and explicit unit conversion definitions."""
from decimal import Decimal
import math
import re

BASE_UNITS = {
    'W': ('power', '1'), 'kW': ('power', '1000'), 'MW': ('power', '1000000'), 'mW': ('power', '0.001'),
    'var': ('reactive', '1'), 'kvar': ('reactive', '1000'), 'Mvar': ('reactive', '1000000'),
    'V': ('voltage', '1'), 'kV': ('voltage', '1000'),
    'A': ('current', '1'), 'kA': ('current', '1000'),
    'Ω': ('resistance', '1'), 'kΩ': ('resistance', '1000'), 'MΩ': ('resistance', '1000000'),
    '℃': ('temperature', '1'), '%': ('ratio', '1'), 'Hz': ('frequency', '1'),
    'MW/min': ('ramp', '1'), '档': ('tap', '1'),
}


def normalize(value=None):
    from .manual_device_config import DEVICE_TYPES
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'device_types', 'units'}:
        raise ValueError('登记内容仅支持device_types和units。')
    result = {'device_types': [], 'units': []}
    for kind in result:
        if not isinstance(value.get(kind, []), list) or len(value.get(kind, [])) > 100:
            raise ValueError('类型与单位各最多登记100项。')
    codes, names = set(DEVICE_TYPES), set(DEVICE_TYPES.values())
    for row in value.get('device_types', []):
        if not isinstance(row, dict) or set(row) != {'code', 'name'}:
            raise ValueError('设备类型须填写code、name。')
        code, name = row['code'], row['name']
        if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', code) or code in codes:
            raise ValueError('类型编号须为唯一的小写英文编号，不能覆盖预置类型。')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or name.strip() in names or any(ord(c) < 32 for c in name):
            raise ValueError('类型名称须为唯一的1至40字符文本。')
        result['device_types'].append(dict(code=code, name=name.strip())); codes.add(code); names.add(name.strip())
    symbols = set(BASE_UNITS)
    for row in value.get('units', []):
        if not isinstance(row, dict) or set(row) != {'symbol', 'base_unit', 'scale', 'offset'}:
            raise ValueError('单位须填写symbol、base_unit、scale、offset。')
        symbol, base = row['symbol'], row['base_unit']
        if (not isinstance(symbol, str) or not 1 <= len(symbol) <= 24 or re.search(r'''[\s<>"'`{}\\,;，；]''', symbol)
                or symbol in symbols or not isinstance(base, str)):
            raise ValueError('单位符号须唯一且不能覆盖预置单位，不能包含空白或分隔符。')
        scale, offset = row['scale'], row['offset']
        if (type(scale) not in (int, float) or not math.isfinite(scale) or not 1e-12 <= scale <= 1e12
                or type(offset) not in (int, float) or not math.isfinite(offset) or abs(offset) > 1e12
                or not base and (scale != 1 or offset != 0)):
            raise ValueError('单位倍率须为有限正数；不换算的单位使用倍率1、偏移0。')
        result['units'].append(dict(row)); symbols.add(symbol)
    unit_map(result['units'])
    return result


def unit_map(rows):
    result = {key: (kind, Decimal(scale), Decimal(0)) for key, (kind, scale) in BASE_UNITS.items()}
    pending = {row['symbol']: row for row in rows}
    visiting = set()
    def resolve(symbol):
        if symbol in result: return result[symbol]
        if symbol not in pending or symbol in visiting: raise ValueError('单位基准不存在或存在循环换算。')
        visiting.add(symbol); row = pending[symbol]
        if row['base_unit']:
            kind, scale, offset = resolve(row['base_unit'])
            result[symbol] = (kind, Decimal(str(row['scale'])) * scale, Decimal(str(row['offset'])) * scale + offset)
        else: result[symbol] = ('custom:' + symbol, Decimal(1), Decimal(0))
        visiting.remove(symbol)
        return result[symbol]
    for symbol in pending: resolve(symbol)
    return result
