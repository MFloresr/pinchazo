"""Motor de reglas de Pinchazo. No sabe nada de la web: recibe acciones y cambia el estado.

Cómo se juega
-------------
- Cada turno puedes jugar las cartas que quieras y debes terminar robando una carta del mazo
  (o jugando «Esquivar» o «Tartazo», que terminan el turno sin robar).
- Si robas un Pinchazo y tienes un Parche, lo gastas y escondes el Pinchazo donde quieras del mazo.
  Si no tienes Parche, tu globo revienta y quedas fuera.
- Gana quien se queda la última persona con el globo entero.
- Al jugar una carta se abre una «ventana»: cualquiera puede responder con «¡Ni hablar!» para
  cancelarla, y otro «¡Ni hablar!» puede cancelar el anterior.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .cartas import ACCIONES, CARTAS_INICIALES, MASCOTAS, PARCHES_EN_EL_MAZO, mazo_base

MIN_JUGADORES = 2
MAX_JUGADORES = 5


class Fase(str, Enum):
    TURNO = "turno"        # la persona del turno juega cartas o roba
    VENTANA = "ventana"    # se acaba de jugar una carta: se puede responder con «¡Ni hablar!»
    FAVOR = "favor"        # alguien debe elegir qué carta dar
    INSERTAR = "insertar"  # alguien se salvó con un Parche y debe esconder el Pinchazo
    FIN = "fin"


class ReglaError(Exception):
    """Una acción que no se puede hacer ahora. El mensaje se muestra a la persona."""


@dataclass
class Jugador:
    id: str
    nombre: str
    es_bot: bool = False
    mano: list[str] = field(default_factory=list)
    vivo: bool = True


@dataclass
class Pendiente:
    """La carta (o pareja) que se acaba de jugar y espera a ver si alguien la niega."""
    jugador: str
    cartas: list[str]
    objetivo: str | None = None
    negada: bool = False
    cadena: list[str] = field(default_factory=list)  # quién ha dicho «¡Ni hablar!», en orden


class Partida:
    def __init__(self, jugadores: list[tuple[str, str, bool]], semilla: int | None = None):
        if not MIN_JUGADORES <= len(jugadores) <= MAX_JUGADORES:
            raise ReglaError(f"Se juega de {MIN_JUGADORES} a {MAX_JUGADORES} personas.")
        if len({j[0] for j in jugadores}) != len(jugadores):
            raise ReglaError("Hay identificadores repetidos.")
        self.rng = random.Random(semilla)
        self.jugadores = [Jugador(i, n, b) for i, n, b in jugadores]
        base = mazo_base()
        self.rng.shuffle(base)
        for j in self.jugadores:
            j.mano = [base.pop() for _ in range(CARTAS_INICIALES)] + ["parche"]
        n = len(self.jugadores)
        self.mazo: list[str] = base + ["pinchazo"] * (n - 1) + ["parche"] * PARCHES_EN_EL_MAZO
        self.rng.shuffle(self.mazo)  # la carta de arriba es mazo[-1]
        self.descarte: list[str] = []
        self.turno = 0                  # índice de quien juega
        self.turnos_pendientes = 1      # cuántos robos le tocan todavía
        self.numero_turno = 1           # sube cada vez que empieza el turno de alguien
        self.fase = Fase.TURNO
        self.pendiente: Pendiente | None = None
        self.favor: dict | None = None  # {"de": id que da, "para": id que recibe}
        self.insertando: str | None = None
        self.visiones: dict[str, list[str]] = {}  # lo que cada persona ha visto con la Bola de cristal
        self.log: list[str] = ["¡Empieza la partida! Que nadie pinche su globo."]
        self.ganador: str | None = None
        self.version = 0
        self.eventos: list[dict] = []   # lo que ha pasado, para animarlo y sonarlo en el navegador
        self._n_evento = 0
        self._evento("turno", j=self.actual().id)

    # ------------------------------------------------------------------ consultas
    def jugador(self, jid: str) -> Jugador:
        for j in self.jugadores:
            if j.id == jid:
                return j
        raise ReglaError("Esa persona no está en la partida.")

    def vivos(self) -> list[Jugador]:
        return [j for j in self.jugadores if j.vivo]

    def actual(self) -> Jugador:
        return self.jugadores[self.turno]

    def siguiente_vivo(self, indice: int | None = None) -> int:
        i = self.turno if indice is None else indice
        for paso in range(1, len(self.jugadores) + 1):
            k = (i + paso) % len(self.jugadores)
            if self.jugadores[k].vivo:
                return k
        return i

    def pinchazos_en_el_mazo(self) -> int:
        return self.mazo.count("pinchazo")

    def riesgo(self) -> float:
        """Probabilidad de que la siguiente carta sea un Pinchazo, para quien no ha visto nada."""
        return self.pinchazos_en_el_mazo() / len(self.mazo) if self.mazo else 0.0

    def ultimo_en_actuar(self) -> str | None:
        if not self.pendiente:
            return None
        return self.pendiente.cadena[-1] if self.pendiente.cadena else self.pendiente.jugador

    def puede_negar(self, jid: str) -> bool:
        """¿Puede esta persona decir «¡Ni hablar!» ahora mismo?"""
        if self.fase != Fase.VENTANA or not self.pendiente:
            return False
        j = self.jugador(jid)
        return j.vivo and "negar" in j.mano and jid != self.ultimo_en_actuar()

    # ------------------------------------------------------------------ utilidades internas
    def _cambio(self) -> None:
        self.version += 1

    def _evento(self, tipo: str, **datos) -> None:
        """Apunta un hecho estructurado (con número creciente) para que cada navegador lo anime."""
        self._n_evento += 1
        self.eventos.append({"n": self._n_evento, "tipo": tipo, **datos})
        del self.eventos[:-40]

    def _anotar(self, texto: str) -> None:
        self.log.append(texto)
        del self.log[:-60]

    def _nombre(self, jid: str) -> str:
        return self.jugador(jid).nombre

    def _quitar(self, j: Jugador, carta: str) -> None:
        j.mano.remove(carta)
        self.descarte.append(carta)

    def _comprobar_fin(self) -> bool:
        vivos = self.vivos()
        if len(vivos) == 1:
            self.fase = Fase.FIN
            self.ganador = vivos[0].id
            self._anotar(f"🏆 ¡{vivos[0].nombre} gana la partida!")
            self._evento("fin", j=vivos[0].id)
            return True
        return False

    def _empezar_turno(self, indice: int, turnos: int) -> None:
        self.turno = indice
        self.turnos_pendientes = turnos
        self.numero_turno += 1
        self.fase = Fase.TURNO
        extra = f" ({turnos} turnos seguidos)" if turnos > 1 else ""
        self._anotar(f"Turno de {self.actual().nombre}{extra}.")
        self._evento("turno", j=self.actual().id, turnos=turnos)

    def _fin_de_un_turno(self) -> None:
        """Se ha gastado uno de los turnos de la persona. Si no le quedan, pasa a la siguiente."""
        self.turnos_pendientes -= 1
        if self.turnos_pendientes <= 0:
            self._empezar_turno(self.siguiente_vivo(), 1)
        else:
            self.numero_turno += 1
            self.fase = Fase.TURNO
            self._anotar(f"{self.actual().nombre} aún tiene {self.turnos_pendientes} turno(s).")

    def _reponer_mazo(self) -> None:
        """Casi imposible, pero si el mazo se acabara se baraja el descarte (sin Pinchazos)."""
        if self.mazo:
            return
        self.mazo = [c for c in self.descarte if c != "pinchazo"]
        self.descarte = [c for c in self.descarte if c == "pinchazo"]
        self.rng.shuffle(self.mazo)
        self._anotar("Se baraja el descarte para formar un mazo nuevo.")
        if not self.mazo:
            raise ReglaError("No quedan cartas en el mazo.")

    # ------------------------------------------------------------------ acciones
    def jugar(self, jid: str, cartas: list[str], objetivo: str | None = None) -> None:
        """Juega una carta de acción o una pareja de mascotas. Abre la ventana para «¡Ni hablar!»."""
        if self.fase != Fase.TURNO:
            raise ReglaError("Ahora no puedes jugar cartas.")
        j = self.jugador(jid)
        if j.id != self.actual().id:
            raise ReglaError("No es tu turno.")
        if not cartas:
            raise ReglaError("Elige qué carta quieres jugar.")
        copia = list(j.mano)
        for c in cartas:
            if c not in copia:
                raise ReglaError("No tienes esa carta.")
            copia.remove(c)

        if len(cartas) == 1:
            if cartas[0] not in ACCIONES:
                raise ReglaError("Esa carta no se juega sola.")
            necesita_objetivo = cartas[0] == "favor"
        elif len(cartas) == 2:
            if cartas[0] != cartas[1] or cartas[0] not in MASCOTAS:
                raise ReglaError("Una pareja necesita dos mascotas iguales.")
            necesita_objetivo = True
        else:
            raise ReglaError("Puedes jugar una carta o una pareja.")

        if necesita_objetivo:
            if objetivo is None:
                raise ReglaError("Elige a quién se lo pides.")
            o = self.jugador(objetivo)
            if not o.vivo or o.id == j.id:
                raise ReglaError("Esa persona no es un objetivo válido.")
            if not o.mano:
                raise ReglaError(f"{o.nombre} no tiene cartas.")
        else:
            objetivo = None

        for c in cartas:
            self._quitar(j, c)
        self.pendiente = Pendiente(jugador=jid, cartas=list(cartas), objetivo=objetivo)
        self.fase = Fase.VENTANA
        nombres = " + ".join(c for c in cartas)
        destino = f" contra {self._nombre(objetivo)}" if objetivo else ""
        self._anotar(f"{j.nombre} juega «{nombres}»{destino}.")
        self._evento("juega", j=jid, cartas=list(cartas), obj=objetivo)
        self._cambio()

    def negar(self, jid: str) -> None:
        """Responde con «¡Ni hablar!»: cancela la última carta, o cancela el «Ni hablar» anterior."""
        if self.fase != Fase.VENTANA or not self.pendiente:
            raise ReglaError("No hay nada que negar ahora.")
        j = self.jugador(jid)
        if not j.vivo:
            raise ReglaError("Ya no estás en la partida.")
        if "negar" not in j.mano:
            raise ReglaError("No tienes «¡Ni hablar!».")
        if jid == self.ultimo_en_actuar():
            raise ReglaError("Esa carta ya es tuya: espera a que responda otra persona.")
        self._quitar(j, "negar")
        p = self.pendiente
        p.negada = not p.negada
        p.cadena.append(jid)
        self._anotar(f"✋ {j.nombre}: «¡Ni hablar!»" + (" (anula la carta)" if p.negada else " (la carta vuelve a valer)"))
        self._evento("negar", j=jid, anulada=p.negada)
        self._cambio()

    def resolver(self) -> None:
        """Se acabó la ventana: si nadie la negó (o se negó un número par de veces), la carta hace efecto."""
        if self.fase != Fase.VENTANA or not self.pendiente:
            raise ReglaError("No hay ninguna carta pendiente.")
        p, self.pendiente = self.pendiente, None
        self.fase = Fase.TURNO
        self._evento("resuelve", j=p.jugador, cartas=list(p.cartas), obj=p.objetivo, anulada=p.negada)
        if p.negada:
            self._anotar("La carta queda anulada.")
            self._cambio()
            return
        j = self.jugador(p.jugador)
        if len(p.cartas) == 2:
            o = self.jugador(p.objetivo)
            if o.mano:
                carta = o.mano.pop(self.rng.randrange(len(o.mano)))
                j.mano.append(carta)
                self._anotar(f"{j.nombre} le roba una carta a {o.nombre}.")
                self._evento("roba_pareja", j=j.id, obj=o.id)
        else:
            self._efecto(j, p)
        self._cambio()

    def _efecto(self, j: Jugador, p: Pendiente) -> None:
        carta = p.cartas[0]
        if carta == "esquivar":
            self._anotar(f"{j.nombre} esquiva y no roba.")
            self._fin_de_un_turno()
        elif carta == "tartazo":
            siguiente = self.siguiente_vivo()
            turnos = 2 * self.turnos_pendientes
            self._anotar(f"🥧 {j.nombre} le lanza un tartazo a {self.jugadores[siguiente].nombre}.")
            self._empezar_turno(siguiente, turnos)
        elif carta == "bola":
            self.visiones[j.id] = list(reversed(self.mazo[-3:]))
            self._anotar(f"{j.nombre} mira el futuro.")
            self._evento("mira", j=j.id)
        elif carta == "remolino":
            self.rng.shuffle(self.mazo)
            self.visiones.clear()
            self._anotar("🌀 El mazo se baraja.")
            self._evento("baraja", j=j.id)
        elif carta == "favor":
            if self.jugador(p.objetivo).mano:
                self.favor = {"de": p.objetivo, "para": j.id}
                self.fase = Fase.FAVOR
                self._anotar(f"{self._nombre(p.objetivo)} debe darle una carta a {j.nombre}.")

    def dar(self, jid: str, carta: str) -> None:
        """Quien debe un favor elige qué carta entrega."""
        if self.fase != Fase.FAVOR or not self.favor:
            raise ReglaError("Nadie te ha pedido un favor.")
        if jid != self.favor["de"]:
            raise ReglaError("No te toca a ti elegir.")
        de = self.jugador(jid)
        if carta not in de.mano:
            raise ReglaError("No tienes esa carta.")
        para = self.jugador(self.favor["para"])
        de.mano.remove(carta)
        para.mano.append(carta)
        self._anotar(f"{de.nombre} le da una carta a {para.nombre}.")
        self._evento("favor_da", j=de.id, obj=para.id)
        self.favor = None
        self.fase = Fase.TURNO
        self._cambio()

    def robar(self, jid: str) -> None:
        """Roba la carta de arriba del mazo. Es lo que termina el turno."""
        if self.fase != Fase.TURNO:
            raise ReglaError("Ahora no puedes robar.")
        j = self.jugador(jid)
        if j.id != self.actual().id:
            raise ReglaError("No es tu turno.")
        self._reponer_mazo()
        carta = self.mazo.pop()
        # Lo que alguien había visto se desplaza: la carta de arriba ya no está
        for k, v in list(self.visiones.items()):
            self.visiones[k] = v[1:] if v and v[0] == carta else []
        if carta != "pinchazo":
            j.mano.append(carta)
            self._anotar(f"{j.nombre} roba una carta.")
            self._evento("roba", j=j.id)
            self._fin_de_un_turno()
        elif "parche" in j.mano:
            self._quitar(j, "parche")
            self.fase = Fase.INSERTAR
            self.insertando = j.id
            self._anotar(f"💥 ¡Pinchazo! {j.nombre} usa un Parche y salva su globo.")
            self._evento("parche", j=j.id)
        else:
            j.vivo = False
            self.descarte += j.mano + ["pinchazo"]
            j.mano = []
            self.visiones.pop(j.id, None)
            self._anotar(f"💥 ¡Pinchazo! El globo de {j.nombre} revienta. Queda fuera.")
            self._evento("pincha", j=j.id)
            if not self._comprobar_fin():
                self._empezar_turno(self.siguiente_vivo(), 1)
        self._cambio()

    def insertar(self, jid: str, posicion: int) -> None:
        """Esconde el Pinchazo en el mazo. 0 = justo arriba (el siguiente lo roba)."""
        if self.fase != Fase.INSERTAR or self.insertando != jid:
            raise ReglaError("No tienes ningún Pinchazo que esconder.")
        if not 0 <= posicion <= len(self.mazo):
            raise ReglaError("Esa posición no existe.")
        self.mazo.insert(len(self.mazo) - posicion, "pinchazo")
        self.visiones.clear()
        self.insertando = None
        self._anotar(f"{self._nombre(jid)} esconde el Pinchazo en el mazo.")
        self._evento("inserta", j=jid)
        self._fin_de_un_turno()
        self._cambio()
