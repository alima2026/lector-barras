import io
import re
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st


# ==========================================================
# APP: Lector Mazda/Kia/Multimarca contra stock + armado de pallets
# Autor: preparado para Carlos / Alimatico
# ==========================================================

st.set_page_config(
    page_title="Lector de códigos Mazda - Stock y Pallets",
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


def numero_seguro(valor, defecto: float = 0.0) -> float:
    """Convierte un valor a número y evita NaN/errores de edición."""
    num = pd.to_numeric(valor, errors="coerce")
    if pd.isna(num):
        return float(defecto)
    return float(num)


def entero_seguro(valor, defecto: int = 0) -> int:
    return int(numero_seguro(valor, defecto))


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
            # El código completo queda primero para no perder variantes reales.
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
    - Estado: columna O, índice 14/15 según exportación
    - Unidad: columna Q, índice 16
    - Cantidad: columna U, índice 20
    """
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

    stock["cantidad"] = stock["cantidad"].apply(lambda x: int(x) if float(x).is_integer() else x)
    stock = stock.drop_duplicates(subset=["articulo", "descripcion", "cantidad"])
    return stock


@st.cache_data(show_spinner=False)
def cargar_stock(file_bytes: bytes, filename: str) -> pd.DataFrame:
    raw = leer_archivo_excel_o_csv(file_bytes, filename)
    return limpiar_stock_desde_reporte(raw)


# -----------------------------
# Búsqueda y consolidación
# -----------------------------
def _primer_valor_no_vacio(serie: pd.Series) -> str:
    for valor in serie:
        if pd.notna(valor) and str(valor).strip():
            return str(valor).strip()
    return ""


def _unir_valores_unicos(serie: pd.Series) -> str:
    valores = []
    for valor in serie:
        if pd.notna(valor):
            texto = str(valor).strip()
            if texto and texto not in valores:
                valores.append(texto)
    return " / ".join(valores)


def consolidar_por_codigo(df: pd.DataFrame) -> pd.DataFrame:
    """
    Si el mismo código aparece en más de una línea del Excel, suma las cantidades.
    Ejemplo real: B6Y1-14-302A con 316 + 49 = 365.
    """
    if df.empty:
        return df

    trabajo = df.copy()
    trabajo["cantidad"] = pd.to_numeric(trabajo["cantidad"], errors="coerce").fillna(0)

    agregaciones = {
        "articulo": _primer_valor_no_vacio,
        "descripcion": _primer_valor_no_vacio,
        "estado": _unir_valores_unicos,
        "unidad": _primer_valor_no_vacio,
        "cantidad": "sum",
    }

    if "match_con" in trabajo.columns:
        agregaciones["match_con"] = _primer_valor_no_vacio
    if "prioridad" in trabajo.columns:
        agregaciones["prioridad"] = "min"
    if "fila_origen" in trabajo.columns:
        agregaciones["fila_origen"] = lambda s: ", ".join(str(int(x)) for x in s if pd.notna(x))

    agrupado = trabajo.groupby("codigo_normalizado", as_index=False).agg(agregaciones)
    agrupado["lineas_sumadas"] = trabajo.groupby("codigo_normalizado").size().values
    agrupado["cantidad"] = agrupado["cantidad"].apply(lambda x: int(x) if float(x).is_integer() else x)
    return agrupado


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
        resultado = consolidar_por_codigo(resultado)
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
                pref = c[:6]
                if len(pref) >= 6 and codigo_stock.startswith(pref):
                    score = max(score, 65)
        return score

    sug = stock.copy()
    sug["puntaje"] = sug["codigo_normalizado"].map(puntaje)
    sug = sug[sug["puntaje"] > 0].copy()
    if sug.empty:
        return sug

    sug["prioridad"] = -sug["puntaje"]
    sug = consolidar_por_codigo(sug)
    sug = sug.sort_values(["prioridad", "cantidad"], ascending=[True, False]).drop(columns=["prioridad"])
    return sug.head(limite)


def preparar_resultado_para_mostrar(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = ["articulo", "descripcion", "estado", "unidad", "cantidad", "lineas_sumadas", "codigo_normalizado"]
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
            "cantidad": "Stock total",
            "lineas_sumadas": "Líneas sumadas",
            "codigo_normalizado": "Código normalizado",
        }
    )


# -----------------------------
# Picking / Pallets / Mudanza
# -----------------------------
def inicializar_estado() -> None:
    if "pick_items" not in st.session_state:
        st.session_state.pick_items = []
    if "pick_seq" not in st.session_state:
        st.session_state.pick_seq = 0


def cantidad_pickeada_por_codigo(codigo_normalizado: str) -> float:
    total = 0.0
    for item in st.session_state.pick_items:
        if item.get("codigo_normalizado") == codigo_normalizado:
            total += float(item.get("cantidad_mudada", 0) or 0)
    return total


def agregar_item_a_pallet(
    lectura_original: str,
    row: pd.Series,
    cantidad_mudada: float,
    pallet: int,
    bultos_pallet: int,
    bultos_item: str,
    deposito_origen: str,
    deposito_destino: str,
    observaciones: str = "",
) -> Tuple[bool, str]:
    codigo_norm = str(row.get("codigo_normalizado", ""))
    stock_total = numero_seguro(row.get("cantidad", 0), 0)
    ya_pickeado = cantidad_pickeada_por_codigo(codigo_norm)

    if cantidad_mudada <= 0:
        return False, "La cantidad a mudar tiene que ser mayor a cero."

    if ya_pickeado + float(cantidad_mudada) > stock_total:
        disponible = max(stock_total - ya_pickeado, 0)
        return (
            False,
            f"No se puede agregar. Stock total {stock_total:g}, ya marcado {ya_pickeado:g}, disponible para mudar {disponible:g}.",
        )

    st.session_state.pick_seq += 1
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    st.session_state.pick_items.append(
        {
            "item_id": st.session_state.pick_seq,
            "fecha_hora": ahora,
            "deposito_origen": deposito_origen.strip() or "DARKINEL",
            "deposito_destino": deposito_destino.strip() or "",
            "pallet": int(pallet),
            "bultos_pallet": int(bultos_pallet),
            "bultos_item": str(bultos_item).strip() or "",
            "lectura_scanner": str(lectura_original).strip(),
            "articulo": str(row.get("articulo", "")).strip(),
            "descripcion": str(row.get("descripcion", "")).strip(),
            "estado": str(row.get("estado", "")).strip(),
            "unidad": str(row.get("unidad", "")).strip(),
            "cantidad_mudada": float(cantidad_mudada),
            "stock_total": stock_total,
            "codigo_normalizado": codigo_norm,
            "observaciones": observaciones.strip(),
        }
    )
    return True, "Artículo agregado al pallet."


def pick_items_df() -> pd.DataFrame:
    df = pd.DataFrame(st.session_state.pick_items)
    if df.empty:
        return df

    df["cantidad_mudada"] = pd.to_numeric(df["cantidad_mudada"], errors="coerce").fillna(0)
    df["stock_total"] = pd.to_numeric(df["stock_total"], errors="coerce").fillna(0)

    total_por_codigo = df.groupby("codigo_normalizado")["cantidad_mudada"].transform("sum")
    df["stock_restante_teorico"] = df["stock_total"] - total_por_codigo

    # Limpieza visual: cantidades enteras sin .0
    for col in ["cantidad_mudada", "stock_total", "stock_restante_teorico"]:
        df[col] = df[col].apply(lambda x: int(x) if float(x).is_integer() else x)

    return df


def preparar_detalle_mudanza(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [
        "fecha_hora",
        "deposito_origen",
        "deposito_destino",
        "pallet",
        "bultos_pallet",
        "bultos_item",
        "lectura_scanner",
        "articulo",
        "descripcion",
        "estado",
        "unidad",
        "cantidad_mudada",
        "stock_total",
        "stock_restante_teorico",
        "codigo_normalizado",
        "observaciones",
    ]
    cols = [c for c in cols if c in df.columns]
    return df[cols].rename(
        columns={
            "fecha_hora": "Fecha/Hora",
            "deposito_origen": "Depósito origen",
            "deposito_destino": "Depósito destino",
            "pallet": "Pallet",
            "bultos_pallet": "Bultos del pallet",
            "bultos_item": "Bulto(s) del artículo",
            "lectura_scanner": "Lectura scanner",
            "articulo": "Artículo",
            "descripcion": "Descripción",
            "estado": "Estado",
            "unidad": "Unidad",
            "cantidad_mudada": "Cantidad mudada",
            "stock_total": "Stock total",
            "stock_restante_teorico": "Stock restante teórico",
            "codigo_normalizado": "Código normalizado",
            "observaciones": "Observaciones",
        }
    )


def resumen_pallets(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    trabajo = df.copy()
    trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)

    resumen = (
        trabajo.groupby(["deposito_origen", "deposito_destino", "pallet", "bultos_pallet"], dropna=False)
        .agg(
            codigos_distintos=("codigo_normalizado", "nunique"),
            lineas_pickeadas=("codigo_normalizado", "size"),
            unidades_totales=("cantidad_mudada", "sum"),
            codigos=("articulo", lambda s: " / ".join(dict.fromkeys(str(x) for x in s if str(x).strip()))),
        )
        .reset_index()
    )
    resumen["unidades_totales"] = resumen["unidades_totales"].apply(lambda x: int(x) if float(x).is_integer() else x)
    return resumen.rename(
        columns={
            "deposito_origen": "Depósito origen",
            "deposito_destino": "Depósito destino",
            "pallet": "Pallet",
            "bultos_pallet": "Bultos del pallet",
            "codigos_distintos": "Códigos distintos",
            "lineas_pickeadas": "Líneas pickeadas",
            "unidades_totales": "Unidades totales",
            "codigos": "Códigos que componen el pallet",
        }
    )


def composicion_por_bulto(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    trabajo = df.copy()
    trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)

    comp = (
        trabajo.groupby(["pallet", "bultos_pallet", "bultos_item"], dropna=False)
        .agg(
            codigos_distintos=("codigo_normalizado", "nunique"),
            unidades_totales=("cantidad_mudada", "sum"),
            codigos=("articulo", lambda s: " / ".join(dict.fromkeys(str(x) for x in s if str(x).strip()))),
            descripciones=("descripcion", lambda s: " / ".join(dict.fromkeys(str(x) for x in s if str(x).strip()))),
        )
        .reset_index()
    )
    comp["unidades_totales"] = comp["unidades_totales"].apply(lambda x: int(x) if float(x).is_integer() else x)
    return comp.rename(
        columns={
            "pallet": "Pallet",
            "bultos_pallet": "Bultos del pallet",
            "bultos_item": "Bulto(s)",
            "codigos_distintos": "Códigos distintos",
            "unidades_totales": "Unidades totales",
            "codigos": "Códigos en el/los bulto(s)",
            "descripciones": "Descripciones",
        }
    )


def generar_excel_mudanza(df_pick: pd.DataFrame) -> bytes:
    detalle = preparar_detalle_mudanza(df_pick)
    resumen = resumen_pallets(df_pick)
    composicion = composicion_por_bulto(df_pick)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resumen.to_excel(writer, index=False, sheet_name="Resumen_Pallets")
        composicion.to_excel(writer, index=False, sheet_name="Composicion_Bultos")
        detalle.to_excel(writer, index=False, sheet_name="Detalle_Mudanza")

        # Ajuste simple de ancho de columnas.
        for sheet_name in writer.book.sheetnames:
            ws = writer.book[sheet_name]
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    val = "" if cell.value is None else str(cell.value)
                    max_len = max(max_len, min(len(val), 60))
                ws.column_dimensions[col_letter].width = max(max_len + 2, 12)

    return output.getvalue()


def nombre_archivo_mudanza() -> str:
    return f"mudanza_deposito_darkinel_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"


# -----------------------------
# Interfaz
# -----------------------------
inicializar_estado()

st.title("🔎 Lector de códigos Mazda contra stock + Mudanza de depósito")
st.caption(
    "Lee el código del scanner, consolida stock repetido, permite pickear artículos y genera el archivo de mudanza desde DARKINEL por pallet y bultos."
)

with st.sidebar:
    st.header("Base de stock")
    uploaded = st.file_uploader("Subí el archivo de stock", type=["xls", "xlsx", "xlsm", "csv"])

    st.markdown("---")
    st.subheader("Datos de mudanza")
    deposito_origen = st.text_input("Depósito origen", value="DARKINEL")
    deposito_destino = st.text_input("Depósito destino", value="")
    pallet_activo = st.number_input("Pallet activo", min_value=1, value=1, step=1)
    bultos_pallet_activo = st.number_input("Cantidad de bultos del pallet activo", min_value=1, value=1, step=1)

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

if uploaded is None:
    st.info("Subí el Excel de stock para empezar. Puede ser el reporte .xls que ya usás.")
    st.stop()

try:
    stock_df = cargar_stock(uploaded.getvalue(), uploaded.name)
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

col1, col2, col3, col4 = st.columns(4)
col1.metric("Artículos con stock", f"{len(stock_df):,}".replace(",", "."))
col2.metric("Stock total unidades", f"{int(pd.to_numeric(stock_df['cantidad'], errors='coerce').fillna(0).sum()):,}".replace(",", "."))
col3.metric("Archivo", uploaded.name)
col4.metric("Líneas en mudanza", len(st.session_state.pick_items))

st.markdown("---")

tab_buscar, tab_pallets, tab_stock = st.tabs(["1) Buscar y pickear", "2) Pallets / archivo de mudanza", "3) Stock limpio"])

with tab_buscar:
    modo = st.radio(
        "Modo de búsqueda",
        ["Un código", "Varios códigos"],
        horizontal=True,
    )

    if modo == "Un código":
        codigo = st.text_input(
            "Escaneá o digitá el código",
            placeholder="Ejemplo: B6Y114302A J",
        )

        if codigo:
            exactos, info = buscar_exactos(stock_df, codigo)

            with st.expander("Ver cómo interpretó el código", expanded=True):
                st.write("**Lectura original:**", info["lectura_original"])
                st.write("**Tokens limpios:**", info["tokens_limpios"])
                st.write("**Sufijos detectados:**", info["sufijos"])
                st.write("**Candidatos de búsqueda:**", info["candidatos"])

            if not exactos.empty:
                st.success(f"Encontré {len(exactos)} artículo(s) con stock consolidado.")
                st.dataframe(preparar_resultado_para_mostrar(exactos), use_container_width=True, hide_index=True)

                st.subheader("Agregar a pallet / mudanza")
                opciones = []
                for i, row in exactos.reset_index(drop=True).iterrows():
                    opciones.append(
                        f"{i + 1}) {row.get('articulo', '')} | {row.get('descripcion', '')} | Stock {row.get('cantidad', 0)}"
                    )
                opcion = st.selectbox("Artículo encontrado", opciones)
                idx = opciones.index(opcion)
                row_sel = exactos.reset_index(drop=True).iloc[idx]

                disponible = float(row_sel["cantidad"]) - cantidad_pickeada_por_codigo(row_sel["codigo_normalizado"])
                if disponible < 0:
                    disponible = 0

                if disponible <= 0:
                    st.warning("Este código ya quedó totalmente marcado para mudanza en los pallets actuales.")
                else:
                    with st.form("form_agregar_un_codigo"):
                        c1, c2, c3, c4 = st.columns(4)
                        cantidad_mudar = c1.number_input(
                            "Cantidad a mudar",
                            min_value=1.0,
                            max_value=float(disponible),
                            value=1.0,
                            step=1.0,
                        )
                        pallet = c2.number_input("Pallet", min_value=1, value=int(pallet_activo), step=1)
                        bultos_pallet = c3.number_input(
                            "Bultos del pallet",
                            min_value=1,
                            value=int(bultos_pallet_activo),
                            step=1,
                        )
                        bultos_item = c4.text_input("Bulto(s) del artículo", placeholder="Ej: 1 o 6,7")
                        observaciones = st.text_input("Observaciones", placeholder="Opcional")
                        submitted = st.form_submit_button("Agregar artículo al pallet")

                    if submitted:
                        ok, msg = agregar_item_a_pallet(
                            lectura_original=codigo,
                            row=row_sel,
                            cantidad_mudada=float(cantidad_mudar),
                            pallet=int(pallet),
                            bultos_pallet=int(bultos_pallet),
                            bultos_item=bultos_item,
                            deposito_origen=deposito_origen,
                            deposito_destino=deposito_destino,
                            observaciones=observaciones,
                        )
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)

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
                            "Lectura scanner": lectura,
                            "Candidatos buscados": ", ".join(info["candidatos"]),
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
                        "lineas_sumadas",
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
                        "cantidad": "Stock total",
                        "lineas_sumadas": "Líneas sumadas",
                        "codigo_normalizado": "Código normalizado",
                        "candidatos": "Candidatos buscados",
                    }
                )
                st.dataframe(mostrar, use_container_width=True, hide_index=True)

                st.subheader("Agregar varios artículos al pallet")
                st.caption(
                    "Marcá Agregar, corregí la cantidad a mudar, pallet, bultos del pallet y bulto(s) de cada artículo."
                )

                para_editar = mostrar.copy()
                para_editar.insert(0, "Agregar", True)
                para_editar["Cantidad a mudar"] = 1
                para_editar["Pallet"] = int(pallet_activo)
                para_editar["Bultos del pallet"] = int(bultos_pallet_activo)
                para_editar["Bulto(s) del artículo"] = ""
                para_editar["Observaciones"] = ""

                editado = st.data_editor(para_editar, use_container_width=True, hide_index=True, num_rows="fixed")

                if st.button("Agregar marcados al pallet", type="primary"):
                    agregados = 0
                    errores = []
                    for _, fila in editado.iterrows():
                        if not bool(fila.get("Agregar", False)):
                            continue
                        codigo_norm = str(fila.get("Código normalizado", ""))
                        match = salida[salida["codigo_normalizado"] == codigo_norm]
                        if match.empty:
                            continue
                        row_sel = match.iloc[0]
                        ok, msg = agregar_item_a_pallet(
                            lectura_original=str(fila.get("Lectura scanner", "")),
                            row=row_sel,
                            cantidad_mudada=numero_seguro(fila.get("Cantidad a mudar", 0), 0),
                            pallet=entero_seguro(fila.get("Pallet", pallet_activo), int(pallet_activo)),
                            bultos_pallet=entero_seguro(fila.get("Bultos del pallet", bultos_pallet_activo), int(bultos_pallet_activo)),
                            bultos_item=str(fila.get("Bulto(s) del artículo", "")),
                            deposito_origen=deposito_origen,
                            deposito_destino=deposito_destino,
                            observaciones=str(fila.get("Observaciones", "")),
                        )
                        if ok:
                            agregados += 1
                        else:
                            errores.append(f"{fila.get('Artículo en stock', codigo_norm)}: {msg}")
                    if agregados:
                        st.success(f"Agregué {agregados} línea(s) al pallet.")
                    if errores:
                        st.error("No se pudieron agregar algunas líneas:")
                        for e in errores:
                            st.write("-", e)

                csv = mostrar.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "Descargar resultado de búsqueda en CSV",
                    data=csv,
                    file_name="resultado_lecturas_stock.csv",
                    mime="text/csv",
                )

            if no_encontrados:
                st.warning(f"No encontré coincidencia exacta para {len(no_encontrados)} lectura(s).")
                st.dataframe(pd.DataFrame(no_encontrados), use_container_width=True, hide_index=True)

with tab_pallets:
    df_pick = pick_items_df()

    if df_pick.empty:
        st.info("Todavía no hay artículos agregados a pallets. Buscá un código y agregalo desde la pestaña 1.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Pallets", df_pick["pallet"].nunique())
        c2.metric("Códigos distintos", df_pick["codigo_normalizado"].nunique())
        c3.metric("Unidades a mudar", int(pd.to_numeric(df_pick["cantidad_mudada"], errors="coerce").fillna(0).sum()))

        st.subheader("Resumen por pallet")
        st.dataframe(resumen_pallets(df_pick), use_container_width=True, hide_index=True)

        st.subheader("Composición por pallet y bulto")
        st.dataframe(composicion_por_bulto(df_pick), use_container_width=True, hide_index=True)

        st.subheader("Detalle de mudanza")
        detalle = preparar_detalle_mudanza(df_pick)
        st.dataframe(detalle, use_container_width=True, hide_index=True)

        excel_bytes = generar_excel_mudanza(df_pick)
        st.download_button(
            "Descargar archivo Excel de mudanza",
            data=excel_bytes,
            file_name=nombre_archivo_mudanza(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

        csv_bytes = detalle.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Descargar detalle en CSV",
            data=csv_bytes,
            file_name="detalle_mudanza_deposito.csv",
            mime="text/csv",
        )

        st.markdown("---")
        st.subheader("Corregir / quitar líneas")
        opciones_borrar = {}
        for _, row in df_pick.iterrows():
            etiqueta = (
                f"ID {row['item_id']} | Pallet {row['pallet']} | Bulto(s) {row.get('bultos_item', '')} | "
                f"{row['articulo']} | Cant. {row['cantidad_mudada']}"
            )
            opciones_borrar[etiqueta] = row["item_id"]

        seleccion_borrar = st.multiselect("Líneas para quitar", list(opciones_borrar.keys()))
        col_borrar, col_limpiar = st.columns(2)
        with col_borrar:
            if st.button("Quitar líneas seleccionadas"):
                ids = {opciones_borrar[x] for x in seleccion_borrar}
                st.session_state.pick_items = [item for item in st.session_state.pick_items if item["item_id"] not in ids]
                st.success("Líneas quitadas.")
                st.rerun()
        with col_limpiar:
            if st.button("Limpiar toda la mudanza"):
                st.session_state.pick_items = []
                st.success("Mudanza limpiada.")
                st.rerun()

with tab_stock:
    st.subheader("Primeras filas limpias del stock")
    st.dataframe(preparar_resultado_para_mostrar(stock_df.head(200)), use_container_width=True, hide_index=True)
