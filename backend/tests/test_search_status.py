from career.db import Session, Record, put, now
from career.service import run_scan


def test_empty_search_records_completion(client):
    response = client.post('/api/scan')
    assert response.status_code == 200
    run = client.get('/api/state').json()['runs'][0]
    assert run['status'] == 'completed'
    assert run['added'] == 0
    assert any('No job sources configured' in warning for warning in run['warnings'])


def test_put_persists_reused_search_result_and_nested_progress(client):
    result = {'status': 'running', 'sources': []}
    with Session() as db:
        row = put(db, 'run', 'run:reused', result)
        run_id = row.id
        result['sources'].append({'name': 'test', 'status': 'failed'})
        result['status'] = 'completed'
        put(db, 'run', row.key, result)
    with Session() as db:
        saved = db.get(Record, run_id).data
        assert saved['status'] == 'completed'
        assert saved['sources'][0]['status'] == 'failed'


def test_failed_feed_is_visible_and_run_finishes(client, monkeypatch):
    client.post('/api/sources', json={'kind': 'greenhouse', 'value': 'example'})
    def fail(*args):
        raise ValueError('Test source unavailable.')
    monkeypatch.setattr('career.service.collect', fail)
    client.post('/api/scan')
    run = client.get('/api/state').json()['runs'][0]
    assert run['status'] == 'completed'
    assert run['sources'][0]['error'] == 'Test source unavailable.'


def test_unexpected_failure_records_failed_status(client, monkeypatch):
    def fail(*args):
        raise RuntimeError('Simulated internal failure')
    monkeypatch.setattr('career.service.read', fail)
    client.post('/api/scan')
    run = client.get('/api/state').json()['runs'][0]
    assert run['status'] == 'failed'
    assert 'error log' in run['error']
    assert 'Simulated internal failure' not in run['error']


def test_explicit_save_of_mutated_record_persists(client):
    with Session() as db:
        row = put(db, 'run', 'run:mutated', {'status': 'running', 'sources': []})
        run_id = row.id
        row.data['status'] = 'completed'
        put(db, 'run', row.key, row.data)
    with Session() as db:
        assert db.get(Record, run_id).data['status'] == 'completed'


def test_repair_preserves_records_and_backs_up_database(client):
    import subprocess
    import sys
    import sqlite3
    from pathlib import Path
    from career.config import settings
    with Session() as db:
        old = put(db, 'run', 'run:old', {'status': 'running', 'created': now()})
        old_id = old.id
        completed = put(db, 'run', 'run:done', {'status': 'completed'})
        completed_id = completed.id
        put(db, 'profile', 'profile', {'name': 'Retained Applicant', 'facts': []})
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / 'deployment/repair_search_status.py')],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with Session() as db:
        assert db.get(Record, old_id).data['status'] == 'interrupted'
        assert db.get(Record, completed_id).data['status'] == 'completed'
        assert db.query(Record).filter_by(key='profile').one().data['name'] == 'Retained Applicant'
    backups = sorted((settings.data_dir / 'backups').glob('*.sqlite3'))
    assert backups
    connection = sqlite3.connect(backups[-1])
    try:
        import json
        original = connection.execute('SELECT data FROM records WHERE id = ?', (old_id,)).fetchone()
        assert json.loads(original[0])['status'] == 'running'
    finally:
        connection.close()
