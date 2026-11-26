import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import gradio as gr
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import interfaces
from .manager import MODELS, Busy, Manager

HERE = Path(__file__).parent


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin model controls are disabled.")


def known_model(key: str):
    if key not in MODELS:
        raise HTTPException(404, "Unknown model")
    return key


def conversion(manager, key):
    def convert(*args):
        if not args[0] or not args[1]:
            raise gr.Error("Choose both source and reference audio.")
        try:
            yield from manager.convert(key, *args)
        except RuntimeError as exc:
            raise gr.Error(str(exc)) from exc

    return convert


def create_app(manager=None):
    data = Path(os.getenv("SEEDVC_DATA", "hub-data")).resolve()
    manager = manager or Manager(data)
    templates = Jinja2Templates(directory=HERE / "templates")

    @asynccontextmanager
    async def lifespan(_app):
        preload = [s.strip() for s in os.getenv("SEEDVC_PRELOAD", "").split(",") if s.strip()]
        if set(preload) - MODELS.keys():
            raise ValueError("SEEDVC_PRELOAD accepts only speech,singing,style")
        try:
            for key in preload:
                manager.load(key)
            yield
        finally:
            manager.unload(shutdown=True)

    app = FastAPI(title="Seed-VC hub", lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=HERE / "static"), name="assets")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def home(request: Request):
        return templates.TemplateResponse(request, "index.html", {"models": MODELS})

    @app.get("/outputs/")
    def outputs(request: Request):
        files = sorted(manager.outputs.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        return templates.TemplateResponse(request, "outputs.html", {"files": [p.name for p in files]})

    app.mount("/outputs/files", StaticFiles(directory=manager.outputs), name="files")

    @app.get("/api/models")
    def models():
        return manager.status()

    @app.post("/api/models/{key}/load", status_code=202, dependencies=[Depends(same_origin)])
    def load(key: str = Depends(known_model)):
        return {"id": key, "state": manager.load(key)}

    def unload(key):
        try:
            manager.unload(key)
        except Busy as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"state": "unloaded"}

    @app.post("/api/models/{key}/unload", dependencies=[Depends(same_origin)])
    def unload_one(key: str = Depends(known_model)):
        return unload(key)

    @app.post("/api/models/unload", dependencies=[Depends(same_origin)])
    def unload_all():
        return unload(None)

    intro = '<a href="/">Back to model hub</a> &middot; <a href="/outputs/">Saved WAVs</a><br>'
    for key in MODELS:
        blocks = interfaces.create_interface(key, conversion(manager, key), intro)
        gr.mount_gradio_app(app, blocks, path=f"/tools/{key}",
                            allowed_paths=[str(manager.outputs)], blocked_paths=[str(data / "models")])
    return app
