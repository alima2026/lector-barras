import io
import re
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

try:
    from reportlab.graphics.barcode import code128
    from reportlab.graphics.barcode import code39
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    REPORTLAB_DISPONIBLE = True
except ModuleNotFoundError:
    REPORTLAB_DISPONIBLE = False


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


def formatear_fila_origen(valor) -> str:
    """Convierte fila_origen a texto sin romper si ya viene como "12, 15"."""
    if pd.isna(valor):
        return ""
    try:
        fx = float(valor)
        return str(int(fx)) if fx.is_integer() else str(fx)
    except Exception:
        return str(valor).strip()


def unir_filas_origen(serie: pd.Series) -> str:
    """Une filas de origen soportando números y textos ya consolidados."""
    valores = []
    for valor in serie:
        texto = formatear_fila_origen(valor)
        if not texto:
            continue
        for parte in re.split(r"[,;/]+", texto):
            parte = parte.strip()
            if parte and parte not in valores:
                valores.append(parte)
    return ", ".join(valores)


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
        agregaciones["fila_origen"] = unir_filas_origen
    if "lineas_sumadas" in trabajo.columns:
        agregaciones["lineas_sumadas"] = lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())

    agrupado = trabajo.groupby("codigo_normalizado", as_index=False).agg(agregaciones)
    if "lineas_sumadas" not in agrupado.columns:
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

    # Migración automática: si la sesión venía de una versión anterior,
    # convertimos bultos_pallet/bultos_item a cantidad_bultos/ubicacion.
    for item in st.session_state.pick_items:
        if "cantidad_bultos" not in item:
            item["cantidad_bultos"] = item.get("bultos_pallet", 1)
        if "bulto" not in item:
            item["bulto"] = 1
        if "ubicacion" not in item:
            item["ubicacion"] = str(item.get("bultos_item", "")).strip().upper()
        if not str(item.get("ubicacion", "")).strip():
            item["ubicacion"] = "PENDIENTE"


def cantidad_pickeada_por_codigo(codigo_normalizado: str) -> float:
    total = 0.0
    for item in st.session_state.pick_items:
        if item.get("codigo_normalizado") == codigo_normalizado:
            total += float(item.get("cantidad_mudada", 0) or 0)
    return total



def normalizar_df_pick(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deja la mudanza con las columnas nuevas aunque la sesión tenga datos viejos.
    Evita errores cuando antes existían columnas como bultos_pallet o bultos_item.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    trabajo = df.copy()

    # Compatibilidad con la versión anterior de la app.
    if "cantidad_bultos" not in trabajo.columns:
        if "bultos_pallet" in trabajo.columns:
            trabajo["cantidad_bultos"] = trabajo["bultos_pallet"]
        elif "Bultos del pallet" in trabajo.columns:
            trabajo["cantidad_bultos"] = trabajo["Bultos del pallet"]
        else:
            trabajo["cantidad_bultos"] = 1

    if "ubicacion" not in trabajo.columns:
        if "bultos_item" in trabajo.columns:
            trabajo["ubicacion"] = trabajo["bultos_item"]
        elif "Bulto(s) del artículo" in trabajo.columns:
            trabajo["ubicacion"] = trabajo["Bulto(s) del artículo"]
        else:
            trabajo["ubicacion"] = ""

    defaults = {
        "fecha_hora": "",
        "deposito_origen": "DARKINEL",
        "deposito_destino": "POLO LOGISTICO",
        "pallet": 1,
        "bulto": 1,
        "lectura_scanner": "",
        "articulo": "",
        "descripcion": "",
        "estado": "",
        "unidad": "",
        "cantidad_mudada": 0,
        "stock_total": 0,
        "codigo_normalizado": "",
        "observaciones": "",
        "cantidad_recibida": None,
        "recepcion_ok": False,
        "ubicacion_recepcion": "",
        "receptor": "",
        "fecha_recepcion": "",
        "observaciones_recepcion": "",
    }
    for col, default in defaults.items():
        if col not in trabajo.columns:
            trabajo[col] = default

    trabajo["cantidad_bultos"] = pd.to_numeric(trabajo["cantidad_bultos"], errors="coerce").fillna(1).astype(int)
    trabajo["pallet"] = pd.to_numeric(trabajo["pallet"], errors="coerce").fillna(1).astype(int)
    trabajo["bulto"] = pd.to_numeric(trabajo["bulto"], errors="coerce").fillna(1).astype(int)
    trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)
    trabajo["cantidad_recibida"] = pd.to_numeric(trabajo["cantidad_recibida"], errors="coerce")
    trabajo["cantidad_recibida"] = trabajo["cantidad_recibida"].fillna(trabajo["cantidad_mudada"])
    trabajo["stock_total"] = pd.to_numeric(trabajo["stock_total"], errors="coerce").fillna(0)
    trabajo["ubicacion"] = trabajo["ubicacion"].fillna("").astype(str).str.strip().str.upper()
    trabajo.loc[trabajo["ubicacion"] == "", "ubicacion"] = "PENDIENTE"
    trabajo["ubicacion_recepcion"] = trabajo["ubicacion_recepcion"].fillna("").astype(str).str.strip().str.upper()
    trabajo["recepcion_ok"] = trabajo["recepcion_ok"].fillna(False).astype(bool)
    return trabajo

