import io
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st


# ==========================================================
# APP: Lector Mazda/Kia/Multimarca contra stock/inventario
# Autor: preparado para Carlos / Alimatico
# ==========================================================

st.set_page_config(
    page_title="Lector de códigos Mazda - Stock",
    page_icon="🔎",
    layout="wide",
)


# -----------------------------
# Normalización de códigos
# -----------------------------
def normalizar_codigo(valor) -> str:
    """
    Convierte cualquier código a una forma comparable:
    - Mayúsculas
    - Sin espacios
    - Sin guiones
    - Sin asteriscos
    - Sin símbolos raros del lector: ', ¡, ., #, etc.

    Ejemplos:
    B6Y1-14-302A  -> B6Y114302A
    KD47-67-UC5A62 -> KD4767UC5A62
    KD4767UC5A62' -> KD4767UC5A62
    """
    if pd.isna(valor):
        return ""
    texto = str(valor).upper().strip()
    texto = texto.replace("Ñ", "N")
    return re.sub(r"[^A-Z0-9]", "", texto)


def agregar_unico(lista: List[str], valor: str) -> None:
    valor = normalizar_codigo(valor)
    if valor and valor not in lista:
        lista.append(valor)


def extraer_candidatos_mazda(codigo_leido: str) -> Dict[str, object]:
    """
    Recibe la lectura cruda del scanner Mazda y genera candidatos de búsqueda.

    Reglas contempladas con ejemplos reales:
    - UCY4584GX   2       -> UCY4584GX y UCY4584GX2
    - B60P34156   3       -> B60P34156 y B60P341563
    - BJT667395   .       -> BJT667395
    - PE0110602   Y       -> PE0110602 y PE0110602Y
    - KD4767UC5A62'       -> KD4767UC5A62 y KD4767UC5A
    - KD47UC1 E4R PAJ8133A0A -> KD47UC1, PAJ8133A0A y combinaciones

    Importante:
    No se descarta el código completo si viene todo pegado, porque puede existir
    en stock con ese sufijo. Ejemplo real: KD47-67-UC5A62.
    """
    raw = "" if codigo_leido is None else str(codigo_leido).strip().upper()
    raw = raw.replace("#", " ")

    tokens_originales = [t for t in re.split(r"\s+", raw) if t.strip()]
    tokens_limpios = [normalizar_codigo(t) for t in tokens_originales]
    tokens_limpios = [t for t in tokens_limpios if t]

    candidatos: List[str] = []
    codigos_largos: List[str] = []
    sufijos: List[str] = []

    for token in tokens_limpios:
        if len(token) >= 7:
            codigos_largos.append(token)
            agregar_unico(candidatos, token)

            # Si viene pegado con sufijo, guardo también una versión base.
            # Pero el código completo queda primero para no perder variantes reales.
            if len(token) > 10:
                agregar_unico(candidatos, token[:10])
                extra = token[10:]
                if extra:
                    sufijos.append(extra)

        elif 1 <= len(token) <= 4:
            # Sufijos reales de proveedor, color o variante: 1, 2, 3, J, Y, N, E4R, etc.
            # Los símbolos como '.', '¡', "'" quedan vacíos por normalizar_codigo y no entran.
            sufijos.append(token)

    # Combinar códigos largos con sufijos.
    # Ejemplo: B6Y114302A + J -> B6Y114302AJ
    for codigo in list(codigos_largos):
        for sufijo in sufijos:
            if sufijo:
                agregar_unico(candidatos, codigo + sufijo)

    # También agrego la lectura entera normalizada como último intento.
    lectura_entera = normalizar_codigo(raw)
    if len(lectura_entera) >= 7:
        agregar_unico(candidatos, lectura_entera)

    return {
        "lectura_original": str(codigo_leido).strip() if codigo_leido is not None else "",
        "tokens_limpios": tokens_limpios,
        "codigos_largos": codigos_largos,
        "sufijos": list(dict.fromkeys(sufijos)),
        "candidatos": candidatos,
    }


