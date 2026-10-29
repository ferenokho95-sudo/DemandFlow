from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator


def daily_pipeline():
    from demandflow.pipeline import run
    return run('/data/sales.csv', horizon=14, full=True)['run_id']


with DAG('demandflow_daily', start_date=datetime(2025, 1, 1), schedule='0 6 * * *',
         catchup=False, max_active_runs=1, is_paused_upon_creation=True,
         default_args={'retries': 2, 'retry_delay': timedelta(minutes=2)},
         tags=['ml', 'demandflow']) as dag:
    PythonOperator(task_id='validate_train_monitor_publish', python_callable=daily_pipeline)
