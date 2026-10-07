"""El servidor: API y partidas reales por WebSocket (con el ritmo acelerado)."""
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.main import app, salas


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c
    salas.salas.clear()


@contextmanager
def conectar(cliente, codigo, token):
    """Abre el WebSocket y se identifica con el primer mensaje."""
    with cliente.websocket_connect(f"/ws/{codigo}") as ws:
        ws.send_json({"accion": "entrar", "token": token})
        yield ws


def crear(cliente, **datos):
    r = cliente.post("/api/salas", json={"nombre": "Ana", **datos})
    assert r.status_code == 200, r.text
    return r.json()


def recibir_hasta(ws, condicion, intentos=400):
    """Lee mensajes hasta que se cumpla la condición sobre el estado."""
    ultimo = None
    for _ in range(intentos):
        m = ws.receive_json()
        if m["t"] == "estado":
            ultimo = m["vista"]
            if condicion(ultimo):
                return ultimo
        elif m["t"] == "error":
            raise AssertionError(m["mensaje"])
    raise AssertionError(f"No se cumplió la condición. Último estado: {ultimo and ultimo.get('partida', {}).get('fase')}")


# ---------------------------------------------------------------- API
def test_salud_y_cartas(cliente):
    assert cliente.get("/salud").json()["ok"] is True
    assert cliente.get("/api/cartas").json()["pinchazo"]["nombre"] == "Pinchazo"
    assert cliente.get("/").status_code == 200


def test_crear_y_consultar_sala(cliente):
    c = crear(cliente, plazas=3)
    assert len(c["codigo"]) == 4 and c["token"] and c["id"]
    r = cliente.get(f"/api/salas/{c['codigo']}").json()
    assert r == {"existe": True, "estado": "lobby", "humanos": 1, "plazas": 3}
    assert cliente.get("/api/salas/ZZZZ").status_code == 404


def test_validacion_de_datos(cliente):
    assert cliente.post("/api/salas", json={"plazas": 9}).status_code == 422
    assert cliente.post("/api/salas", json={"nivel": "imposible"}).status_code == 422
    assert cliente.post("/api/rapida", json={"rivales": 0}).status_code == 422


def test_unirse_y_nombres_repetidos(cliente):
    c = crear(cliente)
    a = cliente.post(f"/api/salas/{c['codigo']}/unirse", json={"nombre": "Ana"}).json()
    assert a["id"] != c["id"]
    assert salas.get(c["codigo"]).asiento(a["id"]).nombre == "Ana 2"
    assert cliente.post("/api/salas/ZZZZ/unirse", json={"nombre": "x"}).status_code == 400


def test_la_sala_se_llena(cliente):
    c = crear(cliente, plazas=2)
    assert cliente.post(f"/api/salas/{c['codigo']}/unirse", json={"nombre": "B"}).status_code == 200
    r = cliente.post(f"/api/salas/{c['codigo']}/unirse", json={"nombre": "C"})
    assert r.status_code == 400 and "llena" in r.json()["detail"]


# ---------------------------------------------------------------- WebSocket
def test_ws_con_token_incorrecto_se_cierra(cliente):
    c = crear(cliente)
    with conectar(cliente, c["codigo"], "malo") as ws:
        m = ws.receive_json()
        assert m["t"] == "error" and m["fatal"]


def test_ws_sin_identificarse_se_cierra(cliente):
    c = crear(cliente)
    with cliente.websocket_connect(f"/ws/{c['codigo']}") as ws:
        m = ws.receive_json()                 # no envía nada: el servidor lo echa tras el tiempo de espera
        assert m["t"] == "error" and m["fatal"]


def test_el_token_no_viaja_en_la_direccion(cliente):
    c = crear(cliente)
    with cliente.websocket_connect(f"/ws/{c['codigo']}?token={c['token']}") as ws:
        assert ws.receive_json()["fatal"]     # la dirección ya no vale como identificación


