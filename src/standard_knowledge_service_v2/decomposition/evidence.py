"""Shared literal normalization; no operation or device is guessed here."""
import re
import unicodedata

CHINESE = '零〇一二两三四五六七八九十百千万亿'
NUMBER_PATTERN = r'(?:[+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[负正]?[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二两三四五六七八九]+)?)'


def literal(text):
    return re.sub(r'\s+', '', str(text)).casefold()


def number_text(text):
    text = unicodedata.normalize('NFKC', str(text)).strip().removeprefix('第')
    text = text.translate(str.maketrans({'−': '-', '－': '-', '＋': '+', '负': '-', '正': '+'}))
    if not any(char in CHINESE for char in text):
        return text
    negative = text.startswith('-')
    text = text.lstrip('+-')
    if not text or any(c not in CHINESE + '点' for c in text):
        raise ValueError('数值文本无效')
    parts = text.split('点')
    digits = dict(zip('零〇一二两三四五六七八九', [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    whole = parts[0]
    if not any(char in '十百千万亿' for char in whole):
        result = ''.join(str(digits[c]) for c in whole)
    else:
        def integer(fragment):
            # Split largest sections first: 一亿二千万 is 120000000.
            for marker, scale in [('亿', 100000000), ('万', 10000)]:
                if marker in fragment:
                    left, right = fragment.split(marker, 1)
                    if not left or marker in right:
                        raise ValueError('数值文本无效')
                    return integer(left) * scale + integer(right)
            section = digit = 0
            for char in fragment:
                if char in digits:
                    digit = digits[char]
                elif char in '十百千':
                    section += (digit or 1) * {'十': 10, '百': 100, '千': 1000}[char]
                    digit = 0
                else:
                    raise ValueError('数值文本无效')
            return section + digit
        result = str(integer(whole))
    if len(parts) == 2:
        result += '.' + ''.join(str(digits[c]) for c in parts[1])
    if len(parts) > 2:
        raise ValueError('数值文本无效')
    return ('-' if negative else '') + result


def reference_text(text):
    """Normalize ordinal fragments only, keeping equipment words intact."""
    text = unicodedata.normalize('NFKC', str(text).casefold())
    text = re.sub(r'sim\s*-\s*[a-z0-9]+(?:\s*-\s*[a-z0-9]+)*',
                  lambda m: re.sub(r'\s+', '', m[0]), text)
    # Keep English word boundaries; removing every space joins "start SIM"
    # into a new identifier and loses the evidence boundary.
    text = re.sub(r'(?<![a-z0-9])\s+|\s+(?![a-z0-9])', '', text)
    pattern = r'(?:第)?([' + CHINESE + r']+)(号|档|台)'
    text = re.sub(pattern, lambda m: number_text(m[1]) + ('' if m[2] == '号' else m[2]), text)
    return re.sub(r'(\d+)号', r'\1', text)


def catalog_spans(text, devices, *, nested=False):
    text = reference_text(text)
    matches = set()
    def base_name(device):
        return re.sub(r'[（(](?:IEC61850|Modbus)[）)]$', '', device.get('display_name', ''), flags=re.I)
    for device in devices:
        base = base_name(device)
        unique_base = [base] if base and sum(base_name(row) == base for row in devices) == 1 else []
        for alias in [device['device_id'], device.get('display_name', ''), *device.get('aliases', []), *unique_base]:
            if alias:
                normalized = reference_text(alias)
                left = r'(?<![a-z0-9-])' if normalized.startswith('sim-') else ''
                for match in re.finditer(left + re.escape(normalized) + r'(?![a-z0-9-])', text):
                    matches.add((device['device_id'], match.start(), match.end()))
    if nested:
        return matches
    return {row for row in matches if not any(other[0] != row[0] and other[1] <= row[1]
        and row[2] <= other[2] and other[2] - other[1] > row[2] - row[1] for other in matches)}


def target_evidence(query, evidence, parameter, convert, unit):
    values = []
    for item in evidence or []:
        if item.get('parameter') != parameter or item.get('role', 'target') != 'target':
            continue
        source, value, source_unit = item.get('source_text', ''), item.get('value_text', ''), item.get('unit_text', '')
        exact = lambda text: re.sub(r'\s+', '', str(text))
        if not source or exact(source) not in exact(query) or not value or exact(value) not in exact(source):
            raise ValueError('动作目标的原文依据不匹配')
        if source_unit and exact(source_unit) not in exact(source):
            raise ValueError('动作目标单位缺少原文依据')
        numeric = exact(value).removeprefix('第')
        suffix = exact(source_unit or unit)
        if suffix and numeric.endswith(suffix):
            numeric = numeric[:-len(suffix)]
        if not re.fullmatch(NUMBER_PATTERN, numeric):
            raise ValueError('动作目标的数值格式无效')
        values.append(convert(numeric, source_unit or unit, unit))
    return values
