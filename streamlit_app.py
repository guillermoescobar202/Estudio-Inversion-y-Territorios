from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent / "datos_streamlit"
FUENTES = ["AFP", "Fondos", "Seguros", "Banca"]
COLORES = ["#285888", "#008275", "#A24B50", "#A66A21"]
VARIABLES = {"Producción total": "produccion_bruta", "Valor agregado": "valor_agregado"}
METRICAS = {
    "Saldo estimado": (None, 1, "millones de CLP"),
    "Por habitante": ("poblacion", 1_000_000, "CLP por habitante"),
    "Por empresa": ("numero_empresas", 1_000_000, "CLP por empresa"),
    "Por km²": ("superficie_km2", 1_000_000, "CLP por km²"),
}
TC = 911.18

st.set_page_config(page_title="Destino del capital en Chile", layout="wide")


@st.cache_data(show_spinner=False)
def cargar(directorio, versiones):
    nombres = ["cartera", "regiones", "ponderadores", "reparto", "macrosectores", "control"]
    return {nombre: pd.read_csv(directorio / f"{nombre}.csv") for nombre in nombres}


def cifra(valor):
    if pd.isna(valor):
        return "Sin monto validado"
    return f"{valor:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


def grafico(datos, eje, serie, unidad, orden, colores, orden_series, apilado=False):
    if datos["Valor"].dropna().empty:
        st.info("No hay montos disponibles para esta selección.")
        return
    y = alt.Y(f"{eje}:N", sort=orden, title=None)
    marca = alt.Chart(datos).mark_bar().encode(
        x=alt.X("Valor:Q", title=unidad, stack="zero" if apilado else None),
        y=y,
        color=alt.Color(f"{serie}:N", title=None,
                        scale=alt.Scale(domain=orden_series, range=colores)),
        tooltip=[alt.Tooltip(f"{eje}:N"), alt.Tooltip(f"{serie}:N"),
                 alt.Tooltip("Valor:Q", title=unidad, format=",.2f")],
    )
    if not apilado:
        marca = marca.encode(yOffset=alt.YOffset(f"{serie}:N", sort=orden_series))
    alto = max(205, len(orden) * (33 if apilado else 46))
    st.altair_chart(marca.properties(height=alto), use_container_width=True)


