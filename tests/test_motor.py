"""Reglas del juego. Se arman situaciones concretas cambiando las manos y el mazo a mano."""
import pytest

from app.juego.motor import Fase, Partida, ReglaError


def nueva(n=3, semilla=1):
    return Partida([(f"j{i}", f"Jugador {i}", False) for i in range(n)], semilla=semilla)


def preparar(p, manos=None, mazo=None):
    """Deja manos y mazo exactos. El mazo se escribe de arriba a abajo."""
    for jid, mano in (manos or {}).items():
        p.jugador(jid).mano = list(mano)
    if mazo is not None:
        p.mazo = list(reversed(mazo))
    return p


# ---------------------------------------------------------------- preparación
def test_reparto_inicial():
    p = nueva(4)
    assert all(len(j.mano) == 8 and j.mano.count("parche") == 1 for j in p.jugadores)
    assert p.mazo.count("pinchazo") == 3            # uno menos que personas
    assert p.mazo.count("parche") == 2
    assert p.fase == Fase.TURNO and p.actual().id == "j0"


def test_numero_de_jugadores():
    with pytest.raises(ReglaError):
        Partida([("a", "A", False)])
    with pytest.raises(ReglaError):
        Partida([(str(i), "X", False) for i in range(6)])


def test_misma_semilla_mismo_reparto():
    assert nueva(3, 7).mazo == nueva(3, 7).mazo
    assert nueva(3, 7).mazo != nueva(3, 8).mazo


# ---------------------------------------------------------------- robar
def test_robar_una_carta_pasa_el_turno():
    p = preparar(nueva(), mazo=["loro", "pulpo"])
    p.robar("j0")
    assert p.jugador("j0").mano[-1] == "loro"
    assert p.actual().id == "j1"


def test_solo_roba_quien_tiene_el_turno():
    p = nueva()
    with pytest.raises(ReglaError):
        p.robar("j1")


def test_pinchazo_con_parche_pide_esconderlo():
    p = preparar(nueva(), manos={"j0": ["parche", "loro"]}, mazo=["pinchazo", "pulpo"])
    p.robar("j0")
    assert p.fase == Fase.INSERTAR and p.insertando == "j0"
    assert "parche" not in p.jugador("j0").mano
    assert p.jugador("j0").vivo
    p.insertar("j0", 0)                      # justo arriba: el siguiente lo roba
    assert p.mazo[-1] == "pinchazo" and p.actual().id == "j1"


def test_insertar_en_una_posicion_profunda():
    p = preparar(nueva(), manos={"j0": ["parche"]}, mazo=["pinchazo", "a", "b", "c"])
    p.robar("j0")
    p.insertar("j0", 2)                      # dos cartas por encima
    assert list(reversed(p.mazo))[:3] == ["a", "b", "pinchazo"]


def test_insertar_fuera_de_rango():
    p = preparar(nueva(), manos={"j0": ["parche"]}, mazo=["pinchazo", "a"])
    p.robar("j0")
    with pytest.raises(ReglaError):
        p.insertar("j0", 99)


def test_pinchazo_sin_parche_elimina_y_pasa_el_turno():
    p = preparar(nueva(), manos={"j0": ["loro", "pulpo"]}, mazo=["pinchazo", "x"])
    p.robar("j0")
    j0 = p.jugador("j0")
    assert not j0.vivo and j0.mano == []
    assert "loro" in p.descarte and p.actual().id == "j1"


def test_gana_la_ultima_persona():
    p = preparar(nueva(2), manos={"j0": []}, mazo=["pinchazo", "x"])
    p.robar("j0")
    assert p.fase == Fase.FIN and p.ganador == "j1"
    with pytest.raises(ReglaError):
        p.robar("j1")


def test_el_turno_salta_a_los_eliminados():
    p = preparar(nueva(3), manos={"j1": []}, mazo=["pinchazo", "x", "y", "z"])
    p.robar("j0")                            # roba "pinchazo" pero j0 tiene parche (mano inicial) -> se salva
    p.insertar("j0", 3)
    assert p.actual().id == "j1"
    p.jugador("j1").mano = []
    p.mazo.append("pinchazo")
    p.robar("j1")
    assert not p.jugador("j1").vivo and p.actual().id == "j2"
    p.mazo.append("a")
    p.robar("j2")
    assert p.actual().id == "j0"             # j1 está fuera


# ---------------------------------------------------------------- cartas de acción
def jugar_y_resolver(p, jid, cartas, objetivo=None):
    p.jugar(jid, cartas, objetivo)
    assert p.fase == Fase.VENTANA
    p.resolver()


def test_esquivar_termina_el_turno_sin_robar():
    p = preparar(nueva(), manos={"j0": ["esquivar", "loro"]}, mazo=["pulpo"])
    jugar_y_resolver(p, "j0", ["esquivar"])
    assert p.actual().id == "j1" and len(p.mazo) == 1 and "esquivar" in p.descarte


