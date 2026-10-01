FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY storage_server.py storage_pb2.py storage_pb2_grpc.py ./
CMD ["python3", "storage_server.py"]
