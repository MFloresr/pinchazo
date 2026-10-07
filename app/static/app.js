/* Pinchazo: la interfaz. Todo lo que muestra viene del servidor (vista); aquí solo se dibuja y se envían acciones. */
(() => {
  const { createApp, ref, computed, watch, nextTick, onMounted } = Vue;
  const CLAVE_SESION = "pinchazo.sesion";
  const CLAVE_NOMBRE = "pinchazo.nombre";

  const leer = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const guardar = (k, v) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } };

  createApp({
    setup() {
      // ---------------------------------------------------------------- estado
      const nombre = ref(leer(CLAVE_NOMBRE) || "");
      const rivales = ref(3);
      const nivel = ref("medio");
      const codigoUnirse = ref("");
      const cargando = ref(false);
      const catalogo = ref({});
      const vista = ref(null);
      const aviso = ref("");
      const reconectando = ref(false);
      const copiado = ref(false);
      const sel = ref([]);
      const eligiendoObjetivo = ref(false);
      const posicion = ref(0);
      const registro = ref(null);
      const ahoraMs = ref(Date.now());
      const finEspera = ref(null);

      let ws = null;
      let sesion = null;
      let pingId = null;
      let reintentos = 0;
      let cerrando = false;
      let avisoId = null;

      // ---------------------------------------------------------------- avisos
      function mostrarAviso(texto, ms = 4500) {
        aviso.value = texto;
        clearTimeout(avisoId);
        avisoId = setTimeout(() => (aviso.value = ""), ms);
      }

      // ---------------------------------------------------------------- red
      async function api(url, cuerpo) {
        const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
        const datos = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof datos.detail === "string" ? datos.detail : "No se pudo completar la petición.");
        return datos;
      }

      function entrar(credenciales) {
        sesion = credenciales;
        guardar(CLAVE_SESION, JSON.stringify(credenciales));
        cerrando = false;
        conectar();
      }

      function conectar() {
        if (!sesion) return;
        const protocolo = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${protocolo}://${location.host}/ws/${sesion.codigo}`);
        ws.onopen = () => {
          ws.send(JSON.stringify({ accion: "entrar", token: sesion.token }));
          reconectando.value = false;
          reintentos = 0;
          clearInterval(pingId);
          pingId = setInterval(() => ws && ws.readyState === 1 && ws.send(JSON.stringify({ accion: "ping" })), 25000);
        };
        ws.onmessage = (e) => {
          const m = JSON.parse(e.data);
          if (m.t === "estado") {
            vista.value = m.vista;
            const espera = m.vista.partida && m.vista.partida.espera;
            finEspera.value = espera ? Date.now() + espera.segundos * 1000 : null;
          } else if (m.t === "error") {
            if (m.fatal) {
              olvidar();
              mostrarAviso(m.mensaje, 7000);
            } else {
              mostrarAviso(m.mensaje);
            }
          }
        };
        ws.onclose = () => {
          clearInterval(pingId);
          if (cerrando || !sesion) return;
          reconectando.value = true;
          reintentos += 1;
          setTimeout(conectar, Math.min(1000 * 2 ** (reintentos - 1), 8000));
        };
      }

      function olvidar() {
        cerrando = true;
        sesion = null;
        guardar(CLAVE_SESION, null);
        vista.value = null;
        finEspera.value = null;
        reconectando.value = false;
        if (ws) { try { ws.close(); } catch { /* ya cerrado */ } }
      }

      function enviar(msg) {
        if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
        else mostrarAviso("Sin conexión con el servidor. Reintentando…");
      }

      function salir() {
        enviar({ accion: "salir" });
        olvidar();
      }

      // ---------------------------------------------------------------- inicio
      function datosNombre() {
        guardar(CLAVE_NOMBRE, nombre.value);
        return nombre.value || "Jugador";
      }

      async function lanzar(peticion) {
        if (cargando.value) return;
        cargando.value = true;
        try {
          entrar(await peticion());
          history.replaceState(null, "", location.pathname);
        } catch (e) {
          mostrarAviso(e.message);
        } finally {
          cargando.value = false;
        }
      }

      const partidaRapida = () => lanzar(() => api("/api/rapida", { nombre: datosNombre(), rivales: rivales.value, nivel: nivel.value }));
      const crearSala = () => lanzar(() => api("/api/salas", { nombre: datosNombre(), plazas: 4, rellenar: true, nivel: nivel.value }));
      const unirse = () => lanzar(() => api(`/api/salas/${codigoUnirse.value.toUpperCase()}/unirse`, { nombre: datosNombre() }));

      async function copiarEnlace() {
        const enlace = `${location.origin}/?sala=${vista.value.sala.codigo}`;
        try {
          await navigator.clipboard.writeText(enlace);
          copiado.value = true;
          setTimeout(() => (copiado.value = false), 2000);
        } catch {
          mostrarAviso(`Copia este enlace: ${enlace}`, 9000);
        }
      }

      // ---------------------------------------------------------------- datos derivados
      const p = computed(() => (vista.value && vista.value.partida) || null);
      const yo = computed(() => (p.value ? p.value.yo : { mano: [], vision: null, vivo: false }));
      const yoId = computed(() => (vista.value ? vista.value.sala.yo : null));
      const soyDuenio = computed(() => vista.value && vista.value.sala.duenio === yoId.value);
      const miTurno = computed(() => !!p.value && yo.value.vivo && p.value.turno === yoId.value);
      const puedoRobar = computed(() => miTurno.value && p.value.fase === "turno");
      const debeDar = computed(() => !!p.value && p.value.fase === "favor" && p.value.favor && p.value.favor.de === yoId.value);
      const debeInsertar = computed(() => !!p.value && p.value.fase === "insertar" && p.value.insertando === yoId.value);
      const plazasLibres = computed(() => (vista.value ? Math.max(0, vista.value.sala.plazas - vista.value.asientos.length) : 0));
      const objetivosPosibles = computed(() => (p.value ? p.value.jugadores.filter((j) => j.vivo && j.id !== yoId.value && j.cartas > 0) : []));

      const info = (c) => catalogo.value[c] || { nombre: c, emoji: "🂠", texto: "", tipo: "" };
      const clase = (c) => "tipo-" + info(c).tipo;
      const inicial = (n) => (n || "?").trim().charAt(0).toUpperCase();
      const nombreDe = (id) => {
        const lista = p.value ? p.value.jugadores : vista.value ? vista.value.asientos : [];
        const j = lista.find((x) => x.id === id);
        return j ? j.nombre : "alguien";
      };

      const cartasSel = computed(() => sel.value.map((i) => yo.value.mano[i]));
      const jugable = computed(() => {
        const c = cartasSel.value;
        if (c.length === 1) return info(c[0]).tipo === "accion";
        if (c.length === 2) return c[0] === c[1] && info(c[0]).tipo === "mascota";
        return false;
      });
      const puedoJugar = computed(() => puedoRobar.value && jugable.value);

      const nivelRiesgo = computed(() => (!p.value ? "" : p.value.riesgo < 0.2 ? "bajo" : p.value.riesgo < 0.4 ? "medio" : "alto"));
      const restanteTexto = computed(() => {
        if (!finEspera.value) return "";
        return Math.max(0, Math.ceil((finEspera.value - ahoraMs.value) / 1000)) + " s";
      });
      const posicionTexto = computed(() => {
        if (!p.value) return "";
        if (posicion.value === 0) return "arriba del todo (la siguiente carta)";
        if (posicion.value >= p.value.mazo) return "al fondo del mazo";
        return `${posicion.value} carta${posicion.value === 1 ? "" : "s"} por debajo de la de arriba`;
      });
      const estadoTexto = computed(() => {
        const pa = p.value;
        if (!pa) return "";
        if (pa.fase === "fin") return "Fin de la partida";
        if (!yo.value.vivo) return "Estás fuera: mirando la partida";
        if (pa.fase === "ventana") return "Se ha jugado una carta: ¿alguien dice «¡Ni hablar!»?";
        if (pa.fase === "favor") return debeDar.value ? "Te piden un favor: elige una carta" : `${nombreDe(pa.favor.de)} elige qué carta dar…`;
        if (pa.fase === "insertar") return debeInsertar.value ? "Esconde el Pinchazo en el mazo" : `${nombreDe(pa.insertando)} esconde un Pinchazo…`;
        return miTurno.value ? "¡Es tu turno! Juega cartas y termina robando" : `Turno de ${nombreDe(pa.turno)}`;
      });

      // ---------------------------------------------------------------- jugar
      function alternar(i) {
        // Durante la ventana, tocar «¡Ni hablar!» en la mano lo juega directamente
        if (yo.value.mano[i] === "negar" && p.value && p.value.pendiente && p.value.pendiente.puedo_negar) {
          enviar({ accion: "negar" });
          return;
        }
        if (sel.value.includes(i)) sel.value = sel.value.filter((x) => x !== i);
        else sel.value = [...sel.value, i].slice(-2);
      }

      function jugarSeleccion() {
        const cartas = cartasSel.value;
        const necesitaObjetivo = cartas.length === 2 || cartas[0] === "favor";
        if (necesitaObjetivo) {
          if (!objetivosPosibles.value.length) return mostrarAviso("Nadie tiene cartas a las que pedir.");
          eligiendoObjetivo.value = true;
        } else {
          enviar({ accion: "jugar", cartas });
        }
      }

      function confirmarObjetivo(id) {
        enviar({ accion: "jugar", cartas: cartasSel.value, objetivo: id });
        eligiendoObjetivo.value = false;
      }

      // ---------------------------------------------------------------- efectos
      watch(() => yo.value.mano.join(","), () => { sel.value = []; eligiendoObjetivo.value = false; });
      watch(debeInsertar, (v) => { if (v) posicion.value = 0; });
      watch(() => (p.value ? p.value.log.length : 0), async () => {
        await nextTick();
        if (registro.value) registro.value.scrollTop = registro.value.scrollHeight;
      });

      onMounted(async () => {
        setInterval(() => (ahoraMs.value = Date.now()), 250);
        try { catalogo.value = await (await fetch("/api/cartas")).json(); } catch { mostrarAviso("No se pudieron cargar las cartas."); }
        const sala = new URLSearchParams(location.search).get("sala");
        if (sala) codigoUnirse.value = sala.toUpperCase().slice(0, 4);
        const guardada = leer(CLAVE_SESION);
        if (guardada) {
          try { entrar(JSON.parse(guardada)); } catch { guardar(CLAVE_SESION, null); }
        }
      });

      return {
        nombre, rivales, nivel, codigoUnirse, cargando, vista, aviso, reconectando, copiado, sel, eligiendoObjetivo, posicion, registro,
        p, yo, soyDuenio, miTurno, puedoRobar, puedoJugar, debeDar, debeInsertar, plazasLibres, objetivosPosibles,
        nivelRiesgo, restanteTexto, posicionTexto, estadoTexto,
        info, clase, inicial, nombreDe, enviar, salir, partidaRapida, crearSala, unirse, copiarEnlace,
        alternar, jugarSeleccion, confirmarObjetivo,
      };
    },
  }).mount("#app");
})();
