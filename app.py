import datetime as dt
from pathlib import Path

import pandas as pd
import plotly.express as px
import pymongo
import streamlit as st
from google import genai

st.set_page_config(page_title="Obesidad Tacna | Analítica Cloud", page_icon="🩺", layout="wide")

DB_NAME = "obesidad_tacna_db"
COLLECTION = "casos"
PROVINCIA_TACNA_PREFIX = "2201"
DATA_PATH = Path(__file__).parent / "data" / "Obesidad_2025.csv"

MONGODB_URI = st.secrets.get("MONGODB_URI", "")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", "")
AUTH = st.secrets.get("auth", {})

if not MONGODB_URI:
    st.error("❌ Falta MONGODB_URI en los secrets.")
    st.stop()

DISTRITO_COORDS = {
    "TACNA": (-18.0066, -70.2463),
    "ALTO DE LA ALIANZA": (-17.9886, -70.2469),
    "CIUDAD NUEVA": (-17.9756, -70.2353),
    "CORONEL GREGORIO ALBARRACIN LANCHIPA": (-18.0500, -70.2500),
    "POCOLLAY": (-17.9931, -70.2186),
    "CALANA": (-17.9333, -70.1833),
    "PACHIA": (-17.8500, -70.1333),
    "PALCA": (-17.7833, -69.9500),
    "INCLAN": (-17.8500, -70.4167),
    "SAMA": (-17.8333, -70.5167),
    "LA YARADA LOS PALOS": (-18.1667, -70.5333),
}


@st.cache_resource
def get_collection():
    client = pymongo.MongoClient(MONGODB_URI)
    return client[DB_NAME][COLLECTION]


def seed_si_vacia():
    col = get_collection()
    if col.estimated_document_count() > 0:
        return
    if not DATA_PATH.exists():
        st.error(f"❌ No se encontró el archivo de datos en: {DATA_PATH}. "
                 "Verifica que la carpeta 'data/' con el CSV esté subida a GitHub.")
        st.stop()
    df = pd.read_csv(DATA_PATH, sep=";", encoding="latin-1", dtype=str)
    df["TOTAL"] = pd.to_numeric(df["TOTAL"], errors="coerce").fillna(0).astype(int)
    df["fecha"] = df["anio"].apply(lambda a: f"{a}-12-31")
    col.insert_many(df.to_dict("records"))


@st.cache_data(ttl=300)
def cargar_datos() -> pd.DataFrame:
    col = get_collection()
    df = pd.DataFrame(list(col.find({}, {"_id": 0})))
    if df.empty:
        return df
    df["TOTAL"] = pd.to_numeric(df["TOTAL"], errors="coerce").fillna(0).astype(int)
    return df


def refrescar():
    cargar_datos.clear()


