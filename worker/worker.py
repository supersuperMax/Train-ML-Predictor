import time

# TODO: сюда подключаем готовую модель и realtime/batch pipeline.
# Первый рабочий цикл: ingest -> normalize -> aggregate -> inference -> snapshot.

print("worker started")
while True:
    time.sleep(60)
