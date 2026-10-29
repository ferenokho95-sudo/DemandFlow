import os
import sqlite3
from pathlib import Path
import pandas as pd


def root():
    path = Path(os.environ.get('DEMANDFLOW_HOME', 'var'))
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect():
    con = sqlite3.connect(root()/'state.db', timeout=30)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, status TEXT, created_at TEXT, report TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS forecasts (run_id TEXT, date TEXT, product_id TEXT, prediction REAL, PRIMARY KEY(run_id,date,product_id))')
    con.execute('CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY CHECK(id=1), run_id TEXT)')
    con.commit()
    return con


def current():
    with connect() as con:
        record = con.execute('SELECT run_id FROM active WHERE id=1').fetchone()
    return record[0] if record else None


def publish(run_id, frame, report):
    import json
    with connect() as con:
        con.executemany('INSERT INTO forecasts VALUES (?,?,?,?)',
                        [(run_id, r.date, r.product_id, r.prediction) for r in frame.itertuples(index=False)])
        con.execute("UPDATE runs SET status='success', report=? WHERE run_id=?", (json.dumps(report), run_id))
        con.execute('INSERT INTO active VALUES (1,?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id', (run_id,))


def realized_errors(df):
    with connect() as con:
        # Monitor one most recently issued forecast per date/product, never average vintages.
        old = pd.read_sql_query('''SELECT f.* FROM forecasts f JOIN runs r USING(run_id)
          WHERE r.status='success' ''', con)
        runs = pd.read_sql_query('SELECT run_id, created_at FROM runs', con)
    if old.empty:
        return {'matched': 0, 'mae': None, 'wape': None}
    old = old.merge(runs, on='run_id').sort_values('created_at').drop_duplicates(['date','product_id'], keep='last')
    actual = df.assign(date=df.date.dt.strftime('%Y-%m-%d'))
    matched = actual.merge(old, on=['date','product_id'])
    if matched.empty:
        return {'matched': 0, 'mae': None, 'wape': None}
    from demandflow.model import scores
    return {'matched': len(matched), **scores(matched.units.to_numpy(), matched.prediction.to_numpy())}
