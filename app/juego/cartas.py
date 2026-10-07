"""Las cartas de Pinchazo: nombres, textos y cuántas hay de cada una.

Todo es original (nombres, textos y dibujos). Las reglas generales de este tipo de juegos no están
protegidas, pero los nombres, el arte y los textos de otros juegos sí, y aquí no se usa ninguno.
"""

# Cada carta: nombre visible, emoji que la dibuja, tipo y un texto corto de ayuda
CARTAS = {
    "pinchazo": {"nombre": "Pinchazo", "emoji": "💥", "tipo": "peligro",
                 "texto": "Si la robas sin un Parche, tu globo revienta y quedas fuera."},
    "parche": {"nombre": "Parche", "emoji": "🩹", "tipo": "salvacion",
               "texto": "Salva tu globo de un Pinchazo. Luego escondes el Pinchazo de nuevo en el mazo."},
    "esquivar": {"nombre": "Esquivar", "emoji": "💨", "tipo": "accion",
                 "texto": "Termina un turno sin robar carta."},
    "tartazo": {"nombre": "Tartazo", "emoji": "🥧", "tipo": "accion",
                "texto": "No robas y el siguiente juega dos turnos seguidos."},
    "bola": {"nombre": "Bola de cristal", "emoji": "🔮", "tipo": "accion",
             "texto": "Mira en secreto las 3 primeras cartas del mazo."},
    "remolino": {"nombre": "Remolino", "emoji": "🌀", "tipo": "accion",
                 "texto": "Baraja el mazo."},
    "favor": {"nombre": "Favor", "emoji": "🤲", "tipo": "accion",
              "texto": "Pide a otra persona una carta: ella elige cuál darte."},
    "negar": {"nombre": "¡Ni hablar!", "emoji": "✋", "tipo": "reaccion",
              "texto": "Cancela la carta que acaban de jugar. Se puede negar un «Ni hablar»."},
    "pulpo": {"nombre": "Pulpo", "emoji": "🐙", "tipo": "mascota", "texto": "Con otro Pulpo robas una carta al azar."},
    "loro": {"nombre": "Loro", "emoji": "🦜", "tipo": "mascota", "texto": "Con otro Loro robas una carta al azar."},
    "tortuga": {"nombre": "Tortuga", "emoji": "🐢", "tipo": "mascota", "texto": "Con otra Tortuga robas una carta al azar."},
    "erizo": {"nombre": "Erizo", "emoji": "🦔", "tipo": "mascota", "texto": "Con otro Erizo robas una carta al azar."},
    "flamenco": {"nombre": "Flamenco", "emoji": "🦩", "tipo": "mascota", "texto": "Con otro Flamenco robas una carta al azar."},
}

MASCOTAS = ["pulpo", "loro", "tortuga", "erizo", "flamenco"]
ACCIONES = ["esquivar", "tartazo", "bola", "remolino", "favor"]  # las que se juegan en tu turno

# Cartas del mazo, sin contar los Pinchazos ni los Parches (esos se reparten aparte)
CANTIDAD = {"esquivar": 4, "tartazo": 4, "bola": 5, "remolino": 4, "favor": 4, "negar": 5,
            **{m: 4 for m in MASCOTAS}}

CARTAS_INICIALES = 7      # además de un Parche
PARCHES_EN_EL_MAZO = 2    # los demás Parches que se esconden en el mazo


def mazo_base() -> list[str]:
    """Todas las cartas normales, sin barajar."""
    mazo: list[str] = []
    for carta, n in CANTIDAD.items():
        mazo += [carta] * n
    return mazo
