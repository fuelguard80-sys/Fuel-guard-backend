from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from core.config import settings
from core.firebase import init_firebase
from routers import (
    auth, users, nozzles, sessions, transactions,
    reports, evidence, fraud, stations, prices,
    admin, fleet, iot,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production_settings()
    init_firebase()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="IoT-Based Fuel Dispenser Management — REST API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = settings.API_V1_PREFIX

app.include_router(auth.router,         prefix=PREFIX + "/auth",         tags=["Auth"])
app.include_router(users.router,        prefix=PREFIX + "/users",        tags=["Users"])
app.include_router(nozzles.router,      prefix=PREFIX + "/nozzles",      tags=["Nozzles"])
app.include_router(sessions.router,     prefix=PREFIX + "/sessions",     tags=["Sessions"])
app.include_router(transactions.router, prefix=PREFIX + "/transactions", tags=["Transactions"])
app.include_router(reports.router,      prefix=PREFIX + "/reports",      tags=["Reports"])
app.include_router(evidence.router,     prefix=PREFIX + "/evidence",     tags=["Evidence"])
app.include_router(fraud.router,        prefix=PREFIX + "/fraud",        tags=["Fraud"])
app.include_router(stations.router,     prefix=PREFIX + "/stations",     tags=["Stations"])
app.include_router(prices.router,       prefix=PREFIX + "/prices",       tags=["Prices"])
app.include_router(admin.router,        prefix=PREFIX + "/admin",        tags=["Admin"])
app.include_router(fleet.router,        prefix=PREFIX + "/fleet",        tags=["Fleet"])
app.include_router(iot.router,          prefix=PREFIX + "/iot",          tags=["IoT"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": settings.APP_NAME, "version": "1.0.0"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}
