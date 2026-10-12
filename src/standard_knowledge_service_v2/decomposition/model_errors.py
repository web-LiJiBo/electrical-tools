"""Stable, secret-free model diagnostics shared by advice and query decomposition."""
import socket
from urllib.error import HTTPError, URLError


MESSAGES = {
    'missing_api_key': '未配置模型密钥，请在启动服务的窗口配置环境变量。',
    'network_permission_denied': '模型联网权限被拒绝（WinError 10013/权限错误）。请从具有外网访问权限的终端启动服务；代码不会绕过系统或沙箱限制。',
    'network_timeout': '模型请求超时，请检查网络或稍后重试。',
    'network_error': '无法连接模型服务，请检查网络、代理及服务地址。',
    'authentication_failed': '模型服务拒绝认证，请检查密钥及访问权限。',
    'rate_limited': '模型服务限流，请稍后重试并检查账户用量。',
    'provider_unavailable': '模型服务暂时不可用，请稍后重试。',
    'http_error': '模型接口请求被拒绝，请检查接口和模型配置。',
    'invalid_response': '模型接口返回结构不符合要求，未接受该响应。',
    'invalid_model_output': '模型输出格式、动作或来源引用不合规，已阻止生成指令。',
    'model_error': '模型调用失败，未生成模型建议；请检查运行环境及模型配置。',
}


class ModelCallError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in MESSAGES else 'model_error'
        super().__init__(MESSAGES[self.code])


def model_error_code(exc: Exception) -> str:
    """Never return arbitrary exception text, provider bodies, headers or keys."""
    if isinstance(exc, ModelCallError):
        return exc.code
    if isinstance(exc, HTTPError):
        if exc.code in (401, 403):
            return 'authentication_failed'
        if exc.code == 429:
            return 'rate_limited'
        return 'provider_unavailable' if exc.code >= 500 else 'http_error'
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, PermissionError) or getattr(reason, 'winerror', None) == 10013 or getattr(reason, 'errno', None) in (1, 13, 10013) or isinstance(reason, str) and '[winerror 10013]' in reason.lower():
        return 'network_permission_denied'
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'network_timeout'
    if isinstance(exc, URLError) or isinstance(reason, OSError):
        return 'network_error'
    return 'model_error'
