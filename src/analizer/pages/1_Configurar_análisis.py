"""Selección de municipios y de las señales a tener en cuenta en el análisis.

Guarda un CSV por municipio en `data/processed/seleccion/<municipio>.csv`, con una fila por
señal y si está activa, y muestra los comandos de escaneo.
Los municipios se leen de la tabla `municipios` de DuckDB, que se crea desde `municipios.csv`
(diccionario de municipios del INE, codmun 2026) si aún no existe.
"""

import duckdb
import pandas as pd
import streamlit as st

from analizer.scan import DB_PATH, init_db

SELECCION_DIR = DB_PATH.parent / "seleccion"

# (clave, señal, qué mira, puntos; None si scan.py aún no la calcula)
CHECKS = {
    "Necesidad web": [
        ("sin_web", "No tiene web", "No se encuentra web del negocio.", "+2,0"),
        ("aparcada", "Dominio aparcado / en construcción", "Dominio sin web real.", "+2,5"),
        ("sin_https", "Sin HTTPS", "El navegador la marca como «No seguro».", "+1,2"),
        ("ssl_roto", "Certificado SSL roto o caducado", "Error de seguridad al abrirla.", "+1,0"),
        ("sin_viewport", "No adaptada a móvil", "Falta la etiqueta viewport.", "+1,2"),
        ("tecnologia_obsoleta", "Tecnología obsoleta", "Flash, tablas, jQuery<1.9, WP<5, Joomla 1/2, Drupal 7.", "+0,8"),
        ("copyright_antiguo", "© antiguo en el pie", "Copyright de hace 2 años o más.", "+1,0 / +0,4"),
        ("wayback", "Años sin cambios (Wayback)", "archive.org no ve cambios en 4 años o más.", "+0,8"),
        ("constructor_diy", "Hecha con constructor DIY", "Wix, Jimdo, Site123, Webnode, GoDaddy.", "+0,4"),
        ("pagespeed", "PageSpeed bajo", "Puntuación de rendimiento en móvil.", None),
        ("enlaces_rotos", "Enlaces o imágenes rotos", "Recursos que devuelven error.", None),
    ],
    "Huecos comerciales": [
        ("sin_reserva", "Sin reserva/cita online", "Solo en sectores que trabajan con reservas.", "+0,4"),
        ("sin_contacto_web", "Sin WhatsApp ni formulario", "No hay forma rápida de contactar.", "+0,3"),
        ("sin_legales", "Faltan textos legales RGPD/LSSI", "Aviso legal, privacidad o cookies.", "+0,5"),
        ("sin_mapa", "Sin mapa", "No enlaza ni incrusta Google Maps.", None),
        ("sin_redes", "Sin enlaces a redes", "No enlaza Instagram, Facebook…", None),
    ],
    "Capacidad de pago": [
        ("ticket_sector", "Ticket del sector", "Alto (clínicas, abogados, talleres…), medio o bajo.", "+1,0 / +0,3 / −0,5"),
        ("analitica_redes", "Analítica o redes activas", "Señal de que invierte en marketing.", "+0,2 c/u"),
        ("agencia_antigua", "Agencia de hace más de 4 años", "«Diseñado por…» con año antiguo.", "+0,3"),
        ("resenas_google", "Reseñas de Google", "Volumen, nota y fecha de la última.", None),
        ("email_dominio", "Email con dominio propio", "info@sunegocio.es frente a Gmail.", None),
        ("sociedad", "Sociedad (S.L.) frente a autónomo", "CIF en el aviso legal.", None),
    ],
    "Frenos": [
        ("cadena", "Cadena, franquicia o entidad pública", "La web la gestiona la central.", "−2,5"),
        ("stack_moderno", "Stack moderno", "Next.js, Nuxt, Webflow, Shopify, Squarespace, Gatsby.", "−1,5"),
        ("agencia_reciente", "Agencia reciente", "«Diseñado por…» de hace 2 años o menos.", "−2,0"),
        ("negocio_inactivo", "Negocio inactivo", "Sin reseñas en 12 meses o cerrado en Maps.", None),
    ],
    "Contacto": [
        ("datos_contacto", "Teléfono o email disponibles", "+0,3 si hay alguno, −0,5 si no hay ninguno.", "+0,3 / −0,5"),
    ],
}

