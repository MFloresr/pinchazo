"""Bots de Pinchazo. Deciden con lo que cualquier persona podría saber (su mano, el mazo y lo que ha visto).

No hacen trampas: nunca miran el mazo ni las manos de los demás. Lo único que «saben» es:
  - cuántos Pinchazos quedan en el mazo (siempre uno menos que las personas vivas), y
  - lo que ellos mismos han visto con la Bola de cristal.

Niveles
  facil   : casi no calcula, comete errores a menudo y se protege poco.
  medio   : calcula el riesgo de robar, se protege cuando sube, usa las parejas y los favores y
            responde a veces con «¡Ni hablar!». De vez en cuando se equivoca, como una persona.
  dificil : umbral de riesgo más bajo, aprovecha mejor la Bola de cristal y casi no falla.
"""
from __future__ import annotations

import random
from collections import Counter

from .cartas import MASCOTAS
from .motor import Fase, Partida, ReglaError

NIVELES = {
    "facil": dict(umbral=0.50, p_pareja=0.20, p_favor=0.15, p_negar_objetivo=0.25, p_negar_tartazo=0.10,
                  p_renegar=0.10, error=0.35, usa_vision=False, p_bola=0.10, p_arriba=0.20),
    "medio": dict(umbral=0.25, p_pareja=0.55, p_favor=0.40, p_negar_objetivo=0.70, p_negar_tartazo=0.50,
                  p_renegar=0.40, error=0.10, usa_vision=True, p_bola=0.50, p_arriba=0.50),
    "dificil": dict(umbral=0.17, p_pareja=0.80, p_favor=0.55, p_negar_objetivo=0.90, p_negar_tartazo=0.70,
                    p_renegar=0.60, error=0.02, usa_vision=True, p_bola=0.80, p_arriba=0.60),
}
NOMBRES = ["Pipo", "Luna", "Tito", "Kiwi", "Nube", "Rocco", "Mimi", "Bruno"]

# Qué cartas regala antes: las de menos valor primero
_VALOR = {"remolino": 2, "bola": 3, "favor": 3, "esquivar": 4, "tartazo": 5, "negar": 6, "parche": 9}


def _cfg(nivel: str) -> dict:
    return NIVELES.get(nivel, NIVELES["medio"])


def _usadas(p: Partida, jid: str) -> set[str]:
    """Qué cartas ha jugado ya este bot en el turno actual (para no repetir remolinos y bolas)."""
    mem = p.__dict__.setdefault("memoria_bots", {})
    clave = (jid, p.numero_turno)
    if clave not in mem:
        mem.clear()
        mem[clave] = set()
    return mem[clave]


def _riesgo(p: Partida, jid: str, cfg: dict) -> float:
    """Probabilidad de robar un Pinchazo. 1.0 o 0.0 si el bot ya miró la carta de arriba."""
    vision = p.visiones.get(jid)
    if cfg["usa_vision"] and vision:
        return 1.0 if vision[0] == "pinchazo" else 0.0
    return p.riesgo()


def _rival_con_mas_cartas(p: Partida, jid: str) -> str | None:
    rivales = [j for j in p.vivos() if j.id != jid and j.mano]
    return max(rivales, key=lambda j: len(j.mano)).id if rivales else None


def decidir_turno(p: Partida, jid: str, nivel: str, rng: random.Random) -> dict:
    """Devuelve la próxima acción de este bot en su turno: jugar una carta o robar."""
    cfg = _cfg(nivel)
    j = p.jugador(jid)
    mano = Counter(j.mano)
    usadas = _usadas(p, jid)
    riesgo = _riesgo(p, jid, cfg)
    con_vision = bool(cfg["usa_vision"] and p.visiones.get(jid))

    def jugar(*cartas, objetivo=None):
        return {"tipo": "jugar", "cartas": list(cartas), "objetivo": objetivo}

    if rng.random() < cfg["error"]:                       # un despiste
        return {"tipo": "robar"}

    # 1) Peligro alto o seguro: intentar no robar
    if riesgo >= max(cfg["umbral"], 0.001) or riesgo >= 0.999:
        for carta in ("tartazo", "esquivar"):
            if mano[carta]:
                return jugar(carta)
        sin_parche = mano["parche"] == 0
        if mano["remolino"] and "remolino" not in usadas and (riesgo >= 0.999 or (sin_parche and riesgo >= 0.3)):
            return jugar("remolino")
        if cfg["usa_vision"] and mano["bola"] and not con_vision and "bola" not in usadas and rng.random() < cfg["p_bola"]:
            return jugar("bola")
    # 2) Riesgo medio: mirar el futuro antes de decidir
    elif (cfg["usa_vision"] and riesgo >= 0.10 and mano["bola"] and not con_vision
          and "bola" not in usadas and rng.random() < cfg["p_bola"]):
        return jugar("bola")

    # 3) Robar cartas a los demás con parejas
    if riesgo < 0.999:
        for mascota in MASCOTAS:
            if mano[mascota] >= 2 and rng.random() < cfg["p_pareja"]:
                objetivo = _rival_con_mas_cartas(p, jid)
                if objetivo:
                    return jugar(mascota, mascota, objetivo=objetivo)
        if mano["favor"] and len(j.mano) <= 6 and rng.random() < cfg["p_favor"]:
            objetivo = _rival_con_mas_cartas(p, jid)
            if objetivo:
                return jugar("favor", objetivo=objetivo)

    return {"tipo": "robar"}


