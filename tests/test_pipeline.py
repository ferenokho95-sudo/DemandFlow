import json
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from demandflow.sample import generate
from demandflow.model import validate, features, forecast, select_model
from demandflow.pipeline import run
from demandflow.store import current, connect
from demandflow.api import app


@pytest.fixture
def sales(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMANDFLOW_HOME', str(tmp_path/'state'))
    path = tmp_path/'sales.csv'
    generate(path, days=100, products=3, end='2025-10-01')
    return path


def read(path):
    return pd.read_csv(path, dtype={'product_id': str})


@pytest.mark.parametrize('issue', ['duplicate', 'negative', 'missing_day', 'null', 'infinite', 'short', 'future', 'different_end'])
def test_invalid_data_rejected(sales, issue):
    df = read(sales)
    if issue == 'duplicate': df = pd.concat([df, df.iloc[:1]])
    if issue == 'negative': df.loc[0, 'units'] = -1
    if issue == 'missing_day': df = df.drop(20)
    if issue == 'null': df.loc[0, 'units'] = np.nan
    if issue == 'infinite': df['units'] = df.units.astype(float); df.loc[0, 'units'] = np.inf
    if issue == 'short': df = df.iloc[:10]
    if issue == 'future': df['date'] = (pd.to_datetime(df.date)+pd.Timedelta(days=5000)).dt.strftime('%Y-%m-%d')
    if issue == 'different_end': df = df.drop(99)
    with pytest.raises(ValueError): validate(df)


def test_features_do_not_use_current_or_future_target(sales):
    df = validate(read(sales))
    before, _ = features(df)
    df.loc[(df.product_id=='SKU-001') & (df.date >= '2025-09-15'), 'units'] += 10000
    after, _ = features(df)
    # Row for 15 September only uses observations before that date.
    index = 100-17-28
    pd.testing.assert_series_equal(before.iloc[index], after.iloc[index])
    assert not before.iloc[index+1].equals(after.iloc[index+1])


def test_forecast_and_selection(sales):
    df = validate(read(sales))
    winner, results, model = select_model(df)
    assert results[winner]['mae'] <= results['seasonal_naive']['mae']
    pred = forecast(df, 14, model)
    assert len(pred) == 42 and pred.prediction.ge(0).all()
    assert pred.date.min() == '2025-10-02' and pred.date.max() == '2025-10-15'
    assert not pred.duplicated(['date','product_id']).any()


def test_failed_update_keeps_published_forecast(sales):
    report = run(sales)
    old = current()
    bad = read(sales); bad.loc[0,'units'] = -1; bad.to_csv(sales, index=False)
    with pytest.raises(ValueError): run(sales)
    assert current() == old == report['run_id']
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM runs WHERE status='failed'").fetchone()[0] == 1


def test_repeated_run_and_new_actuals(sales):
    first = run(sales)
    second = run(sales)
    assert first['run_id'] != second['run_id']
    assert second['realized']['matched'] == 0
    assert first['validation'] == second['validation']
    generate(sales, days=101, products=3, end='2025-10-02')
    third = run(sales)
    assert third['realized']['matched'] == 3
    with connect() as con:
        count = con.execute('SELECT COUNT(*) FROM forecasts WHERE run_id=?',(third['run_id'],)).fetchone()[0]
    assert count == 42


def test_api_and_metrics(sales):
    client = TestClient(app)
    assert client.get('/ready').status_code == 503
    assert client.get('/health').status_code == 200
    report = run(sales)
    assert client.get('/ready').status_code == 200
    assert client.get('/products').json() == ['SKU-001', 'SKU-002', 'SKU-003']
    response = client.get('/forecasts?product_id=SKU-001').json()
    assert response['run_id'] == report['run_id'] and len(response['forecasts']) == 14
    assert client.get('/forecasts?limit=0').status_code == 422
    assert client.get('/forecasts', params={'product_id': "' OR 1=1 --"}).json()['forecasts'] == []
    assert 'demandflow_last_run_success 1' in client.get('/metrics').text
    assert client.get('/report').json()['run_id'] == report['run_id']


def test_external_sink_failure_keeps_active(sales, monkeypatch):
    import sys
    from types import SimpleNamespace
    first = run(sales)
    def broken(*args): raise RuntimeError('Storage unavailable')
    monkeypatch.setitem(sys.modules, 'demandflow.integrations', SimpleNamespace(sync=broken))
    with pytest.raises(RuntimeError): run(sales, full=True)
    assert current() == first['run_id']


def test_zero_demand(sales):
    df = read(sales); df['units'] = 0; df.to_csv(sales, index=False)
    report = run(sales)
    assert report['validation'][report['model']]['wape'] is None
    assert report['validation'][report['model']]['mae'] == 0
