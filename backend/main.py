from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from config import UPLOAD_DIR
from db import init_db
from routers import health, settings, login, curriculum, lessons, articles, progress, skills, stats, coins


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.include_router(health.router)
app.include_router(settings.router)
app.include_router(login.router)
app.include_router(curriculum.router)
app.include_router(lessons.router)
app.include_router(articles.router)
app.include_router(progress.router)
app.include_router(skills.router)
app.include_router(stats.router)
app.include_router(coins.router)
