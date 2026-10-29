import json
from datetime import datetime, timezone, date
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from demandflow.store import connect, current

app = FastAPI(title='DemandFlow', version='1.0.0')


@app.get('/health')
def health():
    return {'status':'ok'}


@app.get('/ready')
def ready():
    if not current():
        raise HTTPException(503, 'Run the pipeline first')
    return {'status':'ready', 'run_id':current()}


@app.get('/report')
def report():
    run_id = current()
    if not run_id:
        raise HTTPException(503, 'No published model')
    with connect() as con:
        return json.loads(con.execute('SELECT report FROM runs WHERE run_id=?',(run_id,)).fetchone()[0])


@app.get('/forecasts')
def forecasts(product_id: str | None = None, limit: int = Query(200, ge=1, le=5000)):
    run_id = current()
    if not run_id:
        raise HTTPException(503, 'No published forecast')
    query = 'SELECT date,product_id,prediction FROM forecasts WHERE run_id=?'
    params = [run_id]
    if product_id is not None:
        query += ' AND product_id=?'
        params.append(product_id)
    query += ' ORDER BY date,product_id LIMIT ?'
    with connect() as con:
        rows = con.execute(query, params+[limit]).fetchall()
    return {'run_id':run_id, 'forecasts':[dict(zip(['date','product_id','prediction'],r)) for r in rows]}


@app.get('/products')
def products():
    with connect() as con:
        rows = con.execute('SELECT DISTINCT product_id FROM forecasts WHERE run_id=? ORDER BY product_id', (current(),)).fetchall()
    return [row[0] for row in rows]


@app.get('/metrics')
def metrics():
    lines = []
    with connect() as con:
        for status, count in con.execute('SELECT status,COUNT(*) FROM runs GROUP BY status'):
            lines.append(f'demandflow_runs_total{{status="{status}"}} {count}')
        last = con.execute('SELECT status FROM runs ORDER BY created_at DESC LIMIT 1').fetchone()
        success = con.execute("SELECT created_at FROM runs WHERE status='success' ORDER BY created_at DESC LIMIT 1").fetchone()
    lines.append(f'demandflow_last_run_success {int(bool(last and last[0] == "success"))}')
    lines.append(f'demandflow_last_success_timestamp_seconds {datetime.fromisoformat(success[0]).timestamp() if success else 0}')
    if current():
        r = report()
        lines += [f'demandflow_validation_mae {r["validation"][r["model"]]["mae"]}',
                  f'demandflow_data_age_days {(datetime.now(timezone.utc).date()-date.fromisoformat(r["last_date"])).days}',
                  f'demandflow_alerts {len(r["alerts"])}']
        if r['realized']['wape'] is not None:
            lines.append(f'demandflow_realized_wape {r["realized"]["wape"]}')
    return Response('\n'.join(lines)+'\n', media_type='text/plain; version=0.0.4')


@app.get('/', response_class=HTMLResponse)
def index():
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><title>DemandFlow</title>
    <style>body{font:17px system-ui;background:#f3f5f8;color:#17253b;max-width:1000px;margin:50px auto;padding:20px}h1{font-size:40px}section{background:white;border-radius:16px;padding:24px;margin:20px 0}pre{white-space:pre-wrap}td,th{padding:8px 20px;text-align:left;border-bottom:1px solid #eee}a{color:#245bd0}</style>
    <h1>DemandFlow</h1><p>Прогнозирование спроса · ежедневный ML-пайплайн</p><a href="/docs">Документация API</a>
    <section><h2>Состояние модели</h2><pre id="report">Загрузка…</pre></section>
    <section><h2>Прогноз продаж</h2><select id="sku"></select>
    <table><thead><tr><th>Дата</th><th>Товар</th><th>Прогноз, шт.</th></tr></thead><tbody id="rows"></tbody></table></section>
    <script>async function load(){let r=await fetch('/report');let j=await r.json();document.getElementById('report').textContent=r.ok?JSON.stringify(j,null,2):'Сначала запустите pipeline';
    let f=await(await fetch('/forecasts?product_id='+encodeURIComponent(document.getElementById('sku').value))).json();let b=document.getElementById('rows');b.replaceChildren();for(let x of f.forecasts||[]){let tr=document.createElement('tr');for(let v of [x.date,x.product_id,x.prediction.toFixed(1)]){let td=document.createElement('td');td.textContent=v;tr.appendChild(td)}b.appendChild(tr)}}async function init(){let select=document.getElementById('sku');for(let p of await(await fetch('/products')).json()){let option=document.createElement('option');option.textContent=p;select.appendChild(option)}select.onchange=load;await load()}init();</script></html>'''
