"""Non-generating online preflight; does not send questions or clause contents."""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from ..config import load_config
from .model_errors import ModelCallError, model_error_code


def check_remote(config):
    if config.backend != 'deepseek_api':
        return {'status': 'skipped', 'reason': '当前不是DeepSeek后端，未执行远程接口预检查'}
    key = os.getenv(config.api_key_env, '').strip()
    try:
        if not key:
            raise ModelCallError('missing_api_key')
        request = Request(config.api_base.rstrip('/') + '/models',
                          headers={'Authorization': 'Bearer ' + key}, method='GET')
        with urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode('utf-8'))
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
            raise ModelCallError('invalid_response')
        listed = any(isinstance(item, dict) and item.get('id') == config.remote_model for item in payload['data'])
        return {'status': 'reachable', 'configured_model_listed': listed,
                'notice': '模型列表接口可访问；尚未验证所配置模型的文本生成、条款建议或指令转换。模型别名可能不出现在列表中。'}
    except Exception as exc:
        error = ModelCallError(model_error_code(exc))
        return {'status': 'unavailable', 'error_code': error.code, 'notice': str(error)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    result = check_remote(load_config(args.config, root).llm)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result['status'] == 'unavailable' else 0


if __name__ == '__main__':
    raise SystemExit(main())
