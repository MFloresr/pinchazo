"""Salas de juego: personas y bots, turnos con tiempo límite, reconexión y difusión del estado.

Cada sala tiene un «conductor» (una tarea asíncrona) que hace avanzar la partida:
  - si le toca a un bot (o a alguien con el piloto automático), decide tras una pausa para que se vea;
  - si le toca a una persona, espera su acción y, si se pasa del tiempo, juega el piloto automático por ella;
  - tras cada carta jugada abre una ventana de unos segundos para que se pueda responder «¡Ni hablar!».

El servidor decide todo. Cada persona recibe solo lo que puede ver (su mano, no la de las demás).
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import secrets
import time
from dataclasses import dataclass

from fastapi import WebSocket

from .juego import bots
from .juego.cartas import CARTAS
from .juego.motor import MAX_JUGADORES, MIN_JUGADORES, Fase, Partida, ReglaError

log = logging.getLogger("pinchazo")

# 1 = ritmo normal. Los tests lo bajan (p. ej. 0.01) para que las partidas pasen deprisa.
RITMO = float(os.environ.get("PINCHAZO_RITMO", "1"))
VENTANA_S = 4.0            # tiempo para responder «¡Ni hablar!» tras una carta
TURNO_S = 45.0             # tiempo para jugar tu turno
FAVOR_S = 25.0             # tiempo para elegir qué carta das
INSERTAR_S = 30.0          # tiempo para esconder el Pinchazo
PAUSA_BOT = (0.9, 1.8)     # lo que «piensa» un bot
PAUSA_BOT_RAPIDA = (0.25, 0.5)   # cuando ya no queda ninguna persona viva
REACCION_BOT = (0.6, 2.4)  # cuánto tarda un bot en responder «¡Ni hablar!»
AUTO_TRAS_FALLOS = 2       # turnos seguidos sin responder antes de pasar al piloto automático
GRACIA_CONEXION_S = 90     # una persona sin conexión en el vestíbulo se quita pasado este tiempo
SALA_VACIA_S = 600         # sala sin nadie conectado
MAX_SALAS = 200
LETRAS = "ABCDEFGHJKLMNPQRSTUVWXYZ"   # sin I ni O, para no confundirlas con 1 y 0
NIVELES = tuple(bots.NIVELES)
ORDEN_MANO = list(CARTAS)


def seg(x: float) -> float:
    return x * RITMO


def ahora() -> float:
    return time.monotonic()


def limpiar_nombre(nombre: str | None, defecto: str = "Jugador") -> str:
    limpio = "".join(c for c in (nombre or "") if c.isprintable()).strip()[:16]
    return limpio or defecto


@dataclass
class Asiento:
    id: str
    nombre: str
    token: str
    es_bot: bool = False
    ws: WebSocket | None = None
    auto: bool = False                 # piloto automático (no responde o se ha ido)
    fallos: int = 0
    desconectado_desde: float | None = None

    @property
    def conectado(self) -> bool:
        return self.ws is not None


class Sala:
    def __init__(self, codigo: str, plazas: int, rellenar: bool, nivel: str):
        self.codigo = codigo
        self.plazas = plazas
        self.rellenar = rellenar
        self.nivel = nivel
        self.asientos: list[Asiento] = []
        self.duenio: str | None = None
        self.estado = "lobby"          # lobby | jugando | fin
        self.partida: Partida | None = None
        self.espera: dict | None = None   # {"jugador": id | None, "hasta": instante}
        self.lock = asyncio.Lock()
        self.evento = asyncio.Event()
        self.tarea: asyncio.Task | None = None
        self.sin_gente_desde: float | None = ahora()
        self.rng = random.Random()

    # -------------------------------------------------------------- consultas
    def por_token(self, token: str) -> Asiento | None:
        return next((a for a in self.asientos if a.token == token and not a.es_bot), None)

    def asiento(self, aid: str) -> Asiento:
        return next(a for a in self.asientos if a.id == aid)

    def humanos(self) -> list[Asiento]:
        return [a for a in self.asientos if not a.es_bot]

    def hay_humanos_conectados(self) -> bool:
        return any(a.conectado for a in self.humanos())

    def hay_humanos_vivos(self) -> bool:
        if not self.partida:
            return False
        vivos = {j.id for j in self.partida.vivos()}
        return any(a.id in vivos for a in self.humanos())

    # -------------------------------------------------------------- vista
    def vista(self, aid: str) -> dict:
        """Lo que ve una persona concreta. Nunca incluye las manos ajenas ni el contenido del mazo."""
        p = self.partida
        v: dict = {
            "sala": {"codigo": self.codigo, "estado": self.estado, "plazas": self.plazas,
                     "rellenar": self.rellenar, "nivel": self.nivel, "duenio": self.duenio, "yo": aid},
            "asientos": [{"id": a.id, "nombre": a.nombre, "bot": a.es_bot, "conectado": a.conectado or a.es_bot,
                          "auto": a.auto} for a in self.asientos],
        }
        if p is None:
            return v
        espera = None
        if self.espera:
            espera = {"jugador": self.espera["jugador"], "segundos": max(0.0, self.espera["hasta"] - ahora()) / (RITMO or 1)}
        yo = p.jugador(aid) if any(j.id == aid for j in p.jugadores) else None
        v["partida"] = {
            "fase": p.fase.value,
            "turno": p.actual().id if p.fase != Fase.FIN else None,
            "turnos_pendientes": p.turnos_pendientes,
            "numero_turno": p.numero_turno,
            "jugadores": [{"id": j.id, "nombre": j.nombre, "bot": j.es_bot, "cartas": len(j.mano), "vivo": j.vivo,
                           "conectado": self.asiento(j.id).conectado or j.es_bot, "auto": self.asiento(j.id).auto}
                          for j in p.jugadores],
            "mazo": len(p.mazo),
            "riesgo": round(p.riesgo(), 3),
            "descarte": len(p.descarte),
            "tope_descarte": p.descarte[-1] if p.descarte else None,
            "yo": {"mano": sorted(yo.mano, key=ORDEN_MANO.index) if yo else [],
                   "vision": p.visiones.get(aid) if yo else None,
                   "vivo": bool(yo and yo.vivo)},
            "pendiente": None if not p.pendiente else {
                "jugador": p.pendiente.jugador, "cartas": p.pendiente.cartas, "objetivo": p.pendiente.objetivo,
                "negada": p.pendiente.negada, "cadena": len(p.pendiente.cadena), "puedo_negar": p.puede_negar(aid)},
            "favor": p.favor,
            "insertando": p.insertando,
            "espera": espera,
            "log": p.log[-30:],
            "ganador": p.ganador,
        }
        return v


class Salas:
    """Todas las salas abiertas, en memoria. (Si el servidor se reinicia, las partidas en curso se pierden.)"""

    def __init__(self):
        self.salas: dict[str, Sala] = {}

    # -------------------------------------------------------------- crear y entrar
    def _codigo(self) -> str:
        while True:
            c = "".join(secrets.choice(LETRAS) for _ in range(4))
            if c not in self.salas:
                return c

    def crear(self, nombre: str, plazas: int, rellenar: bool, nivel: str) -> tuple[Sala, Asiento]:
        if len(self.salas) >= MAX_SALAS:
            raise ReglaError("Hay demasiadas salas abiertas ahora mismo. Inténtalo en unos minutos.")
        if not MIN_JUGADORES <= plazas <= MAX_JUGADORES:
            raise ReglaError(f"Se juega de {MIN_JUGADORES} a {MAX_JUGADORES} personas.")
        if nivel not in NIVELES:
            nivel = "medio"
        sala = Sala(self._codigo(), plazas, rellenar, nivel)
        self.salas[sala.codigo] = sala
        asiento = self._nuevo_asiento(sala, nombre)
        sala.duenio = asiento.id
        return sala, asiento

    def _nuevo_asiento(self, sala: Sala, nombre: str) -> Asiento:
        nombres = {a.nombre.lower() for a in sala.asientos}
        base = limpiar_nombre(nombre)
        final, n = base, 2
        while final.lower() in nombres:
            final = f"{base[:13]} {n}"
            n += 1
        a = Asiento(id="p" + secrets.token_hex(3), nombre=final, token=secrets.token_urlsafe(18))
        sala.asientos.append(a)
        return a

    def unirse(self, codigo: str, nombre: str) -> tuple[Sala, Asiento]:
        sala = self.salas.get(codigo.upper())
        if not sala:
            raise ReglaError("Esa sala no existe. Revisa el código.")
        if sala.estado != "lobby":
            raise ReglaError("Esa partida ya ha empezado.")
        if len(sala.humanos()) >= sala.plazas:
            raise ReglaError("La sala está llena.")
        return sala, self._nuevo_asiento(sala, nombre)

    def get(self, codigo: str) -> Sala | None:
        return self.salas.get(codigo.upper())

    # -------------------------------------------------------------- partida
    async def iniciar(self, sala: Sala) -> None:
        """Rellena con bots los asientos que falten y empieza. (Hay que tener el cerrojo de la sala.)"""
        if sala.estado != "lobby":
            raise ReglaError("La partida ya está en marcha.")
        humanos = sala.humanos()
        faltan = sala.plazas - len(humanos) if sala.rellenar else 0
        if len(humanos) + faltan < MIN_JUGADORES:
            raise ReglaError("Se necesitan al menos 2 jugadores: activa «Completar con bots» o espera a más gente.")
        libres = [n for n in bots.NOMBRES if n.lower() not in {a.nombre.lower() for a in sala.asientos}]
        sala.rng.shuffle(libres)
        for i in range(faltan):
            sala.asientos.append(Asiento(id=f"bot{i + 1}", nombre=libres[i], token="", es_bot=True))
        sala.rng.shuffle(sala.asientos)   # el orden de turnos es aleatorio
        for a in sala.asientos:
            a.auto, a.fallos = False, 0
        sala.partida = Partida([(a.id, a.nombre, a.es_bot) for a in sala.asientos])
        sala.estado = "jugando"
        sala.tarea = asyncio.create_task(conducir(sala, self))

    def volver_al_vestibulo(self, sala: Sala) -> None:
        if sala.estado != "fin":
            raise ReglaError("La partida aún no ha terminado.")
        sala.asientos = [a for a in sala.asientos if not a.es_bot]
        sala.partida, sala.espera, sala.estado = None, None, "lobby"
        for a in sala.asientos:
            a.auto, a.fallos = False, 0

    # -------------------------------------------------------------- conexiones
    async def conectar(self, sala: Sala, asiento: Asiento, ws: WebSocket) -> None:
        anterior = asiento.ws
        asiento.ws, asiento.desconectado_desde = ws, None
        if sala.estado == "jugando":
            asiento.auto, asiento.fallos = False, 0   # vuelve a mandar quien se había ido
        sala.sin_gente_desde = None
        if anterior is not None and anterior is not ws:
            try:
                await anterior.close(code=4000)
            except Exception:
                pass
        sala.evento.set()
        await difundir(sala)

    async def desconectar(self, sala: Sala, asiento: Asiento, ws: WebSocket) -> None:
        if asiento.ws is not ws:
            return
        asiento.ws, asiento.desconectado_desde = None, ahora()
        if not sala.hay_humanos_conectados():
            sala.sin_gente_desde = ahora()
        sala.evento.set()
        await difundir(sala)

    async def salir(self, sala: Sala, asiento: Asiento) -> None:
        """Quien sale del vestíbulo libera su plaza; quien sale en plena partida deja el piloto automático."""
        if sala.estado == "lobby":
            sala.asientos.remove(asiento)
            if not sala.humanos():
                self.salas.pop(sala.codigo, None)
                return
            if sala.duenio == asiento.id:
                sala.duenio = sala.humanos()[0].id
        else:
            asiento.auto = True
            asiento.ws = None
        sala.evento.set()
        await difundir(sala)

    # -------------------------------------------------------------- limpieza
    async def limpiar(self) -> None:
        """Quita salas abandonadas y personas que se fueron del vestíbulo sin avisar."""
        for codigo, sala in list(self.salas.items()):
            if sala.estado == "lobby":
                for a in list(sala.humanos()):
                    if a.desconectado_desde and ahora() - a.desconectado_desde > GRACIA_CONEXION_S:
                        await self.salir(sala, a)
            if codigo in self.salas and sala.sin_gente_desde and ahora() - sala.sin_gente_desde > SALA_VACIA_S:
                if sala.tarea:
                    sala.tarea.cancel()
                self.salas.pop(codigo, None)


# ====================================================================== difusión
async def difundir(sala: Sala) -> None:
    """Envía a cada persona conectada su vista actual."""
    for a in list(sala.asientos):
        if a.ws is None:
            continue
        try:
            await a.ws.send_json({"t": "estado", "vista": sala.vista(a.id)})
        except Exception:
            a.ws, a.desconectado_desde = None, ahora()


async def enviar_error(asiento: Asiento, mensaje: str) -> None:
    if asiento.ws is not None:
        try:
            await asiento.ws.send_json({"t": "error", "mensaje": mensaje})
        except Exception:
            pass


# ====================================================================== mensajes de las personas
async def mensaje(salas: Salas, sala: Sala, asiento: Asiento, msg: dict) -> None:
    accion = msg.get("accion")
    if accion == "ping":
        if asiento.ws is not None:
            await asiento.ws.send_json({"t": "pong"})
        return
    try:
        async with sala.lock:
            if accion == "iniciar":
                if sala.duenio != asiento.id:
                    raise ReglaError("Solo quien creó la sala puede empezar.")
                await salas.iniciar(sala)
            elif accion == "ajustes":
                _ajustes(sala, asiento, msg)
            elif accion == "revancha":
                if sala.duenio != asiento.id:
                    raise ReglaError("Solo quien creó la sala puede preparar otra partida.")
                salas.volver_al_vestibulo(sala)
            elif accion == "salir":
                pass
            elif sala.estado == "jugando":
                _accion_de_juego(sala, asiento, accion, msg)
                asiento.fallos, asiento.auto = 0, False
            else:
                raise ReglaError("Ahora no se puede hacer eso.")
        if accion == "salir":
            await salas.salir(sala, asiento)
            return
    except ReglaError as e:
        await enviar_error(asiento, str(e))
        return
    except (TypeError, ValueError, KeyError):
        await enviar_error(asiento, "Acción no válida.")
        return
    sala.evento.set()
    await difundir(sala)


def _ajustes(sala: Sala, asiento: Asiento, msg: dict) -> None:
    if sala.duenio != asiento.id:
        raise ReglaError("Solo quien creó la sala puede cambiar los ajustes.")
    if sala.estado != "lobby":
        raise ReglaError("No se pueden cambiar los ajustes en plena partida.")
    if "plazas" in msg:
        plazas = int(msg["plazas"])
        if not MIN_JUGADORES <= plazas <= MAX_JUGADORES:
            raise ReglaError(f"Se juega de {MIN_JUGADORES} a {MAX_JUGADORES} personas.")
        if plazas < len(sala.humanos()):
            raise ReglaError("Ya hay más personas que esas plazas.")
        sala.plazas = plazas
    if "rellenar" in msg:
        sala.rellenar = bool(msg["rellenar"])
    if "nivel" in msg:
        if msg["nivel"] not in NIVELES:
            raise ReglaError("Nivel no válido.")
        sala.nivel = msg["nivel"]


def _accion_de_juego(sala: Sala, asiento: Asiento, accion: str, msg: dict) -> None:
    p = sala.partida
    if accion == "jugar":
        cartas = [str(c) for c in msg.get("cartas", [])]
        objetivo = msg.get("objetivo")
        p.jugar(asiento.id, cartas, str(objetivo) if objetivo else None)
    elif accion == "robar":
        p.robar(asiento.id)
    elif accion == "negar":
        p.negar(asiento.id)
    elif accion == "dar":
        p.dar(asiento.id, str(msg["carta"]))
    elif accion == "insertar":
        p.insertar(asiento.id, int(msg["pos"]))
    else:
        raise ReglaError("Acción no válida.")


# ====================================================================== el conductor de la partida
async def conducir(sala: Sala, salas: Salas) -> None:
    """Hace avanzar la partida hasta que termina."""
    try:
        await _esperar_a_alguien(sala)
        while sala.estado == "jugando" and sala.partida.fase != Fase.FIN:
            await _paso(sala)
        sala.estado, sala.espera = "fin", None
        await difundir(sala)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Error en la sala %s", sala.codigo)
        sala.estado, sala.espera = "fin", None
        await difundir(sala)


async def _esperar_a_alguien(sala: Sala) -> None:
    """En una partida rápida los bots no empiezan hasta que la persona se ha conectado (o pasan 10 s)."""
    limite = ahora() + seg(10)
    while not sala.hay_humanos_conectados() and ahora() < limite:
        await asyncio.sleep(0.05)
    await difundir(sala)


async def _pausa(sala: Sala) -> None:
    rango = PAUSA_BOT if sala.hay_humanos_vivos() else PAUSA_BOT_RAPIDA
    await asyncio.sleep(seg(sala.rng.uniform(*rango)))


def _juega_la_maquina(sala: Sala, a: Asiento) -> bool:
    """¿Decide un bot (o el piloto automático) por este asiento?"""
    return a.es_bot or a.auto or not a.conectado


async def _paso(sala: Sala) -> None:
    p = sala.partida
    if p.fase == Fase.VENTANA:
        await _ventana(sala)
        return
    if p.fase == Fase.TURNO:
        actor, limite = sala.asiento(p.actual().id), TURNO_S
    elif p.fase == Fase.FAVOR:
        actor, limite = sala.asiento(p.favor["de"]), FAVOR_S
    else:  # INSERTAR
        actor, limite = sala.asiento(p.insertando), INSERTAR_S
    version = p.version
    if _juega_la_maquina(sala, actor):
        sala.espera = {"jugador": actor.id, "hasta": ahora() + seg(PAUSA_BOT[1])}
        await difundir(sala)
        await _pausa(sala)
        await _jugar_maquina(sala, version)
        return
    sala.espera = {"jugador": actor.id, "hasta": ahora() + seg(limite)}
    await difundir(sala)
    try:
        await asyncio.wait_for(sala.evento.wait(), seg(limite))
        sala.evento.clear()
    except asyncio.TimeoutError:
        actor.fallos += 1
        if actor.fallos >= AUTO_TRAS_FALLOS:
            actor.auto = True
        await _jugar_maquina(sala, version)


async def _jugar_maquina(sala: Sala, version: int) -> None:
    async with sala.lock:
        if sala.partida.version != version or sala.partida.fase in (Fase.FIN, Fase.VENTANA):
            return                                   # mientras tanto cambió algo: se vuelve a evaluar
        bots.jugar_un_paso(sala.partida, sala.nivel, sala.rng)
    await difundir(sala)


async def _ventana(sala: Sala) -> None:
    """Unos segundos para responder con «¡Ni hablar!». Cada respuesta reinicia el tiempo."""
    p = sala.partida

    def planificar() -> list[tuple[float, Asiento]]:
        previstas = []
        for a in sala.asientos:
            if _juega_la_maquina(sala, a) and p.puede_negar(a.id) and bots.reaccion_ventana(p, a.id, sala.nivel, sala.rng):
                previstas.append((ahora() + seg(sala.rng.uniform(*REACCION_BOT)), a))
        return sorted(previstas, key=lambda x: x[0])

    version = p.version
    fin = ahora() + seg(VENTANA_S)
    reacciones = planificar()
    sala.espera = {"jugador": None, "hasta": fin}
    await difundir(sala)
    while True:
        espera = fin - ahora()
        if reacciones:
            espera = min(espera, reacciones[0][0] - ahora())
        try:
            await asyncio.wait_for(sala.evento.wait(), max(0.0, espera))
            sala.evento.clear()
            if p.version != version:                       # alguien respondió: la ventana se reinicia
                version = p.version
                fin = ahora() + seg(VENTANA_S)
                reacciones = planificar()
                sala.espera = {"jugador": None, "hasta": fin}
                await difundir(sala)
            continue
        except asyncio.TimeoutError:
            pass
        if reacciones and ahora() >= reacciones[0][0] - 0.001 and ahora() < fin:
            _, a = reacciones.pop(0)
            async with sala.lock:
                if p.fase == Fase.VENTANA and p.puede_negar(a.id):
                    p.negar(a.id)
            version = p.version
            fin = ahora() + seg(VENTANA_S)
            reacciones = planificar()
            sala.espera = {"jugador": None, "hasta": fin}
            await difundir(sala)
            continue
        if ahora() >= fin - 0.001:
            async with sala.lock:
                if p.fase == Fase.VENTANA:
                    p.resolver()
            await difundir(sala)
            return
