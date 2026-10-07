"""Pinchazo: un juego de cartas de globos para jugar en el navegador, con personas y bots.

Rutas
  GET  /                         la web del juego
  POST /api/salas                crea una sala y devuelve el código y tu «token» (tu llave de asiento)
  POST /api/salas/{codigo}/unirse
  POST /api/rapida               partida contra bots, lista para jugar
  GET  /api/salas/{codigo}       ¿existe la sala y cuánta gente hay?
  WS   /ws/{codigo}              la partida en tiempo real (el primer mensaje trae tu token)
"""
import asyncio
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import salas as modulo_salas
from .juego.cartas import CARTAS
from .juego.motor import ReglaError
from .salas import Salas, limpiar_nombre

ESTATICOS = Path(__file__).parent / "static"
MAX_MENSAJE = 2000   # bytes: ningún mensaje legítimo es más grande
MAX_MENSAJES_5S = 40  # por conexión; una persona jugando no llega ni a 10

salas = Salas()


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    async def limpieza():
        while True:
            await asyncio.sleep(30)
            await salas.limpiar()

    tarea = asyncio.create_task(limpieza())
    yield
    tarea.cancel()
    for sala in salas.salas.values():
        if sala.tarea:
            sala.tarea.cancel()


app = FastAPI(title="Pinchazo", version="1.0", lifespan=ciclo_de_vida)


@app.middleware("http")
async def cabeceras_de_seguridad(request, call_next):
    respuesta = await call_next(request)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    return respuesta


# ---------------------------------------------------------------- modelos de entrada
class CrearSala(BaseModel):
    nombre: str = Field(default="Jugador", max_length=40)
    plazas: int = Field(default=4, ge=2, le=5)
    rellenar: bool = True
    nivel: Literal["facil", "medio", "dificil"] = "medio"


class Unirse(BaseModel):
    nombre: str = Field(default="Jugador", max_length=40)


class PartidaRapida(BaseModel):
    nombre: str = Field(default="Jugador", max_length=40)
    rivales: int = Field(default=3, ge=1, le=4)
    nivel: Literal["facil", "medio", "dificil"] = "medio"


def _credenciales(sala, asiento) -> dict:
    return {"codigo": sala.codigo, "token": asiento.token, "id": asiento.id}


# ---------------------------------------------------------------- API
@app.post("/api/salas")
async def crear_sala(datos: CrearSala):
    try:
        sala, asiento = salas.crear(datos.nombre, datos.plazas, datos.rellenar, datos.nivel)
    except ReglaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _credenciales(sala, asiento)


@app.post("/api/salas/{codigo}/unirse")
async def unirse(codigo: str, datos: Unirse):
    try:
        sala, asiento = salas.unirse(codigo, datos.nombre)
    except ReglaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await modulo_salas.difundir(sala)
    return _credenciales(sala, asiento)


@app.post("/api/rapida")
async def partida_rapida(datos: PartidaRapida):
    try:
        sala, asiento = salas.crear(datos.nombre, datos.rivales + 1, True, datos.nivel)
        async with sala.lock:
            await salas.iniciar(sala)
    except ReglaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _credenciales(sala, asiento)


@app.get("/api/salas/{codigo}")
async def ver_sala(codigo: str):
    sala = salas.get(codigo)
    if not sala:
        raise HTTPException(status_code=404, detail="Esa sala no existe.")
    return {"existe": True, "estado": sala.estado, "humanos": len(sala.humanos()), "plazas": sala.plazas}


@app.get("/api/cartas")
async def cartas():
    """El catálogo de cartas, para que la web dibuje cada una."""
    return CARTAS


@app.get("/salud")
async def salud():
    return {"ok": True, "salas": len(salas.salas)}


# ---------------------------------------------------------------- tiempo real
@app.websocket("/ws/{codigo}")
async def partida(websocket: WebSocket, codigo: str):
    """La llave del asiento (token) se envía como primer mensaje y no en la dirección,
    para que no quede escrita en los registros del servidor."""
    await websocket.accept()
    sala = salas.get(codigo)
    token = ""
    try:
        primero = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=modulo_salas.seg(10)))
        if isinstance(primero, dict) and primero.get("accion") == "entrar":
            token = str(primero.get("token", ""))
    except WebSocketDisconnect:
        return
    except (asyncio.TimeoutError, json.JSONDecodeError):
        pass
    asiento = sala.por_token(token) if sala else None
    if not sala or not asiento:
        await websocket.send_json({"t": "error", "fatal": True, "mensaje": "Esa sala ya no existe o tu plaza no es válida."})
        await websocket.close(code=4404)
        return
    await salas.conectar(sala, asiento, websocket)
    recientes: deque[float] = deque()
    try:
        while True:
            texto = await websocket.receive_text()
            ahora = time.monotonic()
            recientes.append(ahora)
            while recientes and ahora - recientes[0] > 5:
                recientes.popleft()
            if len(recientes) > MAX_MENSAJES_5S:           # demasiados mensajes: se ignora el exceso
                continue
            if len(texto) > MAX_MENSAJE:
                await modulo_salas.enviar_error(asiento, "Mensaje demasiado grande.")
                continue
            try:
                msg = json.loads(texto)
            except json.JSONDecodeError:
                await modulo_salas.enviar_error(asiento, "Mensaje no válido.")
                continue
            if not isinstance(msg, dict):
                continue
            await modulo_salas.mensaje(salas, sala, asiento, msg)
    except WebSocketDisconnect:
        pass
    finally:
        await salas.desconectar(sala, asiento, websocket)


# ---------------------------------------------------------------- la web
app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")


@app.get("/", include_in_schema=False)
async def inicio():
    return FileResponse(ESTATICOS / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(ESTATICOS / "favicon.svg", media_type="image/svg+xml")