def dashboard_publico(df: pd.DataFrame):
    st.title("🩺 Obesidad Diagnosticada — Provincia de Tacna (2025)")
    st.caption("Fuente: Gobierno Regional de Tacna · Datos Abiertos del Perú")

    if df.empty:
        st.warning("No hay datos cargados todavía.")
        return

    total = int(df["TOTAL"].sum())
    n_distritos = df["Distrito_RH_Paciente"].nunique()
    pct_f = 100 * df.loc[df["id_genero"] == "F", "TOTAL"].sum() / total
    top_edad = df.groupby("grupo_edad")["TOTAL"].sum().idxmax()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de casos", f"{total:,}")
    c2.metric("Distritos", n_distritos)
    c3.metric("% Mujeres", f"{pct_f:.1f}%")
    c4.metric("Grupo etario más afectado", top_edad)

    st.divider()

    st.subheader("🗺️ Mapa de calor de casos — Provincia de Tacna")
    prov = df[df["Ubigeo_Declarado_Paciente"].astype(str).str.startswith(PROVINCIA_TACNA_PREFIX)]
    geo = prov.groupby("Distrito_RH_Paciente")["TOTAL"].sum().reset_index()
    geo["lat"] = geo["Distrito_RH_Paciente"].map(lambda d: DISTRITO_COORDS.get(d, (None, None))[0])
    geo["lon"] = geo["Distrito_RH_Paciente"].map(lambda d: DISTRITO_COORDS.get(d, (None, None))[1])
    geo = geo.dropna(subset=["lat", "lon"])

    if not geo.empty:
        fig_map = px.density_mapbox(
            geo, lat="lat", lon="lon", z="TOTAL", radius=45,
            hover_name="Distrito_RH_Paciente", hover_data={"TOTAL": True, "lat": False, "lon": False},
            center=dict(lat=-18.0, lon=-70.25), zoom=9,
            mapbox_style="open-street-map", color_continuous_scale="YlOrRd",
        )
        fig_map.update_layout(height=520, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_map, use_container_width=True)
    else:
        st.info("No se pudieron ubicar distritos en el mapa.")

    st.divider()
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("📊 Casos por distrito (Top 12)")
        por_dist = (df.groupby("Distrito_RH_Paciente")["TOTAL"].sum()
                    .sort_values(ascending=True).tail(12).reset_index())
        fig = px.bar(por_dist, x="TOTAL", y="Distrito_RH_Paciente", orientation="h",
                     color="TOTAL", color_continuous_scale="Blues", text="TOTAL")
        fig.update_layout(yaxis_title="", xaxis_title="Casos", showlegend=False, height=420)
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("🧬 Casos por tipo de diagnóstico")
        por_dx = (df.groupby("Descripcion_Item")["TOTAL"].sum()
                  .sort_values(ascending=False).reset_index())
        fig = px.pie(por_dx, names="Descripcion_Item", values="TOTAL", hole=0.45)
        fig.update_layout(height=420, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)

    col_c, col_d = st.columns(2)

    with col_c:
        st.subheader("👥 Casos por grupo de edad y género")
        piram = df.groupby(["grupo_edad", "id_genero"])["TOTAL"].sum().reset_index()
        fig = px.bar(piram, x="grupo_edad", y="TOTAL", color="id_genero", barmode="group",
                     color_discrete_map={"F": "#E45756", "M": "#4C78A8"})
        fig.update_layout(height=400, xaxis_title="Grupo de edad", yaxis_title="Casos",
                          legend_title="Género")
        st.plotly_chart(fig, use_container_width=True)

    with col_d:
        st.subheader("🔥 Heatmap: distrito × grupo de edad")
        top_d = df.groupby("Distrito_RH_Paciente")["TOTAL"].sum().nlargest(10).index
        matriz = (df[df["Distrito_RH_Paciente"].isin(top_d)]
                  .pivot_table(index="Distrito_RH_Paciente", columns="grupo_edad",
                               values="TOTAL", aggfunc="sum", fill_value=0))
        fig = px.imshow(matriz, color_continuous_scale="YlOrRd", aspect="auto", text_auto=True)
        fig.update_layout(height=400, xaxis_title="Grupo de edad", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)


def panel_dba(df: pd.DataFrame):
    st.title("🛠️ Panel del DBA — Administración de la base de datos")
    st.info("Edite, agregue o elimine registros. Al guardar, las tablas y gráficos se actualizan.")

    col = get_collection()
    distritos = sorted(df["Distrito_RH_Paciente"].dropna().unique())

    st.subheader("✏️ Editar / agregar / eliminar registros por distrito")
    distrito_sel = st.selectbox("Seleccione un distrito para editar", distritos)
    subset = df[df["Distrito_RH_Paciente"] == distrito_sel].reset_index(drop=True)

    edit_cols = ["EESS", "Ubigeo_Declarado_Paciente", "Distrito_RH_Paciente",
                 "Descripcion_Item", "id_genero", "grupo_edad", "TOTAL", "fecha"]
    for c in edit_cols:
        if c not in subset.columns:
            subset[c] = ""

    editado = st.data_editor(
        subset[edit_cols], num_rows="dynamic", use_container_width=True,
        key=f"editor_{distrito_sel}",
    )

    if st.button("💾 Guardar cambios", type="primary"):
        col.delete_many({"Distrito_RH_Paciente": distrito_sel})
        registros = editado.copy()
        registros["Distrito_RH_Paciente"] = distrito_sel
        registros["TOTAL"] = pd.to_numeric(registros["TOTAL"], errors="coerce").fillna(0).astype(int)
        registros = registros.dropna(how="all")
        if not registros.empty:
            col.insert_many(registros.to_dict("records"))
        refrescar()
        st.success(f"✅ Cambios guardados para {distrito_sel}. Gráficos y tablas actualizados.")
        st.rerun()

    st.divider()

    st.subheader("➕ Agregar un registro nuevo")
    with st.form("nuevo_registro"):
        c1, c2, c3 = st.columns(3)
        eess = c1.text_input("Establecimiento (EESS)")
        ubigeo = c1.text_input("Ubigeo", value="220101")
        distrito = c2.text_input("Distrito", value="TACNA")
        dx = c2.text_input("Diagnóstico", value="OBESIDAD NO ESPECIFICADA")
        genero = c3.selectbox("Género", ["F", "M"])
        edad = c3.selectbox("Grupo de edad",
                            ["0-28d", "29d-11m", "1-4a", "5-11a", "12-17a", "18-29a", "30-59a", "60a+"])
        total = c3.number_input("Total de casos", min_value=1, value=1, step=1)
        fecha = c1.date_input("Fecha de registro", value=dt.date.today())
        enviar = st.form_submit_button("Agregar")
    if enviar:
        col.insert_one({
            "anio": str(fecha.year), "EESS": eess, "Ubigeo_Declarado_Paciente": ubigeo,
            "Distrito_RH_Paciente": distrito.upper(), "Descripcion_Item": dx.upper(),
            "id_genero": genero, "grupo_edad": edad, "TOTAL": int(total),
            "fecha": fecha.isoformat(),
        })
        refrescar()
        st.success("✅ Registro agregado.")
        st.rerun()

    st.divider()
    st.subheader("📋 Vista de la tabla actual")
    st.dataframe(df, use_container_width=True, height=300)