def test_tartazo_da_dos_turnos_al_siguiente():
    p = preparar(nueva(), manos={"j0": ["tartazo"]}, mazo=["a", "b", "c", "d"])
    jugar_y_resolver(p, "j0", ["tartazo"])
    assert p.actual().id == "j1" and p.turnos_pendientes == 2
    p.robar("j1")
    assert p.actual().id == "j1" and p.turnos_pendientes == 1   # aún le queda uno
    p.robar("j1")
    assert p.actual().id == "j2"


def test_tartazo_sobre_tartazo_se_acumula():
    p = preparar(nueva(), manos={"j0": ["tartazo"], "j1": ["tartazo"]}, mazo=["a"] * 6)
    jugar_y_resolver(p, "j0", ["tartazo"])
    assert p.turnos_pendientes == 2
    jugar_y_resolver(p, "j1", ["tartazo"])
    assert p.actual().id == "j2" and p.turnos_pendientes == 4


def test_esquivar_con_dos_turnos_solo_gasta_uno():
    p = preparar(nueva(), manos={"j0": ["tartazo"], "j1": ["esquivar"]}, mazo=["a"] * 5)
    jugar_y_resolver(p, "j0", ["tartazo"])
    jugar_y_resolver(p, "j1", ["esquivar"])
    assert p.actual().id == "j1" and p.turnos_pendientes == 1


def test_bola_de_cristal_es_privada_y_ve_tres():
    p = preparar(nueva(), manos={"j0": ["bola"]}, mazo=["a", "b", "c", "d"])
    jugar_y_resolver(p, "j0", ["bola"])
    assert p.visiones["j0"] == ["a", "b", "c"] and "j1" not in p.visiones
    assert p.fase == Fase.TURNO and p.actual().id == "j0"      # no termina el turno


def test_la_vision_se_actualiza_al_robar_y_se_borra_al_barajar():
    p = preparar(nueva(), manos={"j0": ["bola"], "j1": ["remolino"]}, mazo=["a", "b", "c", "d", "e"])
    jugar_y_resolver(p, "j0", ["bola"])
    p.robar("j0")
    assert p.visiones["j0"] == ["b", "c"]
    jugar_y_resolver(p, "j1", ["remolino"])
    assert p.visiones == {}


def test_remolino_baraja_pero_conserva_las_cartas():
    p = preparar(nueva(), manos={"j0": ["remolino"]}, mazo=list("abcdefghij"))
    antes = sorted(p.mazo)
    jugar_y_resolver(p, "j0", ["remolino"])
    assert sorted(p.mazo) == antes


def test_favor_la_otra_persona_elige_la_carta():
    p = preparar(nueva(), manos={"j0": ["favor"], "j1": ["loro", "pulpo"]}, mazo=["a"])
    jugar_y_resolver(p, "j0", ["favor"], "j1")
    assert p.fase == Fase.FAVOR
    with pytest.raises(ReglaError):
        p.dar("j0", "loro")                  # no te toca a ti
    with pytest.raises(ReglaError):
        p.dar("j1", "tortuga")               # no la tiene
    p.dar("j1", "pulpo")
    assert "pulpo" in p.jugador("j0").mano and "pulpo" not in p.jugador("j1").mano
    assert p.fase == Fase.TURNO and p.actual().id == "j0"


def test_favor_a_alguien_sin_cartas_no_se_puede():
    p = preparar(nueva(), manos={"j0": ["favor"], "j1": []})
    with pytest.raises(ReglaError):
        p.jugar("j0", ["favor"], "j1")
    assert "favor" in p.jugador("j0").mano   # no se gasta si falla


def test_pareja_roba_una_carta_al_azar():
    p = preparar(nueva(), manos={"j0": ["loro", "loro"], "j1": ["pulpo"]})
    jugar_y_resolver(p, "j0", ["loro", "loro"], "j1")
    assert p.jugador("j1").mano == [] and "pulpo" in p.jugador("j0").mano


def test_pareja_necesita_mascotas_iguales():
    p = preparar(nueva(), manos={"j0": ["loro", "pulpo", "esquivar", "esquivar"]})
    with pytest.raises(ReglaError):
        p.jugar("j0", ["loro", "pulpo"], "j1")
    with pytest.raises(ReglaError):
        p.jugar("j0", ["esquivar", "esquivar"], "j1")
    with pytest.raises(ReglaError):
        p.jugar("j0", ["loro"], None)        # una mascota sola no se juega


def test_no_puedes_jugar_cartas_que_no_tienes_ni_fuera_de_turno():
    p = preparar(nueva(), manos={"j0": ["loro"], "j1": ["esquivar"]})
    with pytest.raises(ReglaError):
        p.jugar("j0", ["esquivar"])
    with pytest.raises(ReglaError):
        p.jugar("j1", ["esquivar"])


