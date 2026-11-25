from copy import deepcopy
from types import SimpleNamespace
import pytest

from standard_knowledge_service_v2.data_ingestion import local_clauses as c
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository
from standard_knowledge_service_v2.retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter
from standard_knowledge_service_v2.knowledge_graph.current_graph import CurrentKnowledgeGraph
from standard_knowledge_service_v2.retrieval import LunwenMatchingInput


def clause(**changes):
    return dict(standard_id='LOCAL-TEST',standard_name='导入验收文件',version='2026',clause_number='4.2',
                content='专用校验柜的备用照明每月巡检一次，并记录检查日期。',subject='专用校验柜',keywords=['备用照明'],**changes)


@pytest.fixture
def pipeline(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'STORE_PATH',tmp_path/'clauses.json')
    retriever=LocalLunwenRetrievalAdapter(JsonClauseRepository())
    return SimpleNamespace(retriever=retriever,knowledge_graph=CurrentKnowledgeGraph([]),reasoner=SimpleNamespace(semantic_reasoner=None),config=None)


def publish(p,rows):
    checked=c.process(p,{'clauses':rows})
    assert checked['status']=='validated',checked
    return c.process(p,{'clauses':rows,'revision':checked['revision']},publish=True)


def test_publish_immediate_search_deduplication_and_reload(pipeline):
    p=pipeline
    checked=c.process(p,{'clauses':[clause()]});assert checked['status']=='validated'
    assert not c.STORE_PATH.exists() and not p.retriever.repository.units
    assert c.process(p,{'clauses':[clause()],'revision':'old'},publish=True)['status']=='invalid'
    saved=publish(p,[clause()]);assert saved['status']=='published' and saved['added']==1
    u=p.retriever.repository.units[0];assert u.standard_id=='LOCAL-TEST' and u.chapter_path=='4.2'
    assert p.retriever.repository.unit_for_rule(u.rules[0].rule_id).text==clause()['content']
    assert p.knowledge_graph.evidence_path(u.rules[0].rule_id)['quote']==clause()['content']
    found=p.retriever.match(LunwenMatchingInput('专用校验柜备用照明巡检',{'intent':'search','entities':[{'name':'专用校验柜','type':'设备'}]}))
    assert u.rules[0].rule_id in {hit.rule.rule_id for hit in found.rules}
    assert len(c.load_units())==1
    before=p.retriever;stamp=c.STORE_PATH.stat().st_mtime_ns
    repeat=publish(p,[clause(),clause()]);assert repeat['added']==0 and repeat['unchanged']==2
    assert p.retriever is before and c.STORE_PATH.stat().st_mtime_ns==stamp
    other_metadata=dict(clause(),subject='',keywords=['新关键词'])
    repeat=publish(p,[other_metadata]);assert repeat['added']==0 and repeat['unchanged']==1
    assert c.read_records()[0]['subject']=='专用校验柜'


def test_conflicting_batch_is_atomic(pipeline):
    publish(pipeline,[clause()]);before=c.STORE_PATH.read_bytes();index=pipeline.retriever
    different=clause();different['content']='另一个要求'
    result=c.process(pipeline,{'clauses':[dict(clause(),clause_number='4.3'),different]})
    assert result['status']=='conflicts' and result['conflicts'][0]['clause_number']=='4.2'
    assert c.STORE_PATH.read_bytes()==before and pipeline.retriever is index


@pytest.mark.parametrize('change',[{'standard_id':''},{'version':''},{'clause_number':''},{'content':''},{'keywords':'not-a-list'},{'content':42}])
def test_invalid_import_does_not_modify_storage(pipeline,change):
    row=clause();row.update(change)
    assert c.process(pipeline,{'clauses':[row]})['status']=='invalid'
    assert not c.STORE_PATH.exists()


def test_failed_index_preparation_leaves_file_and_runtime_unchanged(pipeline,monkeypatch):
    checked=c.process(pipeline,{'clauses':[clause()]});before=pipeline.retriever
    monkeypatch.setattr(c,'prepare_runtime',lambda *_:(_ for _ in ()).throw(ValueError('index failure')))
    result=c.process(pipeline,{'clauses':[clause()],'revision':checked['revision']},publish=True)
    assert result['status']=='invalid' and not c.STORE_PATH.exists() and pipeline.retriever is before


def test_http_import_and_size_limit(pipeline):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from standard_knowledge_service_v2.api.clause_import_routes import register_clause_import_routes
    app=FastAPI();register_clause_import_routes(app,SimpleNamespace(facade=pipeline));client=TestClient(app)
    assert client.get('/knowledge/local-clauses').json()['clauses']==[]
    assert client.post('/knowledge/local-clauses/preview',json={'clauses':[clause()]},headers={'origin':'https://unrelated.example'}).status_code==403
    payload={'clauses':[clause()]};review=client.post('/knowledge/local-clauses/preview',json=payload).json()
    assert review['status']=='validated'
    saved=client.post('/knowledge/local-clauses/import',json={**payload,'revision':review['revision']}).json()
    assert saved['status']=='published' and len(client.get('/knowledge/local-clauses').json()['clauses'])==1
    assert client.post('/knowledge/local-clauses/preview',content=b' '*(c.MAX_REQUEST+1)).status_code==413


def test_file_failure_cannot_modify_existing_graph(pipeline,monkeypatch):
    checked=c.process(pipeline,{'clauses':[clause()]});graph=pipeline.knowledge_graph
    monkeypatch.setattr(c,'replace_file',lambda *_:(_ for _ in ()).throw(OSError('disk full')))
    result=c.process(pipeline,{'clauses':[clause()],'revision':checked['revision']},publish=True)
    assert result['status']=='invalid' and pipeline.knowledge_graph is graph
    assert graph.summary()['documents']==0 and not c.STORE_PATH.exists()


def test_external_graph_is_not_synchronized_or_closed_during_local_import(pipeline):
    original=pipeline.knowledge_graph
    closed=[]
    external=SimpleNamespace(summary=original.summary,neighbors=original.neighbors,evidence_path=original.evidence_path,close=lambda:closed.append(True))
    pipeline.knowledge_graph=external
    publish(pipeline,[clause()])
    graph=pipeline.knowledge_graph;rule=pipeline.retriever.repository.units[0].rules[0]
    assert graph.base is external and graph.evidence_path(rule.rule_id)['quote']==clause()['content']
    assert graph.summary()['documents']==1
    publish(pipeline,[dict(clause(),clause_number='4.3')]);assert pipeline.knowledge_graph.base is external
    assert pipeline.knowledge_graph.summary()['documents']==2
    assert closed==[]
    pipeline.knowledge_graph.close();assert closed==[True]


def test_incremental_indexes_match_a_fresh_build_without_mutating_old_indexes(pipeline):
    publish(pipeline,[clause()]);old=pipeline.retriever;old_graph=pipeline.knowledge_graph
    publish(pipeline,[dict(clause(),clause_number='4.3',content='专用校验柜通风过滤网每两周检查一次，并记录压差。')])
    fresh=LocalLunwenRetrievalAdapter(JsonClauseRepository(pipeline.retriever.repository.units))
    q=LunwenMatchingInput('专用校验柜通风过滤网检查压差',{'intent':'search','entities':[{'name':'专用校验柜','type':'设备'}]})
    assert [h.rule.rule_id for h in pipeline.retriever.match(q).rules]==[h.rule.rule_id for h in fresh.match(q).rules]
    assert len(old.repository.units)==1 and old_graph.summary()['documents']==1
