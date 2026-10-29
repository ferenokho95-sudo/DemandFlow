import hashlib
import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import joblib
import pandas as pd
from demandflow.model import validate, select_model, forecast, features
from demandflow.store import root, connect, publish, realized_errors

log = logging.getLogger(__name__)


def run(csv_path='data/sales.csv', horizon=14, full=False):
    if not 1 <= horizon <= 60:
        raise ValueError('Horizon must be between 1 and 60')
    # Cross-platform single-writer lock via SQLite. Readers use a separate database.
    lock = sqlite3.connect(root()/'pipeline-lock.db', timeout=1)
    lock.execute('CREATE TABLE IF NOT EXISTS mutex (id INTEGER PRIMARY KEY)')
    lock.commit()
    lock.execute('BEGIN IMMEDIATE')
    run_id = uuid.uuid4().hex
    start = time.monotonic()
    with connect() as con:
        con.execute('INSERT INTO runs VALUES (?,?,?,?)', (run_id, 'running', datetime.now(timezone.utc).isoformat(), '{}'))
    try:
        directory = root()/'runs'/run_id
        directory.mkdir(parents=True)
        # Capture bytes once: training data and checksum refer to the same snapshot.
        snapshot = directory/'sales.csv'
        snapshot.write_bytes(Path(csv_path).read_bytes())
        df = validate(pd.read_csv(snapshot, dtype={'product_id': str}))
        winner, validation, model = select_model(df)
        predictions = forecast(df, horizon, model)
        report = {'run_id': run_id, 'model': winner, 'horizon': horizon, 'rows': len(df),
                  'products': int(df.product_id.nunique()), 'last_date': df.date.max().strftime('%Y-%m-%d'),
                  'data_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                  'validation': validation, 'realized': realized_errors(df),
                  'data_age_days': int((pd.Timestamp.now().normalize()-df.date.max()).days)}
        report['alerts'] = []
        if report['data_age_days'] > 2:
            report['alerts'].append('stale_data')
        if report['realized']['wape'] is not None and report['realized']['wape'] > 0.3:
            report['alerts'].append('forecast_wape_above_30_percent')
        predictions.to_csv(directory/'forecasts.csv', index=False)
        x, _ = features(df)
        x.to_csv(directory/'features.csv', index=False)
        joblib.dump({'model': model, 'winner': winner}, directory/'model.joblib')
        report['duration_seconds'] = time.monotonic()-start
        (directory/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if full:
            from demandflow.integrations import sync
            sync(df, predictions, directory, run_id, report)
        publish(run_id, predictions, report)
        log.info(json.dumps({'event':'pipeline_success', **report}))
        return report
    except Exception as error:
        with connect() as con:
            con.execute("UPDATE runs SET status='failed', report=? WHERE run_id=?", (json.dumps({'error': str(error)}), run_id))
        log.exception('Pipeline failed: %s', run_id)
        raise
    finally:
        lock.rollback()
        lock.close()
