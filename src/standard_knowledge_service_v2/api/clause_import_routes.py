"""Local clause maintenance; JSON payloads never choose filesystem paths."""
import json
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from ..data_ingestion import local_clauses as clauses


def register_clause_import_routes(app, application):
    @app.get('/knowledge/local-clauses')
    def listing():
        try: return {'clauses': clauses.read_records(), 'max_batch': 100, 'max_request': clauses.MAX_REQUEST}
        except (ValueError, OSError) as exc: raise HTTPException(422, str(exc)) from exc

    async def process(request, publish):
        origin = request.headers.get('origin')
        if origin:
            try: allowed = urlsplit(origin).scheme in ('http', 'https') and urlsplit(origin).hostname in ('localhost', '127.0.0.1', '::1')
            except ValueError: allowed = False
            if not allowed: raise HTTPException(403, '条款导入仅允许本机页面发起。')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > clauses.MAX_REQUEST: raise HTTPException(413, '导入内容超过2MB。')
        try: payload = json.loads(body)
        except (ValueError, UnicodeError, RecursionError) as exc: raise HTTPException(422, '请提供合法JSON。') from exc
        return await run_in_threadpool(clauses.process, application.facade, payload, publish=publish)

    @app.post('/knowledge/local-clauses/preview')
    async def preview(request: Request): return await process(request, False)

    @app.post('/knowledge/local-clauses/import')
    async def publish(request: Request): return await process(request, True)