# ---------------------------------------------------------------- ¡Ni hablar!
def test_negar_anula_la_carta():
    p = preparar(nueva(), manos={"j0": ["esquivar"], "j1": ["negar"]}, mazo=["a"])
    p.jugar("j0", ["esquivar"])
    assert p.puede_negar("j1") and not p.puede_negar("j0")
    p.negar("j1")
    p.resolver()
    assert p.actual().id == "j0" and p.jugador("j0").vivo      # el turno sigue
    assert p.descarte.count("negar") == 1


def test_negar_el_negar_restaura_la_carta():
    p = preparar(nueva(), manos={"j0": ["esquivar", "negar"], "j1": ["negar"]}, mazo=["a"])
    p.jugar("j0", ["esquivar"])
    p.negar("j1")
    p.negar("j0")                            # j0 niega el «Ni hablar» de j1
    p.resolver()
    assert p.actual().id == "j1"             # la carta se jugó con normalidad


def test_no_se_puede_negar_dos_veces_seguidas_ni_lo_propio():
    p = preparar(nueva(), manos={"j0": ["esquivar", "negar"], "j1": ["negar", "negar"]})
    p.jugar("j0", ["esquivar"])
    with pytest.raises(ReglaError):
        p.negar("j0")                        # es tu propia carta
    p.negar("j1")
    with pytest.raises(ReglaError):
        p.negar("j1")                        # acabas de negar


def test_negar_sin_tener_la_carta():
    p = preparar(nueva(), manos={"j0": ["esquivar"], "j1": ["loro"]})
    p.jugar("j0", ["esquivar"])
    with pytest.raises(ReglaError):
        p.negar("j1")


def test_negar_un_favor_evita_que_pidan():
    p = preparar(nueva(), manos={"j0": ["favor"], "j1": ["negar", "loro"]})
    p.jugar("j0", ["favor"], "j1")
    p.negar("j1")
    p.resolver()
    assert p.fase == Fase.TURNO and p.jugador("j1").mano == ["loro"]


def test_no_se_puede_robar_durante_la_ventana():
    p = preparar(nueva(), manos={"j0": ["esquivar"]})
    p.jugar("j0", ["esquivar"])
    with pytest.raises(ReglaError):
        p.robar("j0")


# ---------------------------------------------------------------- invariantes
def test_siempre_hay_un_pinchazo_menos_que_jugadores_vivos():
    """Mientras se juega, los Pinchazos del mazo son (vivos - 1), salvo mientras se esconde uno."""
    import random

    from app.juego import bots

    for semilla in range(30):
        p = nueva(4, semilla)
        rng = random.Random(semilla)
        for _ in range(2000):
            if p.fase == Fase.FIN:
                break
            esperado = len(p.vivos()) - 1 - (1 if p.fase == Fase.INSERTAR else 0)
            assert p.pinchazos_en_el_mazo() == esperado
            bots.jugar_un_paso(p, "medio", rng)
        assert p.fase == Fase.FIN


# ---------------------------------------------------------------- eventos para animar
def tipos(p):
    return [e["tipo"] for e in p.eventos]


def test_los_eventos_llevan_numero_creciente_y_empiezan_con_el_turno():
    p = nueva()
    assert tipos(p) == ["turno"] and p.eventos[0]["j"] == "j0"
    p = preparar(p, manos={"j0": ["esquivar"]}, mazo=["a", "b"])
    jugar_y_resolver(p, "j0", ["esquivar"])
    numeros = [e["n"] for e in p.eventos]
    assert numeros == sorted(numeros) and len(set(numeros)) == len(numeros)
    assert tipos(p) == ["turno", "juega", "resuelve", "turno"]


def test_evento_de_robar_negar_y_pinchar():
    p = preparar(nueva(), manos={"j0": ["esquivar"], "j1": ["negar"]}, mazo=["loro", "pinchazo"])
    p.jugar("j0", ["esquivar"])
    p.negar("j1")
    p.resolver()
    assert tipos(p)[-3:] == ["juega", "negar", "resuelve"]
    assert p.eventos[-1]["anulada"] is True and p.eventos[-2]["anulada"] is True
    p.robar("j0")
    assert p.eventos[-2]["tipo"] == "roba" and p.eventos[-2]["j"] == "j0"
    p.jugador("j1").mano = ["loro"]            # sin Parche: reventará
    p.robar("j1")
    assert "pincha" in tipos(p) and [e for e in p.eventos if e["tipo"] == "pincha"][0]["j"] == "j1"


def test_evento_de_parche_inserta_y_fin():
    p = preparar(nueva(2), manos={"j0": ["parche"]}, mazo=["pinchazo", "a", "b"])
    p.robar("j0")
    assert tipos(p)[-1] == "parche"
    p.insertar("j0", 1)
    assert "inserta" in tipos(p)
    p.jugador("j1").mano = []
    p.mazo.append("pinchazo")
    p.robar("j1")
    assert tipos(p)[-1] == "fin" and p.eventos[-1]["j"] == "j0"


def test_solo_se_guardan_los_ultimos_eventos():
    p = nueva(2)
    for i in range(80):
        p._evento("turno", j="j0")
    assert len(p.eventos) == 40 and p.eventos[-1]["n"] == p._n_evento
