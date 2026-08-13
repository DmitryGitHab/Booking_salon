"""
Нагрузочный тест на чтение каталога — GET /api/masters и GET /api/masters/{id}/slots.
Намеренно read-only: не создаёт брони и не трогает состояние БД, поэтому его можно
гонять повторно без побочных эффектов и без отдельной подготовки между запусками.

Подготовка (один раз, БД должна быть пустой или уже содержать мастеров):
    python -m scripts.seed_demo_data

Запуск:
    locust -f locustfile.py --host http://localhost:8000

Дальше открыть http://localhost:8089, задать число пользователей/скорость роста
и нажать Start. Результаты (RPS, p50/p95 latency, число ошибок) — прямо в веб-интерфейсе
Locust, вкладка Statistics/Charts.
"""
import random

from locust import HttpUser, between, task


class CatalogBrowser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(3)
    def list_masters(self):
        self.client.get("/api/masters", name="/api/masters")

    @task(2)
    def list_slots_of_random_master(self):
        # Реалистичный паттерн: сначала листаем каталог, потом открываем случайного
        # мастера — а не бьём в один и тот же захардкоженный id.
        resp = self.client.get("/api/masters", name="/api/masters")
        try:
            masters = resp.json()
        except ValueError:
            return
        if not masters:
            return
        master = random.choice(masters)
        self.client.get(f"/api/masters/{master['id']}/slots", name="/api/masters/[id]/slots")

    @task(1)
    def health_check(self):
        self.client.get("/api/health", name="/api/health")
