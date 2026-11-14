"""Validate model-declared whole-request restrictions without rewriting user text."""
import re


def _controls(understanding):
    if isinstance(understanding, dict):
        return understanding.get('request_controls')
    return getattr(understanding, 'request_controls', None)


def analysis_only_requested(understanding):
    controls = _controls(understanding)
    return isinstance(controls, dict) and controls.get('analysis_only') is True


def request_controls_error(understanding, query):
    controls = _controls(understanding)
    if controls is None:
        return ''  # Legacy output: restriction claims remain undeclared.
    if (not isinstance(controls, dict) or type(controls.get('analysis_only')) is not bool
            or not isinstance(controls.get('source_text'), str)):
        return '整句控制限制格式不完整，请重新明确请求。'
    source = controls['source_text']
    compact = lambda text: re.sub(r'\s+', '', text).casefold()
    if controls['analysis_only'] and not source.strip():
        return '仅分析限制缺少原文证据，未生成操作预览。'
    if source and compact(source) not in compact(query):
        return '整句控制限制的来源未对应本次原文，请重新明确请求。'
    return ''


def control_source_text(understanding, query):
    if request_controls_error(understanding, query):
        return ''
    controls = _controls(understanding)
    return controls['source_text'] if controls else ''
