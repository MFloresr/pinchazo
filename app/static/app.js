/* Pinchazo: la interfaz. El servidor manda el estado (vista) y los hechos (eventos); aquí solo se dibuja, se anima y se envían acciones. */
(() => {
  const { createApp, ref, computed, watch, nextTick, onMounted, inject } = Vue;
  const CLAVE_SESION = "pinchazo.sesion";
  const CLAVE_NOMBRE = "pinchazo.nombre";
  const CLAVE_SONIDO = "pinchazo.sonido";
  const TITULO = document.title;

  const leer = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const guardar = (k, v) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } };
  const reducir = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const sueño = (ms) => new Promise((r) => setTimeout(r, ms));

  const catalogo = ref({});
  const mudo = ref(leer(CLAVE_SONIDO) === "0");
  const FOIL = new Set(["pinchazo", "parche", "negar"]);
  const COLOR_TIPO = { peligro: "#EF3B5B", salvacion: "#3DDBA6", accion: "#38A8F8", reaccion: "#8B6CFF", mascota: "#FFB020" };
  const COLORES_AVATAR = ["#38A8F8", "#3DDBA6", "#8B6CFF", "#FF9A3D", "#FF6FB1", "#2FB5C9"];

  // ---------------------------------------------------------------- dibujo de una carta
  function claseCarta(id, dorso) {
    if (dorso) return "dorso";
    const c = catalogo.value[id];
    return c ? `tipo-${c.tipo}${FOIL.has(id) ? " foil" : ""}` : "";
  }
  function interiorCarta(id, dorso) {
    if (dorso) return '<span class="papel"></span><span class="motivo"><img src="/static/img/globo.webp" alt="" draggable="false"></span>';
    const c = catalogo.value[id];
    if (!c) return "";
    const img = `/static/img/${esc(id)}.webp`;
    return `<span class="papel"></span><span class="esq arriba"><img src="${img}" alt="" draggable="false"></span>` +
      `<span class="arte"><img class="ilus" src="${img}" alt="" draggable="false"></span>` +
      `<span class="esq abajo"><img src="${img}" alt="" draggable="false"></span>` +
      `<span class="titulo${c.nombre.length > 9 ? " largo" : ""}">${esc(c.nombre)}</span><span class="texto">${esc(c.texto)}</span><span class="brillo"></span>`;
  }

  // ---------------------------------------------------------------- sonido (sintetizado, sin archivos)
  let ctxAudio = null;
  function ac() {
    if (mudo.value) return null;
    try {
      if (!ctxAudio) ctxAudio = new (window.AudioContext || window.webkitAudioContext)();
      if (ctxAudio.state === "suspended") ctxAudio.resume();
      return ctxAudio;
    } catch { return null; }
  }
  function tono(f0, dur, { tipo = "sine", v = 0.12, t = 0, f1 = f0 } = {}) {
    const c = ac(); if (!c) return;
    const t0 = c.currentTime + t, o = c.createOscillator(), g = c.createGain();
    o.type = tipo; o.frequency.setValueAtTime(f0, t0);
    if (f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(v, t0 + 0.012); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g).connect(c.destination); o.start(t0); o.stop(t0 + dur + 0.03);
  }
  function ruido(dur, { v = 0.1, t = 0, f0 = 800, f1 = 800, q = 1, tipo = "bandpass" } = {}) {
    const c = ac(); if (!c) return;
    const t0 = c.currentTime + t, n = Math.max(1, Math.floor(c.sampleRate * dur)), b = c.createBuffer(1, n, c.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    const s = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
    s.buffer = b; f.type = tipo; f.Q.value = q; f.frequency.setValueAtTime(f0, t0); f.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t0 + dur);
    g.gain.setValueAtTime(v, t0); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    s.connect(f).connect(g).connect(c.destination); s.start(t0);
  }
  const SONIDOS = {
    robar: () => { ruido(0.09, { v: 0.1, f0: 1800, f1: 900, q: 2 }); tono(520, 0.07, { f1: 700, v: 0.06 }); },
    jugar: () => { ruido(0.2, { v: 0.12, f0: 500, f1: 2400, q: 1.5 }); tono(300, 0.12, { f1: 420, v: 0.05, tipo: "triangle" }); },
    resuelve: () => { tono(660, 0.08, { tipo: "triangle", v: 0.06 }); tono(880, 0.1, { t: 0.07, tipo: "triangle", v: 0.05 }); },
    negar: () => { tono(190, 0.22, { tipo: "sawtooth", v: 0.08, f1: 150 }); tono(120, 0.3, { t: 0.1, tipo: "square", v: 0.06, f1: 80 }); },
    pincha: () => { ruido(0.6, { v: 0.38, f0: 2400, f1: 80, tipo: "lowpass" }); tono(110, 0.5, { f1: 35, v: 0.3 }); },
    parche: () => [523, 659, 784].forEach((f, i) => tono(f, 0.16, { t: i * 0.08, tipo: "triangle", v: 0.09 })),
    turno: () => { tono(784, 0.14, { v: 0.09 }); tono(1047, 0.2, { t: 0.12, v: 0.09 }); },
    ganar: () => [523, 659, 784, 1047, 1319].forEach((f, i) => tono(f, 0.24, { t: i * 0.1, tipo: "triangle", v: 0.11 })),
    emote: () => tono(700, 0.12, { f1: 1200, v: 0.07 }),
    baraja: () => { for (let i = 0; i < 5; i++) ruido(0.07, { t: i * 0.07, v: 0.07, f0: 2000, f1: 1200, q: 3 }); },
    mira: () => [880, 1175, 1568].forEach((f, i) => tono(f, 0.25, { t: i * 0.07, v: 0.05 })),
    clic: () => tono(620, 0.04, { v: 0.05, tipo: "triangle" }),
  };
  const sonar = (n) => { try { if (SONIDOS[n]) SONIDOS[n](); } catch { /* sin audio */ } };
  const vibrar = (patron) => { try { if (!mudo.value && navigator.vibrate) navigator.vibrate(patron); } catch { /* sin vibración */ } };

  // ---------------------------------------------------------------- efectos visuales con la API de animaciones
  const centroDe = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
  function volar(id, desde, hasta, { dur = 520, retraso = 0, giro = 0 } = {}) {
    if (reducir || !desde || !hasta) return;
    const w = 62, e = document.createElement("div");
    e.className = "vuelo";
    e.innerHTML = `<span class="carta ${claseCarta(id, !id)}" style="--cw:${w}px">${interiorCarta(id, !id)}</span>`;
    e.style.left = desde.x - w / 2 + "px"; e.style.top = desde.y - w * 0.7 + "px";
    document.body.appendChild(e);
    const a = e.animate([
      { transform: "translate(0,0) rotate(0deg) scale(.8)", opacity: 0 },
      { opacity: 1, offset: 0.12 },
      { transform: `translate(${hasta.x - desde.x}px,${hasta.y - desde.y}px) rotate(${giro}deg) scale(1.05)`, opacity: 1 },
    ], { duration: dur, delay: retraso, easing: "cubic-bezier(.3,.7,.3,1)", fill: "both" });
    a.onfinish = () => e.remove();
  }
  function chispas(punto, { n = 18, colores = ["#FFD23F", "#FF6FB1", "#38A8F8", "#3DDBA6"], radio = 90, dur = 750 } = {}) {
    if (reducir || !punto) return;
    for (let i = 0; i < n; i++) {
      const d = document.createElement("i"), s = 6 + Math.random() * 8, ang = Math.random() * Math.PI * 2, dist = radio * (0.4 + Math.random() * 0.6);
      d.className = "chispa"; d.style.cssText = `width:${s}px;height:${s}px;left:${punto.x - s / 2}px;top:${punto.y - s / 2}px;background:${colores[i % colores.length]}`;
      document.body.appendChild(d);
      d.animate([{ transform: "translate(0,0) scale(1)", opacity: 1 }, { transform: `translate(${Math.cos(ang) * dist}px,${Math.sin(ang) * dist + 22}px) scale(.2)`, opacity: 0 }],
        { duration: dur * (0.7 + Math.random() * 0.6), easing: "cubic-bezier(.1,.7,.3,1)", fill: "forwards" }).onfinish = () => d.remove();
    }
  }
  function confeti() {
    if (reducir) return;
    const colores = ["#EF3B5B", "#38A8F8", "#FFD23F", "#3DDBA6", "#8B6CFF", "#FF9A3D"];
    for (let i = 0; i < 110; i++) {
      const d = document.createElement("i"), x = Math.random() * innerWidth;
      d.className = "chispa"; d.style.cssText = `width:9px;height:14px;border-radius:2px;left:${x}px;top:-20px;background:${colores[i % colores.length]}`;
      document.body.appendChild(d);
      d.animate([{ transform: "translate(0,0) rotate(0deg)", opacity: 1 }, { transform: `translate(${(Math.random() - 0.5) * 220}px,${innerHeight + 40}px) rotate(${Math.random() * 900}deg)`, opacity: 1 }],
        { duration: 2200 + Math.random() * 1800, delay: Math.random() * 900, easing: "cubic-bezier(.3,.2,.6,1)", fill: "forwards" }).onfinish = () => d.remove();
    }
  }

  // ---------------------------------------------------------------- componente carta
  const app = createApp({
    setup() {
      // ------------------------------------------------------------ estado
      const nombre = ref(leer(CLAVE_NOMBRE) || "");
      const nRivales = ref(3);
      const nivel = ref("medio");
      const codigoUnirse = ref("");
      const cargando = ref(false);
      const vista = ref(null);
      const aviso = ref("");
      const reconectando = ref(false);
      const copiado = ref(false);
      const sel = ref([]);
      const cartasPend = ref(null);          // cartas que se van a jugar y esperan que elijas a quién
      const posicion = ref(0);
      const registro = ref(null);
      const registroAbierto = ref(false);
      const manoZona = ref(null);
      const reglas = ref(null);
      const ahoraMs = ref(Date.now());
      const finEspera = ref(null);
      const totalEspera = ref(1);
      const foco = ref(-1);
      const emotesAbierto = ref(false);
      const emotes = ref([]);
      const anuncio = ref(null);
      const sello = ref(null);
      const sacude = ref(false);
      const barajando = ref(false);
      const mirando = ref(false);
      const resaltado = ref(null);
      const arrastre = ref(null);
      const sobreMesa = ref(false);
      const sobreAsiento = ref(null);
      const area = ref({ w: innerWidth, h: innerHeight });

      const niveles = [{ v: "facil", t: "Fácil" }, { v: "medio", t: "Medio" }, { v: "dificil", t: "Difícil" }];
      const demo = ["pinchazo", "parche", "negar", "bola", "pulpo"];
      const emotesLista = [
        { k: "risa", t: "Risa" }, { k: "aplauso", t: "Aplauso" }, { k: "susto", t: "Susto" }, { k: "diablo", t: "Travieso" },
        { k: "fiesta", t: "Fiesta" }, { k: "llanto", t: "Llanto" }, { k: "fuego", t: "Fuego" }, { k: "bomba", t: "Bomba" },
      ];
      const globosFondo = [
        { k: 1, s: 70, x: 6, d: 22, r: -3, dx: 40, bl: 0 }, { k: 2, s: 110, x: 22, d: 30, r: -14, dx: -30, bl: 2 }, { k: 3, s: 56, x: 41, d: 19, r: -9, dx: 30, bl: 0 },
        { k: 4, s: 90, x: 63, d: 27, r: -20, dx: -50, bl: 1 }, { k: 5, s: 64, x: 80, d: 21, r: -6, dx: 35, bl: 0 }, { k: 6, s: 120, x: 92, d: 34, r: -25, dx: -40, bl: 3 },
      ];

      let ws = null, sesion = null, pingId = null, reintentos = 0, cerrando = false, avisoId = null;
      let ultimoEvento = null;               // número del último hecho ya animado (null: aún no se ha recibido el primer estado)
      let esperaClave = "";
      let pre = null, ignorarClick = false;  // arrastre en preparación y clic que hay que tragarse tras arrastrar

      // ------------------------------------------------------------ avisos y anuncios
      function mostrarAviso(texto, ms = 4500) {
        aviso.value = texto;
        clearTimeout(avisoId);
        avisoId = setTimeout(() => (aviso.value = ""), ms);
      }
      let kAnuncio = 0, anuncioId = null, selloId = null;
      function anunciar(texto, tono = "", ms = 1500) {
        anuncio.value = { texto, tono, k: ++kAnuncio };
        clearTimeout(anuncioId);
        anuncioId = setTimeout(() => (anuncio.value = null), ms);
      }
      function sellar(texto) {
        sello.value = { texto, k: ++kAnuncio };
        clearTimeout(selloId);
        selloId = setTimeout(() => (sello.value = null), 1500);
      }
      function breve(r, ms) { r.value = true; setTimeout(() => (r.value = false), ms); }

      // ------------------------------------------------------------ red
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
          if (m.t === "estado") recibirEstado(m.vista);
          else if (m.t === "emote") mostrarEmote(m.id, m.e);
          else if (m.t === "error") {
            if (m.fatal) { olvidar(); mostrarAviso(m.mensaje, 7000); } else mostrarAviso(m.mensaje);
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

      function recibirEstado(v) {
        vista.value = v;
        const pa = v.partida;
        if (!pa) { ultimoEvento = null; finEspera.value = null; esperaClave = ""; return; }
        if (pa.espera) {
          const clave = `${pa.espera.jugador}|${pa.fase}`;
          if (clave !== esperaClave || pa.espera.segundos > totalEspera.value) totalEspera.value = Math.max(0.5, pa.espera.segundos);
          esperaClave = clave;
          finEspera.value = Date.now() + pa.espera.segundos * 1000;
        } else { finEspera.value = null; esperaClave = ""; }
        procesarEventos(pa.eventos || []);
      }

      function olvidar() {
        cerrando = true;
        sesion = null;
        guardar(CLAVE_SESION, null);
        vista.value = null;
        finEspera.value = null;
        ultimoEvento = null;
        reconectando.value = false;
        registroAbierto.value = false;
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

      // ------------------------------------------------------------ inicio
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
      const partidaRapida = () => lanzar(() => api("/api/rapida", { nombre: datosNombre(), rivales: nRivales.value, nivel: nivel.value }));
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

      // ------------------------------------------------------------ datos derivados
      const p = computed(() => (vista.value && vista.value.partida) || null);
      const yo = computed(() => (p.value ? p.value.yo : { mano: [], vision: null, vivo: false }));
      const yoId = computed(() => (vista.value ? vista.value.sala.yo : null));
      const soyDuenio = computed(() => !!vista.value && vista.value.sala.duenio === yoId.value);
      const miTurno = computed(() => !!p.value && yo.value.vivo && p.value.turno === yoId.value && p.value.fase !== "fin");
      const puedoRobar = computed(() => miTurno.value && p.value.fase === "turno");
      const debeDar = computed(() => !!p.value && p.value.fase === "favor" && p.value.favor && p.value.favor.de === yoId.value);
      const debeInsertar = computed(() => !!p.value && p.value.fase === "insertar" && p.value.insertando === yoId.value);
      const plazasLibres = computed(() => (vista.value ? Math.max(0, vista.value.sala.plazas - vista.value.asientos.length) : 0));
      const otros = computed(() => (p.value ? p.value.jugadores.filter((j) => j.id !== yoId.value) : []));
      const eligiendo = computed(() => !!cartasPend.value);
      const puedoNegar = computed(() => !!p.value && !!p.value.pendiente && p.value.pendiente.puedo_negar);

      const info = (c) => catalogo.value[c] || { nombre: c || "", texto: "", tipo: "" };
      const inicial = (n) => (n || "?").trim().charAt(0).toUpperCase();
      const color = (id) => { let h = 0; for (const ch of String(id || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return COLORES_AVATAR[h % COLORES_AVATAR.length]; };
      const nombreDe = (id) => {
        const lista = p.value ? p.value.jugadores : vista.value ? vista.value.asientos : [];
        const j = lista.find((x) => x.id === id);
        return j ? j.nombre : "alguien";
      };
      const arco = (k) => { const t = k - (otros.value.length - 1) / 2; return (t * t * 5).toFixed(1) + "px"; };
      const cantidad = (id) => (catalogo.value[id] && catalogo.value[id].cantidad) || 0;
      const cuantas = (c) => yo.value.mano.filter((x) => x === c).length;
      const mascotaRepetida = (c) => info(c).tipo === "mascota" && cuantas(c) >= 2;
      const claveCarta = (c, i) => yo.value.mano.slice(0, i).filter((x) => x === c).length;
      const esJugable = (c) => {
        const t = info(c).tipo;
        if (c === "negar") return puedoNegar.value;
        if (!puedoRobar.value) return false;
        return t === "accion" || (t === "mascota" && cuantas(c) >= 2);
      };
      const esObjetivo = (j) => j.vivo && j.id !== yoId.value && j.cartas > 0;

      const cartasSel = computed(() => sel.value.map((i) => yo.value.mano[i]).filter(Boolean));
      const jugable = computed(() => {
        const c = cartasSel.value;
        if (c.length === 1) return info(c[0]).tipo === "accion";
        if (c.length === 2) return c[0] === c[1] && info(c[0]).tipo === "mascota";
        return false;
      });
      const puedoJugar = computed(() => puedoRobar.value && jugable.value && !eligiendo.value);

      const pctRiesgo = computed(() => (p.value ? Math.round(p.value.riesgo * 100) : 0));
      const nivelRiesgo = computed(() => (!p.value ? "" : p.value.riesgo < 0.2 ? "bajo" : p.value.riesgo < 0.4 ? "medio" : "alto"));
      const colorRiesgo = computed(() => `hsl(${Math.round(150 - Math.min(1, (p.value ? p.value.riesgo : 0) / 0.55) * 150)} 85% 55%)`);
      const escalaGlobo = computed(() => (0.6 + Math.min(1, (p.value ? p.value.riesgo : 0) / 0.5) * 0.42).toFixed(3));

      const progresoEspera = computed(() => {
        if (!finEspera.value) return 0;
        return Math.max(0, Math.min(1, (finEspera.value - ahoraMs.value) / (totalEspera.value * 1000)));
      });
      const restanteTexto = computed(() => (finEspera.value ? Math.max(0, Math.ceil((finEspera.value - ahoraMs.value) / 1000)) + " s" : ""));
      const posicionTexto = computed(() => {
        if (!p.value) return "";
        if (posicion.value === 0) return "Arriba del todo: la siguiente carta";
        if (posicion.value >= p.value.mazo) return "Al fondo del mazo";
        return `${posicion.value} carta${posicion.value === 1 ? "" : "s"} por debajo de la de arriba`;
      });
      const estadoTexto = computed(() => {
        const pa = p.value;
        if (!pa) return "";
        if (pa.fase === "fin") return "Fin de la partida";
        if (!yo.value.vivo) return "Estás fuera: mirando la partida";
        if (pa.fase === "ventana") return puedoNegar.value ? "¿Dices «¡Ni hablar!»?" : "Se ha jugado una carta…";
        if (pa.fase === "favor") return debeDar.value ? "Te piden un favor: elige una carta" : `${nombreDe(pa.favor.de)} elige qué carta dar…`;
        if (pa.fase === "insertar") return debeInsertar.value ? "Esconde el Pinchazo en el mazo" : `${nombreDe(pa.insertando)} esconde un Pinchazo…`;
        return miTurno.value ? "¡Es tu turno!" : `Turno de ${nombreDe(pa.turno)}`;
      });
      const focoCarta = computed(() => {
        const i = foco.value >= 0 ? foco.value : sel.value.length ? sel.value[sel.value.length - 1] : -1;
        return i >= 0 ? yo.value.mano[i] || null : null;
      });
      const pistaTexto = computed(() => {
        const pa = p.value;
        if (!pa || pa.fase === "fin") return "";
        if (!yo.value.vivo) return "Tu globo reventó. Puedes seguir mirando la partida.";
        if (eligiendo.value) return "Elige a quién: toca su avatar.";
        if (puedoNegar.value) return "Puedes frenar esa carta con «¡Ni hablar!».";
        if (puedoRobar.value) return "Arrastra una carta a la mesa para jugarla, o toca el mazo para robar y terminar el turno.";
        return "Pasa el ratón o toca una carta para ver qué hace.";
      });

      // ------------------------------------------------------------ mano en abanico
      const estiloAbanico = (i) => {
        const n = yo.value.mano.length, t = i - (n - 1) / 2;
        const cw = Math.max(78, Math.min(116, 0.21 * area.value.w, 0.15 * area.value.h));
        const paso = Math.min(cw * 0.78, (area.value.w - 40 - cw) / Math.max(1, n - 1));
        const tmax = Math.max(1, (n - 1) / 2);
        return { "--t": t.toFixed(2), "--z": i + 1, "--paso": paso.toFixed(1) + "px", "--ang": Math.min(3.8, 24 / Math.max(n, 1)).toFixed(2) + "deg", "--curva": Math.min(2.4, 34 / (tmax * tmax)).toFixed(2) + "px" };
      };

      // ------------------------------------------------------------ jugar: toque, teclado o arrastre
      function alternar(i) {
        if (ignorarClick) { ignorarClick = false; return; }
        const c = yo.value.mano[i];
        if (c === "negar" && puedoNegar.value) { enviar({ accion: "negar" }); return; }
        cancelarObjetivo();
        if (sel.value.includes(i)) sel.value = sel.value.filter((x) => x !== i);
        else sel.value = [...sel.value, i].slice(-2);
        sonar("clic");
      }

      function pedirObjetivo(cartas) {
        if (!otros.value.some(esObjetivo)) { mostrarAviso("Nadie tiene cartas a las que pedir."); return; }
        cartasPend.value = cartas;
      }
      function jugarSeleccion() {
        const cartas = cartasSel.value;
        if (cartas.length === 2 || cartas[0] === "favor") pedirObjetivo(cartas);
        else { enviar({ accion: "jugar", cartas }); sel.value = []; }
      }
      function confirmarObjetivo(id) {
        if (!cartasPend.value) return;
        enviar({ accion: "jugar", cartas: cartasPend.value, objetivo: id });
        cartasPend.value = null;
        sel.value = [];
      }
      function cancelarObjetivo() { cartasPend.value = null; }
      function cancelar() { cartasPend.value = null; sel.value = []; emotesAbierto.value = false; }
      function robar() {
        if (!puedoRobar.value) return;
        cancelar();
        enviar({ accion: "robar" });
      }

      const arrastrable = (i) => esJugable(yo.value.mano[i]);
      function bajar(e, i) {
        ignorarClick = false;
        if (e.pointerType === "mouse" && e.button > 0) return;
        pre = arrastrable(i) ? { i, x0: e.clientX, y0: e.clientY, pid: e.pointerId, el: e.currentTarget } : null;
      }
      function asientoEn(x, y) {
        const el = document.elementFromPoint(x, y), s = el && el.closest("[data-asiento]");
        return s ? s.dataset.asiento : null;
      }
      const arribaDeLaMano = (y) => { const m = manoZona.value; return m ? y < m.getBoundingClientRect().top : false; };
      function mover(e) {
        if (pre && !arrastre.value && Math.hypot(e.clientX - pre.x0, e.clientY - pre.y0) > 8) {
          try { pre.el.setPointerCapture(pre.pid); } catch { /* el navegador ya lo captura */ }
          const r = pre.el.getBoundingClientRect();
          arrastre.value = { i: pre.i, id: yo.value.mano[pre.i], x: e.clientX, y: e.clientY, w: r.width, h: r.height, mueve: true };
          sel.value = []; cartasPend.value = null; foco.value = -1;
          document.body.classList.add("arrastrando");
        }
        if (!arrastre.value) return;
        arrastre.value.x = e.clientX; arrastre.value.y = e.clientY;
        const a = asientoEn(e.clientX, e.clientY), valido = a && otros.value.some((j) => j.id === a && esObjetivo(j));
        sobreAsiento.value = valido ? a : null;
        sobreMesa.value = !a && arribaDeLaMano(e.clientY);
      }
      function soltar(e) {
        const a = arrastre.value;
        pre = null;
        document.body.classList.remove("arrastrando");
        if (!a) return;
        arrastre.value = null; sobreMesa.value = false; sobreAsiento.value = null; ignorarClick = true;
        const asiento = asientoEn(e.clientX, e.clientY), enMesa = !asiento && arribaDeLaMano(e.clientY);
        if (asiento || enMesa) resolverSoltar(a.id, asiento);
      }
      function cancelarArrastre() { document.body.classList.remove("arrastrando"); pre = null; arrastre.value = null; sobreMesa.value = false; sobreAsiento.value = null; }
      function resolverSoltar(id, asiento) {
        if (id === "negar") {
          if (puedoNegar.value) enviar({ accion: "negar" }); else mostrarAviso("Ahora no hay nada que frenar.");
          return;
        }
        if (!puedoRobar.value) { mostrarAviso("Solo puedes jugar cartas en tu turno."); return; }
        const tipo = info(id).tipo;
        let cartas;
        if (tipo === "accion") cartas = [id];
        else if (tipo === "mascota" && cuantas(id) >= 2) cartas = [id, id];
        else { mostrarAviso(tipo === "mascota" ? `Necesitas dos ${info(id).nombre} iguales.` : "Esa carta no se juega así."); return; }
        if (cartas.length === 1 && id !== "favor") { enviar({ accion: "jugar", cartas }); return; }
        if (asiento) {
          if (!otros.value.some((j) => j.id === asiento && esObjetivo(j))) { mostrarAviso("A esa persona no se le puede pedir nada."); return; }
          enviar({ accion: "jugar", cartas, objetivo: asiento });
        } else pedirObjetivo(cartas);
      }

      function alClicMesa(e) {
        if (e.target.closest("button, a, input, .velo, .registro, .emotes-lista")) return;
        sel.value = []; emotesAbierto.value = false; foco.value = -1;
      }

      // ------------------------------------------------------------ emotes, sonido y reglas
      let kEmote = 0;
      function mostrarEmote(id, e) {
        const k = ++kEmote;
        emotes.value = [...emotes.value.filter((x) => x.id !== id), { k, id, e }];
        setTimeout(() => (emotes.value = emotes.value.filter((x) => x.k !== k)), 2500);
        sonar("emote");
      }
      const emotesDe = (id) => emotes.value.filter((x) => x.id === id);
      function emote(k) { enviar({ accion: "emote", e: k }); emotesAbierto.value = false; }
      function alternarSonido() {
        mudo.value = !mudo.value;
        guardar(CLAVE_SONIDO, mudo.value ? "0" : "1");
        if (!mudo.value) sonar("clic");
      }
      const abrirReglas = () => reglas.value && reglas.value.showModal();
      const cerrarReglasFuera = (e) => { if (e.target === reglas.value) reglas.value.close(); };

      // ------------------------------------------------------------ hechos del servidor -> animación y sonido
      function procesarEventos(evs) {
        const max = evs.length ? evs[evs.length - 1].n : 0;
        if (ultimoEvento === null) { ultimoEvento = max; return; }   // primer estado (o reconexión): no se repite lo viejo
        if (max < ultimoEvento) ultimoEvento = 0;                     // empezó otra partida
        const nuevos = evs.filter((x) => x.n > ultimoEvento).slice(-6);
        ultimoEvento = max;
        nuevos.forEach((x, i) => setTimeout(() => reaccionar(x), i * 260));
      }
      function puntoAsiento(id) {
        if (id === yoId.value) { const m = manoZona.value; if (!m) return null; const r = m.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height * 0.45 }; }
        return centroDe(document.querySelector(`[data-asiento="${id}"] .avatar`));
      }
      const puntoMazo = () => centroDe(document.getElementById("mazo"));
      const puntoEscenario = () => centroDe(document.getElementById("escenario"));
      function resaltar(id) { resaltado.value = id; setTimeout(() => (resaltado.value === id ? (resaltado.value = null) : 0), 1600); }

      function reaccionar(ev) {
        if (!vista.value || !vista.value.partida) return;
        const soy = ev.j === yoId.value;
        switch (ev.tipo) {
          case "turno":
            if (soy) { sonar("turno"); anunciar("¡Tu turno!", "chico", 900); vibrar(40); }
            break;
          case "roba":
            sonar("robar"); volar(null, puntoMazo(), puntoAsiento(ev.j), { dur: 480 });
            break;
          case "juega":
            sonar("jugar");
            ev.cartas.forEach((c, i) => volar(c, puntoAsiento(ev.j), puntoEscenario(), { retraso: i * 90, dur: 480, giro: i ? 8 : -6 }));
            if (ev.obj) resaltar(ev.obj);
            break;
          case "negar":
            sonar("negar"); vibrar(60);
            volar("negar", puntoAsiento(ev.j), puntoEscenario(), { dur: 380 });
            sellar(ev.anulada ? "¡NI HABLAR!" : "¡Vuelve a valer!");
            break;
          case "resuelve":
            sonar("resuelve");
            chispas(puntoEscenario(), ev.anulada ? { colores: ["#8a96a8", "#c4ccd8"], n: 10 } : { colores: [COLOR_TIPO[info(ev.cartas[0]).tipo] || "#FFD23F", "#fff"], n: 14, radio: 70 });
            break;
          case "roba_pareja":
            sonar("robar"); volar(null, puntoAsiento(ev.obj), puntoAsiento(ev.j), { dur: 520 });
            break;
          case "favor_da":
            sonar("robar"); volar(null, puntoAsiento(ev.j), puntoAsiento(ev.obj), { dur: 520 });
            break;
          case "baraja": sonar("baraja"); breve(barajando, 700); break;
          case "mira": sonar("mira"); breve(mirando, 1400); break;
          case "inserta": sonar("robar"); volar(null, puntoAsiento(ev.j), puntoMazo(), { dur: 460 }); break;
          case "parche":
            sonar("parche");
            chispas(puntoAsiento(ev.j), { colores: ["#3DDBA6", "#FFFDF8", "#38A8F8"], n: 22, radio: 80 });
            anunciar(`¡Parche! ${soy ? "Te salvas" : nombreDe(ev.j) + " se salva"}`, "bueno", 1500);
            break;
          case "pincha":
            sonar("pincha"); vibrar([90, 40, 140]); breve(sacude, 520);
            chispas(puntoAsiento(ev.j), { colores: ["#EF3B5B", "#FF9A3D", "#FFD23F", "#fff"], n: 44, radio: 150, dur: 900 });
            anunciar(soy ? "¡Tu globo revienta!" : `¡Pinchazo! ${nombreDe(ev.j)} se queda sin globo`, "malo", 1900);
            break;
          case "fin":
            setTimeout(() => { sonar("ganar"); if (soy) confeti(); }, 500);
            break;
          default: break;
        }
      }

      // ------------------------------------------------------------ efectos de estado
      watch(() => yo.value.mano.join(","), () => { sel.value = []; cartasPend.value = null; foco.value = -1; });
      watch(debeInsertar, (v) => { if (v) posicion.value = 0; });
      watch(miTurno, (v) => { document.title = v ? "¡Tu turno! · Pinchazo" : TITULO; });
      watch([debeDar, debeInsertar, () => p.value && p.value.fase === "fin"], async ([a, b, c]) => {
        if (!(a || b || c)) return;
        await nextTick();
        const el = document.querySelector(".velo [data-foco]") || document.querySelector(".velo button");
        if (el) el.focus();
      });
      watch(() => (p.value ? p.value.log.length : 0), async () => {
        await nextTick();
        if (registro.value) registro.value.scrollTop = registro.value.scrollHeight;
      });

      onMounted(async () => {
        setInterval(() => (ahoraMs.value = Date.now()), 100);
        window.addEventListener("resize", () => (area.value = { w: innerWidth, h: innerHeight }));
        window.addEventListener("keydown", (e) => {
          if (e.key === "Escape") { cancelar(); registroAbierto.value = false; cancelarArrastre(); }
        });
        window.addEventListener("pointerdown", ac, { once: true });
        try {
          catalogo.value = await (await fetch("/api/cartas")).json();
        } catch { mostrarAviso("No se pudieron cargar las cartas."); }
        const sala = new URLSearchParams(location.search).get("sala");
        if (sala) codigoUnirse.value = sala.toUpperCase().slice(0, 4);
        const guardada = leer(CLAVE_SESION);
        if (guardada) {
          try { entrar(JSON.parse(guardada)); } catch { guardar(CLAVE_SESION, null); }
        }
      });

      return {
        nombre, nRivales, nivel, niveles, demo, globosFondo, codigoUnirse, cargando, vista, aviso, reconectando, copiado, sel, posicion, registro, registroAbierto,
        manoZona, reglas, foco, emotesAbierto, emotesLista, anuncio, sello, sacude, barajando, mirando, resaltado, arrastre, sobreMesa, sobreAsiento, mudo, catalogo,
        p, yo, yoId, soyDuenio, miTurno, puedoRobar, puedoJugar, puedoNegar, debeDar, debeInsertar, plazasLibres, otros, eligiendo, cartasSel,
        pctRiesgo, nivelRiesgo, colorRiesgo, escalaGlobo, progresoEspera, restanteTexto, posicionTexto, estadoTexto, focoCarta, pistaTexto,
        info, inicial, color, nombreDe, arco, cantidad, mascotaRepetida, claveCarta, esJugable, esObjetivo, estiloAbanico, emotesDe,
        enviar, salir, partidaRapida, crearSala, unirse, copiarEnlace, alternar, jugarSeleccion, confirmarObjetivo, cancelar, robar,
        bajar, mover, soltar, cancelarArrastre, alClicMesa, emote, alternarSonido, abrirReglas, cerrarReglasFuera,
      };
    },
  });

  app.component("carta", {
    props: { cid: String, dorso: Boolean, detalle: Boolean, inclinar: Boolean },
    setup(props) {
      const interior = computed(() => interiorCarta(props.cid, props.dorso));
      const clases = computed(() => claseCarta(props.cid, props.dorso));
      function mover(e) {
        if (!props.inclinar || reducir || e.pointerType === "touch") return;
        const el = e.currentTarget, r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
        el.style.setProperty("--ry", ((x - 0.5) * 20).toFixed(1) + "deg");
        el.style.setProperty("--rx", ((0.5 - y) * 16).toFixed(1) + "deg");
        el.style.setProperty("--mx", (x * 100).toFixed(0) + "%");
        el.style.setProperty("--my", (y * 100).toFixed(0) + "%");
        el.style.setProperty("--mn", x.toFixed(2));
      }
      function soltar(e) {
        const el = e.currentTarget;
        ["--ry", "--rx", "--mx", "--my", "--mn"].forEach((v) => el.style.removeProperty(v));
      }
      return { interior, clases, mover, soltar };
    },
    template: `<span class="carta" :class="[clases, { detalle, inclina: inclinar }]" @pointermove="mover" @pointerleave="soltar" v-html="interior"></span>`,
  });

  app.mount("#app");
})();