def test_vestibulo_y_ajustes_solo_el_duenio(cliente):
    c = crear(cliente, plazas=4)
    b = cliente.post(f"/api/salas/{c['codigo']}/unirse", json={"nombre": "Beto"}).json()
    with conectar(cliente, c['codigo'], c['token']) as dueno, \
         conectar(cliente, c['codigo'], b['token']) as invitado:
        v = recibir_hasta(dueno, lambda v: len([a for a in v["asientos"] if a["conectado"]]) == 2)
        assert v["sala"]["estado"] == "lobby" and v["sala"]["duenio"] == c["id"]
        invitado.send_json({"accion": "ajustes", "plazas": 3})
        # el invitado no puede cambiar nada
        while True:
            m = invitado.receive_json()
            if m["t"] == "error":
                assert "creó la sala" in m["mensaje"]
                break
        dueno.send_json({"accion": "ajustes", "plazas": 3, "nivel": "dificil"})
        v = recibir_hasta(dueno, lambda v: v["sala"]["plazas"] == 3)
        assert v["sala"]["nivel"] == "dificil"


def test_no_se_puede_empezar_a_solas_sin_bots(cliente):
    c = crear(cliente, rellenar=False)
    with conectar(cliente, c['codigo'], c['token']) as ws:
        recibir_hasta(ws, lambda v: True)
        ws.send_json({"accion": "iniciar"})
        for _ in range(10):
            m = ws.receive_json()
            if m["t"] == "error":
                assert "al menos 2" in m["mensaje"]
                return
        raise AssertionError("debía rechazarlo")


def jugar_como_persona(ws, yo, limite=1500):
    """Una persona sencilla: roba siempre y, si se salva con un Parche, esconde el Pinchazo arriba."""
    ultimo = None
    for _ in range(limite):
        m = ws.receive_json()
        if m["t"] != "estado":
            continue
        v = m["vista"]
        ultimo = v
        p = v.get("partida")
        if not p or v["sala"]["estado"] == "fin":
            return v
        if p["fase"] == "turno" and p["turno"] == yo:
            ws.send_json({"accion": "robar"})
        elif p["fase"] == "insertar" and p["insertando"] == yo:
            ws.send_json({"accion": "insertar", "pos": 0})
        elif p["fase"] == "favor" and p["favor"]["de"] == yo:
            ws.send_json({"accion": "dar", "carta": p["yo"]["mano"][0]})
    raise AssertionError("la partida no terminó")


def test_partida_rapida_contra_bots_termina(cliente):
    r = cliente.post("/api/rapida", json={"nombre": "Ana", "rivales": 3, "nivel": "medio"}).json()
    with conectar(cliente, r['codigo'], r['token']) as ws:
        final = jugar_como_persona(ws, r["id"])
    p = final["partida"]
    assert p["fase"] == "fin" and p["ganador"] and final["sala"]["estado"] == "fin"
    assert len(p["jugadores"]) == 4 and sum(1 for j in p["jugadores"] if j["bot"]) == 3


def test_cada_persona_solo_ve_su_mano(cliente):
    r = cliente.post("/api/rapida", json={"nombre": "Ana", "rivales": 2}).json()
    with conectar(cliente, r['codigo'], r['token']) as ws:
        v = recibir_hasta(ws, lambda v: v.get("partida"))
        p = v["partida"]
        assert len(p["yo"]["mano"]) == 8
        for j in p["jugadores"]:
            assert set(j) == {"id", "nombre", "bot", "cartas", "vivo", "conectado", "auto"}   # ni rastro de sus cartas
        texto = str(v)
        assert "mazo_cartas" not in texto and isinstance(p["mazo"], int)


def test_dos_personas_y_un_bot_en_la_misma_partida(cliente):
    c = crear(cliente, plazas=3, rellenar=True)
    b = cliente.post(f"/api/salas/{c['codigo']}/unirse", json={"nombre": "Beto"}).json()
    with conectar(cliente, c['codigo'], c['token']) as ana, \
         conectar(cliente, c['codigo'], b['token']) as beto:
        recibir_hasta(ana, lambda v: len([a for a in v["asientos"] if a["conectado"]]) == 2)
        ana.send_json({"accion": "iniciar"})
        va = recibir_hasta(ana, lambda v: v.get("partida"))
        vb = recibir_hasta(beto, lambda v: v.get("partida"))
        assert len(va["partida"]["jugadores"]) == 3
        assert sum(1 for j in va["partida"]["jugadores"] if j["bot"]) == 1     # un bot completa la tercera plaza
        # cada una ve sus propias cartas
        assert len(va["partida"]["yo"]["mano"]) == len(vb["partida"]["yo"]["mano"]) == 8


