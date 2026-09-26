import hashlib
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse, Response

from app import errors
from app.api.export import router as export_router
from app.api.forecast import router as forecast_router
from app.api.predict import router as predict_router
from app.api.datasets import router as datasets_router
from app.api.routes import router as routes_router
from app.services.snapshot import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Tram Passenger Flow Forecast API", version="0.2.0",
              default_response_class=ORJSONResponse, docs_url="/api/docs", openapi_url="/api/openapi.json")
# За nginx-прокси фронт и API на одном origin; CORS нужен только для локальной разработки.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


class SelectiveGZip:
    """GZip для JSON-ответов API; файлы (/api/predict/batch, /api/export) отдаются без сжатия — сжимать гигабайты на лету дорого."""

    def __init__(self, app, skip: tuple[str, ...] = ("/api/predict/batch", "/api/export/", "/api/datasets")):
        self.app, self.skip = app, skip
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(self.skip):
            return await self.app(scope, receive, send)
        return await self.gzip(scope, receive, send)


app.add_middleware(SelectiveGZip)
errors.install(app)

app.include_router(forecast_router, prefix="/api")
app.include_router(routes_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(predict_router, prefix="/api")
app.include_router(datasets_router, prefix="/api")


@app.middleware("http")
async def etag_cache(request: Request, call_next):
    """Ответы зависят только от версии snapshot и URL — отдаём ETag и 304 на повторные запросы."""
    snap = store.get() if request.method == "GET" and request.url.path.startswith("/api/") else None
    if snap is None or request.url.path.startswith("/api/docs"):
        return await call_next(request)
    etag = '"' + hashlib.md5(f"{snap.version}|{request.url.path}?{request.url.query}".encode()).hexdigest() + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response = await call_next(request)
    if response.status_code == 200:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=30"
    return response


@app.get("/health", summary="Живость сервиса")
def health():
    snap = store.get()
    return {"status": "ok", "snapshot": snap.version if snap else None}


@app.get("/ready", summary="Готовность: snapshot прогноза загружен")
def ready():
    snap = store.get()
    if snap is None:
        raise errors.not_ready()
    return {"status": "ready", "snapshot": snap.version}
