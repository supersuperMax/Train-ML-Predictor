FROM python:3.12-slim
WORKDIR /app
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker ./worker
COPY data ./data
COPY model ./model
CMD ["python", "worker/worker.py"]
