FROM python:3.11.11-slim
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-full.txt
COPY demandflow ./demandflow
COPY data ./data
ENV PYTHONUNBUFFERED=1 DEMANDFLOW_HOME=/state
CMD ["python", "-m", "uvicorn", "demandflow.api:app", "--host", "0.0.0.0", "--port", "8000"]
