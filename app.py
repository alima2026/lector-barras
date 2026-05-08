import io
import re
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st


# ==========================================================
# APP: Lector Mazda/Kia/Multimarca contra stock + mudanza de depósitos
# Autor: preparado para Carlos / Alimatico
# ==========================================================

st.set_page_config(
    page_title="Lector de códigos Mazda - Stock, Pallets y Depósitos",
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
    """
    if pd.isna(valor):
        return ""
    texto = str(valor).upper().strip().replace("Ñ", "N")
    return re.sub(r"[^A-Z0-9]", "", texto)


def agregar_unico(lista: List[str], valor: str) -> None:
    valor = normalizar_codigo(valor)
    if valor and valor not in lista:
        lista.append(valor)


def numero_seguro(valor, defecto: float = 0.0) -> float:
    num = pd.to_numeric(valor, errors="coerce")
    if pd.isna(num):
        return float(defecto)
    return float(num)


def entero_seguro(valor, defecto: int = 0) -> int:
    return int(numero_seguro(valor, defecto))


def formatear_numero(x):
    try:
        fx = float(x)
        return int(fx) if fx.is_integer() else fx
    except Exception:
        return x


def extraer_candidatos_mazda(codigo_leido: str) -> Dict[str, object]:
    """
    Recibe la lectura cruda del scanner y genera candidatos de búsqueda.
    Sirve para Mazda/Kia/Multimarca porque compara todo normalizado.
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

            # Si viene pegado con sufijo, también pruebo una versión base de 10 caracteres.
            if len(token) > 10:
                agregar_unico(candidatos, token[:10])
                extra = token[10:]
                if extra:
                    sufijos.append(extra)

        elif 1 <= len(token) <= 4:
            sufijos.append(token)

    for codigo in list(codigos_largos):
        for sufijo in sufijos:
            if sufijo:
                agregar_unico(candidatos, codigo + sufijo)

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
    """Lee .xls, .xlsx, .xlsm o .csv como tabla cruda, sin asumir encabezado."""
    nombre = filename.lower()
    buffer = io.BytesIO(file_bytes)

    if nombre.endswith(".csv"):
        try:
            return pd.read_csv(buffer, header=None, dtype=object, sep=None, engine="python")
        except UnicodeDecodeError:
            buffer.seek(0)
            return pd.read_csv(buffer, header=None, dtype=object, sep=None, engine="python", encoding="latin1")

    if nombre.endswith(".xls"):
        return pd.read_excel(buffer, header=None, dtype=object, engine="xlrd")

    if nombre.endswith((".xlsx", ".xlsm")):
        return pd.read_excel(buffer, header=None, dtype=object, engine="openpyxl")

    raise ValueError("Formato no soportado. Use .xls, .xlsx, .xlsm o .csv")


def buscar_columna_por_texto(df_raw: pd.DataFrame, textos: List[str]) -> Tuple[int, int]:
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
    Convierte el reporte de inventario a tabla limpia:
    articulo, descripcion, estado, unidad, cantidad, codigo_normalizado.
    Si el reporte no trae encabezados claros, usa el formato real del reporte de stock.
    """
    fila_art, col_art = buscar_columna_por_texto(df_raw, ["Artículo", "Articulo"])
    _, col_estado = buscar_columna_por_texto(df_raw, ["Estado"])
    _, col_unidad = buscar_columna_por_texto(df_raw, ["Unidad"])
    _, col_cantidad = buscar_columna_por_texto(df_raw, ["Cantidad", "Stock"])

    if col_art == -1:
        fila_art, col_art = 4, 2
    if col_estado == -1:
        col_estado = 14
    if col_unidad == -1:
        col_unidad = 16
    if col_cantidad == -1:
        col_cantidad = 20

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
        if art_norm in {"ARTICULO", "RJINVSTOCKARTDEP", "DARKINELSA", "TODAS", "CANTIDAD"}:
            continue
        if articulo_txt.upper().startswith("FECHA DE EMISION"):
            continue

        cantidad_num = pd.to_numeric(cantidad, errors="coerce")
        if pd.isna(cantidad_num) or float(cantidad_num) <= 0:
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

    stock["cantidad"] = stock["cantidad"].apply(formatear_numero)
    return stock


@st.cache_data(show_spinner=False)
def cargar_stock(file_bytes: bytes, filename: str) -> pd.DataFrame:
    raw = leer_archivo_excel_o_csv(file_bytes, filename)
    return limpiar_stock_desde_reporte(raw)


# -----------------------------
# Consolidación y búsqueda
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
    """Si el mismo código aparece varias veces, suma cantidades. Ej.: 316 + 49 = 365."""
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
    if "puntaje" in trabajo.columns:
        agregaciones["puntaje"] = "max"
    if "fila_origen" in trabajo.columns:
        agregaciones["fila_origen"] = lambda s: ", ".join(str(int(x)) for x in s if pd.notna(x))

    agrupado = trabajo.groupby("codigo_normalizado", as_index=False).agg(agregaciones)
    agrupado["lineas_sumadas"] = trabajo.groupby("codigo_normalizado").size().values
    agrupado["cantidad"] = agrupado["cantidad"].apply(formatear_numero)
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
        resultado = resultado.sort_values(["prioridad", "articulo"]).drop(columns=["prioridad"], errors="ignore")
    return resultado, info


def buscar_sugerencias(stock: pd.DataFrame, candidatos: List[str], limite: int = 25) -> pd.DataFrame:
    if stock.empty or not candidatos:
        return pd.DataFrame()

    candidatos_validos = sorted([c for c in candidatos if len(c) >= 5], key=len, reverse=True)
    if not candidatos_validos:
        return pd.DataFrame()

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
    sug = sug.sort_values(["prioridad", "cantidad"], ascending=[True, False]).drop(columns=["prioridad"], errors="ignore")
    return sug.head(limite)


def preparar_resultado_para_mostrar(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = ["articulo", "descripcion", "estado", "unidad", "cantidad", "lineas_sumadas", "codigo_normalizado"]
    if "match_con" in df.columns:
        cols.insert(0, "match_con")
    if "puntaje" in df.columns:
        cols.append("puntaje")
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
            "puntaje": "Coincidencia",
        }
    )


# -----------------------------
# Picking / mudanza / depósitos
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


def agregar_item_a_mudanza(
    lectura_original: str,
    row: pd.Series,
    cantidad_mudada: float,
    pallet: int,
    cantidad_bultos: int,
    ubicacion: str,
    deposito_origen: str,
    deposito_destino: str,
    observaciones: str = "",
) -> Tuple[bool, str]:
    codigo_norm = str(row.get("codigo_normalizado", ""))
    stock_total = numero_seguro(row.get("cantidad", 0), 0)
    ya_pickeado = cantidad_pickeada_por_codigo(codigo_norm)

    if cantidad_mudada <= 0:
        return False, "La cantidad a mudar tiene que ser mayor a cero."

    if not str(ubicacion).strip():
        return False, "Falta completar la ubicación. Ejemplo: 1-L-3."

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
            "deposito_destino": deposito_destino.strip() or "POLO LOGISTICO",
            "pallet": int(pallet),
            "cantidad_bultos": int(cantidad_bultos),
            "ubicacion": str(ubicacion).strip().upper(),
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
    return True, "Artículo agregado a la mudanza."


def pick_items_df() -> pd.DataFrame:
    df = pd.DataFrame(st.session_state.pick_items)
    if df.empty:
        return df
    df["cantidad_mudada"] = pd.to_numeric(df["cantidad_mudada"], errors="coerce").fillna(0)
    df["stock_total"] = pd.to_numeric(df["stock_total"], errors="coerce").fillna(0)
    total_por_codigo = df.groupby("codigo_normalizado")["cantidad_mudada"].transform("sum")
    df["stock_restante_darkinel"] = df["stock_total"] - total_por_codigo
    for col in ["cantidad_mudada", "stock_total", "stock_restante_darkinel"]:
        df[col] = df[col].apply(formatear_numero)
    return df


def mudado_por_codigo(df_pick: pd.DataFrame) -> pd.DataFrame:
    if df_pick.empty:
        return pd.DataFrame(columns=["codigo_normalizado", "mudado_al_polo"])
    trabajo = df_pick.copy()
    trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)
    return (
        trabajo.groupby("codigo_normalizado", as_index=False)
        .agg(mudado_al_polo=("cantidad_mudada", "sum"))
    )


def preparar_detalle_mudanza(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Fecha/Hora",
                "Depósito origen",
                "Depósito destino",
                "Pallet",
                "Cantidad de bultos",
                "Ubicación",
                "Lectura scanner",
                "Artículo",
                "Descripción",
                "Unidad",
                "Cantidad mudada",
                "Stock original Darkinel",
                "Stock restante Darkinel",
                "Código normalizado",
                "Observaciones",
            ]
        )

    cols = [
        "fecha_hora",
        "deposito_origen",
        "deposito_destino",
        "pallet",
        "cantidad_bultos",
        "ubicacion",
        "lectura_scanner",
        "articulo",
        "descripcion",
        "unidad",
        "cantidad_mudada",
        "stock_total",
        "stock_restante_darkinel",
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
            "cantidad_bultos": "Cantidad de bultos",
            "ubicacion": "Ubicación",
            "lectura_scanner": "Lectura scanner",
            "articulo": "Artículo",
            "descripcion": "Descripción",
            "unidad": "Unidad",
            "cantidad_mudada": "Cantidad mudada",
            "stock_total": "Stock original Darkinel",
            "stock_restante_darkinel": "Stock restante Darkinel",
            "codigo_normalizado": "Código normalizado",
            "observaciones": "Observaciones",
        }
    )


def resumen_pallets(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Depósito origen",
                "Depósito destino",
                "Pallet",
                "Cantidad de bultos",
                "Ubicaciones",
                "Cantidad de códigos diferentes",
                "Unidades totales",
                "Códigos que componen el pallet",
                "Descripciones",
            ]
        )

    trabajo = df.copy()
    trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)
    resumen = (
        trabajo.groupby(["deposito_origen", "deposito_destino", "pallet", "cantidad_bultos"], dropna=False)
        .agg(
            ubicaciones=("ubicacion", lambda s: " / ".join(dict.fromkeys(str(x) for x in s if str(x).strip()))),
            codigos_distintos=("codigo_normalizado", "nunique"),
            unidades_totales=("cantidad_mudada", "sum"),
            codigos=("articulo", lambda s: " / ".join(dict.fromkeys(str(x) for x in s if str(x).strip()))),
            descripciones=("descripcion", lambda s: " / ".join(dict.fromkeys(str(x) for x in s if str(x).strip()))),
        )
        .reset_index()
    )
    resumen["unidades_totales"] = resumen["unidades_totales"].apply(formatear_numero)
    return resumen.rename(
        columns={
            "deposito_origen": "Depósito origen",
            "deposito_destino": "Depósito destino",
            "pallet": "Pallet",
            "cantidad_bultos": "Cantidad de bultos",
            "ubicaciones": "Ubicaciones",
            "codigos_distintos": "Cantidad de códigos diferentes",
            "unidades_totales": "Unidades totales",
            "codigos": "Códigos que componen el pallet",
            "descripciones": "Descripciones",
        }
    )


def stock_darkinel_actualizado(stock_consolidado: pd.DataFrame, df_pick: pd.DataFrame) -> pd.DataFrame:
    if stock_consolidado.empty:
        return pd.DataFrame()
    base = stock_consolidado.copy()
    base["cantidad"] = pd.to_numeric(base["cantidad"], errors="coerce").fillna(0)
    mudado = mudado_por_codigo(df_pick)
    actualizado = base.merge(mudado, on="codigo_normalizado", how="left")
    actualizado["mudado_al_polo"] = actualizado["mudado_al_polo"].fillna(0)
    actualizado["stock_restante_darkinel"] = actualizado["cantidad"] - actualizado["mudado_al_polo"]
    actualizado["control"] = actualizado["stock_restante_darkinel"].apply(lambda x: "ERROR: mudanza mayor al stock" if x < 0 else "OK")
    actualizado["stock_restante_darkinel"] = actualizado["stock_restante_darkinel"].clip(lower=0)
    for col in ["cantidad", "mudado_al_polo", "stock_restante_darkinel"]:
        actualizado[col] = actualizado[col].apply(formatear_numero)
    return actualizado.rename(
        columns={
            "articulo": "Artículo",
            "descripcion": "Descripción",
            "estado": "Estado",
            "unidad": "Unidad",
            "cantidad": "Stock original Darkinel",
            "mudado_al_polo": "Mudado al Polo",
            "stock_restante_darkinel": "Stock restante Darkinel",
            "codigo_normalizado": "Código normalizado",
            "lineas_sumadas": "Líneas sumadas",
            "control": "Control",
        }
    )[
        [
            "Artículo",
            "Descripción",
            "Estado",
            "Unidad",
            "Stock original Darkinel",
            "Mudado al Polo",
            "Stock restante Darkinel",
            "Código normalizado",
            "Líneas sumadas",
            "Control",
        ]
    ]


def extraer_columna(df: pd.DataFrame, posibles: List[str]) -> str:
    mapa = {normalizar_codigo(c): c for c in df.columns}
    for p in posibles:
        key = normalizar_codigo(p)
        if key in mapa:
            return mapa[key]
    return ""


def leer_base_polo_anterior(file_bytes: bytes, filename: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Lee un archivo generado anteriormente por la app para continuar actualizando Polo."""
    if not file_bytes:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    nombre = filename.lower()
    if not nombre.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    buffer = io.BytesIO(file_bytes)
    engine = "xlrd" if nombre.endswith(".xls") else "openpyxl"
    try:
        xls = pd.ExcelFile(buffer, engine=engine)
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def read_sheet(preferida: str) -> pd.DataFrame:
        if preferida in xls.sheet_names:
            return pd.read_excel(xls, sheet_name=preferida, dtype=object)
        return pd.DataFrame()

    stock_polo = read_sheet("STOCK_POLO_LOGISTICO")
    ubicaciones = read_sheet("UBICACION_POLO_LOGISTICO")
    historial = read_sheet("HISTORIAL_MUDANZAS")
    return stock_polo, ubicaciones, historial


def stock_polo_actualizado(df_pick: pd.DataFrame, stock_polo_anterior: pd.DataFrame) -> pd.DataFrame:
    columnas = ["Artículo", "Descripción", "Stock total Polo", "Código normalizado"]
    nuevos = pd.DataFrame(columns=columnas)

    if not df_pick.empty:
        trabajo = df_pick.copy()
        trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)
        nuevos = (
            trabajo.groupby("codigo_normalizado", as_index=False)
            .agg(
                articulo=("articulo", _primer_valor_no_vacio),
                descripcion=("descripcion", _primer_valor_no_vacio),
                stock_total_polo=("cantidad_mudada", "sum"),
            )
            .rename(
                columns={
                    "articulo": "Artículo",
                    "descripcion": "Descripción",
                    "stock_total_polo": "Stock total Polo",
                    "codigo_normalizado": "Código normalizado",
                }
            )
        )

    anterior = pd.DataFrame(columns=columnas)
    if stock_polo_anterior is not None and not stock_polo_anterior.empty:
        art_col = extraer_columna(stock_polo_anterior, ["Artículo", "Articulo"])
        desc_col = extraer_columna(stock_polo_anterior, ["Descripción", "Descripcion"])
        stock_col = extraer_columna(stock_polo_anterior, ["Stock total Polo", "Stock Polo Logístico", "Stock Polo", "Cantidad"])
        norm_col = extraer_columna(stock_polo_anterior, ["Código normalizado", "Codigo normalizado"])

        if art_col and stock_col:
            anterior = pd.DataFrame(
                {
                    "Artículo": stock_polo_anterior[art_col].astype(str).str.strip(),
                    "Descripción": stock_polo_anterior[desc_col].astype(str).str.strip() if desc_col else "",
                    "Stock total Polo": pd.to_numeric(stock_polo_anterior[stock_col], errors="coerce").fillna(0),
                    "Código normalizado": stock_polo_anterior[norm_col].astype(str).str.strip()
                    if norm_col
                    else stock_polo_anterior[art_col].map(normalizar_codigo),
                }
            )

    combinado = pd.concat([anterior, nuevos], ignore_index=True)
    if combinado.empty:
        return pd.DataFrame(columns=columnas)

    combinado["Stock total Polo"] = pd.to_numeric(combinado["Stock total Polo"], errors="coerce").fillna(0)
    res = (
        combinado.groupby("Código normalizado", as_index=False)
        .agg(
            **{
                "Artículo": ("Artículo", _primer_valor_no_vacio),
                "Descripción": ("Descripción", _primer_valor_no_vacio),
                "Stock total Polo": ("Stock total Polo", "sum"),
            }
        )
    )
    res["Stock total Polo"] = res["Stock total Polo"].apply(formatear_numero)
    return res[["Artículo", "Descripción", "Stock total Polo", "Código normalizado"]]