def deteccion_brotes(df: pd.DataFrame, fecha_eval: dt.date):
    prov = df[df["Ubigeo_Declarado_Paciente"].astype(str).str.startswith(PROVINCIA_TACNA_PREFIX)]
    agg = prov.groupby("Distrito_RH_Paciente")["TOTAL"].sum()
    media, sd = agg.mean(), agg.std(ddof=0) or 1
    espacial = agg.to_frame("casos")
    espacial["z_score"] = (agg - media) / sd
    espacial["hotspot"] = espacial["z_score"] >= 1.0
    espacial = espacial.sort_values("casos", ascending=False)

    temporal = None
    if "fecha" in df.columns:
        f = prov.copy()
        f["fecha"] = pd.to_datetime(f["fecha"], errors="coerce")
        ini_act = pd.Timestamp(fecha_eval) - pd.Timedelta(days=14)
        ini_prev = pd.Timestamp(fecha_eval) - pd.Timedelta(days=28)
        actual = f[(f["fecha"] > ini_act) & (f["fecha"] <= pd.Timestamp(fecha_eval))]
        previo = f[(f["fecha"] > ini_prev) & (f["fecha"] <= ini_act)]
        if not actual.empty:
            a = actual.groupby("Distrito_RH_Paciente")["TOTAL"].sum()
            p = previo.groupby("Distrito_RH_Paciente")["TOTAL"].sum()
            temporal = pd.DataFrame({"ventana_actual": a, "ventana_previa": p}).fillna(0)
            temporal["crecimiento_%"] = (
                (temporal["ventana_actual"] - temporal["ventana_previa"])
                / temporal["ventana_previa"].replace(0, 1) * 100
            ).round(1)
            temporal = temporal.sort_values("crecimiento_%", ascending=False)
    return espacial, temporal


def panel_essalud(df: pd.DataFrame):
    st.title("🚨 Panel EsSalud — Vigilancia y consultas")
    tab1, tab2 = st.tabs(["🚨 Detección de brotes (cada 14 días)", "🤖 Chatbot (Gemini)"])

    with tab1:
        st.subheader("Identificación de zonas representativas de obesidad")
        fecha_eval = st.date_input("Fecha de evaluación", value=dt.date.today())
        st.caption("La ventana de análisis temporal es de 14 días previos a esta fecha.")

        espacial, temporal = deteccion_brotes(df, fecha_eval)

        hotspots = espacial[espacial["hotspot"]].index.tolist()
        if hotspots:
            st.error(f"🔴 Zonas de alta concentración detectadas: {', '.join(hotspots)}")
        st.markdown("**Concentración por distrito (z-score espacial)**")
        st.dataframe(espacial.style.format({"z_score": "{:.2f}"}), use_container_width=True)

        fig = px.bar(espacial.reset_index(), x="Distrito_RH_Paciente", y="casos",
                     color="hotspot", color_discrete_map={True: "#E45756", False: "#4C78A8"},
                     title="Casos por distrito (rojo = zona de brote)")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Análisis temporal — ventana de 14 días**")
        if temporal is not None and not temporal.empty:
            st.dataframe(temporal, use_container_width=True)
        else:
            st.info("Aún no hay suficientes registros con fecha en la ventana de 14 días "
                    "(la data base es anual). El análisis temporal se activa a medida que el "
                    "DBA registra casos con fecha.")

    with tab2:
        chatbot_gemini(df)


