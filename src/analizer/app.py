"""Visor del ranking en el navegador con descarga a Excel.

Uso:
    streamlit run src/analizer/app.py
"""

from io import BytesIO

import duckdb
import pandas as pd
import streamlit as st

from analizer.scan import DB_PATH

st.set_page_config(page_title="Analizer · Ranking de leads web", layout="wide")
st.title("Ranking de negocios propensos a hacer o rehacer su web")

if not DB_PATH.exists():
    st.error(f"No hay datos todavía. Lanza primero: `python -m analizer.scan --municipio Serra --provincia Valencia`")
    st.stop()

con = duckdb.connect(DB_PATH, read_only=True)
ranking = con.sql("SELECT * FROM ranking").df()
resumen = con.sql("SELECT * FROM ranking_municipio").df()
ultimo = con.sql("""SELECT codigo_ine, coalesce(m.municipio, e.municipio) AS municipio, m.provincia, max(fecha) AS fecha
                   FROM escaneos e LEFT JOIN municipios m USING (codigo_ine) GROUP BY ALL""").df()
con.close()

# Por código INE: hay municipios con el mismo nombre en provincias distintas
etiquetas = resumen.set_index("codigo_ine").apply(lambda r: f"{r.municipio} ({r.provincia})", axis=1)
municipios = sorted(etiquetas.index, key=etiquetas.get)
with st.sidebar:
    sel_mun = st.multiselect("Municipio", municipios, default=municipios, format_func=etiquetas.get)
    sel_pri = st.multiselect("Prioridad", ["caliente", "templado", "frio"], default=["caliente", "templado"])
    sel_est = st.multiselect("Estado web", sorted(ranking["estado_web"].unique()),
                             default=sorted(ranking["estado_web"].unique()))
    solo_contacto = st.checkbox("Solo con teléfono o email")
    p_min = st.slider("Probabilidad mínima", 0.0, 1.0, 0.0, 0.05)

vista = ranking[
    ranking["codigo_ine"].isin(sel_mun)
    & ranking["prioridad"].isin(sel_pri)
    & ranking["estado_web"].isin(sel_est)
    & (ranking["probabilidad"] >= p_min)
]
if solo_contacto:
    vista = vista[vista["telefono"].notna() | vista["email"].notna()]

st.subheader("Resumen por municipio")
st.dataframe(resumen[resumen["codigo_ine"].isin(sel_mun)], hide_index=True, width="stretch")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Negocios filtrados", len(vista))
c2.metric("Calientes", int((vista["prioridad"] == "caliente").sum()))
c3.metric("Leads esperados (Σp)", f"{vista['probabilidad'].sum():.1f}")
c4.metric("Sin web", int((vista["estado_web"] == "sin_web").sum()))

st.subheader("Ranking")
columnas = ["posicion", "municipio", "provincia", "nombre", "tipo", "probabilidad", "prioridad", "estado_web",
            "web", "observaciones", "telefono", "email", "direccion", "argumentos_venta", "frenos"]
st.dataframe(
    vista[columnas],
    hide_index=True,
    width="stretch",
    column_config={
        "probabilidad": st.column_config.ProgressColumn("probabilidad", min_value=0, max_value=1, format="%.2f"),
        "web": st.column_config.LinkColumn("web"),
        "observaciones": st.column_config.TextColumn("observaciones", width="large"),
    },
)

mapa = vista.dropna(subset=["lat", "lon"])
if not mapa.empty:
    st.subheader("Mapa")
    st.map(mapa, latitude="lat", longitude="lon", size=30)


def to_excel() -> bytes:
    criterios = pd.DataFrame({
        "bloque": ["Necesidad", "Necesidad", "Necesidad", "Necesidad", "Necesidad", "Necesidad",
                   "Necesidad", "Necesidad", "Necesidad", "Pago", "Pago", "Penalización",
                   "Penalización", "Penalización", "Contacto"],
        "señal": ["Sin web", "Dominio aparcado / en construcción", "Sin HTTPS", "SSL roto",
                  "No adaptada a móvil", "Tecnología obsoleta", "© antiguo (≥5 años / ≥2)",
                  "≥4 años sin cambios (Wayback)", "Faltan textos legales", "Sector ticket alto/medio/bajo",
                  "Analítica o redes activas", "Cadena / entidad pública", "Stack moderno",
                  "Agencia reciente", "Con / sin datos de contacto"],
        "puntos": ["+2.0", "+2.5", "+1.2", "+1.0", "+1.2", "+0.8", "+1.0 / +0.4", "+0.8", "+0.5",
                   "+1.0 / +0.3 / -0.5", "+0.2 c/u", "-2.5", "-1.5", "-2.0", "+0.3 / -0.5"],
    })
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xls:
        vista.drop(columns=["lat", "lon"]).to_excel(xls, sheet_name="Ranking", index=False)
        resumen[resumen["codigo_ine"].isin(sel_mun)].to_excel(xls, sheet_name="Por municipio", index=False)
        criterios.to_excel(xls, sheet_name="Criterios", index=False)
        ultimo.to_excel(xls, sheet_name="Escaneos", index=False)
        for ws in xls.sheets.values():
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 70)
    return buf.getvalue()


st.sidebar.download_button(
    "⬇️ Descargar Excel",
    data=to_excel(),
    file_name=f"ranking_{'_'.join(sel_mun) or 'vacio'}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    width="stretch",
)
st.caption("Fuente: OpenStreetMap + análisis de cada web. Probabilidades de arranque en frío: "
           "recalibrar con resultados reales de contacto.")
