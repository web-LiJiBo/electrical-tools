"""Resumable source queues and explicitly labelled rule-based drafts."""
import argparse
import hashlib
import json
import re

from .remaining_inventory import inventory
from .reviewed_extension import INDEX, OUTPUT, publish, SOURCE_SHA256
from .clause_filenames import clause_filename
from .supplemental_excel import _write_json


def snapshot(batch_number):
    root, _, _ = paths(batch_number)
    target = root / '入库前哈希.json'
    if target.exists():
        return json.loads(target.read_text(encoding='utf-8'))
    result = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in OUTPUT.glob('*.json')}
    _write_json(target, result)
    return result


def paths(batch_number):
    if not 1 <= batch_number <= 999:
        raise ValueError('批号范围1至999')
    root = OUTPUT.parent / '连续分批' / f'{batch_number:03d}'
    return root, root / '来源清单.json', root / '助手语义分解.json'


def prepare(batch_number, target_count=1000):
    if not 1 <= target_count <= 1000:
        raise ValueError('每批数量范围1至1000')
    root, queue, annotations = paths(batch_number)
    if queue.exists():
        saved = json.loads(queue.read_text(encoding='utf-8'))
        if saved['source_index_sha256'] != SOURCE_SHA256:
            raise ValueError('已有清单来源哈希不匹配')
        return saved
    remaining = inventory(INDEX, OUTPUT)
    if remaining['source_index_sha256'] != SOURCE_SHA256:
        raise ValueError('来源索引改变，必须重新核对')
    items = []
    reserved = set()
    for other in (OUTPUT.parent / '连续分批').glob('*/来源清单.json'):
        reserved.update(r['index_line'] for r in json.loads(other.read_text(encoding='utf-8'))['items'])
    occupied = {p.name.casefold() for p in OUTPUT.glob('*.json')}
    for item in remaining['items']:
        if item['index_line'] in reserved:
            continue
        number = re.match(r'^\s*(\d+(?:\.\d+)*)(?=\s|$)', item['text'])
        if batch_number < 7:
            if item['preflight_issues'] or not re.match(r'^(\d+(?:\.\d+)+)\s', item['text']):
                continue
            chapter_path = number[1]
            selection_note = ''
        elif not item['preflight_issues'] and number:
            chapter_path = number[1]
            selection_note = ''
        else:
            chapter_path = f'来源行-{item["index_line"]:08d}'
            selection_note = '；'.join(item['preflight_issues']) or '条款编号需复核'
        try:
            filename = clause_filename(item['standard_id'], chapter_path)
        except ValueError:
            digest = hashlib.sha256((item['standard_id'] + '\0' + item['text']).encode('utf-8')).hexdigest()[:20]
            filename = clause_filename('来源记录-' + digest, chapter_path)
            extra = '存储文件名使用哈希别名，原始standard_id保留在JSON'
            selection_note = (selection_note + '；' + extra).strip('；')
        folded_filename = filename.casefold()
        if folded_filename in occupied:
            continue
        occupied.add(folded_filename)
        items.append({k: item[k] for k in ('index_line', 'standard_name', 'standard_id', 'text')}
                     | {'chapter_path': chapter_path, 'selection_note': selection_note,
                        'storage_filename': filename})
        if len(items) == target_count:
            break
    if len(items) != target_count:
        raise ValueError(f'可安全命名且未入库的来源不足{target_count}条')
    result = {'batch': f'assistant_remaining_{batch_number:03d}',
              'source_index_sha256': SOURCE_SHA256,
              'selection': ('来源顺序；排除已分解、重复原文及已预留批次；清晰唯一编号沿用原条款号；'
                            '自007批起，缺号或重号记录使用来源行号作为可追溯章节路径并保留异常标记；不覆盖既有文件'),
              'target_count': target_count, 'items': items}
    _write_json(queue, result)
    if not annotations.exists():
        _write_json(annotations, {'method': 'assistant_semantic_review',
                                 'fields': ['index_line', 'subject', 'operation', 'condition', 'optional_review_note'],
                                 'items': []})
    return result


def draft(batch_number):
    """Create a rule-based field extraction draft; this is not semantic review."""
    root, queue, annotations = paths(batch_number)
    selected = json.loads(queue.read_text(encoding='utf-8'))
    items = []
    normative = re.compile(r'应|不得|必须|宜|可|采用|按照|符合|禁止|要求|检查|检测|记录|设置|控制')
    for row in selected['items']:
        text = re.sub(r'\s+', ' ', row['text']).strip()
        body = re.sub(r'^\d+(?:\.\d+)*\s*', '', text).strip(' ：:；;、')
        first = re.split(r'[。；;：:\n]', body, maxsplit=1)[0].strip()
        subject = (first[:36] or '原始条款记录')
        notes = []
        if row.get('selection_note'):
            notes.append('章节路径使用来源行号；' + row['selection_note'])
        if '\t' in row['text'] or (len(re.findall(r'\d+(?:\.\d+)?', text)) >= 6 and not normative.search(text)):
            subject = '原始参数或表格行'
            operation = '保留原始表格行；须关联表头、单位和上下文后方可判定'
            notes.append('疑似表格或参数行，不作为独立控制条件')
        elif len(body) <= 28 and not normative.search(body):
            operation = '仅保留标题或术语；具体要求须结合相邻正文'
            notes.append('疑似标题或术语，不能单独作为判定依据')
        else:
            operation = body[:240]
            if len(body) > 240:
                notes.append('操作摘要截取前240字符，完整约束以原文content为准')
        items.append([row['index_line'], subject, operation, '', *notes])
    _write_json(annotations, {'method': 'rule_based_field_extraction_draft',
                              'fields': ['index_line', 'subject', 'operation', 'condition', 'optional_review_note'],
                              'draft_policy': '保留完整原文；保守抽取对象与操作；不生成设备动作；全部待领域专家复核',
                              'items': items})
    return {'batch': selected['batch'], 'drafted_count': len(items), 'annotations': str(annotations)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('batch', type=int)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--show', nargs=2, type=int)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--snapshot', action='store_true')
    parser.add_argument('--draft', action='store_true')
    parser.add_argument('--count', type=int, default=1000)
    args = parser.parse_args()
    root, queue, annotations = paths(args.batch)
    if args.snapshot:
        print(json.dumps({'preserved_file_count': len(snapshot(args.batch))}))
    elif args.prepare:
        result = prepare(args.batch, args.count)
        print(json.dumps({'batch': result['batch'], 'count': len(result['items']), 'queue': str(queue)}, ensure_ascii=False))
    elif args.draft:
        print(json.dumps(draft(args.batch), ensure_ascii=False))
    elif args.show:
        start, count = args.show
        items = json.loads(queue.read_text(encoding='utf-8'))['items']
        for row in items[start:start + count]:
            standard = row['standard_id']
            label = standard if len(standard) <= 80 else '[标准编号字段过长，完整值保留在来源清单]'
            print(f'{row["index_line"]}|{label}|{row["text"]}')
    elif args.publish:
        result = publish(queue=queue, annotations=annotations,
                         batch=f'assistant_remaining_{args.batch:03d}',
                         summary_name=f'连续分批{args.batch:03d}入库汇总.json')
        print(json.dumps({k: v for k, v in result.items() if k != 'clause_files'}, ensure_ascii=False))
    else:
        items = json.loads(annotations.read_text(encoding='utf-8'))['items']
        print(json.dumps({'batch': args.batch, 'authored_count': len(items), 'published': (OUTPUT.parent / f'连续分批{args.batch:03d}入库汇总.json').exists()}))


if __name__ == '__main__':
    main()
