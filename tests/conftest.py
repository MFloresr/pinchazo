import os

# Antes de importar la app: las partidas de prueba van 100 veces más rápido
os.environ.setdefault("PINCHAZO_RITMO", "0.01")
os.environ.setdefault("PINCHAZO_MAX_MENSAJES", "100000")   # a ese ritmo las pruebas mandan muchos mensajes