def agregar_item_a_mudanza(
    lectura_original: str,
    row: pd.Series,
    cantidad_mudada: float,
    pallet: int,
    cantidad_bultos: int,
    bulto: int,
    ubicacion: str,
    deposito_origen: str,
    deposito_destino: str,
    observaciones: str = "",
    validar_stock: bool = True,
) -> Tuple[bool, str]:
    codigo_norm = str(row.get("codigo_normalizado", ""))
    stock_total = numero_seguro(row.get("cantidad", 0), 0)
    ya_pickeado = cantidad_pickeada_por_codigo(codigo_norm)

    if cantidad_mudada <= 0:
        return False, "La cantidad a mudar tiene que ser mayor a cero."

    if validar_stock and ya_pickeado + float(cantidad_mudada) > stock_total:
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
            "bulto": int(bulto),
            "ubicacion": str(ubicacion).strip().upper() or "PENDIENTE",
            "lectura_scanner": str(lectura_original).strip(),
            "articulo": str(row.get("articulo", "")).strip(),
            "descripcion": str(row.get("descripcion", "")).strip(),
            "estado": str(row.get("estado", "")).strip(),
            "unidad": str(row.get("unidad", "")).strip(),
            "cantidad_mudada": float(cantidad_mudada),
            "stock_total": stock_total,
            "codigo_normalizado": codigo_norm,
            "observaciones": observaciones.strip(),
            "cantidad_recibida": float(cantidad_mudada),
            "recepcion_ok": False,
            "ubicacion_recepcion": "",
            "receptor": "",
            "fecha_recepcion": "",
            "observaciones_recepcion": "",
        }
    )
    return True, "Artículo agregado a la mudanza."


def actualizar_ubicacion_item(item_id: int, nueva_ubicacion: str) -> Tuple[bool, str]:
    ubicacion = str(nueva_ubicacion).strip().upper() or "PENDIENTE"
    for item in st.session_state.pick_items:
        if int(item.get("item_id", 0)) == int(item_id):
            item["ubicacion"] = ubicacion
            return True, "Ubicación actualizada."
    return False, "No encontré esa línea de mudanza."


def actualizar_cantidad_item(item_id: int, nueva_cantidad: float) -> Tuple[bool, str]:
    if nueva_cantidad <= 0:
        return False, "La cantidad a mudar tiene que ser mayor a cero."

    item_objetivo = None
    for item in st.session_state.pick_items:
        if int(item.get("item_id", 0)) == int(item_id):
            item_objetivo = item
            break

    if item_objetivo is None:
        return False, "No encontré esa línea de mudanza."

    item_objetivo["cantidad_mudada"] = float(nueva_cantidad)
    return True, "Cantidad actualizada."


def actualizar_linea_item(
    item_id: int,
    nueva_cantidad: float,
    nuevo_pallet: int,
    nueva_cantidad_bultos: int,
    nuevo_bulto: int,
    nueva_ubicacion: str,
    stock_darkinel_restante: float | None = None,
) -> Tuple[bool, str]:
    ok, msg = actualizar_cantidad_item(item_id, nueva_cantidad)
    if not ok:
        return ok, msg

    for item in st.session_state.pick_items:
        if int(item.get("item_id", 0)) == int(item_id):
            item["pallet"] = int(nuevo_pallet)
            item["cantidad_bultos"] = int(nueva_cantidad_bultos)
            item["bulto"] = int(nuevo_bulto)
            item["ubicacion"] = str(nueva_ubicacion).strip().upper() or "PENDIENTE"
            if stock_darkinel_restante is not None:
                item["stock_total"] = float(nueva_cantidad) + float(stock_darkinel_restante)
                obs = str(item.get("observaciones", "")).strip()
                marca = f"Stock real Darkinel restante: {float(stock_darkinel_restante):g}"
                item["observaciones"] = f"{obs} | {marca}".strip(" |")
            return True, "Línea actualizada."
    return False, "No encontré esa línea de mudanza."


def pick_items_df() -> pd.DataFrame:
    df = pd.DataFrame(st.session_state.pick_items)
    if df.empty:
        return df
    df = normalizar_df_pick(df)
    total_por_codigo = df.groupby("codigo_normalizado")["cantidad_mudada"].transform("sum")
    df["stock_restante_darkinel"] = df["stock_total"] - total_por_codigo
    for col in ["cantidad_mudada", "stock_total", "stock_restante_darkinel"]:
        df[col] = df[col].apply(formatear_numero)
    return df


