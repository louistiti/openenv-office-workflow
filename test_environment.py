import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from tasks import TASK_IDS, csv_text, make_task, half_up
from server import OfficeAction, OfficeEnvironment, connect, query, grade, app, MAX_STEPS
from oracle import solve, QUERIES, summary_sql

@pytest.mark.parametrize('task_id', TASK_IDS)
@pytest.mark.parametrize('seed', range(40))
def test_fresh_seed_independent_sql_oracle(task_id, seed):
    t = make_task(task_id, seed)
    db = connect(t)
    try:
        actual = solve(db, task_id.split('-')[0], t.columns)
        assert list(json.loads(query(db, QUERIES[task_id.split('-')[0]]))['rows']) == t.rows
        assert json.loads(actual['summary.json']) == t.summary
        assert grade(t, actual)[0] == 1
        assert grade(t, {})[0] == 0
        assert grade(t, {'report.csv':actual['report.csv']})[0] <= 0.6
        assert grade(t, {'summary.json':actual['summary.json']})[0] <= 0.4
    finally: db.close()

@pytest.mark.parametrize('task_id', TASK_IDS)
def test_reset_replay_and_no_intermediate_reward(task_id):
    env = OfficeEnvironment()
    first = env.reset(task_id=task_id, seed=512)
    files = env.task.files
    assert first.done is False and first.reward == 0
    assert 'summary.json' not in first.files
    out = solve(env.db, task_id.split('-')[0], env.task.columns)
    for path, content in out.items():
        assert env.step(OfficeAction(operation='write', path=path, content=content)).reward == 0
    final = env.step(OfficeAction(operation='submit'))
    assert final.done and final.reward == 1
    assert env.step(OfficeAction(operation='write',path='summary.json',content='{}')).reward == 1
    second = env.reset(task_id=task_id, seed=512)
    assert env.task.files == files and not env.artifacts
    assert second.reward == 0
    env.reset(task_id=task_id, seed=513)
    assert env.task.files != files
    env.close()

@pytest.mark.parametrize('sql', [
    'SELECT * FROM sqlite_master', 'SELECT * FROM expected', 'PRAGMA table_info(contacts)',
    'ATTACH DATABASE "/tmp/leak" AS x', 'SELECT load_extension("x")',
    'UPDATE contacts SET consent=1', 'DROP TABLE contacts', 'SELECT 1; SELECT 2',
    'SELECT randomblob(100000000)', 'SELECT printf("%100000000s","x")',
])
def test_sql_isolation(sql):
    db = connect(make_task('crm-advanced', 2))
    try:
        with pytest.raises((sqlite3.Error, ValueError)): query(db, sql)
        assert json.loads(query(db, 'SELECT count(*) n FROM contacts'))['rows'][0]['n'] > 0
    finally: db.close()

def test_recursive_query_budget_and_size_limits():
    db = connect(make_task('crm-standard', 0))
    try:
        with pytest.raises(sqlite3.Error):
            query(db, 'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT sum(n) FROM x')
        with pytest.raises(ValueError):
            query(db, 'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x WHERE n<300) SELECT n FROM x')
        with pytest.raises(ValueError): query(db, 'SELECT contact_id,contact_id FROM contacts')
    finally: db.close()

def test_duplicate_and_malformed_artifacts_do_not_get_full_credit():
    t = make_task('inventory-advanced', 3)
    good = {'report.csv':csv_text(t.rows, t.columns), 'summary.json':json.dumps(t.summary)}
    assert grade(t, good)[0] == 1
    duplicated = {**good, 'report.csv':csv_text(t.rows + t.rows, t.columns)}
    assert grade(t, duplicated)[0] == 0.4
    assert grade(t, {**good, 'summary.json':'{"sku_count":true}'})[0] == 0.6
    assert grade(t, {**good, 'summary.json':'{"sku_count":1,"sku_count":1}'})[0] == 0.6
    damaged = [dict(x) for x in t.rows]
    damaged[0]['on_hand'] += 1
    reward = grade(t, {**good, 'report.csv':csv_text(damaged,t.columns)})[0]
    assert 0.4 < reward < 1

def test_action_budget_paths_and_session_isolation():
    a, b = OfficeEnvironment(), OfficeEnvironment()
    a.reset(task_id='expenses-advanced', seed=1)
    b.reset(task_id='expenses-advanced', seed=2)
    assert a.task.files != b.task.files
    assert 'Action error' in a.step(OfficeAction(operation='write',path='../secret',content='x')).message
    assert not a.artifacts and not b.artifacts
    for _ in range(MAX_STEPS - 1): obs = a.step(OfficeAction(operation='read',path='brief.txt'))
    assert obs.done and obs.reward == 0 and obs.steps_left == 0
    assert not b.ended
    a.close(); b.close()

def test_independent_rounding_boundaries():
    assert half_up(1,2) == 1
    assert half_up(29,60) == 0
    assert half_up(30,60) == 1
    assert half_up(5000,10000) == 1

def test_live_sdk_schema_and_websocket():
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        schema = client.get('/schema').json()
        assert schema['action'] == OfficeAction.model_json_schema()
        with client.websocket_connect('/ws') as ws:
            ws.send_json({'type':'reset','data':{'task_id':'invoices-standard','seed':10}})
            initial = ws.receive_json()
            assert initial['type'] == 'observation' and not initial['data']['done']
            ws.send_json({'type':'step','data':{'operation':'submit'}})
            final = ws.receive_json()['data']
            assert final['done'] and final['reward'] == 0
