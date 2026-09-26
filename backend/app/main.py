from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.forecast import router as forecast_router
from app.api.routes import router as routes_router
from app.api.export import router as export_router

app = FastAPI(title="Tram Passenger Flow Forecast API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(forecast_router, prefix="/api")
app.include_router(routes_router, prefix="/api")
app.include_router(export_router, prefix="/api")

@app.get("/health")
def health():
    return {"status": "ok"}