def mudado_por_codigo(df_pick: pd.DataFrame) -> pd.DataFrame:
    if df_pick.empty:
        return pd.DataFrame(columns=["codigo_normalizado", "mudado_al_polo"])
    trabajo = normalizar_df_pick(df_pick)
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
                "Bulto",
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

    df = normalizar_df_pick(df)

    cols = [
        "fecha_hora",
        "deposito_origen",
        "deposito_destino",
        "pallet",
        "cantidad_bultos",
        "bulto",
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
            "bulto": "Bulto",
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

    trabajo = normalizar_df_pick(df)
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
    columnas_finales = [
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
    if stock_consolidado.empty and df_pick.empty:
        return pd.DataFrame(columns=columnas_finales)

    base = stock_consolidado.copy() if not stock_consolidado.empty else pd.DataFrame()
    if base.empty:
        base = pd.DataFrame(columns=["articulo", "descripcion", "estado", "unidad", "cantidad", "codigo_normalizado", "lineas_sumadas"])
    base["cantidad"] = pd.to_numeric(base["cantidad"], errors="coerce").fillna(0)

    if not df_pick.empty:
        trabajo = normalizar_df_pick(df_pick)
        manuales = trabajo[~trabajo["codigo_normalizado"].isin(base["codigo_normalizado"])].copy()
        if not manuales.empty:
            manuales_base = (
                manuales.groupby("codigo_normalizado", as_index=False)
                .agg(
                    articulo=("articulo", _primer_valor_no_vacio),
                    descripcion=("descripcion", _primer_valor_no_vacio),
                    estado=("estado", _primer_valor_no_vacio),
                    unidad=("unidad", _primer_valor_no_vacio),
                    cantidad=("stock_total", "max"),
                )
            )
            manuales_base["estado"] = manuales_base["estado"].replace("", "MANUAL")
            manuales_base["lineas_sumadas"] = 0
            base = pd.concat([base, manuales_base], ignore_index=True)

    mudado = mudado_por_codigo(df_pick)
    actualizado = base.merge(mudado, on="codigo_normalizado", how="left")
    actualizado["mudado_al_polo"] = actualizado["mudado_al_polo"].fillna(0)
    actualizado["stock_restante_darkinel"] = actualizado["cantidad"] - actualizado["mudado_al_polo"]
    actualizado["control"] = actualizado["stock_restante_darkinel"].apply(lambda x: "REVISAR: mudanza mayor al stock" if x < 0 else "OK")
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
    )[columnas_finales]


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
        trabajo = normalizar_df_pick(df_pick)
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


def preparar_recepcion_polo(df_pick: pd.DataFrame) -> pd.DataFrame:
    if df_pick.empty:
        return pd.DataFrame(
            columns=[
                "Fecha recepción",
                "Receptor",
                "OK recepción",
                "Pallet",
                "Bulto",
                "Ubicación informada",
                "Artículo",
                "Descripción",
                "Unidad",
                "Cantidad mudada",
                "Cantidad recibida",
                "Diferencia",
                "Código normalizado",
                "Observaciones recepción",
            ]
        )

    trabajo = normalizar_df_pick(df_pick)
    recepcion = trabajo.copy()
    recepcion["diferencia"] = pd.to_numeric(recepcion["cantidad_recibida"], errors="coerce").fillna(0) - pd.to_numeric(recepcion["cantidad_mudada"], errors="coerce").fillna(0)
    return recepcion[
        [
            "fecha_recepcion",
            "receptor",
            "recepcion_ok",
            "pallet",
            "bulto",
            "ubicacion_recepcion",
            "articulo",
            "descripcion",
            "unidad",
            "cantidad_mudada",
            "cantidad_recibida",
            "diferencia",
            "codigo_normalizado",
            "observaciones_recepcion",
        ]
    ].rename(
        columns={
            "fecha_recepcion": "Fecha recepción",
            "receptor": "Receptor",
            "recepcion_ok": "OK recepción",
            "pallet": "Pallet",
            "bulto": "Bulto",
            "ubicacion_recepcion": "Ubicación informada",
            "articulo": "Artículo",
            "descripcion": "Descripción",
            "unidad": "Unidad",
            "cantidad_mudada": "Cantidad mudada",
            "cantidad_recibida": "Cantidad recibida",
            "diferencia": "Diferencia",
            "codigo_normalizado": "Código normalizado",
            "observaciones_recepcion": "Observaciones recepción",
        }
    )


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
    recepcion = preparar_recepcion_polo(df_pick)

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
        recepcion.to_excel(writer, index=False, sheet_name="RECEPCION_POLO")
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


def _barcode_articulo_flowable(codigo: str):
    if not codigo:
        codigo = "SIN-CODIGO"
    return code128.Code128(codigo, barHeight=13 * mm, barWidth=0.30 * mm, humanReadable=False)


def codigo_barra_articulo(articulo: str, corregir_guion_teclado: bool = False) -> str:
    codigo = str(articulo or "").strip().upper()
    codigo = "".join(ch if ch in CODE39_PATTERNS and ch != "*" else "-" for ch in codigo)
    if corregir_guion_teclado:
        codigo = codigo.replace("-", "/")
    return codigo


CODE39_PATTERNS = {
    "0": "101001101101",
    "1": "110100101011",
    "2": "101100101011",
    "3": "110110010101",
    "4": "101001101011",
    "5": "110100110101",
    "6": "101100110101",
    "7": "101001011011",
    "8": "110100101101",
    "9": "101100101101",
    "A": "110101001011",
    "B": "101101001011",
    "C": "110110100101",
    "D": "101011001011",
    "E": "110101100101",
    "F": "101101100101",
    "G": "101010011011",
    "H": "110101001101",
    "I": "101101001101",
    "J": "101011001101",
    "K": "110101010011",
    "L": "101101010011",
    "M": "110110101001",
    "N": "101011010011",
    "O": "110101101001",
    "P": "101101101001",
    "Q": "101010110011",
    "R": "110101011001",
    "S": "101101011001",
    "T": "101011011001",
    "U": "110010101011",
    "V": "100110101011",
    "W": "110011010101",
    "X": "100101101011",
    "Y": "110010110101",
    "Z": "100110110101",
    "-": "100101011011",
    ".": "110010101101",
    " ": "100110101101",
    "$": "100100100101",
    "/": "100100101001",
    "+": "100101001001",
    "%": "101001001001",
    "*": "100101101101",
}


def _html_escape(valor) -> str:
    texto = "" if valor is None else str(valor)
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _codigo_barra_code39_svg(codigo: str, height: int = 54, module: int = 2) -> str:
    limpio = codigo_barra_articulo(codigo) or "SIN-CODIGO"
    completo = f"*{limpio}*"
    width = (len(completo) * 13 + max(len(completo) - 1, 0)) * module
    x = 0
    rects = []
    for idx, ch in enumerate(completo):
        pattern = CODE39_PATTERNS.get(ch, CODE39_PATTERNS["-"])
        for pos, bit in enumerate(pattern):
            if bit == "1":
                rects.append(f'<rect x="{x}" y="0" width="{module}" height="{height}" />')
            x += module
        if idx < len(completo) - 1:
            x += module
    return f'<svg class="barcode" viewBox="0 0 {width} {height}" preserveAspectRatio="none">{"".join(rects)}</svg>'


def generar_html_pallet_bultos(df_pick: pd.DataFrame, pallet: int, modo: str = "pallet", corregir_guion_teclado: bool = False) -> bytes:
    trabajo = normalizar_df_pick(df_pick)
    if trabajo.empty:
        return b""

    trabajo = trabajo[pd.to_numeric(trabajo["pallet"], errors="coerce").fillna(0).astype(int) == int(pallet)].copy()
    if trabajo.empty:
        return b""

    trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)
    cantidad_bultos = int(pd.to_numeric(trabajo["cantidad_bultos"], errors="coerce").fillna(1).max())
    unidades = formatear_numero(trabajo["cantidad_mudada"].sum())
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    paginas = list(range(1, cantidad_bultos + 1)) if modo == "bultos" else [None]

    pages = []
    for bulto in paginas:
        trabajo_pagina = trabajo[trabajo["bulto"] == int(bulto)].copy() if bulto is not None else trabajo
        subtitulo = f"BULTO {bulto} DE {cantidad_bultos}" if bulto is not None else f"BULTOS: {cantidad_bultos}"
        filas_html = []
        for r in trabajo_pagina.sort_values(["articulo", "descripcion"]).itertuples():
            articulo = str(getattr(r, "articulo", "")).strip()
            codigo_barra = codigo_barra_articulo(articulo, corregir_guion_teclado)
            descripcion = str(getattr(r, "descripcion", "")).strip()
            cantidad = formatear_numero(getattr(r, "cantidad_mudada", 0))
            filas_html.append(
                "<tr>"
                f"<td class='art'>{_html_escape(articulo)}</td>"
                f"<td>{_html_escape(descripcion)}</td>"
                f"<td class='cant'>{_html_escape(cantidad)}</td>"
                f"<td class='bar'>{_codigo_barra_code39_svg(codigo_barra)}<div>{_html_escape(articulo)}</div></td>"
                "</tr>"
            )
        if not filas_html:
            filas_html.append("<tr><td colspan='4' class='empty'>Sin articulos cargados para este bulto</td></tr>")

        pages.append(
            f"""
            <section class="page">
                <header>
                    <div class="title">PALLET {int(pallet)}</div>
                    <div class="meta">
                        <strong>{subtitulo}</strong><br>
                        Unidades: {unidades}<br>
                        Fecha: {_html_escape(fecha)}
                    </div>
                </header>
                <table>
                    <thead>
                        <tr><th>Articulo</th><th>Descripcion</th><th>Cant.</th><th>Codigo de barras</th></tr>
                    </thead>
                    <tbody>{''.join(filas_html)}</tbody>
                </table>
            </section>
            """
        )

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Pallet {int(pallet)} - codigos de barras</title>
        <style>
            @page {{ size: A4; margin: 10mm; }}
            * {{ box-sizing: border-box; }}
            body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #111; }}
            .page {{ min-height: 277mm; page-break-after: always; padding: 0; }}
            .page:last-child {{ page-break-after: auto; }}
            header {{ display: grid; grid-template-columns: 1fr 1fr; border: 2px solid #111; background: #f2f2f2; margin-bottom: 8mm; }}
            .title {{ font-size: 34px; font-weight: 800; padding: 8mm; display: flex; align-items: center; }}
            .meta {{ font-size: 15px; line-height: 1.45; padding: 8mm; border-left: 1px solid #111; }}
            table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
            th {{ background: #111; color: #fff; text-align: left; font-size: 12px; padding: 5px; }}
            td {{ border: 1px solid #bbb; padding: 5px; vertical-align: middle; font-size: 11px; overflow-wrap: anywhere; }}
            .art {{ width: 24%; font-weight: 700; }}
            .cant {{ width: 8%; text-align: center; font-weight: 700; }}
            .bar {{ width: 34%; text-align: center; font-size: 10px; }}
            .barcode {{ display: block; width: 100%; height: 48px; fill: #000; margin-bottom: 3px; }}
            .empty {{ text-align: center; padding: 18px; color: #666; }}
            @media print {{ .page {{ break-after: page; }} .page:last-child {{ break-after: auto; }} }}
        </style>
    </head>
    <body>{''.join(pages)}</body>
    </html>
    """
    return html.encode("utf-8")


def generar_pdf_pallet_bultos(df_pick: pd.DataFrame, pallet: int, modo: str = "pallet", corregir_guion_teclado: bool = False) -> bytes:
    if not REPORTLAB_DISPONIBLE:
        return b""

    trabajo = normalizar_df_pick(df_pick)
    if trabajo.empty:
        return b""

    trabajo = trabajo[pd.to_numeric(trabajo["pallet"], errors="coerce").fillna(0).astype(int) == int(pallet)].copy()
    if trabajo.empty:
        return b""

    trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)
    cantidad_bultos = int(pd.to_numeric(trabajo["cantidad_bultos"], errors="coerce").fillna(1).max())
    unidades = formatear_numero(trabajo["cantidad_mudada"].sum())
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    styles = getSampleStyleSheet()
    barcode_text_style = styles["Normal"].clone("BarcodeText")
    barcode_text_style.alignment = 1
    story = []

    paginas = list(range(1, cantidad_bultos + 1)) if modo == "bultos" else [None]

    for idx, bulto in enumerate(paginas):
        titulo = f"PALLET {int(pallet)}"
        subtitulo = f"BULTO {bulto} DE {cantidad_bultos}" if bulto is not None else f"BULTOS: {cantidad_bultos}"

        header = Table(
            [
                [
                    Paragraph(f"<b>{titulo}</b>", styles["Title"]),
                    Paragraph(f"<b>{subtitulo}</b><br/>Unidades: {unidades}<br/>Fecha: {fecha}", styles["Normal"]),
                ]
            ],
            colWidths=[95 * mm, 95 * mm],
        )
        header.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 1.2, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(header)
        story.append(Spacer(1, 6 * mm))

        trabajo_pagina = trabajo[trabajo["bulto"] == int(bulto)].copy() if bulto is not None else trabajo
        rows = [["Articulo", "Descripcion", "Cant.", "Codigo de barras"]]
        for r in trabajo_pagina.sort_values(["articulo", "descripcion"]).itertuples():
            articulo = str(getattr(r, "articulo", "")).strip()
            codigo_barra = codigo_barra_articulo(articulo, corregir_guion_teclado)
            descripcion = str(getattr(r, "descripcion", "")).strip()
            cantidad = formatear_numero(getattr(r, "cantidad_mudada", 0))
            rows.append(
                [
                    Paragraph(articulo, styles["Normal"]),
                    Paragraph(descripcion[:80], styles["Normal"]),
                    Paragraph(str(cantidad), styles["Normal"]),
                    [_barcode_articulo_flowable(codigo_barra), Paragraph(articulo, barcode_text_style)],
                ]
            )

        if len(rows) == 1:
            rows.append(["", "Sin articulos cargados para este bulto", "", ""])

        tabla = Table(rows, colWidths=[33 * mm, 62 * mm, 15 * mm, 80 * mm], repeatRows=1)
        tabla.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.black),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (3, 1), (3, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(tabla)

        if idx < len(paginas) - 1:
            story.append(PageBreak())

    doc.build(story)
    return output.getvalue()


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
    bulto_activo = st.number_input("Bulto activo", min_value=1, max_value=int(cantidad_bultos_activo), value=1, step=1)
    ubicacion_default = st.text_input(
        "Ubicación base opcional",
        value="",
        help="Podés dejarla vacía al cargar la mudanza y completarla cuando llegue al Polo. Ejemplo final: 1-L-3",
    )

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

tab_buscar, tab_pallets, tab_recepcion, tab_bases, tab_stock = st.tabs(
    ["1) Buscar y pickear", "2) Pallets / mudanza", "3) Recepción Polo", "4) Bases actualizadas", "5) Stock limpio"]
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
                        c1, c2, c3, c4, c5 = st.columns(5)
                        cantidad_mudar = c1.number_input("Cantidad a mudar", min_value=1.0, value=1.0, step=1.0)
                        pallet = c2.number_input("Pallet", min_value=1, value=int(pallet_activo), step=1)
                        cantidad_bultos = c3.number_input("Cantidad de bultos", min_value=1, value=int(cantidad_bultos_activo), step=1)
                        bulto = c4.number_input("Bulto", min_value=1, max_value=int(cantidad_bultos), value=min(int(bulto_activo), int(cantidad_bultos)), step=1)
                        ubicacion = c5.text_input("Ubicación en Polo", value=str(ubicacion_default), placeholder="Pendiente / Ej: 1-L-3")
                        observaciones = st.text_input("Observaciones", placeholder="Opcional")
                        submit = st.form_submit_button("Agregar a mudanza", type="primary")

                    if submit:
                        ok, msg = agregar_item_a_mudanza(
                            lectura_original=codigo,
                            row=row_sel,
                            cantidad_mudada=cantidad_mudar,
                            pallet=pallet,
                            cantidad_bultos=cantidad_bultos,
                            bulto=bulto,
                            ubicacion=ubicacion,
                            deposito_origen=deposito_origen,
                            deposito_destino=deposito_destino,
                            observaciones=observaciones,
                            validar_stock=False,
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

            if exactos.empty:
                st.subheader("Agregar articulo manual")
                st.caption("Usalo cuando el articulo no existe en el Excel/base cargada. No descuenta stock de DARKINEL, pero si entra a la mudanza y al POLO.")
                with st.form("form_agregar_manual"):
                    m1, m2, m3 = st.columns([1.2, 2, 0.8])
                    articulo_manual = m1.text_input("Articulo", value=str(codigo).strip().upper())
                    descripcion_manual = m2.text_input("Descripcion", value="")
                    unidad_manual = m3.text_input("Unidad", value="uni")

                    m4, m5, m6, m7, m8, m9 = st.columns(6)
                    cantidad_manual = m4.number_input("Cantidad a mudar", min_value=1.0, value=1.0, step=1.0, key="cantidad_manual")
                    stock_darkinel_manual = m5.number_input("Queda en Darkinel", min_value=0.0, value=0.0, step=1.0, key="stock_darkinel_manual")
                    pallet_manual = m6.number_input("Pallet", min_value=1, value=int(pallet_activo), step=1, key="pallet_manual")
                    cantidad_bultos_manual = m7.number_input("Cantidad de bultos", min_value=1, value=int(cantidad_bultos_activo), step=1, key="cantidad_bultos_manual")
                    bulto_manual = m8.number_input("Bulto", min_value=1, max_value=int(cantidad_bultos_manual), value=min(int(bulto_activo), int(cantidad_bultos_manual)), step=1, key="bulto_manual")
                    ubicacion_manual = m9.text_input("Ubicacion", value=str(ubicacion_default), placeholder="Pendiente / Ej: 1-L-3")
                    observaciones_manual = st.text_input("Observaciones manual", value="Articulo agregado manualmente")
                    submit_manual = st.form_submit_button("Agregar manual a mudanza", type="primary")

                if submit_manual:
                    articulo_manual = str(articulo_manual).strip().upper()
                    if not articulo_manual:
                        st.error("El articulo manual no puede quedar vacio.")
                    else:
                        row_manual = pd.Series(
                            {
                                "articulo": articulo_manual,
                                "descripcion": str(descripcion_manual).strip() or "SIN DESCRIPCION",
                                "estado": "MANUAL",
                                "unidad": str(unidad_manual).strip() or "uni",
                                "cantidad": float(cantidad_manual) + float(stock_darkinel_manual),
                                "codigo_normalizado": normalizar_codigo(articulo_manual),
                            }
                        )
                        ok, msg = agregar_item_a_mudanza(
                            lectura_original=codigo,
                            row=row_manual,
                            cantidad_mudada=cantidad_manual,
                            pallet=pallet_manual,
                            cantidad_bultos=cantidad_bultos_manual,
                            bulto=bulto_manual,
                            ubicacion=ubicacion_manual,
                            deposito_origen=deposito_origen,
                            deposito_destino=deposito_destino,
                            observaciones=observaciones_manual,
                            validar_stock=False,
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    else:
        codigos_texto = st.text_area("Pegá varios códigos, uno por línea", height=160)
        st.caption("En este modo la app busca y muestra el primer match de cada línea. Para registrar ubicación exacta, conviene agregar de a un código.")
        col_buscar_varios, col_agregar_varios = st.columns([1, 2])
        buscar_varios = col_buscar_varios.button("Buscar varios")
        agregar_varios = col_agregar_varios.button("Buscar y agregar a mudanza", type="primary")
        if (buscar_varios or agregar_varios) and codigos_texto.strip():
            filas = []
            agregados = 0
            errores = []
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
                    if agregar_varios:
                        ok, msg = agregar_item_a_mudanza(
                            lectura_original=linea,
                            row=row,
                            cantidad_mudada=1,
                            pallet=int(pallet_activo),
                            cantidad_bultos=int(cantidad_bultos_activo),
                            bulto=int(bulto_activo),
                            ubicacion=ubicacion_default,
                            deposito_origen=deposito_origen,
                            deposito_destino=deposito_destino,
                            observaciones="Carga masiva",
                            validar_stock=False,
                        )
                        if ok:
                            agregados += 1
                        else:
                            errores.append(f"{linea}: {msg}")
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
            if agregar_varios:
                if agregados:
                    st.success(f"Agregue {agregados} articulo(s) a la mudanza.")
                if errores:
                    st.warning("Algunas lineas no se pudieron agregar:")
                    st.write(errores)
                if agregados:
                    st.rerun()

with tab_pallets:
    st.subheader("Composición por pallet")
    st.dataframe(resumen_pallets(df_pick), use_container_width=True, hide_index=True)

    st.subheader("Detalle de mudanza")
    detalle_display = preparar_detalle_mudanza(df_pick)
    if df_pick.empty:
        st.dataframe(detalle_display, use_container_width=True, hide_index=True)
    else:
        detalle_editor = normalizar_df_pick(df_pick)[
            [
                "item_id",
                "fecha_hora",
                "deposito_origen",
                "deposito_destino",
                "pallet",
                "cantidad_bultos",
                "bulto",
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
        ].rename(
            columns={
                "item_id": "ID",
                "fecha_hora": "Fecha/Hora",
                "deposito_origen": "Depósito origen",
                "deposito_destino": "Depósito destino",
                "pallet": "Pallet",
                "cantidad_bultos": "Cantidad de bultos",
                "bulto": "Bulto",
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
        detalle_editado = st.data_editor(
            detalle_editor,
            use_container_width=True,
            hide_index=True,
            disabled=["ID", "Stock original Darkinel", "Stock restante Darkinel"],
            num_rows="fixed",
            key="detalle_mudanza_editor",
        )
        if st.button("Guardar cambios del detalle"):
            por_id = {int(item.get("item_id", 0)): item for item in st.session_state.pick_items}
            for row in detalle_editado.to_dict("records"):
                item_id = int(row.get("ID", 0))
                item = por_id.get(item_id)
                if not item:
                    continue
                item["fecha_hora"] = str(row.get("Fecha/Hora", "")).strip()
                item["deposito_origen"] = str(row.get("Depósito origen", "")).strip() or "DARKINEL"
                item["deposito_destino"] = str(row.get("Depósito destino", "")).strip() or "POLO LOGISTICO"
                item["pallet"] = entero_seguro(row.get("Pallet", 1), 1)
                item["cantidad_bultos"] = entero_seguro(row.get("Cantidad de bultos", 1), 1)
                item["bulto"] = max(1, min(entero_seguro(row.get("Bulto", 1), 1), int(item["cantidad_bultos"])))
                item["ubicacion"] = str(row.get("Ubicación", "")).strip().upper() or "PENDIENTE"
                item["lectura_scanner"] = str(row.get("Lectura scanner", "")).strip()
                item["articulo"] = str(row.get("Artículo", "")).strip()
                item["descripcion"] = str(row.get("Descripción", "")).strip()
                item["unidad"] = str(row.get("Unidad", "")).strip()
                item["cantidad_mudada"] = numero_seguro(row.get("Cantidad mudada", 0), 0)
                item["codigo_normalizado"] = str(row.get("Código normalizado", "")).strip() or normalizar_codigo(item["articulo"])
                item["observaciones"] = str(row.get("Observaciones", "")).strip()
            st.success("Detalle actualizado.")
            st.rerun()

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

        st.markdown("---")
        st.subheader("Hoja A4 con codigos de barras")
        pallets_disponibles = sorted(pd.to_numeric(df_pick["pallet"], errors="coerce").dropna().astype(int).unique().tolist())
        c_pdf1, c_pdf2, c_pdf3 = st.columns([1, 1, 1.4])
        pallet_pdf = c_pdf1.selectbox("Pallet para imprimir", pallets_disponibles)
        modo_pdf = c_pdf2.radio("Formato", ["Una hoja por pallet", "Una hoja por bulto"], horizontal=True)
        corregir_guion_teclado = c_pdf3.checkbox(
            "Corregir guion del lector",
            value=True,
            help="Dejalo marcado si al escanear el guion sale como apostrofe. Si el lector ya lee bien los guiones, desmarcalo.",
        )
        modo_pdf_interno = "bultos" if modo_pdf == "Una hoja por bulto" else "pallet"
        if REPORTLAB_DISPONIBLE:
            pdf_bytes = generar_pdf_pallet_bultos(df_pick, pallet_pdf, modo_pdf_interno, corregir_guion_teclado)
            st.download_button(
                "Descargar A4 pallet / bultos PDF",
                data=pdf_bytes,
                file_name=f"pallet_{int(pallet_pdf)}_{modo_pdf_interno}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                type="primary",
            )
        else:
            html_bytes = generar_html_pallet_bultos(df_pick, pallet_pdf, modo_pdf_interno, corregir_guion_teclado)
            st.warning("Reportlab no esta instalado en Streamlit Cloud. Mientras tanto podes descargar esta hoja HTML, abrirla e imprimirla en A4 o guardarla como PDF.")
            st.download_button(
                "Descargar A4 imprimible HTML",
                data=html_bytes,
                file_name=f"pallet_{int(pallet_pdf)}_{modo_pdf_interno}_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                type="primary",
            )
    else:
        st.info("Todavía no hay artículos agregados a la mudanza.")

    st.markdown("---")
    st.subheader("Completar ubicación al llegar al Polo")
    if df_pick.empty:
        st.caption("No hay líneas pendientes para ubicar.")
    else:
        opciones_ubicacion = [
            f"{r.item_id}) Pallet {r.pallet} | Bulto {r.bulto} | {r.ubicacion} | {r.articulo} | Cant. {r.cantidad_mudada}"
            for r in df_pick.itertuples()
        ]
        linea_ubicacion = st.selectbox("Línea a actualizar", opciones_ubicacion)
        id_ubicacion = int(linea_ubicacion.split(")", 1)[0])
        ubicacion_actual = str(df_pick.loc[df_pick["item_id"] == id_ubicacion, "ubicacion"].iloc[0])
        nueva_ubicacion = st.text_input("Nueva ubicación en Polo", value="" if ubicacion_actual == "PENDIENTE" else ubicacion_actual, placeholder="Ej: 1-L-3")
        if st.button("Guardar ubicación"):
            ok, msg = actualizar_ubicacion_item(id_ubicacion, nueva_ubicacion)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    st.markdown("---")
    st.subheader("Corregir / quitar líneas")
    if df_pick.empty:
        st.caption("No hay líneas para corregir.")
    else:
        opciones_corregir = [f"{r.item_id}) Pallet {r.pallet} | Bulto {r.bulto} | {r.ubicacion} | {r.articulo} | Cant. {r.cantidad_mudada}" for r in df_pick.itertuples()]

        st.markdown("**Modificar línea**")
        linea_cantidad = st.selectbox("Línea para modificar", opciones_corregir, key="linea_modificar_cantidad")
        id_cantidad = int(linea_cantidad.split(")", 1)[0])
        fila_editar = df_pick.loc[df_pick["item_id"] == id_cantidad].iloc[0]
        cantidad_actual = float(pd.to_numeric(fila_editar["cantidad_mudada"], errors="coerce"))
        pallet_actual = int(pd.to_numeric(fila_editar["pallet"], errors="coerce"))
        cantidad_bultos_actual = int(pd.to_numeric(fila_editar["cantidad_bultos"], errors="coerce"))
        bulto_actual = int(pd.to_numeric(fila_editar["bulto"], errors="coerce"))
        ubicacion_actual_editar = str(fila_editar["ubicacion"])
        stock_total_linea = float(pd.to_numeric(fila_editar["stock_total"], errors="coerce"))
        stock_restante_sugerido = max(stock_total_linea - cantidad_actual, 0)

        with st.form("form_modificar_linea"):
            e1, e2, e3, e4, e5 = st.columns(5)
            nueva_cantidad = e1.number_input("Cantidad a mudar", min_value=1.0, value=cantidad_actual, step=1.0)
            nuevo_pallet = e2.number_input("Pallet", min_value=1, value=pallet_actual, step=1)
            nueva_cantidad_bultos = e3.number_input("Cantidad de bultos", min_value=1, value=cantidad_bultos_actual, step=1)
            nuevo_bulto = e4.number_input("Bulto", min_value=1, max_value=int(nueva_cantidad_bultos), value=min(bulto_actual, int(nueva_cantidad_bultos)), step=1)
            nueva_ubicacion_editar = e5.text_input("Ubicación", value="" if ubicacion_actual_editar == "PENDIENTE" else ubicacion_actual_editar)

            aplicar_stock_real = st.checkbox(
                "Actualizar stock real que queda en Darkinel",
                value=str(fila_editar.get("estado", "")).strip().upper() == "MANUAL",
                help="Usalo si el Excel no tiene el stock real o si el artículo fue creado manualmente.",
            )
            stock_darkinel_restante = st.number_input(
                "Cantidad que queda en Darkinel",
                min_value=0.0,
                value=float(stock_restante_sugerido),
                step=1.0,
                disabled=not aplicar_stock_real,
            )
            guardar_linea = st.form_submit_button("Guardar cambios de línea", type="primary")

        if guardar_linea:
            ok, msg = actualizar_linea_item(
                id_cantidad,
                nueva_cantidad,
                nuevo_pallet,
                nueva_cantidad_bultos,
                nuevo_bulto,
                nueva_ubicacion_editar,
                stock_darkinel_restante if aplicar_stock_real else None,
            )
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

        st.markdown("**Quitar líneas**")
        opciones_quitar = [f"{r.item_id}) Pallet {r.pallet} | Bulto {r.bulto} | {r.ubicacion} | {r.articulo} | Cant. {r.cantidad_mudada}" for r in df_pick.itertuples()]
        quitar = st.multiselect("Líneas para quitar", opciones_quitar)
        if st.button("Quitar líneas seleccionadas") and quitar:
            ids = {int(x.split(")", 1)[0]) for x in quitar}
            st.session_state.pick_items = [item for item in st.session_state.pick_items if int(item.get("item_id", 0)) not in ids]
            st.success("Líneas quitadas.")
            st.rerun()

with tab_recepcion:
    st.subheader("Recepción en Polo")
    if df_pick.empty:
        st.info("Todavía no hay artículos en la mudanza para recibir.")
    else:
        st.caption("El receptor confirma cantidades y ubicación. Al guardar, la ubicación informada actualiza la mudanza y las bases.")
        recepcion_editor = normalizar_df_pick(df_pick)[
            [
                "item_id",
                "pallet",
                "bulto",
                "articulo",
                "descripcion",
                "unidad",
                "cantidad_mudada",
                "cantidad_recibida",
                "recepcion_ok",
                "ubicacion_recepcion",
                "receptor",
                "fecha_recepcion",
                "observaciones_recepcion",
            ]
        ].rename(
            columns={
                "item_id": "ID",
                "pallet": "Pallet",
                "bulto": "Bulto",
                "articulo": "Artículo",
                "descripcion": "Descripción",
                "unidad": "Unidad",
                "cantidad_mudada": "Cantidad mudada",
                "cantidad_recibida": "Cantidad recibida",
                "recepcion_ok": "OK recepción",
                "ubicacion_recepcion": "Ubicación Polo",
                "receptor": "Recibido por",
                "fecha_recepcion": "Fecha recepción",
                "observaciones_recepcion": "Observaciones recepción",
            }
        )

        recepcion_editada = st.data_editor(
            recepcion_editor,
            use_container_width=True,
            hide_index=True,
            disabled=["ID", "Pallet", "Bulto", "Artículo", "Descripción", "Unidad", "Cantidad mudada"],
            num_rows="fixed",
            key="recepcion_polo_editor",
        )

        if st.button("Guardar recepción Polo", type="primary"):
            por_id = {int(item.get("item_id", 0)): item for item in st.session_state.pick_items}
            ahora_recepcion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for row in recepcion_editada.to_dict("records"):
                item_id = int(row.get("ID", 0))
                item = por_id.get(item_id)
                if not item:
                    continue
                ubicacion_polo = str(row.get("Ubicación Polo", "")).strip().upper()
                item["cantidad_recibida"] = numero_seguro(row.get("Cantidad recibida", item.get("cantidad_mudada", 0)), 0)
                item["recepcion_ok"] = bool(row.get("OK recepción", False))
                item["ubicacion_recepcion"] = ubicacion_polo
                if ubicacion_polo:
                    item["ubicacion"] = ubicacion_polo
                item["receptor"] = str(row.get("Recibido por", "")).strip()
                item["fecha_recepcion"] = str(row.get("Fecha recepción", "")).strip() or ahora_recepcion
                item["observaciones_recepcion"] = str(row.get("Observaciones recepción", "")).strip()
            st.success("Recepción guardada y ubicación actualizada.")
            st.rerun()

        recepcion_actual = preparar_recepcion_polo(df_pick)
        if not recepcion_actual.empty:
            pendientes = int((~recepcion_actual["OK recepción"].astype(bool)).sum())
            diferencias = int((pd.to_numeric(recepcion_actual["Diferencia"], errors="coerce").fillna(0) != 0).sum())
            r1, r2, r3 = st.columns(3)
            r1.metric("Líneas recibidas OK", len(recepcion_actual) - pendientes)
            r2.metric("Líneas pendientes", pendientes)
            r3.metric("Diferencias cantidad", diferencias)

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
