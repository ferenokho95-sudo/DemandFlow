"""Optional full-stack sinks; exceptions intentionally fail publication."""
import os
import pandas as pd


def sync(df, forecast, directory, run_id, report):
    from sqlalchemy import create_engine, text
    import clickhouse_connect
    import boto3
    from botocore.config import Config
    import mlflow
    engine = create_engine(os.environ['DWH_URL'], pool_pre_ping=True)
    daily = df.assign(date=df.date.dt.date)
    with engine.begin() as con:
        con.execute(text('''CREATE TABLE IF NOT EXISTS sales_daily (
          date DATE NOT NULL, product_id TEXT NOT NULL, units DOUBLE PRECISION NOT NULL CHECK(units>=0),
          PRIMARY KEY(date,product_id))'''))
        # Full validated CSV is an authoritative snapshot; replacement is transactional.
        con.execute(text('DELETE FROM sales_daily'))
        daily.to_sql('sales_daily', con, if_exists='append', index=False, method='multi', chunksize=1000)
        con.execute(text('''CREATE TABLE IF NOT EXISTS forecast_runs (
          run_id TEXT PRIMARY KEY, model TEXT, validation_mae DOUBLE PRECISION)'''))
        con.execute(text('INSERT INTO forecast_runs VALUES (:r,:m,:v) ON CONFLICT(run_id) DO NOTHING'),
                    {'r': run_id, 'm': report['model'], 'v': report['validation'][report['model']]['mae']})
    engine.dispose()
    ch = clickhouse_connect.get_client(host=os.environ.get('CLICKHOUSE_HOST', 'clickhouse'),
                                      username='demand', password=os.environ['CLICKHOUSE_PASSWORD'])
    ch.command('''CREATE TABLE IF NOT EXISTS forecasts (
      run_id String, date Date, product_id String, prediction Float64)
      ENGINE=ReplacingMergeTree ORDER BY (run_id,date,product_id)''')
    export = forecast.assign(run_id=run_id, date=pd.to_datetime(forecast.date).dt.date)
    ch.insert_df('forecasts', export[['run_id','date','product_id','prediction']])
    ch.close()
    s3 = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT_URL'],
                      config=Config(request_checksum_calculation='when_required', response_checksum_validation='when_required'))
    bucket = 'demandflow'
    existing = [b['Name'] for b in s3.list_buckets()['Buckets']]
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)
    for file in directory.iterdir():
        if file.is_file():
            s3.upload_file(str(file), bucket, f'runs/{run_id}/{file.name}')
    mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI'])
    mlflow.set_experiment('demandflow')
    with mlflow.start_run(run_name=run_id):
        mlflow.log_params({'winner': report['model'], 'horizon': report['horizon'], 'data_sha256': report['data_sha256']})
        for model_name, metrics in report['validation'].items():
            mlflow.log_metrics({f'{model_name}_{k}': v for k,v in metrics.items() if v is not None})
        mlflow.log_artifacts(str(directory), artifact_path='pipeline')