# -----------------------------
# Lectura y limpieza del stock
# -----------------------------
def leer_archivo_excel_o_csv(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Lee .xls, .xlsx o .csv como tabla cruda, sin asumir encabezado."""
    nombre = filename.lower()
    buffer = io.BytesIO(file_bytes)

    if nombre.endswith(".csv"):
        try:
            return pd.read_csv(buffer, header=None, dtype=object, sep=None, engine="python")
        except UnicodeDecodeError:
            buffer.seek(0)
            return pd.read_csv(buffer, header=None, dtype=object, sep=None, engine="python", encoding="latin1")

    if nombre.endswith(".xls"):
        # Para archivos Excel 97-2003 hace falta xlrd en requirements.txt
        return pd.read_excel(buffer, header=None, dtype=object, engine="xlrd")

    if nombre.endswith((".xlsx", ".xlsm")):
        return pd.read_excel(buffer, header=None, dtype=object, engine="openpyxl")

    raise ValueError("Formato no soportado. Use .xls, .xlsx, .xlsm o .csv")


def buscar_columna_por_texto(df_raw: pd.DataFrame, textos: List[str]) -> Tuple[int, int]:
    """
    Busca una celda que contenga alguno de los textos indicados.
    Devuelve (fila, columna). Si no encuentra, devuelve (-1, -1).
    """
    textos_norm = [normalizar_codigo(t) for t in textos]

    for i in range(min(len(df_raw), 80)):
        fila = df_raw.iloc[i]
        for j, valor in fila.items():
            val_norm = normalizar_codigo(valor)
            if val_norm in textos_norm:
                return i, int(j)
    return -1, -1


def limpiar_stock_desde_reporte(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte el reporte de inventario a una tabla limpia:
    articulo, descripcion, estado, unidad, cantidad, codigo_normalizado.

    Formato detectado en Stock_07052026.xls:
    - Artículo: columna C, índice 2
    - Descripción: columna I, índice 8
    - Estado: columna O, índice 14/15 según exportación; en este archivo queda 14/15 visualmente,
      pandas usa el índice real detectado desde el Excel.
    - Unidad: columna Q, índice 16
    - Cantidad: columna U, índice 20
    """
    # Intento detectar por encabezados visibles.
    fila_art, col_art = buscar_columna_por_texto(df_raw, ["Artículo", "Articulo"])
    _, col_estado = buscar_columna_por_texto(df_raw, ["Estado"])
    _, col_unidad = buscar_columna_por_texto(df_raw, ["Unidad"])
    _, col_cantidad = buscar_columna_por_texto(df_raw, ["Cantidad"])

    # Si no detecta, uso el formato real del reporte Zenex/Darkinel.
    if col_art == -1:
        fila_art, col_art = 4, 2
    if col_estado == -1:
        col_estado = 14
    if col_unidad == -1:
        col_unidad = 16
    if col_cantidad == -1:
        col_cantidad = 20

    # En el reporte la descripción no trae encabezado visible, pero está en la columna I.
    col_descripcion = 8 if df_raw.shape[1] > 8 else min(col_art + 1, df_raw.shape[1] - 1)

    inicio = max(fila_art + 1, 0)
    filas = []

    for idx in range(inicio, len(df_raw)):
        row = df_raw.iloc[idx]

        articulo = row.iloc[col_art] if col_art < len(row) else None
        descripcion = row.iloc[col_descripcion] if col_descripcion < len(row) else ""
        estado = row.iloc[col_estado] if col_estado < len(row) else ""
        unidad = row.iloc[col_unidad] if col_unidad < len(row) else ""
        cantidad = row.iloc[col_cantidad] if col_cantidad < len(row) else 0

        articulo_txt = "" if pd.isna(articulo) else str(articulo).strip()
        if not articulo_txt:
            continue

        art_norm = normalizar_codigo(articulo_txt)

        # Saltar encabezados repetidos, pies de página y basura del reporte.
        if art_norm in {"ARTICULO", "RJINVSTOCKARTDEP", "DARKINELSA", "TODAS"}:
            continue
        if articulo_txt.upper().startswith("FECHA DE EMISION"):
            continue

        cantidad_num = pd.to_numeric(cantidad, errors="coerce")
        if pd.isna(cantidad_num):
            continue

        # El programa debe buscar solamente artículos con stock.
        if float(cantidad_num) <= 0:
            continue

        filas.append(
            {
                "articulo": articulo_txt,
                "descripcion": "" if pd.isna(descripcion) else str(descripcion).strip(),
                "estado": "" if pd.isna(estado) else str(estado).strip(),
                "unidad": "" if pd.isna(unidad) else str(unidad).strip(),
                "cantidad": float(cantidad_num),
                "codigo_normalizado": art_norm,
                "fila_origen": idx + 1,
            }
        )

    stock = pd.DataFrame(filas)
    if stock.empty:
        return stock

    # Orden visual y limpieza de cantidad entera cuando corresponde.
    stock["cantidad"] = stock["cantidad"].apply(lambda x: int(x) if float(x).is_integer() else x)
    stock = stock.drop_duplicates(subset=["articulo", "descripcion", "cantidad"])
    return stock


@st.cache_data(show_spinner=False)
def cargar_stock(file_bytes: bytes, filename: str) -> pd.DataFrame:
    raw = leer_archivo_excel_o_csv(file_bytes, filename)
    return limpiar_stock_desde_reporte(raw)


def buscar_archivo_stock_por_defecto() -> Path | None:
    """
    Para GitHub/Streamlit Cloud: si existe un archivo dentro de /data,
    la app lo puede cargar automáticamente.

    Recomendación:
    - Repositorio público: NO subir stock real. Usar upload manual.
    - Repositorio privado: se puede guardar data/Stock_07052026.xls.
    """
    carpeta = Path("data")
    if not carpeta.exists():
        return None

    for patron in ("*.xls", "*.xlsx", "*.xlsm", "*.csv"):
        encontrados = sorted(carpeta.glob(patron))
        if encontrados:
            return encontrados[0]
    return None


# -----------------------------
# Búsqueda
# -----------------------------
def buscar_exactos(stock: pd.DataFrame, codigo_leido: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    info = extraer_candidatos_mazda(codigo_leido)
    candidatos = info["candidatos"]

    if stock.empty or not candidatos:
        return pd.DataFrame(), info

    prioridad = {codigo: pos for pos, codigo in enumerate(candidatos)}
    resultado = stock[stock["codigo_normalizado"].isin(candidatos)].copy()

    if not resultado.empty:
        resultado["match_con"] = resultado["codigo_normalizado"].map(lambda x: x if x in prioridad else "")
        resultado["prioridad"] = resultado["codigo_normalizado"].map(lambda x: prioridad.get(x, 999))
        resultado = resultado.sort_values(["prioridad", "articulo"]).drop(columns=["prioridad"])

    return resultado, info


def buscar_sugerencias(stock: pd.DataFrame, candidatos: List[str], limite: int = 25) -> pd.DataFrame:
    if stock.empty or not candidatos:
        return pd.DataFrame()

    candidatos_validos = [c for c in candidatos if len(c) >= 5]
    if not candidatos_validos:
        return pd.DataFrame()

    candidatos_validos = sorted(candidatos_validos, key=len, reverse=True)

    def puntaje(codigo_stock: str) -> int:
        score = 0
        for c in candidatos_validos:
            if codigo_stock == c:
                score = max(score, 100)
            elif codigo_stock.startswith(c) or c.startswith(codigo_stock):
                score = max(score, 90)
            elif c in codigo_stock or codigo_stock in c:
                score = max(score, 80)
            else:
                # Coincidencia por prefijo de 6 caracteres para sugerir familias.
                pref = c[:6]
                if len(pref) >= 6 and codigo_stock.startswith(pref):
                    score = max(score, 65)
        return score

    sug = stock.copy()
    sug["puntaje"] = sug["codigo_normalizado"].map(puntaje)
    sug = sug[sug["puntaje"] > 0].sort_values(["puntaje", "cantidad"], ascending=[False, False])
    return sug.head(limite).drop(columns=["puntaje"])


def preparar_resultado_para_mostrar(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = ["articulo", "descripcion", "estado", "unidad", "cantidad", "codigo_normalizado"]
    if "match_con" in df.columns:
        cols.insert(0, "match_con")
    cols = [c for c in cols if c in df.columns]
    return df[cols].rename(
        columns={
            "match_con": "Match",
            "articulo": "Artículo en stock",
            "descripcion": "Descripción",
            "estado": "Estado",
            "unidad": "Unidad",
            "cantidad": "Cantidad",
            "codigo_normalizado": "Código normalizado",
        }
    )


# -----------------------------
# Interfaz
# -----------------------------
st.title("🔎 Lector de códigos Mazda contra stock")
st.caption("Lee el código del scanner, lo normaliza y busca únicamente artículos con stock en la base de inventario.")

with st.sidebar:
    st.header("Base de stock")
    archivo_default = buscar_archivo_stock_por_defecto()

    usar_default = False
    if archivo_default is not None:
        usar_default = st.checkbox(
            f"Usar stock del repositorio: {archivo_default.name}",
            value=True,
            help="Útil si el repo es privado y subiste el stock a la carpeta data/.",
        )

    uploaded = None
    if not usar_default:
        uploaded = st.file_uploader("Subí el archivo de stock", type=["xls", "xlsx", "xlsm", "csv"])

    st.markdown("---")
    st.subheader("Ejemplos reales Mazda")
    st.code(
        "UCY4584GX   2\n"
        "B60P34156   3\n"
        "BJT667395   .\n"
        "PE0110602   Y\n"
        "KD4767UC5A62'\n"
        "KD47UC1 E4R  PAJ8133A0A",
        language="text",
    )

if usar_default and archivo_default is not None:
    file_bytes = archivo_default.read_bytes()
    file_name = archivo_default.name
elif uploaded is not None:
    file_bytes = uploaded.getvalue()
    file_name = uploaded.name
else:
    st.info("Subí el Excel de stock para empezar. Puede ser el reporte .xls que ya usás.")
    st.stop()

try:
    stock_df = cargar_stock(file_bytes, file_name)
except ImportError as e:
    st.error("No se pudo leer el archivo .xls porque falta la librería xlrd.")
    st.code("pip install xlrd", language="bash")
    st.exception(e)
    st.stop()
except Exception as e:
    st.error("No se pudo leer el archivo de stock. Revisá que sea .xls, .xlsx o .csv válido.")
    st.exception(e)
    st.stop()

if stock_df.empty:
    st.error("No encontré artículos con cantidad mayor a cero en el archivo.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Artículos con stock", f"{len(stock_df):,}".replace(",", "."))
col2.metric("Stock total unidades", f"{int(pd.to_numeric(stock_df['cantidad'], errors='coerce').fillna(0).sum()):,}".replace(",", "."))
col3.metric("Archivo", file_name)

st.markdown("---")

modo = st.radio(
    "Modo de búsqueda",
    ["Un código", "Varios códigos"],
    horizontal=True,
)

if modo == "Un código":
    codigo = st.text_input(
        "Escaneá o digitá el código",
        placeholder="Ejemplo: KD4767UC5A62'",
    )

    if codigo:
        exactos, info = buscar_exactos(stock_df, codigo)

        with st.expander("Ver cómo interpretó el código", expanded=True):
            st.write("**Lectura original:**", info["lectura_original"])
            st.write("**Tokens limpios:**", info["tokens_limpios"])
            st.write("**Sufijos detectados:**", info["sufijos"])
            st.write("**Candidatos de búsqueda:**", info["candidatos"])

        if not exactos.empty:
            st.success(f"Encontré {len(exactos)} artículo(s) con stock.")
            st.dataframe(preparar_resultado_para_mostrar(exactos), use_container_width=True, hide_index=True)
        else:
            st.warning("No encontré coincidencia exacta con stock.")
            sug = buscar_sugerencias(stock_df, info["candidatos"])
            if not sug.empty:
                st.info("Sugerencias similares con stock:")
                st.dataframe(preparar_resultado_para_mostrar(sug), use_container_width=True, hide_index=True)
            else:
                st.info("Tampoco encontré sugerencias cercanas con stock.")

else:
    codigos = st.text_area(
        "Escaneá varios códigos, uno por línea",
        height=180,
        placeholder="UCY4584GX   2\nB60P34156   3\nKD4767UC5A62'",
    )

    if codigos:
        lecturas = [linea.strip() for linea in codigos.splitlines() if linea.strip()]
        resultados = []
        no_encontrados = []

        for lectura in lecturas:
            exactos, info = buscar_exactos(stock_df, lectura)
            if exactos.empty:
                no_encontrados.append(
                    {
                        "lectura_original": lectura,
                        "candidatos": ", ".join(info["candidatos"]),
                    }
                )
            else:
                tmp = exactos.copy()
                tmp.insert(0, "lectura_original", lectura)
                tmp.insert(1, "candidatos", ", ".join(info["candidatos"]))
                resultados.append(tmp)

        if resultados:
            salida = pd.concat(resultados, ignore_index=True)
            st.success(f"Encontré stock para {salida['lectura_original'].nunique()} lectura(s).")
            mostrar = salida[
                [
                    "lectura_original",
                    "articulo",
                    "descripcion",
                    "estado",
                    "unidad",
                    "cantidad",
                    "codigo_normalizado",
                    "candidatos",
                ]
            ].rename(
                columns={
                    "lectura_original": "Lectura scanner",
                    "articulo": "Artículo en stock",
                    "descripcion": "Descripción",
                    "estado": "Estado",
                    "unidad": "Unidad",
                    "cantidad": "Cantidad",
                    "codigo_normalizado": "Código normalizado",
                    "candidatos": "Candidatos buscados",
                }
            )
            st.dataframe(mostrar, use_container_width=True, hide_index=True)

            csv = mostrar.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Descargar resultado en CSV",
                data=csv,
                file_name="resultado_lecturas_stock.csv",
                mime="text/csv",
            )

        if no_encontrados:
            st.warning(f"No encontré coincidencia exacta para {len(no_encontrados)} lectura(s).")
            st.dataframe(pd.DataFrame(no_encontrados), use_container_width=True, hide_index=True)

st.markdown("---")
with st.expander("Ver primeras filas limpias del stock"):
    st.dataframe(preparar_resultado_para_mostrar(stock_df.head(100)), use_container_width=True, hide_index=True)