def tabla(datos, llave, titulo="Descargar CSV"):
    st.dataframe(datos, use_container_width=True, hide_index=True)
    st.download_button(titulo, datos.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{llave}.csv", mime="text/csv", key=llave)


def completar(datos, campo, dominio, fuentes):
    indice = pd.MultiIndex.from_product([dominio, fuentes], names=[campo, "fuente"])
    return (datos.set_index([campo, "fuente"]).reindex(indice, fill_value=0)
            .reset_index())


def normalizar(datos, regiones, metrica, usd):
    divisor, escala, unidad = METRICAS[metrica]
    datos = datos.merge(regiones, on="cut_region", how="left", validate="many_to_one")
    datos["Valor"] = datos["saldo_regional_mmclp"] * escala
    if divisor:
        datos["Valor"] /= datos[divisor]
    if usd:
        datos["Valor"] /= TC
        unidad = unidad.replace("CLP", "USD")
    return datos, unidad


st.title("Destino del capital en Chile")
st.caption("Saldos de diciembre de 2025 · Reparto territorial estimado con cuentas CED 2022")
archivos = sorted(BASE.glob("*.csv"))
necesarios = {"cartera", "regiones", "ponderadores", "reparto", "macrosectores", "control"}
if not necesarios.issubset({archivo.stem for archivo in archivos}):
    st.error(f"Faltan tablas en {BASE}. Ejecuta el notebook de preparación y coloca aquí la carpeta datos_streamlit.")
    st.stop()
tablas = cargar(BASE, tuple((archivo.name, archivo.stat().st_mtime_ns) for archivo in archivos))
cartera, regiones = tablas["cartera"], tablas["regiones"].sort_values("orden")
nombres = tablas["macrosectores"].set_index("macro").sector.to_dict()
region_nombres = regiones.set_index("cut_region").region.to_dict()

st.sidebar.header("Filtros")
fuentes = st.sidebar.multiselect("Fuentes de capital", FUENTES, default=FUENTES)
if not fuentes:
    st.info("Selecciona al menos una fuente de capital.")
    st.stop()
subfondos = ["Fondos mutuos", "Fondos de inversión"]
if "Fondos" in fuentes:
    subfondos = st.sidebar.multiselect("Tipos de fondo", subfondos, default=subfondos)
    if not subfondos:
        st.info("Selecciona al menos un tipo de fondo o retira Fondos del filtro.")
        st.stop()
moneda = st.sidebar.radio("Moneda", ["CLP", "USD"], horizontal=True)
usd = moneda == "USD"
metrica = st.sidebar.radio("Medida regional", list(METRICAS))
variable = st.sidebar.radio("Base del reparto regional", list(VARIABLES))

cartera = cartera.loc[cartera.fuente.isin(fuentes) &
    (cartera.fuente.ne("Fondos") | cartera.subfuente.isin(subfondos))].copy()
reparto = tablas["reparto"]
reparto = reparto.loc[reparto.fuente.isin(fuentes) &
    (reparto.fuente.ne("Fondos") | reparto.subfuente.isin(subfondos)) &
    reparto.variable.eq(VARIABLES[variable])].copy()
saldos = cartera.loc[cartera.medida.eq("Saldo")].copy()
saldos["Monto"] = saldos.saldo_mmclp / (TC if usd else 1)
unidad_saldo = f"millones de {moneda}"
faltantes = int((saldos.registros - saldos.registros_con_monto).sum())
if faltantes:
    st.warning(f"{faltantes:,} posiciones de las fuentes seleccionadas están pendientes de valorización. "
               "Se muestran en el detalle de instrumentos y se omiten de las sumas.")
if len(fuentes) > 1:
    st.caption("La suma de fuentes es bruta. Una misma inversión puede aparecer en distintas carteras.")

vista = st.radio("Vista", ["Sectores e instrumentos", "Regiones", "Detalle regional",
                         "Comparar dos regiones", "Método y controles"], horizontal=True)
if vista == "Sectores e instrumentos":
    total = saldos.Monto.sum(min_count=1)
    con_sector = saldos.loc[saldos.macro.gt(0), "Monto"].sum(min_count=1)
    sin_sector = saldos.loc[saldos.macro.eq(0), "Monto"].sum(min_count=1)
    columnas = st.columns(3)
    for c, titulo, valor in zip(columnas, ["Saldo cubierto", "Nacional con sector", "Sin asignación sectorial"],
                                [total, con_sector, sin_sector]):
        c.metric(titulo, cifra(valor), help=unidad_saldo)
    st.caption(f"Importes en {unidad_saldo}. El saldo cubierto suma las posiciones valorizadas en las bases procesadas.")
    st.subheader("Distribución nacional en nueve macrocategorías")
    datos = saldos.loc[saldos.macro.gt(0)].groupby(["macro", "fuente"], as_index=False).Monto.sum(min_count=1)
    # Una fuente sin un monto validado puede tener posiciones en el sector.
    if not datos.Monto.notna().any():
        st.info("Esta selección aún no tiene saldos sectoriales valorizados.")
    else:
        datos = completar(datos, "macro", list(nombres), fuentes)
        datos["Sector"] = datos.macro.map(nombres)
        grafico(datos.rename(columns={"Monto": "Valor"}), "Sector", "fuente", unidad_saldo,
                list(nombres.values()), [COLORES[FUENTES.index(f)] for f in fuentes], fuentes, apilado=True)
        pivot = datos.pivot(index="macro", columns="fuente", values="Monto").reindex(list(nombres))
        pivot["Total"] = pivot[fuentes].sum(axis=1, min_count=1)
        pivot.insert(0, "Sector", pivot.index.map(nombres))
        tabla(pivot.reset_index(drop=True), "sectores_nacionales")
    st.subheader("Composición por instrumento")
    opciones = ["Toda la cartera", "Detalle nacional", "Sin sector"]
    alcance = st.radio("Ámbito del detalle", opciones, horizontal=True)
    detalle = cartera.copy()
    if alcance == "Detalle nacional":
        detalle = detalle.loc[detalle.ambito.eq("Nacional")].copy()
    elif alcance == "Sin sector":
        detalle = detalle.loc[detalle.macro.eq(0)].copy()
    detalle["Sector"] = detalle.macro.map(nombres).fillna("No asignada")
    medidas = list(detalle.medida.drop_duplicates())
    seleccion_medidas = st.multiselect("Medidas del detalle", medidas, default=medidas)
    detalle = detalle.loc[detalle.medida.isin(seleccion_medidas)].copy()
    detalle[f"Monto ({unidad_saldo})"] = detalle.saldo_mmclp / (TC if usd else 1)
    detalle = detalle.rename(columns={"fuente": "Fuente", "subfuente": "Subfuente", "ambito": "Ámbito",
        "naturaleza": "Naturaleza", "instrumento": "Instrumento", "medida": "Medida",
        "registros": "Posiciones", "registros_con_monto": "Posiciones con monto"})
    detalle = detalle[["Fuente", "Subfuente", "Ámbito", "Sector", "Naturaleza", "Instrumento",
        "Medida", f"Monto ({unidad_saldo})", "Posiciones", "Posiciones con monto"]]
    tabla(detalle.sort_values(["Medida", f"Monto ({unidad_saldo})"], ascending=[True, False]),
          "composicion_instrumentos")

elif vista in {"Regiones", "Detalle regional", "Comparar dos regiones"}:
    st.caption(f"Reparto estimado con {variable.lower()} CED 2022. Incluye los saldos nacionales valorizados con macrocategoría.")
    if reparto.empty:
        st.info("La selección no tiene saldos con macrocategoría y monto validado para repartir.")
        st.stop()

    if vista == "Regiones":
        sector = st.selectbox("Sector", [0, *nombres],
                              format_func=lambda m: nombres.get(m, "Total de sectores"))
        datos = reparto if sector == 0 else reparto.loc[reparto.macro.eq(sector)]
        sumas = datos.groupby(["cut_region", "fuente"], as_index=False).saldo_regional_mmclp.sum()
        disponibles = [f for f in fuentes if f in reparto.fuente.unique()]
        sumas = completar(sumas, "cut_region", list(region_nombres), disponibles)
        valores, unidad = normalizar(sumas, regiones, metrica, usd)
        valores["Región"] = valores.region
        totales = valores.groupby("Región").Valor.sum().sort_values(ascending=False)
        grafico(valores, "Región", "fuente", unidad, list(totales.index),
                [COLORES[FUENTES.index(f)] for f in disponibles], disponibles, apilado=True)
        pivot = valores.pivot(index="Región", columns="fuente", values="Valor").reindex(totales.index)
        pivot["Total"] = totales
        st.caption(unidad)
        tabla(pivot.reset_index(), "distribucion_regional")
    else:
        cortes = list(region_nombres)
        izq, der = st.columns(2)
        comparar = vista == "Comparar dos regiones"
        with izq:
            a = st.selectbox("Región A" if comparar else "Región", cortes,
                             format_func=region_nombres.get, index=cortes.index(13))
        elegidas = [a]
        if comparar:
            candidatas = [c for c in cortes if c != a]
            with der:
                b = st.selectbox("Región B", candidatas, format_func=region_nombres.get,
                                 index=candidatas.index(8) if 8 in candidatas else 0)
            elegidas.append(b)
        datos = reparto.loc[reparto.cut_region.isin(elegidas)]
        disponibles = [f for f in fuentes if f in reparto.fuente.unique()]
        indice = pd.MultiIndex.from_product([elegidas, list(nombres), disponibles],
                                            names=["cut_region", "macro", "fuente"])
        sumas = (datos.groupby(["cut_region", "macro", "fuente"]).saldo_regional_mmclp.sum()
                 .reindex(indice, fill_value=0).rename("saldo_regional_mmclp").reset_index())
        valores, unidad = normalizar(sumas, regiones, metrica, usd)
        valores["Sector"] = valores.macro.map(nombres)
        totales = valores.groupby("cut_region").Valor.sum()
        metricas = st.columns(len(elegidas))
        for c, region in zip(metricas, elegidas):
            c.metric(region_nombres[region], cifra(totales.loc[region]), help=unidad)
        if comparar:
            por_region = valores.groupby(["macro", "region"], as_index=False).Valor.sum()
            por_region["Sector"] = por_region.macro.map(nombres)
            nombres_regiones = [region_nombres[c] for c in elegidas]
            grafico(por_region.rename(columns={"region": "Región"}), "Sector", "Región",
                    unidad, list(nombres.values()), ["#285888", "#C47F27"], nombres_regiones)
            pivot = por_region.pivot(index="macro", columns="region", values="Valor").reindex(list(nombres))
            pivot["Diferencia A − B"] = pivot[nombres_regiones[0]] - pivot[nombres_regiones[1]]
            for cut in elegidas:
                nombre = region_nombres[cut]
                if totales.loc[cut] != 0:
                    pivot[f"{nombre} · % del total regional"] = (100 * pivot[nombre] / totales.loc[cut]).round(2)
        else:
            grafico(valores, "Sector", "fuente", unidad, list(nombres.values()),
                    [COLORES[FUENTES.index(f)] for f in disponibles], disponibles, apilado=True)
            pivot = valores.pivot(index="macro", columns="fuente", values="Valor").reindex(list(nombres))
            pivot["Total"] = pivot[disponibles].sum(axis=1)
        pivot.insert(0, "Sector", pivot.index.map(nombres))
        st.caption(unidad)
        tabla(pivot.reset_index(drop=True), "comparacion_regiones" if comparar else "detalle_regional")
    fuera = saldos.loc[saldos.macro.eq(0), "Monto"].sum(min_count=1)
    st.caption(f"Saldo valorizado fuera del reparto por falta de macrocategoría: {cifra(fuera)} {unidad_saldo}.")

else:
    st.subheader("Método de reparto")
    st.latex(r"C_{f,r,s}=C_{f,s}\,\frac{X_{r,s}}{\sum_{r'\in Chile} X_{r',s}}")
    st.markdown(
        "Para cada macrosector se suman las provincias de cada región. "
        "La variable X es la producción bruta o el valor agregado. "
        "La división por habitantes, empresas o superficie se aplica después de estimar los saldos regionales. "
        "El denominador de empresas corresponde al total de empresas de la región.")
    st.markdown("Denominadores regionales · [Población Censo INE 2024](https://censo2024.ine.gob.cl/resultados/) · "
                "[Empresas SII 2025](https://www.sii.cl/sobre_el_sii/estadisticas_de_empresas.html) por domicilio tributario · "
                "[Superficie SIMBIO](https://simbio.mma.gob.cl/) sumada desde las provincias.")
    st.caption("La banca se reparte a partir de sus nueve macrocategorías comerciales. "
               "Vivienda (CED 37) y administración pública (CED 43) quedan fuera del universo común de nueve sectores.")
    st.caption("La superficie de la provincia Antártica Chilena corresponde a Cabo de Hornos en la base SIMBIO.")
    with st.expander("Ponderadores regionales"):
        pesos = tablas["ponderadores"].loc[tablas["ponderadores"].variable.eq(VARIABLES[variable])].copy()
        pesos["Región"] = pesos.cut_region.map(region_nombres)
        pesos["Sector"] = pesos.macro.map(nombres)
        pesos["Participación (%)"] = 100 * pesos.participacion
        tabla(pesos[["Región", "Sector", "Participación (%)"]], "ponderadores_regionales")
    with st.expander("Denominadores"):
        tabla(regiones[["cut_region", "region", "poblacion", "numero_empresas", "superficie_km2"]],
              "denominadores_regionales")
    with st.expander("Controles y cobertura", expanded=True):
        tabla(tablas["control"], "controles_preparacion")