def ubicacion_polo_logistico(df_pick: pd.DataFrame, ubicaciones_anteriores: pd.DataFrame) -> pd.DataFrame:
    detalle = preparar_detalle_mudanza(df_pick)
    if not detalle.empty:
        detalle = detalle[
            [
                "Fecha/Hora",
                "Depósito origen",
                "Depósito destino",
                "Pallet",
                "Cantidad de bultos",
                "Ubicación",
                "Artículo",
                "Descripción",
                "Cantidad mudada",
                "Código normalizado",
                "Observaciones",
            ]
        ].rename(columns={"Cantidad mudada": "Cantidad"})

    if ubicaciones_anteriores is not None and not ubicaciones_anteriores.empty:
        combinado = pd.concat([ubicaciones_anteriores, detalle], ignore_index=True)
    else:
        combinado = detalle
    return combinado


def historial_mudanzas(df_pick: pd.DataFrame, historial_anterior: pd.DataFrame) -> pd.DataFrame:
    actual = preparar_detalle_mudanza(df_pick)
    if historial_anterior is not None and not historial_anterior.empty:
        return pd.concat([historial_anterior, actual], ignore_index=True)
    return actual


def generar_excel_control(
    stock_consolidado: pd.DataFrame,
    df_pick: pd.DataFrame,
    stock_polo_anterior: pd.DataFrame,
    ubicaciones_anteriores: pd.DataFrame,
    historial_anterior: pd.DataFrame,
) -> bytes:
    darkinel = stock_darkinel_actualizado(stock_consolidado, df_pick)
    polo = stock_polo_actualizado(df_pick, stock_polo_anterior)
    ubicacion = ubicacion_polo_logistico(df_pick, ubicaciones_anteriores)
    historial = historial_mudanzas(df_pick, historial_anterior)
    resumen = resumen_pallets(df_pick)
    detalle = preparar_detalle_mudanza(df_pick)

    resumen_depositos = pd.DataFrame(
        [
            {
                "Depósito": "DARKINEL",
                "Cantidad de códigos": int((pd.to_numeric(darkinel["Stock restante Darkinel"], errors="coerce").fillna(0) > 0).sum()) if not darkinel.empty else 0,
                "Unidades totales": formatear_numero(pd.to_numeric(darkinel["Stock restante Darkinel"], errors="coerce").fillna(0).sum()) if not darkinel.empty else 0,
            },
            {
                "Depósito": "POLO LOGISTICO",
                "Cantidad de códigos": int((pd.to_numeric(polo["Stock total Polo"], errors="coerce").fillna(0) > 0).sum()) if not polo.empty else 0,
                "Unidades totales": formatear_numero(pd.to_numeric(polo["Stock total Polo"], errors="coerce").fillna(0).sum()) if not polo.empty else 0,
            },
        ]
    )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        darkinel.to_excel(writer, index=False, sheet_name="STOCK_DARKINEL_ACTUALIZADO")
        polo.to_excel(writer, index=False, sheet_name="STOCK_POLO_LOGISTICO")
        ubicacion.to_excel(writer, index=False, sheet_name="UBICACION_POLO_LOGISTICO")
        historial.to_excel(writer, index=False, sheet_name="HISTORIAL_MUDANZAS")
        resumen.to_excel(writer, index=False, sheet_name="COMPOSICION_PALLETS")
        detalle.to_excel(writer, index=False, sheet_name="DETALLE_MUDANZA")
        resumen_depositos.to_excel(writer, index=False, sheet_name="RESUMEN_DEPOSITOS")

        for sheet_name in writer.book.sheetnames:
            ws = writer.book[sheet_name]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    val = "" if cell.value is None else str(cell.value)
                    max_len = max(max_len, min(len(val), 70))
                ws.column_dimensions[col_letter].width = max(max_len + 2, 12)

    return output.getvalue()