def reaccion_ventana(p: Partida, jid: str, nivel: str, rng: random.Random) -> bool:
    """¿Responde este bot con «¡Ni hablar!» a la carta que está en la ventana?"""
    if not p.puede_negar(jid):
        return False
    cfg = _cfg(nivel)
    pen = p.pendiente
    if pen.negada:
        # Alguien anuló la carta. Si era mía, a veces la defiendo con otro «Ni hablar»
        return pen.jugador == jid and rng.random() < cfg["p_renegar"]
    if pen.objetivo == jid:
        return rng.random() < cfg["p_negar_objetivo"]
    if pen.cartas == ["tartazo"]:
        yo = next(i for i, x in enumerate(p.jugadores) if x.id == jid)
        quien = next(i for i, x in enumerate(p.jugadores) if x.id == pen.jugador)
        if p.siguiente_vivo(quien) == yo:
            return rng.random() < cfg["p_negar_tartazo"]
    return False


def elegir_dar(p: Partida, jid: str, nivel: str, rng: random.Random) -> str:
    """Qué carta entrega este bot cuando le piden un favor: la que menos le sirve."""
    mano = p.jugador(jid).mano
    if rng.random() < _cfg(nivel)["error"]:
        return rng.choice(mano)
    cuenta = Counter(mano)

    def valor(carta: str) -> int:
        if carta in MASCOTAS:
            return 0 if cuenta[carta] == 1 else 1   # una mascota suelta no sirve; si hay pareja, se guarda
        return _VALOR.get(carta, 5)

    return min(mano, key=lambda c: (valor(c), rng.random()))


def elegir_insercion(p: Partida, jid: str, nivel: str, rng: random.Random) -> int:
    """Dónde esconde el Pinchazo: a menudo arriba (para que lo robe la siguiente persona)."""
    cfg = _cfg(nivel)
    if rng.random() < cfg["p_arriba"]:
        return 0
    return rng.randint(0, min(len(p.mazo), 6))


def ejecutar(p: Partida, jid: str, accion: dict) -> None:
    """Aplica la decisión del bot al motor."""
    if accion["tipo"] == "robar":
        p.robar(jid)
    else:
        p.jugar(jid, accion["cartas"], accion.get("objetivo"))
        _usadas(p, jid).update(accion["cartas"])


def jugar_un_paso(p: Partida, nivel: str, rng: random.Random) -> None:
    """Hace lo que toca ahora en la partida, como lo haría un bot de este nivel.

    Sirve para simular partidas enteras y para el «piloto automático» de quien no responde a tiempo.
    """
    if p.fase == Fase.TURNO:
        jid = p.actual().id
        try:
            ejecutar(p, jid, decidir_turno(p, jid, nivel, rng))
        except ReglaError:
            p.robar(jid)
    elif p.fase == Fase.VENTANA:
        candidatos = [j.id for j in p.vivos()]
        rng.shuffle(candidatos)
        for jid in candidatos:
            if reaccion_ventana(p, jid, nivel, rng):
                p.negar(jid)
                return
        p.resolver()
    elif p.fase == Fase.FAVOR:
        jid = p.favor["de"]
        p.dar(jid, elegir_dar(p, jid, nivel, rng))
    elif p.fase == Fase.INSERTAR:
        jid = p.insertando
        p.insertar(jid, elegir_insercion(p, jid, nivel, rng))