def construir_contexto(df: pd.DataFrame) -> str:
    total = int(df["TOTAL"].sum())
    por_dist = df.groupby("Distrito_RH_Paciente")["TOTAL"].sum().nlargest(10).to_dict()
    por_genero = df.groupby("id_genero")["TOTAL"].sum().to_dict()
    por_edad = df.groupby("grupo_edad")["TOTAL"].sum().to_dict()
    por_dx = df.groupby("Descripcion_Item")["TOTAL"].sum().to_dict()
    return (
        f"Base de datos: obesidad diagnosticada, provincia de Tacna, año 2025.\n"
        f"Total de casos: {total}.\n"
        f"Casos por distrito (top 10): {por_dist}.\n"
        f"Casos por género: {por_genero}.\n"
        f"Casos por grupo de edad: {por_edad}.\n"
        f"Casos por tipo de diagnóstico: {por_dx}."
    )


def chatbot_gemini(df: pd.DataFrame):
    st.subheader("Consultas sobre la base de datos")
    if not GOOGLE_API_KEY:
        st.warning("Falta GOOGLE_API_KEY en los secrets para usar el chatbot.")
        return

    if "chat_hist" not in st.session_state:
        st.session_state.chat_hist = []

    for m in st.session_state.chat_hist:
        st.chat_message(m["rol"]).write(m["texto"])

    pregunta = st.chat_input("Pregunta sobre los datos de obesidad...")
    if pregunta:
        st.session_state.chat_hist.append({"rol": "user", "texto": pregunta})
        st.chat_message("user").write(pregunta)
        with st.spinner("Consultando..."):
            contexto = construir_contexto(df)
            prompt = (
                "Eres un analista de salud. Responde SOLO con base en el siguiente "
                "resumen de datos. Si la respuesta no está en los datos, indícalo.\n\n"
                f"DATOS:\n{contexto}\n\nPREGUNTA: {pregunta}\n\nResponde claro y en español."
            )
            try:
                client = genai.Client(api_key=GOOGLE_API_KEY)
                resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                texto = resp.text
            except Exception as e:
                texto = f"⚠️ Error al consultar Gemini: {e}"
        st.session_state.chat_hist.append({"rol": "assistant", "texto": texto})
        st.chat_message("assistant").write(texto)


def login_sidebar():
    st.sidebar.title("🔐 Acceso")
    if "rol" not in st.session_state:
        st.session_state.rol = None

    if st.session_state.rol:
        st.sidebar.success(f"Sesión: {st.session_state.rol}")
        if st.sidebar.button("Cerrar sesión"):
            st.session_state.rol = None
            st.rerun()
        return

    st.sidebar.caption("Ingrese para acceder a los paneles DBA o EsSalud.")
    usuario = st.sidebar.text_input("Usuario")
    clave = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        if usuario == AUTH.get("dba_user") and clave == AUTH.get("dba_pass"):
            st.session_state.rol = "DBA"
            st.rerun()
        elif usuario == AUTH.get("essalud_user") and clave == AUTH.get("essalud_pass"):
            st.session_state.rol = "EsSalud"
            st.rerun()
        else:
            st.sidebar.error("Credenciales inválidas.")


def main():
    seed_si_vacia()
    df = cargar_datos()
    login_sidebar()

    rol = st.session_state.get("rol")
    if rol == "DBA":
        vista = st.sidebar.radio("Vista", ["Dashboard público", "Panel DBA"])
        if vista == "Panel DBA":
            panel_dba(df)
        else:
            dashboard_publico(df)
    elif rol == "EsSalud":
        vista = st.sidebar.radio("Vista", ["Dashboard público", "Panel EsSalud"])
        if vista == "Panel EsSalud":
            panel_essalud(df)
        else:
            dashboard_publico(df)
    else:
        dashboard_publico(df)


if __name__ == "__main__":
    main()