def nombre_archivo_control() -> str:
    return f"control_depositos_darkinel_polo_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"


def limpiar_mudanza_actual() -> None:
    st.session_state.pick_items = []
    st.session_state.pick_seq = 0


# -----------------------------
# Interfaz
# -----------------------------
inicializar_estado()

st.title("🔎 Lector de códigos + Mudanza Darkinel → Polo Logístico")
st.caption(
    "Busca códigos en la base, suma stock repetido, arma pallets, registra ubicación física y genera las bases actualizadas de DARKINEL y POLO LOGISTICO."
)

with st.sidebar:
    st.header("Base de stock")
    uploaded = st.file_uploader("Subí el archivo de stock de DARKINEL", type=["xls", "xlsx", "xlsm", "csv"])

    st.markdown("---")
    st.subheader("Base Polo anterior opcional")
    uploaded_polo = st.file_uploader(
        "Subí el último control generado para seguir actualizando el POLO",
        type=["xls", "xlsx", "xlsm"],
        help="Opcional. Si lo subís, la app suma esta mudanza al stock y ubicaciones ya existentes del Polo Logístico.",
    )

    st.markdown("---")
    st.subheader("Datos de mudanza")
    deposito_origen = st.text_input("Depósito origen", value="DARKINEL")
    deposito_destino = st.text_input("Depósito destino", value="POLO LOGISTICO")
    pallet_activo = st.number_input("Pallet activo", min_value=1, value=1, step=1)
    cantidad_bultos_activo = st.number_input("Cantidad de bultos del pallet", min_value=1, value=1, step=1)
    ubicacion_default = st.text_input("Ubicación base", value=f"{int(pallet_activo)}-L-", help="Ejemplo final: 1-L-3")

    st.markdown("---")
    if st.button("🧹 Vaciar mudanza actual", type="secondary"):
        limpiar_mudanza_actual()
        st.success("Mudanza actual vaciada.")
        st.rerun()

    st.markdown("---")
    st.subheader("Ejemplos reales")
    st.code(
        "Mazda: B6Y114302A  J\n"
        "Mazda: PE0110602   Y\n"
        "Kia: # 865141W200        JJ15\n"
        "Kia: 252122E820        JC25",
        language="text",
    )