@st.cache_data
def leer_municipios() -> pd.DataFrame:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(DB_PATH) as con:
        init_db(con)
        return con.sql("SELECT * FROM municipios ORDER BY codigo_ine").df()


st.set_page_config(page_title="Analizer · Configurar análisis", layout="wide")
st.title("Configurar análisis")

try:
    municipios = leer_municipios()
except duckdb.IOException:
    st.error("La base de datos está ocupada (¿hay un escaneo en marcha?). Recarga la página cuando termine.")
    st.stop()
municipios["etiqueta"] = municipios["municipio"] + " (" + municipios["provincia"] + ")"
guardados = [pd.read_csv(f, dtype={"codigo_ine": str}) for f in sorted(SELECCION_DIR.glob("*.csv"))]
guardada = pd.concat(guardados) if guardados else pd.DataFrame(columns=["codigo_ine", "clave", "activo"])

st.subheader("Municipios")
c1, c2 = st.columns(2)
comunidad = c1.selectbox("Comunidad autónoma", sorted(municipios["comunidad"].unique()), index=None,
                         placeholder="Todas")
opciones = municipios if comunidad is None else municipios[municipios["comunidad"] == comunidad]
provincia = c2.selectbox("Provincia", sorted(opciones["provincia"].unique()), index=None, placeholder="Todas")
if provincia is not None:
    opciones = opciones[opciones["provincia"] == provincia]

# Los ya elegidos se mantienen aunque el filtro de comunidad o provincia los oculte
previos = st.session_state.get("sel_codigos", guardada["codigo_ine"].unique().tolist())
codigos = list(dict.fromkeys(previos + opciones["codigo_ine"].tolist()))
etiquetas = municipios.set_index("codigo_ine")["etiqueta"]
sel_codigos = st.multiselect(f"Municipios ({len(opciones):,} disponibles)".replace(",", "."), codigos,
                             default=previos, format_func=etiquetas.get, key="sel_codigos",
                             placeholder="Escribe para buscar…")

st.subheader("Señales a tener en cuenta")
st.caption("Las marcadas como *pendiente* están en los criterios pero el escaneo todavía no las calcula.")
if guardada.empty:
    marcadas = {k for bloque in CHECKS.values() for k, *_, pts in bloque if pts}
else:
    marcadas = set(guardada.loc[guardada["activo"].astype(bool), "clave"])
sel_checks = []
for col, (bloque, checks) in zip(st.columns(len(CHECKS)), CHECKS.items()):
    col.markdown(f"**{bloque}**")
    for clave, senal, ayuda, puntos in checks:
        texto = f"{senal} · {puntos}" if puntos else f"{senal} · *pendiente*"
        if col.checkbox(texto, value=clave in marcadas, help=ayuda, key=f"chk_{clave}"):
            sel_checks.append(clave)

st.divider()
seleccion = municipios[municipios["codigo_ine"].isin(sel_codigos)]
c1, c2 = st.columns([1, 3])
c1.metric("Municipios", len(seleccion))
c2.metric("Señales activas", f"{len(sel_checks)} de {sum(len(b) for b in CHECKS.values())}")

if st.button("💾 Guardar selección", type="primary", disabled=seleccion.empty):
    SELECCION_DIR.mkdir(parents=True, exist_ok=True)
    senales = pd.DataFrame(
        [(bloque, clave, senal, puntos or "pendiente", clave in sel_checks)
         for bloque, checks in CHECKS.items() for clave, senal, _, puntos in checks],
        columns=["bloque", "clave", "senal", "puntos", "activo"],
    )
    rutas = []
    for m in seleccion.itertuples():
        # "/" separa las dos lenguas en nombres como Agurain/Salvatierra y no vale en un fichero
        ruta = SELECCION_DIR / f"{m.municipio.replace('/', '-')}.csv"
        senales.assign(codigo_ine=m.codigo_ine, municipio=m.municipio, provincia=m.provincia)[
            ["codigo_ine", "municipio", "provincia", *senales.columns]
        ].to_csv(ruta, index=False)
        rutas.append(ruta.name)
    st.success(f"Guardado en `{SELECCION_DIR}`: " + ", ".join(rutas))

if not seleccion.empty:
    st.markdown("**Comandos de escaneo** (uno por municipio)")
    st.code("\n".join(
        f"uv run python -m analizer.scan --codigo-ine {c}  # {e}"
        for c, e in zip(seleccion["codigo_ine"], seleccion["etiqueta"])
    ), language="bash")