def test_acciones_ilegales_dan_error_y_no_rompen_nada(cliente):
    r = cliente.post("/api/rapida", json={"nombre": "Ana", "rivales": 1}).json()
    with conectar(cliente, r['codigo'], r['token']) as ws:
        v = recibir_hasta(ws, lambda v: v.get("partida"))
        for accion in ({"accion": "jugar", "cartas": ["pinchazo"]}, {"accion": "negar"}, {"accion": "dar", "carta": "x"},
                       {"accion": "insertar", "pos": "mucho"}, {"accion": "no_existe"}):
            ws.send_json(accion)
            for _ in range(50):
                m = ws.receive_json()
                if m["t"] == "error":
                    break
            else:
                raise AssertionError(f"no hubo error para {accion}")
        ws.send_text("esto no es json")
        ws.send_text("[1,2,3]")
        ws.send_json({"accion": "ping"})
        for _ in range(100):
            if ws.receive_json()["t"] == "pong":
                break
        else:
            raise AssertionError("el servidor dejó de responder")


def test_revancha_vuelve_al_vestibulo_sin_los_bots(cliente):
    r = cliente.post("/api/rapida", json={"nombre": "Ana", "rivales": 2}).json()
    with conectar(cliente, r['codigo'], r['token']) as ws:
        jugar_como_persona(ws, r["id"])
        ws.send_json({"accion": "revancha"})
        v = recibir_hasta(ws, lambda v: v["sala"]["estado"] == "lobby")
        assert [a["nombre"] for a in v["asientos"]] == ["Ana"] and "partida" not in v


def test_quien_se_va_en_plena_partida_queda_con_piloto_automatico(cliente):
    r = cliente.post("/api/rapida", json={"nombre": "Ana", "rivales": 2}).json()
    with conectar(cliente, r['codigo'], r['token']) as ws:
        recibir_hasta(ws, lambda v: v.get("partida"))
    # Ana se desconecta: la partida debe terminar sola, jugando el piloto automático
    sala = salas.get(r["codigo"])
    limite = time.time() + 20
    while sala.estado != "fin" and time.time() < limite:
        time.sleep(0.05)
    assert sala.estado == "fin" and sala.partida.ganador


def test_limpieza_de_salas_abandonadas(cliente, monkeypatch):
    from app import salas as m
    c = crear(cliente)
    sala = salas.get(c["codigo"])
    monkeypatch.setattr(m, "SALA_VACIA_S", 0)
    sala.sin_gente_desde = m.ahora() - 5
    import asyncio
    asyncio.run(salas.limpiar())
    assert salas.get(c["codigo"]) is None


def test_una_accion_tardia_tras_el_fin_se_ignora_sin_error(cliente):
    r = cliente.post("/api/rapida", json={"nombre": "Ana", "rivales": 1}).json()
    with conectar(cliente, r["codigo"], r["token"]) as ws:
        jugar_como_persona(ws, r["id"])
        ws.send_json({"accion": "robar"})          # llega tarde: la partida ya terminó
        ws.send_json({"accion": "ping"})
        for _ in range(50):
            m = ws.receive_json()
            assert m["t"] != "error", m
            if m["t"] == "pong":
                return
        raise AssertionError("no llegó el pong")


def test_una_rafaga_de_mensajes_recibe_un_aviso_y_no_se_cuelga(cliente, monkeypatch):
    import app.main as principal
    monkeypatch.setattr(principal, "MAX_MENSAJES", 3)
    c = crear(cliente)
    with conectar(cliente, c["codigo"], c["token"]) as ws:
        for _ in range(30):
            ws.send_json({"accion": "ping"})
        avisos = pongs = 0
        for _ in range(60):
            m = ws.receive_json()
            if m["t"] == "error" and "demasiado rápido" in m["mensaje"]:
                avisos += 1
            if m["t"] == "pong":
                pongs += 1
            if avisos and pongs >= 1:
                break
        assert avisos == 1                         # un solo aviso por ráfaga
        ws.send_json({"accion": "ping"})           # y tras calmarse vuelve a responder
        time.sleep(0.2)
        ws.send_json({"accion": "ping"})
        for _ in range(60):
            if ws.receive_json()["t"] == "pong":
                return
        raise AssertionError("no volvió a responder")