if uploaded is None:
    st.info("Subí el Excel de stock de DARKINEL para empezar.")
    st.stop()

try:
    stock_df = cargar_stock(uploaded.getvalue(), uploaded.name)
except ImportError as e:
    st.error("No se pudo leer el archivo .xls porque falta la librería xlrd.")
    st.code("xlrd>=2.0.1", language="text")
    st.exception(e)
    st.stop()
except Exception as e:
    st.error("No se pudo leer el archivo de stock. Revisá que sea .xls, .xlsx o .csv válido.")
    st.exception(e)
    st.stop()

if stock_df.empty:
    st.error("No encontré artículos con cantidad mayor a cero en el archivo.")
    st.stop()

stock_consolidado = consolidar_por_codigo(stock_df)

if uploaded_polo is not None:
    stock_polo_anterior, ubicaciones_anteriores, historial_anterior = leer_base_polo_anterior(uploaded_polo.getvalue(), uploaded_polo.name)
else:
    stock_polo_anterior, ubicaciones_anteriores, historial_anterior = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_pick = pick_items_df()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Códigos con stock", f"{len(stock_consolidado):,}".replace(",", "."))
col2.metric("Stock total DARKINEL", f"{int(pd.to_numeric(stock_consolidado['cantidad'], errors='coerce').fillna(0).sum()):,}".replace(",", "."))
col3.metric("Líneas en mudanza", len(df_pick))
col4.metric("Unidades a mudar", f"{int(pd.to_numeric(df_pick.get('cantidad_mudada', pd.Series(dtype=float)), errors='coerce').fillna(0).sum()):,}".replace(",", "."))

