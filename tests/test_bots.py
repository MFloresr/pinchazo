"""Los bots: simulaciones de partidas completas y decisiones concretas."""
import random

import pytest

from app.juego import bots
from app.juego.motor import Fase, Partida


def nueva(n=3, semilla=1, mano=None, mazo=None):
    p = Partida([(f"j{i}", f"J{i}", True) for i in range(n)], semilla=semilla)
    for jid, m in (mano or {}).items():
        p.jugador(jid).mano = list(m)
    if mazo is not None:
        p.mazo = list(reversed(mazo))
    return p


def simular(n, semilla, nivel="medio", limite=5000):
    p = nueva(n, semilla)
    rng = random.Random(semilla)
    pasos = 0
    while p.fase != Fase.FIN and pasos < limite:
        bots.jugar_un_paso(p, nivel, rng)
        pasos += 1
    return p, pasos


@pytest.mark.parametrize("nivel", ["facil", "medio", "dificil"])
@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_las_partidas_entre_bots_siempre_terminan_con_un_ganador(n, nivel):
    for semilla in range(25):
        p, pasos = simular(n, semilla, nivel)
        assert p.fase == Fase.FIN, f"no termina: n={n} nivel={nivel} semilla={semilla}"
        assert p.ganador is not None and p.jugador(p.ganador).vivo
        assert len(p.vivos()) == 1
        assert pasos < 5000


def test_los_bots_no_hacen_trampas_con_cartas_que_no_tienen():
    # Si algún bot intentara jugar una carta inexistente, el motor lanzaría ReglaError y el
    # paso caería a "robar"; aquí comprobamos que no hay cartas fantasma (el total se conserva).
    for semilla in range(20):
        p = nueva(4, semilla)
        total = len(p.mazo) + sum(len(j.mano) for j in p.jugadores) + len(p.descarte)
        rng = random.Random(semilla)
        for _ in range(3000):
            if p.fase == Fase.FIN:
                break
            bots.jugar_un_paso(p, "medio", rng)
            assert len(p.mazo) + sum(len(j.mano) for j in p.jugadores) + len(p.descarte) + (
                1 if p.fase == Fase.INSERTAR else 0) == total


def test_con_la_siguiente_carta_un_pinchazo_conocido_se_evita_si_se_puede():
    p = nueva(3, mano={"j0": ["esquivar", "loro", "parche"]}, mazo=["pinchazo", "a", "b"])
    p.visiones["j0"] = ["pinchazo", "a", "b"]
    rng = random.Random(0)
    accion = None
    for semilla in range(30):                # el 10 % de despistes del nivel medio no cuenta aquí
        accion = bots.decidir_turno(p, "j0", "medio", random.Random(semilla))
        if accion["tipo"] == "jugar":
            break
    assert accion == {"tipo": "jugar", "cartas": ["esquivar"], "objetivo": None}


def test_con_riesgo_bajo_roba_sin_gastar_cartas():
    p = nueva(2, mano={"j0": ["esquivar", "tartazo", "parche"]}, mazo=["a"] * 40)   # sin Pinchazos
    p.mazo = ["a"] * 40
    acciones = {bots.decidir_turno(p, "j0", "medio", random.Random(s))["tipo"] for s in range(20)}
    assert acciones == {"robar"}


def test_el_bot_usa_la_pareja_contra_quien_tiene_mas_cartas():
    p = nueva(3, mano={"j0": ["loro", "loro", "parche"], "j1": ["a"], "j2": ["a", "b", "c"]}, mazo=["x"] * 20)
    visto = set()
    for s in range(60):
        a = bots.decidir_turno(p, "j0", "dificil", random.Random(s))
        if a["tipo"] == "jugar":
            visto.add((tuple(a["cartas"]), a["objetivo"]))
    assert visto == {(("loro", "loro"), "j2")}


def test_reaccion_solo_si_tiene_la_carta_y_puede():
    p = nueva(3, mano={"j0": ["favor"], "j1": ["negar"], "j2": ["loro"]}, mazo=["x"] * 10)
    p.jugar("j0", ["favor"], "j1")
    siempre = [bots.reaccion_ventana(p, "j1", "dificil", random.Random(s)) for s in range(40)]
    assert any(siempre)                                  # a veces responde, porque el favor va contra él
    assert not any(bots.reaccion_ventana(p, "j2", "dificil", random.Random(s)) for s in range(40))   # no tiene «Ni hablar»
    assert not any(bots.reaccion_ventana(p, "j0", "dificil", random.Random(s)) for s in range(40))   # es su carta


def test_el_favor_regala_lo_menos_util_y_guarda_el_parche():
    p = nueva(3, mano={"j1": ["parche", "negar", "loro", "pulpo", "pulpo"]}, mazo=["x"] * 10)
    from collections import Counter

    dadas = Counter(bots.elegir_dar(p, "j1", "dificil", random.Random(s)) for s in range(200))
    assert dadas.most_common(1)[0][0] == "loro"        # lo normal: la mascota suelta
    assert dadas["parche"] <= 0.06 * 200                # solo en los pocos despistes del nivel


def test_la_insercion_esta_dentro_del_mazo():
    p = nueva(3, mazo=["a", "b", "c"])
    for s in range(50):
        assert 0 <= bots.elegir_insercion(p, "j0", "medio", random.Random(s)) <= 3


def test_el_nivel_medio_se_defiende_mejor_que_el_facil():
    """Un bot medio contra tres fáciles gana bastante más de la cuarta parte de las partidas."""
    victorias = 0
    partidas = 60
    for semilla in range(partidas):
        p = Partida([("m", "Medio", True), ("f1", "F1", True), ("f2", "F2", True), ("f3", "F3", True)], semilla=semilla)
        rng = random.Random(semilla)
        niveles = {"m": "medio", "f1": "facil", "f2": "facil", "f3": "facil"}
        while p.fase != Fase.FIN:
            # cada bot decide con su nivel: se elige por quien le toca actuar
            if p.fase == Fase.TURNO:
                nivel = niveles[p.actual().id]
            elif p.fase == Fase.FAVOR:
                nivel = niveles[p.favor["de"]]
            elif p.fase == Fase.INSERTAR:
                nivel = niveles[p.insertando]
            else:
                nivel = "medio"
            bots.jugar_un_paso(p, nivel, rng)
        victorias += p.ganador == "m"
    assert victorias / partidas > 0.30        # el azar daría 0,25
