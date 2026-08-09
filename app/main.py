from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, masters
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # для учебного проекта; в проде — конкретные домены
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(masters.router)

# Отдаём простой vanilla-JS фронтенд из /static (появится на следующем этапе)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