st.markdown("---")

tab_buscar, tab_pallets, tab_bases, tab_stock = st.tabs(
    ["1) Buscar y pickear", "2) Pallets / mudanza", "3) Bases actualizadas", "4) Stock limpio"]
)

with tab_buscar:
    modo = st.radio("Modo de búsqueda", ["Un código", "Varios códigos"], horizontal=True)

    if modo == "Un código":
        codigo = st.text_input("Escaneá o digitá el código", placeholder="Ejemplo: B6Y114302A J")

        if codigo:
            exactos, info = buscar_exactos(stock_consolidado, codigo)

            with st.expander("Ver cómo interpretó el código", expanded=False):
                st.write("**Lectura original:**", info["lectura_original"])
                st.write("**Tokens limpios:**", info["tokens_limpios"])
                st.write("**Sufijos detectados:**", info["sufijos"])
                st.write("**Candidatos de búsqueda:**", info["candidatos"])

            if not exactos.empty:
                st.success(f"Encontré {len(exactos)} artículo(s) con stock consolidado.")
                st.dataframe(preparar_resultado_para_mostrar(exactos), use_container_width=True, hide_index=True)
            else:
                st.warning("No encontré coincidencia exacta con stock. Te muestro sugerencias posibles.")
                sugerencias = buscar_sugerencias(stock_consolidado, info["candidatos"])
                if sugerencias.empty:
                    st.info("No hay sugerencias para esa lectura.")
                else:
                    st.dataframe(preparar_resultado_para_mostrar(sugerencias), use_container_width=True, hide_index=True)
                exactos = sugerencias

            if not exactos.empty:
                st.subheader("Agregar a mudanza")
                opciones = []
                exactos_reset = exactos.reset_index(drop=True)
                for i, row in exactos_reset.iterrows():
                    opciones.append(f"{i + 1}) {row.get('articulo', '')} | {row.get('descripcion', '')} | Stock {row.get('cantidad', 0)}")

                opcion = st.selectbox("Artículo", opciones)
                idx = opciones.index(opcion)
                row_sel = exactos_reset.iloc[idx]

                disponible = float(row_sel["cantidad"]) - cantidad_pickeada_por_codigo(row_sel["codigo_normalizado"])
                disponible = max(disponible, 0)

                if disponible <= 0:
                    st.warning("Este código ya quedó totalmente marcado para mudanza en los pallets actuales.")
                else:
                    with st.form("form_agregar_un_codigo"):
                        c1, c2, c3, c4 = st.columns(4)
                        cantidad_mudar = c1.number_input("Cantidad a mudar", min_value=1.0, max_value=float(disponible), value=1.0, step=1.0)
                        pallet = c2.number_input("Pallet", min_value=1, value=int(pallet_activo), step=1)
                        cantidad_bultos = c3.number_input("Cantidad de bultos", min_value=1, value=int(cantidad_bultos_activo), step=1)
                        ubicacion = c4.text_input("Ubicación", value=str(ubicacion_default), placeholder="Ej: 1-L-3")
                        observaciones = st.text_input("Observaciones", placeholder="Opcional")
                        submit = st.form_submit_button("Agregar a mudanza", type="primary")

                    if submit:
                        ok, msg = agregar_item_a_mudanza(
                            lectura_original=codigo,
                            row=row_sel,
                            cantidad_mudada=cantidad_mudar,
                            pallet=pallet,
                            cantidad_bultos=cantidad_bultos,
                            ubicacion=ubicacion,
                            deposito_origen=deposito_origen,
                            deposito_destino=deposito_destino,
                            observaciones=observaciones,
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    else:
        codigos_texto = st.text_area("Pegá varios códigos, uno por línea", height=160)
        st.caption("En este modo la app busca y muestra el primer match de cada línea. Para registrar ubicación exacta, conviene agregar de a un código.")
        if st.button("Buscar varios") and codigos_texto.strip():
            filas = []
            for linea in codigos_texto.splitlines():
                linea = linea.strip()
                if not linea:
                    continue
                exactos, info = buscar_exactos(stock_consolidado, linea)
                if exactos.empty:
                    sugerencias = buscar_sugerencias(stock_consolidado, info["candidatos"], limite=1)
                    base = sugerencias
                    tipo = "Sugerencia"
                else:
                    base = exactos
                    tipo = "Exacto"
                if base.empty:
                    filas.append({"Lectura": linea, "Resultado": "Sin stock encontrado", "Artículo": "", "Descripción": "", "Stock total": ""})
                else:
                    row = base.iloc[0]
                    filas.append(
                        {
                            "Lectura": linea,
                            "Resultado": tipo,
                            "Artículo": row.get("articulo", ""),
                            "Descripción": row.get("descripcion", ""),
                            "Stock total": row.get("cantidad", ""),
                        }
                    )
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

with tab_pallets:
    st.subheader("Composición por pallet")
    st.dataframe(resumen_pallets(df_pick), use_container_width=True, hide_index=True)

    st.subheader("Detalle de mudanza")
    detalle_display = preparar_detalle_mudanza(df_pick)
    st.dataframe(detalle_display, use_container_width=True, hide_index=True)

    if not df_pick.empty:
        excel_bytes = generar_excel_control(stock_consolidado, df_pick, stock_polo_anterior, ubicaciones_anteriores, historial_anterior)
        st.download_button(
            "Descargar control actualizado Excel",
            data=excel_bytes,
            file_name=nombre_archivo_control(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

        st.download_button(
            "Descargar detalle en CSV",
            data=detalle_display.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"detalle_mudanza_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )
    else:
        st.info("Todavía no hay artículos agregados a la mudanza.")

    st.markdown("---")
    st.subheader("Corregir / quitar líneas")
    if df_pick.empty:
        st.caption("No hay líneas para quitar.")
    else:
        opciones_quitar = [f"{r.item_id}) Pallet {r.pallet} | {r.ubicacion} | {r.articulo} | Cant. {r.cantidad_mudada}" for r in df_pick.itertuples()]
        quitar = st.multiselect("Líneas para quitar", opciones_quitar)
        if st.button("Quitar líneas seleccionadas") and quitar:
            ids = {int(x.split(")", 1)[0]) for x in quitar}
            st.session_state.pick_items = [item for item in st.session_state.pick_items if int(item.get("item_id", 0)) not in ids]
            st.success("Líneas quitadas.")
            st.rerun()

with tab_bases:
    st.subheader("STOCK_DARKINEL_ACTUALIZADO")
    darkinel_actual = stock_darkinel_actualizado(stock_consolidado, df_pick)
    st.dataframe(darkinel_actual, use_container_width=True, hide_index=True)

    st.subheader("STOCK_POLO_LOGISTICO")
    polo_actual = stock_polo_actualizado(df_pick, stock_polo_anterior)
    st.dataframe(polo_actual, use_container_width=True, hide_index=True)

    st.subheader("UBICACION_POLO_LOGISTICO")
    ubicacion_actual = ubicacion_polo_logistico(df_pick, ubicaciones_anteriores)
    st.dataframe(ubicacion_actual, use_container_width=True, hide_index=True)

with tab_stock:
    st.subheader("Stock limpio y consolidado")
    st.caption("Esta tabla ya suma los códigos repetidos de la base original.")
    st.dataframe(preparar_resultado_para_mostrar(stock_consolidado), use_container_width=True, hide_index=True)

    csv_stock = preparar_resultado_para_mostrar(stock_consolidado).to_csv(index=False).encode("utf-8-sig")
    st.download_button("Descargar stock limpio CSV", data=csv_stock, file_name="stock_limpio_consolidado.csv", mime="text/csv")
