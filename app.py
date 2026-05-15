import io
import json
import re
import sqlite3
import base64
import hashlib
import uuid
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import quote

import pandas as pd
import streamlit as st

try:
    import requests

    REQUESTS_DISPONIBLE = True
except ModuleNotFoundError:
    REQUESTS_DISPONIBLE = False

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
# APP: Lector Mazda/Kia/Multimarca contra stock + mudanza de depÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sitos
# Autor: preparado para Carlos / Alimatico
# ==========================================================

st.set_page_config(
    page_title="Lector codigos Mazda - Stock y depositos",
    page_icon="ðŸ”Ž",
    layout="wide",
)


# -----------------------------
# NormalizaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n de cÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digos
# -----------------------------
DB_PATH = Path(__file__).resolve().parent / "data" / "mudanza_estado.sqlite"
CLOUD_TABLE = "estado_app"


def ahora_texto() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def supabase_config() -> Dict[str, str]:
    try:
        cfg = st.secrets.get("supabase", {})
    except Exception:
        cfg = {}
    url = str(cfg.get("url", "")).strip().rstrip("/")
    key = str(cfg.get("service_role_key") or cfg.get("anon_key") or cfg.get("key", "")).strip()
    table = str(cfg.get("table", CLOUD_TABLE)).strip() or CLOUD_TABLE
    return {"url": url, "key": key, "table": table}


def nube_disponible() -> bool:
    cfg = supabase_config()
    return bool(REQUESTS_DISPONIBLE and cfg["url"] and cfg["key"])


def supabase_headers(prefer: str = "") -> Dict[str, str]:
    cfg = supabase_config()
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_endpoint(clave: str = "") -> str:
    cfg = supabase_config()
    base = f"{cfg['url']}/rest/v1/{cfg['table']}"
    if clave:
        return f"{base}?clave=eq.{quote(clave)}"
    return base


def guardar_estado_nube(clave: str, valor) -> bool:
    if not nube_disponible():
        return False
    try:
        payload = {
            "clave": clave,
            "valor": json.dumps(valor, ensure_ascii=False, default=str),
            "actualizado_en": ahora_texto(),
        }
        resp = requests.post(
            supabase_endpoint(),
            headers=supabase_headers("resolution=merge-duplicates"),
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


def cargar_estado_nube(clave: str, defecto):
    if not nube_disponible():
        return defecto
    try:
        resp = requests.get(
            f"{supabase_endpoint(clave)}&select=valor",
            headers=supabase_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return defecto
        return json.loads(rows[0]["valor"])
    except Exception:
        return defecto


def fecha_estado_nube(clave: str) -> str:
    if not nube_disponible():
        return ""
    try:
        resp = requests.get(
            f"{supabase_endpoint(clave)}&select=actualizado_en",
            headers=supabase_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
        return "" if not rows else str(rows[0].get("actualizado_en", ""))
    except Exception:
        return ""


def conectar_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS estado_app (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            actualizado_en TEXT NOT NULL
        )
        """
    )
    return conn


def guardar_estado_db(clave: str, valor) -> None:
    try:
        payload = json.dumps(valor, ensure_ascii=False, default=str)
        ahora = ahora_texto()
        with conectar_db() as conn:
            conn.execute(
                """
                INSERT INTO estado_app (clave, valor, actualizado_en)
                VALUES (?, ?, ?)
                ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, actualizado_en = excluded.actualizado_en
                """,
                (clave, payload, ahora),
            )
    except Exception:
        pass
    guardar_estado_nube(clave, valor)


def cargar_estado_db(clave: str, defecto):
    estado_nube = cargar_estado_nube(clave, None)
    if estado_nube is not None:
        return estado_nube
    try:
        with conectar_db() as conn:
            row = conn.execute("SELECT valor FROM estado_app WHERE clave = ?", (clave,)).fetchone()
        if not row:
            return defecto
        return json.loads(row[0])
    except Exception:
        return defecto


def fecha_estado_db(clave: str) -> str:
    fecha_nube = fecha_estado_nube(clave)
    if fecha_nube:
        return fecha_nube
    try:
        with conectar_db() as conn:
            row = conn.execute("SELECT actualizado_en FROM estado_app WHERE clave = ?", (clave,)).fetchone()
        return "" if not row else str(row[0])
    except Exception:
        return ""


def firma_item_mudanza(item: dict) -> str:
    campos = [
        "fecha_hora", "deposito_origen", "deposito_destino", "pallet", "cantidad_bultos", "bulto",
        "lectura_scanner", "articulo", "descripcion", "cantidad_mudada", "codigo_normalizado", "ubicacion",
        "observaciones",
    ]
    base = "|".join(str(item.get(c, "")).strip() for c in campos)
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()


def fusionar_items_mudanza(items_nube: list, items_locales: list) -> list:
    fusionados = []
    vistos = set()
    for origen in (items_nube or [], items_locales or []):
        for item in origen:
            if not isinstance(item, dict):
                continue
            clave = str(item.get("item_uid", "")).strip() or firma_item_mudanza(item)
            if clave in vistos:
                for i, existente in enumerate(fusionados):
                    clave_existente = str(existente.get("item_uid", "")).strip() or firma_item_mudanza(existente)
                    if clave_existente == clave:
                        fusionados[i] = item
                        break
            else:
                vistos.add(clave)
                fusionados.append(item)
    return fusionados


def guardar_mudanza_actual_db(fusionar_con_nube: bool = True) -> None:
    pick_items = st.session_state.get("pick_items", [])
    pick_seq = st.session_state.get("pick_seq", 0)
    if fusionar_con_nube and nube_disponible():
        estado_nube = cargar_estado_nube("mudanza_actual", {"pick_items": [], "pick_seq": 0})
        if isinstance(estado_nube, dict):
            pick_items = fusionar_items_mudanza(estado_nube.get("pick_items", []), pick_items)
            pick_seq = max(
                int(estado_nube.get("pick_seq", 0) or 0),
                int(pick_seq or 0),
                max([int(x.get("item_id", 0) or 0) for x in pick_items if isinstance(x, dict)] or [0]),
            )
            st.session_state.pick_items = pick_items
            st.session_state.pick_seq = pick_seq
    guardar_estado_db(
        "mudanza_actual",
        {
            "pick_items": pick_items,
            "pick_seq": pick_seq,
        },
    )


def guardar_salidas_polo_db() -> None:
    guardar_estado_db("salidas_polo", {"salidas": st.session_state.get("salidas_polo", []), "salida_seq": st.session_state.get("salida_seq", 0)})


def cargar_salidas_polo_db() -> Dict[str, object]:
    estado = cargar_estado_db("salidas_polo", {"salidas": [], "salida_seq": 0})
    if not isinstance(estado, dict):
        return {"salidas": [], "salida_seq": 0}
    estado.setdefault("salidas", [])
    estado.setdefault("salida_seq", 0)
    return estado


def cargar_mudanza_actual_db() -> Dict[str, object]:
    estado = cargar_estado_db("mudanza_actual", {"pick_items": [], "pick_seq": 0})
    if not isinstance(estado, dict):
        return {"pick_items": [], "pick_seq": 0}
    estado.setdefault("pick_items", [])
    estado.setdefault("pick_seq", 0)
    return estado


def guardar_archivo_estado(clave: str, nombre: str, contenido: bytes) -> None:
    guardar_estado_db(
        clave,
        {
            "nombre": nombre,
            "contenido_b64": base64.b64encode(contenido).decode("ascii"),
        },
    )


def cargar_archivo_estado(clave: str) -> Dict[str, object]:
    estado = cargar_estado_db(clave, {})
    if not isinstance(estado, dict) or not estado.get("contenido_b64"):
        return {}
    try:
        return {
            "nombre": str(estado.get("nombre", "")),
            "contenido": base64.b64decode(str(estado["contenido_b64"])),
        }
    except Exception:
        return {}


def firma_archivo(nombre: str, contenido: bytes) -> str:
    return f"{nombre}:{len(contenido)}:{hashlib.sha256(contenido).hexdigest()}"


def guardar_archivo_si_cambio(clave: str, nombre: str, contenido: bytes) -> None:
    session_key = f"firma_{clave}"
    firma = firma_archivo(nombre, contenido)
    if st.session_state.get(session_key) != firma:
        guardar_archivo_estado(clave, nombre, contenido)
        st.session_state[session_key] = firma


def normalizar_codigo(valor) -> str:
    """
    Convierte cualquier cÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo a una forma comparable:
    - MayÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºsculas
    - Sin espacios
    - Sin guiones
    - Sin asteriscos
    - Sin sÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­mbolos raros del lector: ', ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡, ., #, etc.
    """
    if pd.isna(valor):
        return ""
    texto = str(valor).upper().strip().replace("ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“", "N")
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


def normalizar_bultos_item(valor, defecto: str = "1") -> str:
    texto = str(valor if valor is not None else "").strip()
    if not texto:
        texto = defecto
    numeros = []
    for parte in re.split(r"[,;/\s]+", texto):
        parte = parte.strip()
        if not parte:
            continue
        if "-" in parte:
            inicio_txt, fin_txt = parte.split("-", 1)
            inicio = entero_seguro(inicio_txt, 0)
            fin = entero_seguro(fin_txt, 0)
            if inicio > 0 and fin >= inicio:
                numeros.extend(range(inicio, fin + 1))
        else:
            num = entero_seguro(parte, 0)
            if num > 0:
                numeros.append(num)
    unicos = []
    for num in numeros:
        if num not in unicos:
            unicos.append(num)
    return ", ".join(str(n) for n in unicos) if unicos else str(defecto)


def item_en_bulto(valor, bulto: int) -> bool:
    bultos = normalizar_bultos_item(valor).replace(" ", "").split(",")
    return str(int(bulto)) in bultos


def parsear_cantidades_por_bulto(valor, cantidad_total: float = 0, bulto_default: int = 1) -> Dict[int, float]:
    texto = str(valor if valor is not None else "").strip()
    total = numero_seguro(cantidad_total, 0)
    if not texto:
        return {int(bulto_default): total} if total > 0 else {}

    distribucion: Dict[int, float] = {}
    partes = [p.strip() for p in re.split(r"[,;/]+", texto) if p.strip()]
    for parte in partes:
        if "=" in parte:
            bulto_txt, cant_txt = parte.split("=", 1)
        elif ":" in parte:
            bulto_txt, cant_txt = parte.split(":", 1)
        else:
            bulto_txt, cant_txt = parte, ""

        bultos_txt = re.sub(r"\bCAJA\b", "", bulto_txt.strip(), flags=re.IGNORECASE).strip()
        cant_limpia = re.sub(r"\bCANTIDAD\b", "", cant_txt.strip(), flags=re.IGNORECASE).strip()
        cantidad = numero_seguro(cant_limpia, 0) if cant_limpia else 0

        bultos = []
        if "-" in bultos_txt:
            inicio_txt, fin_txt = bultos_txt.split("-", 1)
            inicio = entero_seguro(inicio_txt, 0)
            fin = entero_seguro(fin_txt, 0)
            if inicio > 0 and fin >= inicio:
                bultos = list(range(inicio, fin + 1))
        else:
            bulto = entero_seguro(bultos_txt, 0)
            if bulto > 0:
                bultos = [bulto]

        for bulto in bultos:
            distribucion[bulto] = distribucion.get(bulto, 0) + cantidad

    if distribucion and sum(distribucion.values()) == 0 and total > 0:
        bultos = list(distribucion.keys())
        if len(bultos) == 1:
            distribucion[bultos[0]] = total
    return distribucion


def normalizar_cantidades_por_bulto(valor, cantidad_total: float = 0, bulto_default: int = 1) -> str:
    distribucion = parsear_cantidades_por_bulto(valor, cantidad_total, bulto_default)
    if not distribucion:
        return ""
    return ", ".join(f"Caja {bulto} = Cantidad {formatear_numero(cantidad)}" for bulto, cantidad in sorted(distribucion.items()))


def piezas_en_caja_de_fila(row) -> float:
    caja = entero_seguro(row.get("bulto", 1), 1) if isinstance(row, dict) else entero_seguro(getattr(row, "bulto", 1), 1)
    distribucion = row.get("cantidades_bulto", "") if isinstance(row, dict) else getattr(row, "cantidades_bulto", "")
    cantidad_total = row.get("cantidad_mudada", 0) if isinstance(row, dict) else getattr(row, "cantidad_mudada", 0)
    piezas = cantidad_en_bulto(distribucion, caja, cantidad_total)
    if piezas <= 0 and numero_seguro(cantidad_total, 0) > 0:
        return numero_seguro(cantidad_total, 0)
    return piezas


def cantidad_en_bulto(valor, bulto: int, cantidad_total: float = 0) -> float:
    distribucion = parsear_cantidades_por_bulto(valor, cantidad_total, bulto)
    return float(distribucion.get(int(bulto), 0))


def suma_cantidades_bulto(valor, cantidad_total: float = 0, bulto_default: int = 1) -> float:
    distribucion = parsear_cantidades_por_bulto(valor, cantidad_total, bulto_default)
    return float(sum(distribucion.values()))


def bultos_desde_distribucion(valor, cantidad_total: float = 0, bulto_default: int = 1) -> str:
    distribucion = parsear_cantidades_por_bulto(valor, cantidad_total, bulto_default)
    return ", ".join(str(bulto) for bulto in sorted(distribucion)) if distribucion else str(bulto_default)


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
    """Une filas de origen soportando nÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºmeros y textos ya consolidados."""
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
    Recibe la lectura cruda del scanner y genera candidatos de bÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºsqueda.
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

            # Si viene pegado con sufijo, tambiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â©n pruebo una versiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n base de 10 caracteres.
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
    fila_art, col_art = buscar_columna_por_texto(df_raw, ["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "Articulo"])
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


def clasificar_frecuencia_meses(meses) -> str:
    meses_num = pd.to_numeric(meses, errors="coerce")
    if pd.isna(meses_num):
        return "Sin ventas registradas"
    meses_num = float(meses_num)
    if meses_num <= 6:
        return "A"
    if meses_num <= 12:
        return "B"
    if meses_num <= 18:
        return "C"
    if meses_num <= 24:
        return "E"
    if meses_num <= 38:
        return "F"
    return "Scrap"


def meses_entre(inicio: datetime, fin: datetime) -> int:
    return max((fin.year - inicio.year) * 12 + (fin.month - inicio.month), 0)


def fecha_mes_desde_indice(primer_mes: datetime, indice: int) -> datetime:
    total = primer_mes.year * 12 + primer_mes.month - 1 + indice
    return datetime(total // 12, total % 12 + 1, 1)


def fecha_mes_hoja(nombre_hoja: str) -> datetime | None:
    meses = {
        "ENERO": 1,
        "FEBRERO": 2,
        "FEBREO": 2,
        "MARZO": 3,
        "ABRIL": 4,
        "MAYO": 5,
        "MAyo".upper(): 5,
        "JUNIO": 6,
        "JULIO": 7,
        "AGOSTO": 8,
        "SETIEMBRE": 9,
        "SEPTIEMBRE": 9,
        "OCTUBRE": 10,
        "NOVIEMBRE": 11,
        "DICIEMBRE": 12,
        "DIECIEMBRE": 12,
    }
    texto = str(nombre_hoja).strip().upper()
    year_match = re.search(r"(20\d{2})", texto)
    if not year_match:
        return None
    anio = int(year_match.group(1))
    mes = 0
    for nombre_mes, numero_mes in meses.items():
        if nombre_mes in texto:
            mes = numero_mes
            break
    if not mes:
        return None
    return datetime(anio, mes, 1)


def leer_frecuencia_desde_ventas_mensuales(file_bytes: bytes, filename: str) -> pd.DataFrame:
    nombre = filename.lower()
    if not nombre.endswith((".xls", ".xlsx", ".xlsm")):
        return pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])

    buffer = io.BytesIO(file_bytes)
    engine = "xlrd" if nombre.endswith(".xls") else "openpyxl"
    try:
        xls = pd.ExcelFile(buffer, engine=engine)
    except Exception:
        return pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])
    if len(xls.sheet_names) < 3:
        return pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])

    primera_fecha = fecha_mes_hoja(xls.sheet_names[0])
    ventas = []
    for idx, sheet_name in enumerate(xls.sheet_names):
        fecha_mes = fecha_mes_hoja(sheet_name)
        if primera_fecha is not None:
            fecha_secuencial = fecha_mes_desde_indice(primera_fecha, idx)
            if fecha_mes is None or fecha_mes < fecha_secuencial.replace(year=fecha_secuencial.year - 1):
                fecha_mes = fecha_secuencial
        if fecha_mes is None:
            continue

        df = pd.read_excel(xls, sheet_name=sheet_name, header=None, dtype=object)
        if df.shape[0] < 3 or df.shape[1] < 4:
            continue
        col_ventas = 3
        for fila_hdr in list(range(1, min(5, len(df)))) + [0]:
            for col_hdr, valor_hdr in df.iloc[fila_hdr].items():
                if normalizar_codigo(valor_hdr) == "VENTAS":
                    col_ventas = int(col_hdr)
                    break
            else:
                continue
            break
        for row_idx in range(2, len(df)):
            row = df.iloc[row_idx]
            codigo = normalizar_codigo(row.iloc[0] if len(row) > 0 else "")
            if not codigo or codigo in ["PRODUCTO", "TOTAL"]:
                continue
            descripcion = "" if len(row) < 2 or pd.isna(row.iloc[1]) else str(row.iloc[1]).strip()
            cantidad = pd.to_numeric(row.iloc[col_ventas] if len(row) > col_ventas else 0, errors="coerce")
            if pd.isna(cantidad) or float(cantidad) <= 0:
                continue
            ventas.append(
                {
                    "codigo_normalizado": codigo,
                    "descripcion_venta": descripcion,
                    "fecha_venta": fecha_mes,
                    "unidades_vendidas": float(cantidad),
                }
            )

    if not ventas:
        return pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])

    tabla = pd.DataFrame(ventas)
    fecha_referencia = tabla["fecha_venta"].max()
    resumen = (
        tabla.groupby("codigo_normalizado", as_index=False)
        .agg(
            ultima_venta=("fecha_venta", "max"),
            unidades_vendidas=("unidades_vendidas", "sum"),
            descripcion_venta=("descripcion_venta", _primer_valor_no_vacio),
        )
    )
    resumen["meses_venta"] = resumen["ultima_venta"].map(lambda fecha: meses_entre(fecha, fecha_referencia))
    resumen["frecuencia"] = resumen["meses_venta"].map(clasificar_frecuencia_meses)
    return resumen[["codigo_normalizado", "frecuencia", "meses_venta"]]


def leer_frecuencias(file_bytes: bytes, filename: str) -> pd.DataFrame:
    if not file_bytes:
        return pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])
    ventas_mensuales = leer_frecuencia_desde_ventas_mensuales(file_bytes, filename)
    if not ventas_mensuales.empty:
        return ventas_mensuales
    raw = leer_archivo_excel_o_csv(file_bytes, filename)
    if raw.empty:
        return pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])

    header_row = 0
    for i in range(min(len(raw), 30)):
        fila_norm = [normalizar_codigo(v) for v in raw.iloc[i].tolist()]
        tiene_codigo = any(v in ["ARTICULO", "CODIGO", "CODIGONORMALIZADO", "SKU"] for v in fila_norm)
        tiene_frecuencia = any(v in ["FRECUENCIA", "CATEGORIA", "ABC", "MESES", "MESESVENTA", "MESESSINVENTA"] for v in fila_norm)
        if tiene_codigo and tiene_frecuencia:
            header_row = i
            break

    tabla = raw.iloc[header_row + 1 :].copy()
    tabla.columns = [str(c).strip() if pd.notna(c) else "" for c in raw.iloc[header_row].tolist()]
    tabla = tabla.dropna(how="all")

    col_codigo = extraer_columna(tabla, ["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "Articulo", "Codigo", "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo", "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado", "Codigo normalizado", "SKU"])
    col_categoria = extraer_columna(tabla, ["Frecuencia", "Categoria", "CategorÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­a", "ABC"])
    col_meses = extraer_columna(tabla, ["Meses", "Meses venta", "Meses sin venta", "Antiguedad", "AntigÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼edad"])
    if not col_codigo:
        return pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])

    salida = pd.DataFrame()
    salida["codigo_normalizado"] = tabla[col_codigo].map(normalizar_codigo)
    salida["meses_venta"] = pd.to_numeric(tabla[col_meses], errors="coerce") if col_meses else pd.NA
    if col_categoria:
        salida["frecuencia"] = tabla[col_categoria].fillna("").astype(str).str.strip().str.upper()
        salida["frecuencia"] = salida["frecuencia"].where(salida["frecuencia"] != "", salida["meses_venta"].map(clasificar_frecuencia_meses))
    else:
        salida["frecuencia"] = salida["meses_venta"].map(clasificar_frecuencia_meses)
    salida = salida[salida["codigo_normalizado"] != ""].copy()
    return salida[["codigo_normalizado", "frecuencia", "meses_venta"]]


# -----------------------------
# ConsolidaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n y bÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Âºsqueda
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
    """Si el mismo cÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo aparece varias veces, suma cantidades. Ej.: 316 + 49 = 365."""
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
            "articulo": "Articulo en stock",
            "descripcion": "Descripcion",
            "estado": "Estado",
            "unidad": "Unidad",
            "cantidad": "Stock total",
            "lineas_sumadas": "Lineas sumadas",
            "codigo_normalizado": "Codigo normalizado",
            "puntaje": "Coincidencia",
        }
    )


def mapa_frecuencia(frecuencias: pd.DataFrame) -> Dict[str, str]:
    if frecuencias is None or frecuencias.empty:
        return {}
    if "codigo_normalizado" not in frecuencias.columns or "frecuencia" not in frecuencias.columns:
        return {}
    trabajo = frecuencias[["codigo_normalizado", "frecuencia"]].copy()
    trabajo["codigo_normalizado"] = trabajo["codigo_normalizado"].astype(str).str.strip()
    trabajo["frecuencia"] = trabajo["frecuencia"].fillna("").astype(str).str.strip()
    trabajo = trabajo[trabajo["codigo_normalizado"] != ""]
    return dict(zip(trabajo["codigo_normalizado"], trabajo["frecuencia"]))


def inventario_para_buscar(
    stock_consolidado: pd.DataFrame,
    df_pick: pd.DataFrame,
    ubicaciones_anteriores: pd.DataFrame,
    frecuencias: pd.DataFrame,
    salidas: pd.DataFrame | None = None,
) -> pd.DataFrame:
    columnas = ["codigo_normalizado", "articulo", "descripcion", "deposito", "ubicacion", "cantidad", "frecuencia"]
    partes = []

    darkinel = limpiar_df_visible(stock_darkinel_actualizado(stock_consolidado, df_pick))
    if not darkinel.empty:
        norm_col = extraer_columna(darkinel, ["Codigo normalizado"])
        art_col = extraer_columna(darkinel, ["Articulo"])
        desc_col = extraer_columna(darkinel, ["Descripcion"])
        stock_col = extraer_columna(darkinel, ["Stock restante Darkinel"])
        if norm_col and art_col and stock_col:
            dark = pd.DataFrame(
                {
                    "codigo_normalizado": darkinel[norm_col].astype(str).str.strip(),
                    "articulo": darkinel[art_col].astype(str).str.strip(),
                    "descripcion": darkinel[desc_col].astype(str).str.strip() if desc_col else "",
                    "deposito": "DARKINEL",
                    "ubicacion": "DARKINEL",
                    "cantidad": pd.to_numeric(darkinel[stock_col], errors="coerce").fillna(0),
                }
            )
            partes.append(dark[dark["cantidad"] > 0].copy())

    trabajo_polo = normalizar_df_pick(df_pick) if df_pick is not None and not df_pick.empty and (salidas is None or salidas.empty) else pd.DataFrame()
    if not trabajo_polo.empty:
        polo = pd.DataFrame(
            {
                "codigo_normalizado": trabajo_polo["codigo_normalizado"].astype(str).str.strip(),
                "articulo": trabajo_polo["articulo"].astype(str).str.strip(),
                "descripcion": trabajo_polo["descripcion"].astype(str).str.strip(),
                "deposito": "POLO LOGISTICO",
                "ubicacion": trabajo_polo["ubicacion"].astype(str).str.strip().str.upper(),
                "cantidad": pd.to_numeric(trabajo_polo["cantidad_mudada"], errors="coerce").fillna(0),
            }
        )
        polo = polo[(polo["codigo_normalizado"] != "") & (polo["cantidad"] > 0)].copy()
        if not polo.empty:
            partes.append(
                polo.groupby(["codigo_normalizado", "articulo", "descripcion", "deposito", "ubicacion"], as_index=False)
                .agg(cantidad=("cantidad", "sum"))
            )
        df_pick = pd.DataFrame()
        ubicaciones_anteriores = pd.DataFrame()

    ubicaciones = limpiar_df_visible(aplicar_salidas_a_ubicaciones(ubicacion_polo_logistico(df_pick, ubicaciones_anteriores), salidas))
    if not ubicaciones.empty:
        norm_col = extraer_columna(ubicaciones, ["Codigo normalizado"])
        art_col = extraer_columna(ubicaciones, ["Articulo"])
        desc_col = extraer_columna(ubicaciones, ["Descripcion"])
        ubic_col = extraer_columna(ubicaciones, ["Ubicacion"])
        piezas_col = extraer_columna(ubicaciones, ["Piezas"])
        if norm_col and art_col and ubic_col and piezas_col:
            polo = pd.DataFrame(
                {
                    "codigo_normalizado": ubicaciones[norm_col].astype(str).str.strip(),
                    "articulo": ubicaciones[art_col].astype(str).str.strip(),
                    "descripcion": ubicaciones[desc_col].astype(str).str.strip() if desc_col else "",
                    "deposito": "POLO LOGISTICO",
                    "ubicacion": ubicaciones[ubic_col].astype(str).str.strip().str.upper(),
                    "cantidad": pd.to_numeric(ubicaciones[piezas_col], errors="coerce").fillna(0),
                }
            )
            polo = polo[polo["ubicacion"].apply(es_ubicacion_real)].copy()
            if not polo.empty:
                partes.append(
                    polo.groupby(["codigo_normalizado", "articulo", "descripcion", "deposito", "ubicacion"], as_index=False)
                    .agg(cantidad=("cantidad", "sum"))
                )

    if not partes:
        return pd.DataFrame(columns=columnas)

    inventario = pd.concat(partes, ignore_index=True)
    inventario["codigo_normalizado"] = inventario["codigo_normalizado"].astype(str).str.strip()
    inventario["frecuencia"] = inventario["codigo_normalizado"].map(mapa_frecuencia(frecuencias)).fillna("Sin ventas registradas")
    inventario = inventario[inventario["codigo_normalizado"] != ""].copy()
    return inventario[columnas]


def buscar_en_inventario(inventario: pd.DataFrame, texto: str) -> pd.DataFrame:
    if inventario.empty or not str(texto).strip():
        return pd.DataFrame(columns=inventario.columns)
    info = extraer_candidatos_mazda(texto)
    candidatos = info["candidatos"]
    if not candidatos:
        return pd.DataFrame(columns=inventario.columns)

    candidatos_validos = [c for c in candidatos if len(c) >= 5]
    if not candidatos_validos:
        return pd.DataFrame(columns=inventario.columns)

    def coincidencia(codigo) -> int:
        codigo_norm = normalizar_codigo(codigo)
        mejor = 0
        for candidato in candidatos_validos:
            if codigo_norm == candidato:
                mejor = max(mejor, 100)
            elif codigo_norm.startswith(candidato) or candidato.startswith(codigo_norm):
                mejor = max(mejor, 95)
            else:
                mejor = max(mejor, int(round(SequenceMatcher(None, codigo_norm, candidato).ratio() * 100)))
        return mejor

    resultado = inventario.copy()
    resultado["coincidencia"] = resultado["codigo_normalizado"].map(coincidencia)
    resultado = resultado[resultado["coincidencia"] >= 90].copy()
    if resultado.empty:
        return pd.DataFrame(columns=list(inventario.columns) + ["coincidencia"])
    return resultado.sort_values(["coincidencia", "codigo_normalizado", "deposito", "ubicacion"], ascending=[False, True, True, True]).head(50)


def mostrar_inventario(df: pd.DataFrame) -> pd.DataFrame:
    columnas = ["Codigo normalizado", "Articulo", "Descripcion", "Deposito", "Locacion", "Cantidad", "Frecuencia"]
    if df.empty:
        return pd.DataFrame(columns=columnas)
    return df.rename(
        columns={
            "codigo_normalizado": "Codigo normalizado",
            "articulo": "Articulo",
            "descripcion": "Descripcion",
            "deposito": "Deposito",
            "ubicacion": "Locacion",
            "cantidad": "Cantidad",
            "frecuencia": "Frecuencia",
        }
    )[columnas]


def limpiar_columna_visible(columna) -> str:
    texto = str(columna)
    if not any(marca in texto for marca in ["\u00c3", "\u00c2", "\u00e2", "\u00c6", "\ufffd"]):
        return texto
    bajo = texto.lower()
    if "ok" in bajo and "recepci" in bajo:
        return "OK recepcion"
    if "fecha" in bajo and "recepci" in bajo:
        return "Fecha recepcion"
    if "observaciones" in bajo and "recepci" in bajo:
        return "Observaciones recepcion"
    if "fecha" in bajo and "hora" in bajo:
        return "Fecha/Hora"
    if "dep" in bajo and "origen" in bajo:
        return "Deposito origen"
    if "dep" in bajo and "destino" in bajo:
        return "Deposito destino"
    if "dep" in bajo:
        return "Deposito"
    if ("ubic" in bajo or "locaci" in bajo) and "polo" in bajo:
        return "Ubicacion Polo"
    if ("ubic" in bajo or "locaci" in bajo) and "informada" in bajo:
        return "Ubicacion informada"
    if "ubic" in bajo or "locaci" in bajo:
        return "Ubicacion"
    if "art" in bajo and "culo" in bajo:
        return "Articulo"
    if "descrip" in bajo:
        return "Descripcion"
    if "codigo normalizado" in bajo or "digo normalizado" in bajo:
        return "Codigo normalizado"
    if "cantidad de c" in bajo and "digos" in bajo:
        return "Cantidad de codigos diferentes"
    if "digos que componen" in bajo:
        return "Codigos que componen el pallet"
    if "lineas" in bajo or "neas" in bajo:
        return "Lineas"
    if "mas" in bajo:
        return "Mas"
    return re.sub(r"[^A-Za-z0-9 /_-]+", " ", texto).strip() or "Columna"


def limpiar_df_visible(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    salida = df.copy()
    salida.columns = [limpiar_columna_visible(c) for c in salida.columns]
    salida = salida.loc[:, ~pd.Index(salida.columns).duplicated()]
    return salida


def salidas_polo_df() -> pd.DataFrame:
    columnas = ["salida_id", "fecha_hora", "codigo_normalizado", "articulo", "descripcion", "ubicacion", "cantidad", "responsable", "observaciones"]
    df = pd.DataFrame(st.session_state.get("salidas_polo", []))
    if df.empty:
        return pd.DataFrame(columns=columnas)
    for col in columnas:
        if col not in df.columns:
            df[col] = "" if col not in ["salida_id", "cantidad"] else 0
    df["salida_id"] = pd.to_numeric(df["salida_id"], errors="coerce").fillna(0).astype(int)
    df["codigo_normalizado"] = df["codigo_normalizado"].map(normalizar_codigo)
    df["ubicacion"] = df["ubicacion"].fillna("").astype(str).str.strip().str.upper()
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    return df[columnas]


def mostrar_salidas_polo(df: pd.DataFrame) -> pd.DataFrame:
    columnas = ["Fecha/Hora", "Codigo normalizado", "Articulo", "Descripcion", "Locacion", "Cantidad", "Responsable", "Observaciones"]
    if df.empty:
        return pd.DataFrame(columns=columnas)
    salida = df.rename(
        columns={
            "fecha_hora": "Fecha/Hora",
            "codigo_normalizado": "Codigo normalizado",
            "articulo": "Articulo",
            "descripcion": "Descripcion",
            "ubicacion": "Locacion",
            "cantidad": "Cantidad",
            "responsable": "Responsable",
            "observaciones": "Observaciones",
        }
    )
    salida["Cantidad"] = salida["Cantidad"].apply(formatear_numero)
    return salida[columnas]


def aplicar_salidas_a_ubicaciones(ubicaciones: pd.DataFrame, salidas: pd.DataFrame) -> pd.DataFrame:
    if ubicaciones is None or ubicaciones.empty:
        return ubicaciones
    trabajo = ubicaciones.copy()
    if salidas is None or salidas.empty:
        return trabajo

    ubic_col = extraer_columna(trabajo, ["UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Ubicacion", "UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n Polo", "Ubicacion Polo"])
    piezas_col = extraer_columna(trabajo, ["Piezas", "Piezas enviadas", "Piezas en esta caja", "Cantidad mudada"])
    norm_col = extraer_columna(trabajo, ["CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado", "Codigo normalizado"])
    if not ubic_col or not piezas_col or not norm_col:
        return trabajo

    trabajo["_codigo_salida"] = trabajo[norm_col].map(normalizar_codigo)
    trabajo["_ubicacion_salida"] = trabajo[ubic_col].fillna("").astype(str).str.strip().str.upper()
    trabajo["_piezas_num"] = pd.to_numeric(trabajo[piezas_col], errors="coerce").fillna(0)

    sal = salidas.copy()
    sal["codigo_normalizado"] = sal["codigo_normalizado"].map(normalizar_codigo)
    sal["ubicacion"] = sal["ubicacion"].fillna("").astype(str).str.strip().str.upper()
    sal["cantidad"] = pd.to_numeric(sal["cantidad"], errors="coerce").fillna(0)
    salidas_por_locacion = sal.groupby(["codigo_normalizado", "ubicacion"])["cantidad"].sum().to_dict()

    restantes = []
    for _, row in trabajo.iterrows():
        clave = (row["_codigo_salida"], row["_ubicacion_salida"])
        descontar = float(salidas_por_locacion.get(clave, 0) or 0)
        piezas = float(row["_piezas_num"] or 0)
        if descontar > 0:
            usado = min(piezas, descontar)
            piezas -= usado
            salidas_por_locacion[clave] = descontar - usado
        restantes.append(piezas)

    trabajo[piezas_col] = restantes
    trabajo = trabajo[pd.to_numeric(trabajo[piezas_col], errors="coerce").fillna(0) > 0].copy()
    trabajo[piezas_col] = pd.to_numeric(trabajo[piezas_col], errors="coerce").fillna(0).apply(formatear_numero)
    return trabajo.drop(columns=["_codigo_salida", "_ubicacion_salida", "_piezas_num"], errors="ignore")


def stock_polo_desde_ubicaciones_con_salidas(ubicaciones: pd.DataFrame, salidas: pd.DataFrame) -> pd.DataFrame:
    return stock_polo_desde_ubicaciones(aplicar_salidas_a_ubicaciones(ubicaciones, salidas))


def firma_lineas_mudanza(df: pd.DataFrame) -> set:
    if df is None or df.empty:
        return set()
    trabajo = normalizar_df_pick(df)
    claves = []
    for row in trabajo.itertuples():
        claves.append(
            (
                str(getattr(row, "codigo_normalizado", "")).strip(),
                entero_seguro(getattr(row, "pallet", 0), 0),
                entero_seguro(getattr(row, "bulto", 0), 0),
                numero_seguro(getattr(row, "cantidad_mudada", 0), 0),
                str(getattr(row, "ubicacion", "")).strip().upper(),
            )
        )
    return set(claves)


def misma_mudanza(df_a: pd.DataFrame, df_b: pd.DataFrame) -> bool:
    firma_a = firma_lineas_mudanza(df_a)
    firma_b = firma_lineas_mudanza(df_b)
    return bool(firma_a and firma_a == firma_b)


def formulario_agregar_desde_base(
    codigo: str,
    opciones_df: pd.DataFrame,
    titulo: str,
    form_key: str,
    pallet_activo: int,
    cantidad_bultos_activo: int,
    bulto_activo: int,
    ubicacion_default: str,
    deposito_origen: str,
    deposito_destino: str,
) -> None:
    if opciones_df.empty:
        return
    st.subheader(titulo)
    opciones = []
    opciones_reset = opciones_df.reset_index(drop=True)
    for i, row in opciones_reset.iterrows():
        opciones.append(f"{i + 1}) {row.get('articulo', '')} | {row.get('descripcion', '')} | Stock {row.get('cantidad', 0)}")

    opcion = st.selectbox("Articulo", opciones, key=f"{form_key}_select")
    idx = opciones.index(opcion)
    row_sel = opciones_reset.iloc[idx]

    disponible = float(row_sel["cantidad"]) - cantidad_pickeada_por_codigo(row_sel["codigo_normalizado"])
    disponible = max(disponible, 0)

    if disponible <= 0:
        st.warning("Este codigo ya quedo totalmente marcado para mudanza en los pallets actuales.")
        return

    with st.form(form_key):
        c1, c2, c3, c4, c5 = st.columns(5)
        cantidad_mudar = c1.number_input("Piezas a mudar", min_value=1.0, value=1.0, step=1.0, key=f"{form_key}_cantidad")
        pallet = c2.number_input("Pallet", min_value=1, value=int(pallet_activo), step=1, key=f"{form_key}_pallet")
        cantidad_bultos = c3.number_input("Cantidad de cajas", min_value=1, value=int(cantidad_bultos_activo), step=1, key=f"{form_key}_cajas")
        bulto = c4.number_input("Caja", min_value=1, max_value=int(cantidad_bultos), value=min(int(bulto_activo), int(cantidad_bultos)), step=1, key=f"{form_key}_bulto")
        ubicacion = c5.text_input("Ubicacion en Polo", value=str(ubicacion_default), placeholder="Pendiente / Ej: 1-L-3", key=f"{form_key}_ubicacion")
        observaciones = st.text_input("Observaciones", placeholder="Opcional", key=f"{form_key}_obs")
        submit = st.form_submit_button("Agregar a mudanza", type="primary")

    if submit:
        ok, msg = agregar_item_a_mudanza(
            lectura_original=codigo,
            row=row_sel,
            cantidad_mudada=cantidad_mudar,
            pallet=pallet,
            cantidad_bultos=cantidad_bultos,
            bulto=bulto,
            bultos_item="",
            cantidades_bulto=f"Caja {int(bulto)} = Cantidad {formatear_numero(cantidad_mudar)}",
            ubicacion=ubicacion,
            deposito_origen=deposito_origen,
            deposito_destino=deposito_destino,
            observaciones=observaciones,
            validar_stock=False,
        )
        if ok:
            guardar_mudanza_actual_db()
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)


def formulario_agregar_manual(
    codigo: str,
    titulo: str,
    form_key: str,
    pallet_activo: int,
    cantidad_bultos_activo: int,
    bulto_activo: int,
    ubicacion_default: str,
    deposito_origen: str,
    deposito_destino: str,
    pendientes_key: str | None = None,
) -> None:
    st.subheader(titulo)
    st.caption("Usalo cuando el articulo no existe exacto en el Excel/base cargada. No descuenta stock de DARKINEL, pero si entra a la mudanza y al POLO.")
    with st.form(form_key):
        m1, m2, m3 = st.columns([1.2, 2, 0.8])
        articulo_manual = m1.text_input("Articulo", value=str(codigo).strip().upper(), key=f"{form_key}_articulo")
        descripcion_manual = m2.text_input("Descripcion", value="", key=f"{form_key}_descripcion")
        unidad_manual = m3.text_input("Unidad", value="uni", key=f"{form_key}_unidad")

        m4, m5, m6, m7, m8, m9 = st.columns(6)
        cantidad_manual = m4.number_input("Piezas a mudar", min_value=1.0, value=1.0, step=1.0, key=f"{form_key}_cantidad")
        stock_darkinel_manual = m5.number_input("Queda en Darkinel", min_value=0.0, value=0.0, step=1.0, key=f"{form_key}_stock_darkinel")
        pallet_manual = m6.number_input("Pallet", min_value=1, value=int(pallet_activo), step=1, key=f"{form_key}_pallet")
        cantidad_bultos_manual = m7.number_input("Cantidad de cajas", min_value=1, value=int(cantidad_bultos_activo), step=1, key=f"{form_key}_cajas")
        bulto_manual = m8.number_input("Caja", min_value=1, max_value=int(cantidad_bultos_manual), value=min(int(bulto_activo), int(cantidad_bultos_manual)), step=1, key=f"{form_key}_bulto")
        ubicacion_manual = m9.text_input("Ubicacion", value=str(ubicacion_default), placeholder="Pendiente / Ej: 1-L-3", key=f"{form_key}_ubicacion")
        observaciones_manual = st.text_input("Observaciones manual", value="Articulo agregado manualmente", key=f"{form_key}_obs")
        submit_manual = st.form_submit_button("Agregar manual a mudanza", type="primary")

    if submit_manual:
        articulo_manual = str(articulo_manual).strip().upper()
        if not articulo_manual:
            st.error("El articulo manual no puede quedar vacio.")
            return
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
            bultos_item="",
            cantidades_bulto=f"Caja {int(bulto_manual)} = Cantidad {formatear_numero(cantidad_manual)}",
            ubicacion=ubicacion_manual,
            deposito_origen=deposito_origen,
            deposito_destino=deposito_destino,
            observaciones=observaciones_manual,
            validar_stock=False,
        )
        if ok:
            if pendientes_key:
                pendientes = [x for x in st.session_state.get(pendientes_key, []) if str(x).strip() != str(codigo).strip()]
                st.session_state[pendientes_key] = pendientes
            guardar_mudanza_actual_db()
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)


# -----------------------------
# Picking / mudanza / depÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sitos
# -----------------------------
def inicializar_estado() -> None:
    if "pick_items" not in st.session_state:
        estado_db = cargar_mudanza_actual_db()
        st.session_state.pick_items = estado_db.get("pick_items", [])
    if "pick_seq" not in st.session_state:
        estado_db = cargar_mudanza_actual_db()
        st.session_state.pick_seq = int(estado_db.get("pick_seq", 0) or 0)
    if "salidas_polo" not in st.session_state:
        estado_salidas = cargar_salidas_polo_db()
        st.session_state.salidas_polo = estado_salidas.get("salidas", [])
    if "salida_seq" not in st.session_state:
        estado_salidas = cargar_salidas_polo_db()
        st.session_state.salida_seq = int(estado_salidas.get("salida_seq", 0) or 0)

    # MigraciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n automÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡tica: si la sesiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n venÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­a de una versiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n anterior,
    # convertimos bultos_pallet/bultos_item a cantidad_bultos/ubicacion.
    for item in st.session_state.pick_items:
        if "cantidad_bultos" not in item:
            item["cantidad_bultos"] = item.get("bultos_pallet", 1)
        if "bulto" not in item:
            item["bulto"] = 1
        if "bultos_item" not in item:
            item["bultos_item"] = str(item.get("bulto", 1))
        if "cantidades_bulto" not in item:
            item["cantidades_bulto"] = normalizar_cantidades_por_bulto(
                f"{item.get('bulto', 1)}={item.get('cantidad_mudada', 0)}",
                item.get("cantidad_mudada", 0),
                item.get("bulto", 1),
            )
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
    Deja la mudanza con las columnas nuevas aunque la sesiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n tenga datos viejos.
    Evita errores cuando antes existÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­an columnas como bultos_pallet o bultos_item.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    trabajo = df.copy()

    # Compatibilidad con la versiÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n anterior de la app.
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
        elif "Bulto(s) del artÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo" in trabajo.columns:
            trabajo["ubicacion"] = trabajo["Bulto(s) del artÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo"]
        else:
            trabajo["ubicacion"] = ""

    defaults = {
        "fecha_hora": "",
        "deposito_origen": "DARKINEL",
        "deposito_destino": "POLO LOGISTICO",
        "pallet": 1,
        "bulto": 1,
        "bultos_item": "1",
        "cantidades_bulto": "",
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
    trabajo["cantidades_bulto"] = trabajo.apply(
        lambda r: normalizar_cantidades_por_bulto(r.get("cantidades_bulto", ""), r.get("cantidad_mudada", 0), r.get("bulto", 1)),
        axis=1,
    )
    trabajo["bultos_item"] = trabajo.apply(
        lambda r: bultos_desde_distribucion(r.get("cantidades_bulto", ""), r.get("cantidad_mudada", 0), r.get("bulto", 1)),
        axis=1,
    )
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
    bultos_item: str,
    cantidades_bulto: str,
    ubicacion: str,
    deposito_origen: str,
    deposito_destino: str,
    observaciones: str = "",
    validar_stock: bool = True,
) -> Tuple[bool, str]:
    codigo_norm = str(row.get("codigo_normalizado", ""))
    stock_total = numero_seguro(row.get("cantidad", 0), 0)
    ya_pickeado = cantidad_pickeada_por_codigo(codigo_norm)
    cantidades_bulto_norm = normalizar_cantidades_por_bulto(cantidades_bulto or bultos_item, cantidad_mudada, bulto)
    cantidad_mudada = suma_cantidades_bulto(cantidades_bulto_norm, cantidad_mudada, bulto) or float(cantidad_mudada)

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
            "item_uid": uuid.uuid4().hex,
            "item_id": st.session_state.pick_seq,
            "fecha_hora": ahora,
            "deposito_origen": deposito_origen.strip() or "DARKINEL",
            "deposito_destino": deposito_destino.strip() or "POLO LOGISTICO",
            "pallet": int(pallet),
            "cantidad_bultos": int(cantidad_bultos),
            "bulto": int(bulto),
            "cantidades_bulto": cantidades_bulto_norm,
            "bultos_item": bultos_desde_distribucion(cantidades_bulto_norm, cantidad_mudada, bulto),
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
    return True, "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo agregado a la mudanza."


def registrar_pallet_sin_detalle(
    pallet: int,
    cantidad_bultos: int,
    deposito_origen: str,
    deposito_destino: str,
    observaciones: str = "",
) -> None:
    st.session_state.pick_seq += 1
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.pick_items.append(
        {
            "item_uid": uuid.uuid4().hex,
            "item_id": st.session_state.pick_seq,
            "fecha_hora": ahora,
            "deposito_origen": deposito_origen.strip() or "DARKINEL",
            "deposito_destino": deposito_destino.strip() or "POLO LOGISTICO",
            "pallet": int(pallet),
            "cantidad_bultos": int(cantidad_bultos),
            "bulto": 1,
            "cantidades_bulto": "Caja 1 = Cantidad 0",
            "bultos_item": "1",
            "ubicacion": "PENDIENTE",
            "lectura_scanner": f"PALLET-{int(pallet)}-SIN-DETALLE",
            "articulo": "",
            "descripcion": "PALLET REGISTRADO SIN DETALLE",
            "estado": "PENDIENTE",
            "unidad": "uni",
            "cantidad_mudada": 0.0,
            "stock_total": 0.0,
            "codigo_normalizado": f"PALLET{int(pallet):03d}SINDETALLE",
            "observaciones": observaciones.strip() or "Pallet registrado sin detalle para no perder numeracion",
            "cantidad_recibida": 0.0,
            "recepcion_ok": False,
            "ubicacion_recepcion": "",
            "receptor": "",
            "fecha_recepcion": "",
            "observaciones_recepcion": "",
        }
    )


def parsear_lineas_pallet_faltante(texto: str) -> list[dict]:
    lineas = []
    for raw in str(texto or "").splitlines():
        linea = raw.strip()
        if not linea:
            continue
        partes = [p.strip() for p in re.split(r"\s*[;|]\s*", linea) if p.strip()]
        if len(partes) >= 4:
            caja_txt, codigo, descripcion, piezas_txt = partes[0], partes[1], " ".join(partes[2:-1]), partes[-1]
            caja = entero_seguro(caja_txt, len(lineas) + 1)
        elif len(partes) >= 3:
            codigo, descripcion, piezas_txt = partes[0], " ".join(partes[1:-1]), partes[-1]
            caja = len(lineas) + 1
        else:
            tokens = linea.split()
            if len(tokens) < 3:
                continue
            codigo, piezas_txt = tokens[0], tokens[-1]
            descripcion = " ".join(tokens[1:-1])
            caja = len(lineas) + 1
        piezas = numero_seguro(str(piezas_txt).replace(",", "."), 0)
        if not codigo or piezas <= 0:
            continue
        lineas.append(
            {
                "caja": max(int(caja), 1),
                "codigo": str(codigo).strip().upper(),
                "descripcion": str(descripcion).strip().upper() or "SIN DESCRIPCION",
                "piezas": float(piezas),
            }
        )
    return lineas


def actualizar_ubicacion_item(item_id: int, nueva_ubicacion: str) -> Tuple[bool, str]:
    ubicacion = str(nueva_ubicacion).strip().upper() or "PENDIENTE"
    for item in st.session_state.pick_items:
        if int(item.get("item_id", 0)) == int(item_id):
            item["ubicacion"] = ubicacion
            return True, "UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n actualizada."
    return False, "No encontrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â© esa lÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­nea de mudanza."


def actualizar_cantidad_item(item_id: int, nueva_cantidad: float) -> Tuple[bool, str]:
    if nueva_cantidad <= 0:
        return False, "La cantidad a mudar tiene que ser mayor a cero."

    item_objetivo = None
    for item in st.session_state.pick_items:
        if int(item.get("item_id", 0)) == int(item_id):
            item_objetivo = item
            break

    if item_objetivo is None:
        return False, "No encontrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â© esa lÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­nea de mudanza."

    item_objetivo["cantidad_mudada"] = float(nueva_cantidad)
    return True, "Cantidad actualizada."


def actualizar_linea_item(
    item_id: int,
    nueva_cantidad: float,
    nuevo_pallet: int,
    nueva_cantidad_bultos: int,
    nuevo_bulto: int,
    nuevos_bultos_item: str,
    nuevas_cantidades_bulto: str,
    nueva_ubicacion: str,
    stock_darkinel_restante: float | None = None,
) -> Tuple[bool, str]:
    ok, msg = actualizar_cantidad_item(item_id, nueva_cantidad)
    if not ok:
        return ok, msg

    for item in st.session_state.pick_items:
        if int(item.get("item_id", 0)) == int(item_id):
            cantidades_norm = normalizar_cantidades_por_bulto(nuevas_cantidades_bulto or nuevos_bultos_item, nueva_cantidad, nuevo_bulto)
            nueva_cantidad = suma_cantidades_bulto(cantidades_norm, nueva_cantidad, nuevo_bulto) or float(nueva_cantidad)
            item["pallet"] = int(nuevo_pallet)
            item["cantidad_bultos"] = int(nueva_cantidad_bultos)
            item["bulto"] = int(nuevo_bulto)
            item["cantidad_mudada"] = float(nueva_cantidad)
            item["cantidades_bulto"] = cantidades_norm
            item["bultos_item"] = bultos_desde_distribucion(item["cantidades_bulto"], nueva_cantidad, nuevo_bulto)
            item["ubicacion"] = str(nueva_ubicacion).strip().upper() or "PENDIENTE"
            if stock_darkinel_restante is not None:
                item["stock_total"] = float(nueva_cantidad) + float(stock_darkinel_restante)
                obs = str(item.get("observaciones", "")).strip()
                marca = f"Stock real Darkinel restante: {float(stock_darkinel_restante):g}"
                item["observaciones"] = f"{obs} | {marca}".strip(" |")
            return True, "LÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­nea actualizada."
    return False, "No encontrÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â© esa lÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­nea de mudanza."


def pick_items_df() -> pd.DataFrame:
    df = pd.DataFrame(st.session_state.pick_items)
    if df.empty:
        return df
    df = normalizar_df_pick(df)
    df["piezas_en_caja"] = df.apply(lambda r: piezas_en_caja_de_fila(r), axis=1)
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
    columnas = [
        "Fecha/Hora", "Deposito origen", "Deposito destino", "Pallet", "Cantidad de cajas", "Caja",
        "Piezas en esta caja", "Ubicacion", "Lectura scanner", "Articulo", "Descripcion", "Unidad",
        "Piezas enviadas", "Stock original Darkinel", "Stock restante Darkinel", "Codigo normalizado", "Observaciones",
    ]
    if df.empty:
        return pd.DataFrame(columns=columnas)
    df = normalizar_df_pick(df)
    origen = [
        "fecha_hora", "deposito_origen", "deposito_destino", "pallet", "cantidad_bultos", "bulto",
        "piezas_en_caja", "ubicacion", "lectura_scanner", "articulo", "descripcion", "unidad",
        "cantidad_mudada", "stock_total", "stock_restante_darkinel", "codigo_normalizado", "observaciones",
    ]
    salida = pd.DataFrame()
    for col_origen, col_destino in zip(origen, columnas):
        salida[col_destino] = df[col_origen] if col_origen in df.columns else ""
    return salida


def resumen_pallets(df: pd.DataFrame) -> pd.DataFrame:
    columnas = [
        "Deposito origen", "Deposito destino", "Pallet", "Cantidad de cajas", "Ubicaciones",
        "Cantidad de codigos diferentes", "Piezas totales", "Codigos que componen el pallet", "Descripciones",
    ]
    if df.empty:
        return pd.DataFrame(columns=columnas)
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
    return resumen.rename(columns={
        "deposito_origen": "Deposito origen",
        "deposito_destino": "Deposito destino",
        "pallet": "Pallet",
        "cantidad_bultos": "Cantidad de cajas",
        "ubicaciones": "Ubicaciones",
        "codigos_distintos": "Cantidad de codigos diferentes",
        "unidades_totales": "Piezas totales",
        "codigos": "Codigos que componen el pallet",
        "descripciones": "Descripciones",
    })[columnas]


def stock_darkinel_actualizado(stock_consolidado: pd.DataFrame, df_pick: pd.DataFrame) -> pd.DataFrame:
    columnas_finales = [
        "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo",
        "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
        "Estado",
        "Unidad",
        "Stock original Darkinel",
        "Mudado al Polo",
        "Stock restante Darkinel",
        "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado",
        "LÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­neas sumadas",
        "Control",
    ]
    if stock_consolidado.empty and df_pick.empty:
        return pd.DataFrame(columns=columnas_finales)

    base = stock_consolidado.copy() if not stock_consolidado.empty else pd.DataFrame()
    if base.empty:
        base = pd.DataFrame(columns=["articulo", "descripcion", "estado", "unidad", "cantidad", "codigo_normalizado", "lineas_sumadas"])
    base["cantidad"] = pd.to_numeric(base["cantidad"], errors="coerce").fillna(0)

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
            "articulo": "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo",
            "descripcion": "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
            "estado": "Estado",
            "unidad": "Unidad",
            "cantidad": "Stock original Darkinel",
            "mudado_al_polo": "Mudado al Polo",
            "stock_restante_darkinel": "Stock restante Darkinel",
            "codigo_normalizado": "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado",
            "lineas_sumadas": "LÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­neas sumadas",
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


def leer_base_polo_anterior(file_bytes: bytes, filename: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Lee un archivo generado anteriormente por la app para continuar actualizando Polo."""
    if not file_bytes:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    nombre = filename.lower()
    if not nombre.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    buffer = io.BytesIO(file_bytes)
    engine = "xlrd" if nombre.endswith(".xls") else "openpyxl"
    try:
        xls = pd.ExcelFile(buffer, engine=engine)
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def read_sheet(preferida: str) -> pd.DataFrame:
        if preferida in xls.sheet_names:
            return pd.read_excel(xls, sheet_name=preferida, dtype=object)
        return pd.DataFrame()

    stock_polo = read_sheet("STOCK_POLO_LOGISTICO")
    ubicaciones = read_sheet("UBICACION_POLO_LOGISTICO")
    historial = read_sheet("HISTORIAL_MUDANZAS")
    detalle = read_sheet("DETALLE_MUDANZA")
    return stock_polo, ubicaciones, historial, detalle


def detalle_excel_a_pick_items(detalle: pd.DataFrame) -> pd.DataFrame:
    if detalle is None or detalle.empty:
        return pd.DataFrame()

    col_map = {
        "Fecha/Hora": "fecha_hora",
        "DepÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sito origen": "deposito_origen",
        "Deposito origen": "deposito_origen",
        "DepÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sito destino": "deposito_destino",
        "Deposito destino": "deposito_destino",
        "Pallet": "pallet",
        "Cantidad de cajas": "cantidad_bultos",
        "Cantidad de bultos": "cantidad_bultos",
        "Caja": "bulto",
        "Bulto": "bulto",
        "Cajas del item": "bultos_item",
        "Cajas del ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­tem": "bultos_item",
        "Bultos del item": "bultos_item",
        "Bultos del ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­tem": "bultos_item",
        "Caja = Cantidad": "cantidades_bulto",
        "Piezas por caja": "cantidades_bulto",
        "Cantidades por bulto": "cantidades_bulto",
        "UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": "ubicacion",
        "Ubicacion": "ubicacion",
        "Lectura scanner": "lectura_scanner",
        "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": "articulo",
        "Articulo": "articulo",
        "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": "descripcion",
        "Descripcion": "descripcion",
        "Unidad": "unidad",
        "Piezas enviadas": "cantidad_mudada",
        "Cantidad mudada": "cantidad_mudada",
        "Stock original Darkinel": "stock_total",
        "Stock restante Darkinel": "stock_restante_darkinel",
        "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado": "codigo_normalizado",
        "Codigo normalizado": "codigo_normalizado",
        "Observaciones": "observaciones",
    }
    normalizados = {normalizar_codigo(k): v for k, v in col_map.items()}
    salida = pd.DataFrame()
    for col in detalle.columns:
        destino = normalizados.get(normalizar_codigo(col))
        if destino:
            salida[destino] = detalle[col]
    if salida.empty:
        return salida
    salida["item_id"] = range(1, len(salida) + 1)
    return normalizar_df_pick(salida)


def es_ubicacion_real(valor) -> bool:
    ubicacion = str(valor or "").strip().upper()
    return bool(ubicacion and ubicacion not in ["PENDIENTE", "NAN", "NONE"])


def stock_polo_desde_ubicaciones(ubicaciones: pd.DataFrame) -> pd.DataFrame:
    columnas = ["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Stock total Polo", "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado"]
    if ubicaciones is None or ubicaciones.empty:
        return pd.DataFrame(columns=columnas)

    art_col = extraer_columna(ubicaciones, ["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "Articulo"])
    desc_col = extraer_columna(ubicaciones, ["DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Descripcion"])
    piezas_col = extraer_columna(ubicaciones, ["Piezas", "Piezas enviadas", "Piezas en esta caja", "Cantidad mudada"])
    norm_col = extraer_columna(ubicaciones, ["CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado", "Codigo normalizado"])
    ubic_col = extraer_columna(ubicaciones, ["UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Ubicacion", "UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n Polo", "Ubicacion Polo"])

    if not art_col or not piezas_col:
        return pd.DataFrame(columns=columnas)

    trabajo = pd.DataFrame(
        {
            "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": ubicaciones[art_col].astype(str).str.strip(),
            "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": ubicaciones[desc_col].astype(str).str.strip() if desc_col else "",
            "Stock total Polo": pd.to_numeric(ubicaciones[piezas_col], errors="coerce").fillna(0),
            "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado": ubicaciones[norm_col].astype(str).str.strip() if norm_col else ubicaciones[art_col].map(normalizar_codigo),
            "UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": ubicaciones[ubic_col].astype(str).str.strip().str.upper() if ubic_col else "",
        }
    )
    trabajo = trabajo[trabajo["UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n"].apply(es_ubicacion_real)].copy()
    if trabajo.empty:
        return pd.DataFrame(columns=columnas)

    res = (
        trabajo.groupby("CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado", as_index=False)
        .agg(
            **{
                "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": ("ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", _primer_valor_no_vacio),
                "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": ("DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", _primer_valor_no_vacio),
                "Stock total Polo": ("Stock total Polo", "sum"),
            }
        )
    )
    res["Stock total Polo"] = res["Stock total Polo"].apply(formatear_numero)
    return res[["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Stock total Polo", "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado"]]


def stock_polo_actualizado(df_pick: pd.DataFrame, stock_polo_anterior: pd.DataFrame, ubicaciones_anteriores: pd.DataFrame | None = None, salidas: pd.DataFrame | None = None) -> pd.DataFrame:
    columnas = ["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Stock total Polo", "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado"]
    if df_pick is not None and not df_pick.empty:
        ubicaciones_actuales = ubicacion_polo_logistico(df_pick, ubicaciones_anteriores)
        ubicaciones_actuales = aplicar_salidas_a_ubicaciones(ubicaciones_actuales, salidas)
        desde_ubicaciones = stock_polo_desde_ubicaciones(ubicaciones_actuales)
        if desde_ubicaciones.empty:
            return pd.DataFrame(columns=columnas)
        return desde_ubicaciones[columnas]
        trabajo = normalizar_df_pick(df_pick)
        trabajo["cantidad_mudada"] = pd.to_numeric(trabajo["cantidad_mudada"], errors="coerce").fillna(0)
        trabajo = trabajo[(trabajo["codigo_normalizado"].astype(str).str.strip() != "") & (trabajo["cantidad_mudada"] > 0)].copy()
        if trabajo.empty:
            return pd.DataFrame(columns=columnas)
        res = (
            trabajo.groupby("codigo_normalizado", as_index=False)
            .agg(
                articulo=("articulo", _primer_valor_no_vacio),
                descripcion=("descripcion", _primer_valor_no_vacio),
                stock_total_polo=("cantidad_mudada", "sum"),
            )
            .rename(
                columns={
                    "articulo": "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo",
                    "descripcion": "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
                    "stock_total_polo": "Stock total Polo",
                    "codigo_normalizado": "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado",
                }
            )
        )
        res.columns = [columnas[3], columnas[0], columnas[1], columnas[2]]
        res["Stock total Polo"] = res["Stock total Polo"].apply(formatear_numero)
        return res[columnas]

    ubicaciones_consolidadas = ubicacion_polo_logistico(df_pick, ubicaciones_anteriores)
    ubicaciones_consolidadas = aplicar_salidas_a_ubicaciones(ubicaciones_consolidadas, salidas)
    desde_ubicaciones = stock_polo_desde_ubicaciones(ubicaciones_consolidadas)
    if not desde_ubicaciones.empty or not ubicaciones_consolidadas.empty:
        return desde_ubicaciones

    nuevos = pd.DataFrame(columns=columnas)

    if not df_pick.empty:
        trabajo = normalizar_df_pick(df_pick)
        trabajo = trabajo[trabajo["ubicacion"].apply(es_ubicacion_real)].copy()
        if not trabajo.empty:
            nuevos = (
                trabajo.groupby("codigo_normalizado", as_index=False)
                .agg(
                    articulo=("articulo", _primer_valor_no_vacio),
                    descripcion=("descripcion", _primer_valor_no_vacio),
                    stock_total_polo=("cantidad_mudada", "sum"),
                )
                .rename(
                    columns={
                        "articulo": "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo",
                        "descripcion": "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
                        "stock_total_polo": "Stock total Polo",
                        "codigo_normalizado": "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado",
                    }
                )
            )

    anterior = pd.DataFrame(columns=columnas)
    if stock_polo_anterior is not None and not stock_polo_anterior.empty:
        art_col = extraer_columna(stock_polo_anterior, ["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "Articulo"])
        desc_col = extraer_columna(stock_polo_anterior, ["DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Descripcion"])
        stock_col = extraer_columna(stock_polo_anterior, ["Stock total Polo", "Stock Polo LogÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­stico", "Stock Polo", "Cantidad"])
        norm_col = extraer_columna(stock_polo_anterior, ["CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado", "Codigo normalizado"])

        if art_col and stock_col:
            anterior = pd.DataFrame(
                {
                    "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": stock_polo_anterior[art_col].astype(str).str.strip(),
                    "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": stock_polo_anterior[desc_col].astype(str).str.strip() if desc_col else "",
                    "Stock total Polo": pd.to_numeric(stock_polo_anterior[stock_col], errors="coerce").fillna(0),
                    "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado": stock_polo_anterior[norm_col].astype(str).str.strip()
                    if norm_col
                    else stock_polo_anterior[art_col].map(normalizar_codigo),
                }
            )

    combinado = pd.concat([anterior, nuevos], ignore_index=True)
    if combinado.empty:
        return pd.DataFrame(columns=columnas)

    combinado["Stock total Polo"] = pd.to_numeric(combinado["Stock total Polo"], errors="coerce").fillna(0)
    res = (
        combinado.groupby("CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado", as_index=False)
        .agg(
            **{
                "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": ("ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", _primer_valor_no_vacio),
                "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": ("DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", _primer_valor_no_vacio),
                "Stock total Polo": ("Stock total Polo", "sum"),
            }
        )
    )
    res["Stock total Polo"] = res["Stock total Polo"].apply(formatear_numero)
    return res[["ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Stock total Polo", "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado"]]


def ubicacion_polo_logistico(df_pick: pd.DataFrame, ubicaciones_anteriores: pd.DataFrame) -> pd.DataFrame:
    columnas = [
        "Fecha/Hora", "Deposito origen", "Deposito destino", "Pallet", "Cantidad de cajas", "Ubicacion",
        "Articulo", "Descripcion", "Piezas", "Codigo normalizado", "Observaciones",
    ]
    detalle = preparar_detalle_mudanza(df_pick)
    if not detalle.empty:
        seleccion = [
            "Fecha/Hora", "Deposito origen", "Deposito destino", "Pallet", "Cantidad de cajas", "Ubicacion",
            "Articulo", "Descripcion", "Piezas enviadas", "Codigo normalizado", "Observaciones",
        ]
        detalle = detalle[[c for c in seleccion if c in detalle.columns]].rename(columns={"Piezas enviadas": "Piezas"})
    partes_ubicacion = []
    if ubicaciones_anteriores is not None and not ubicaciones_anteriores.empty:
        anterior = limpiar_df_visible(ubicaciones_anteriores.copy())
        anterior["_fuente_actual"] = 0
        partes_ubicacion.append(anterior)
    if detalle is not None and not detalle.empty:
        actual = detalle.copy()
        actual["_fuente_actual"] = 1
        partes_ubicacion.append(actual)
    combinado = pd.concat(partes_ubicacion, ignore_index=True) if partes_ubicacion else pd.DataFrame(columns=columnas)
    if combinado is None or combinado.empty:
        return pd.DataFrame(columns=columnas)
    for col in columnas:
        if col not in combinado.columns:
            combinado[col] = ""
    if "_fuente_actual" not in combinado.columns:
        combinado["_fuente_actual"] = 0
    combinado = combinado[columnas + ["_fuente_actual"]].copy()
    for col in ["Fecha/Hora", "Deposito origen", "Deposito destino", "Ubicacion", "Articulo", "Descripcion", "Codigo normalizado", "Observaciones"]:
        combinado[col] = combinado[col].fillna("").astype(str).str.strip()
    combinado["Pallet"] = pd.to_numeric(combinado["Pallet"], errors="coerce").fillna(0).astype(int)
    combinado["Cantidad de cajas"] = pd.to_numeric(combinado["Cantidad de cajas"], errors="coerce").fillna(0).astype(int)
    combinado["Piezas"] = pd.to_numeric(combinado["Piezas"], errors="coerce").fillna(0)
    identidad_vacia = (
        combinado["Articulo"].astype(str).str.strip().eq("")
        & combinado["Descripcion"].astype(str).str.strip().eq("")
        & combinado["Codigo normalizado"].astype(str).str.strip().eq("")
    )
    ubicacion_vacia = ~combinado["Ubicacion"].apply(es_ubicacion_real)
    combinado = combinado.loc[~(identidad_vacia & ubicacion_vacia)].copy()
    if combinado.empty:
        return pd.DataFrame(columns=columnas)
    ubicacion_upper = combinado["Ubicacion"].astype(str).str.strip().str.upper()
    combinado["_ubicacion_real"] = (~ubicacion_upper.isin(["", "PENDIENTE", "NAN"])).astype(int)
    combinado["_fuente_actual"] = pd.to_numeric(combinado["_fuente_actual"], errors="coerce").fillna(0).astype(int)
    combinado["_orden_original"] = range(len(combinado))
    claves_linea = ["Fecha/Hora", "Deposito origen", "Deposito destino", "Pallet", "Cantidad de cajas", "Articulo", "Descripcion", "Piezas", "Observaciones"]
    combinado["_ocurrencia"] = combinado.groupby(claves_linea + ["_fuente_actual"], dropna=False).cumcount()
    claves_unicas = claves_linea + ["_ocurrencia"]
    combinado = (
        combinado.sort_values(["_fuente_actual", "_ubicacion_real", "_orden_original"], ascending=[False, False, False])
        .drop_duplicates(claves_unicas, keep="first")
        .sort_values(["Pallet", "Cantidad de cajas", "Fecha/Hora", "Articulo", "_orden_original"])
        .drop(columns=["_fuente_actual", "_ubicacion_real", "_orden_original", "_ocurrencia"], errors="ignore")
        .reset_index(drop=True)
    )
    combinado["Pallet"] = combinado["Pallet"].replace(0, "")
    combinado["Cantidad de cajas"] = combinado["Cantidad de cajas"].replace(0, "")
    combinado["Piezas"] = combinado["Piezas"].apply(formatear_numero)
    return combinado[columnas]


def historial_mudanzas(df_pick: pd.DataFrame, historial_anterior: pd.DataFrame) -> pd.DataFrame:
    actual = preparar_detalle_mudanza(df_pick)
    partes_historial = []
    if historial_anterior is not None and not historial_anterior.empty:
        anterior = historial_anterior.copy()
        anterior["_fuente_actual"] = 0
        partes_historial.append(anterior)
    if actual is not None and not actual.empty:
        actual = actual.copy()
        actual["_fuente_actual"] = 1
        partes_historial.append(actual)

    if not partes_historial:
        return actual

    combinado = pd.concat(partes_historial, ignore_index=True)
    ubic_col = extraer_columna(combinado, ["UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n", "Ubicacion"])
    if not ubic_col:
        return combinado.drop(columns=["_fuente_actual"], errors="ignore")

    combinado["_ubicacion_real"] = combinado[ubic_col].apply(es_ubicacion_real).astype(int)
    combinado["_fuente_actual"] = pd.to_numeric(combinado["_fuente_actual"], errors="coerce").fillna(0).astype(int)
    combinado["_orden_original"] = range(len(combinado))

    excluir_clave = {
        "_fuente_actual",
        "_ubicacion_real",
        "_orden_original",
        ubic_col,
        extraer_columna(combinado, ["CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado", "Codigo normalizado"]),
        extraer_columna(combinado, ["Stock restante Darkinel"]),
    }
    claves_linea = [c for c in combinado.columns if c not in excluir_clave and not str(c).startswith("_")]
    combinado["_ocurrencia"] = combinado.groupby(claves_linea + ["_fuente_actual"], dropna=False).cumcount()
    claves_unicas = claves_linea + ["_ocurrencia"]
    orden_cols = [c for c in ["Pallet", "Caja", "Fecha/Hora", "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo", "_orden_original"] if c in combinado.columns]

    return (
        combinado.sort_values(["_fuente_actual", "_ubicacion_real", "_orden_original"], ascending=[False, False, False])
        .drop_duplicates(claves_unicas, keep="first")
        .sort_values(orden_cols)
        .drop(columns=["_fuente_actual", "_ubicacion_real", "_orden_original", "_ocurrencia"], errors="ignore")
        .reset_index(drop=True)
    )


def preparar_recepcion_polo(df_pick: pd.DataFrame) -> pd.DataFrame:
    columnas = [
        "Fecha recepcion", "Receptor", "OK recepcion", "Pallet", "Caja", "Ubicacion informada",
        "Articulo", "Descripcion", "Unidad", "Piezas enviadas", "Piezas recibidas", "Diferencia",
        "Codigo normalizado", "Observaciones recepcion",
    ]
    if df_pick.empty:
        return pd.DataFrame(columns=columnas)
    trabajo = normalizar_df_pick(df_pick)
    recepcion = trabajo.copy()
    recepcion["diferencia"] = pd.to_numeric(recepcion["cantidad_recibida"], errors="coerce").fillna(0) - pd.to_numeric(recepcion["cantidad_mudada"], errors="coerce").fillna(0)
    origen = [
        "fecha_recepcion", "receptor", "recepcion_ok", "pallet", "bulto", "ubicacion_recepcion",
        "articulo", "descripcion", "unidad", "cantidad_mudada", "cantidad_recibida", "diferencia",
        "codigo_normalizado", "observaciones_recepcion",
    ]
    salida = pd.DataFrame()
    for col_origen, col_destino in zip(origen, columnas):
        salida[col_destino] = recepcion[col_origen] if col_origen in recepcion.columns else ""
    return salida


def generar_excel_control(
    stock_consolidado: pd.DataFrame,
    df_pick: pd.DataFrame,
    stock_polo_anterior: pd.DataFrame,
    ubicaciones_anteriores: pd.DataFrame,
    historial_anterior: pd.DataFrame,
    salidas_polo: pd.DataFrame | None = None,
) -> bytes:
    darkinel = limpiar_df_visible(stock_darkinel_actualizado(stock_consolidado, df_pick))
    polo = limpiar_df_visible(stock_polo_actualizado(df_pick, stock_polo_anterior, ubicaciones_anteriores, salidas_polo))
    ubicacion = limpiar_df_visible(aplicar_salidas_a_ubicaciones(ubicacion_polo_logistico(df_pick, ubicaciones_anteriores), salidas_polo))
    historial = limpiar_df_visible(historial_mudanzas(df_pick, historial_anterior))
    resumen = limpiar_df_visible(resumen_pallets(df_pick))
    detalle = limpiar_df_visible(preparar_detalle_mudanza(df_pick))
    recepcion = limpiar_df_visible(preparar_recepcion_polo(df_pick))
    salidas_export = limpiar_df_visible(mostrar_salidas_polo(salidas_polo_df() if salidas_polo is None else salidas_polo))

    resumen_depositos = pd.DataFrame(
        [
            {
                "DepÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sito": "DARKINEL",
                "Cantidad de cÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digos": int((pd.to_numeric(darkinel["Stock restante Darkinel"], errors="coerce").fillna(0) > 0).sum()) if not darkinel.empty else 0,
                "Piezas totales": formatear_numero(pd.to_numeric(darkinel["Stock restante Darkinel"], errors="coerce").fillna(0).sum()) if not darkinel.empty else 0,
            },
            {
                "DepÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sito": "POLO LOGISTICO",
                "Cantidad de cÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digos": int((pd.to_numeric(polo["Stock total Polo"], errors="coerce").fillna(0) > 0).sum()) if not polo.empty else 0,
                "Piezas totales": formatear_numero(pd.to_numeric(polo["Stock total Polo"], errors="coerce").fillna(0).sum()) if not polo.empty else 0,
            },
        ]
    )

    resumen_depositos.columns = ["Deposito", "Cantidad de codigos", "Piezas totales"]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        darkinel.to_excel(writer, index=False, sheet_name="STOCK_DARKINEL_ACTUALIZADO")
        polo.to_excel(writer, index=False, sheet_name="STOCK_POLO_LOGISTICO")
        ubicacion.to_excel(writer, index=False, sheet_name="UBICACION_POLO_LOGISTICO")
        historial.to_excel(writer, index=False, sheet_name="HISTORIAL_MUDANZAS")
        salidas_export.to_excel(writer, index=False, sheet_name="SALIDAS_POLO")
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
                    max_len = max(max_len, min(len(val), 45))
                ws.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 47)

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


def filas_packing_list(trabajo: pd.DataFrame, caja: int | None = None) -> List[Dict[str, object]]:
    filas = []
    for r in trabajo.itertuples():
        articulo = str(getattr(r, "articulo", "")).strip()
        descripcion = str(getattr(r, "descripcion", "")).strip()
        cantidad_total = numero_seguro(getattr(r, "cantidad_mudada", 0), 0)
        distribucion = parsear_cantidades_por_bulto(getattr(r, "cantidades_bulto", ""), cantidad_total, getattr(r, "bulto", 1))
        if not distribucion and cantidad_total > 0:
            distribucion = {entero_seguro(getattr(r, "bulto", 1), 1): cantidad_total}

        if caja is not None:
            piezas = float(distribucion.get(int(caja), 0))
            if piezas <= 0 and entero_seguro(getattr(r, "bulto", 1), 1) == int(caja):
                piezas = cantidad_total
            if piezas > 0:
                filas.append({"caja": int(caja), "articulo": articulo, "descripcion": descripcion, "piezas": piezas})
        else:
            for caja_item, piezas in sorted(distribucion.items()):
                if float(piezas) > 0:
                    filas.append({"caja": int(caja_item), "articulo": articulo, "descripcion": descripcion, "piezas": float(piezas)})
    return filas


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
        filas_pagina = filas_packing_list(trabajo, int(bulto) if bulto is not None else None)
        subtitulo = f"CAJA {bulto} DE {cantidad_bultos}" if bulto is not None else f"CAJAS: {cantidad_bultos}"
        unidades_pagina = formatear_numero(sum(float(f["piezas"]) for f in filas_pagina)) if filas_pagina else "0"
        filas_html = []
        for fila in sorted(filas_pagina, key=lambda x: (x["caja"], x["articulo"], x["descripcion"])):
            articulo = str(fila["articulo"]).strip()
            codigo_barra = codigo_barra_articulo(articulo, corregir_guion_teclado)
            descripcion = str(fila["descripcion"]).strip()
            cantidad = formatear_numero(fila["piezas"])
            filas_html.append(
                "<tr>"
                f"<td class='caja'>{_html_escape(fila['caja'])}</td>"
                f"<td class='art'>{_html_escape(articulo)}</td>"
                f"<td>{_html_escape(descripcion)}</td>"
                f"<td class='cant'>{_html_escape(cantidad)}</td>"
                f"<td class='bar'>{_codigo_barra_code39_svg(codigo_barra)}<div>{_html_escape(articulo)}</div></td>"
                "</tr>"
            )
        if not filas_html:
            filas_html.append("<tr><td colspan='5' class='empty'>Sin articulos cargados para esta caja</td></tr>")

        pages.append(
            f"""
            <section class="page">
                <header>
                    <div class="title">PALLET {int(pallet)}</div>
                    <div class="meta">
                        <strong>{subtitulo}</strong><br>
                        Piezas: {unidades_pagina}<br>
                        Fecha: {_html_escape(fecha)}
                    </div>
                </header>
                <table>
                    <thead>
                        <tr><th>Caja</th><th>Articulo</th><th>Descripcion</th><th>Piezas</th><th>Codigo de barras</th></tr>
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
            .caja {{ width: 8%; text-align: center; font-weight: 700; }}
            .art {{ width: 22%; font-weight: 700; }}
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
        subtitulo = f"CAJA {bulto} DE {cantidad_bultos}" if bulto is not None else f"CAJAS: {cantidad_bultos}"
        filas_pagina = filas_packing_list(trabajo, int(bulto) if bulto is not None else None)
        unidades_pagina = formatear_numero(sum(float(f["piezas"]) for f in filas_pagina)) if filas_pagina else "0"

        header = Table(
            [
                [
                    Paragraph(f"<b>{titulo}</b>", styles["Title"]),
                    Paragraph(f"<b>{subtitulo}</b><br/>Piezas: {unidades_pagina}<br/>Fecha: {fecha}", styles["Normal"]),
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

        rows = [["Caja", "Articulo", "Descripcion", "Piezas", "Codigo de barras"]]
        for fila in sorted(filas_pagina, key=lambda x: (x["caja"], x["articulo"], x["descripcion"])):
            articulo = str(fila["articulo"]).strip()
            codigo_barra = codigo_barra_articulo(articulo, corregir_guion_teclado)
            descripcion = str(fila["descripcion"]).strip()
            cantidad = formatear_numero(fila["piezas"])
            rows.append(
                [
                    Paragraph(str(fila["caja"]), styles["Normal"]),
                    Paragraph(articulo, styles["Normal"]),
                    Paragraph(descripcion[:80], styles["Normal"]),
                    Paragraph(str(cantidad), styles["Normal"]),
                    [_barcode_articulo_flowable(codigo_barra), Paragraph(articulo, barcode_text_style)],
                ]
            )

        if len(rows) == 1:
            rows.append(["", "", "Sin articulos cargados para esta caja", "", ""])

        tabla = Table(rows, colWidths=[14 * mm, 32 * mm, 54 * mm, 15 * mm, 75 * mm], repeatRows=1)
        tabla.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.black),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (0, 1), (0, -1), "CENTER"),
                    ("ALIGN", (3, 1), (4, -1), "CENTER"),
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
    guardar_mudanza_actual_db(fusionar_con_nube=False)


# -----------------------------
# Interfaz
# -----------------------------
inicializar_estado()

st.title("Lector de codigos + Mudanza Darkinel -> Polo Logistico")
st.caption(
    "Busca codigos en la base, arma pallets, registra ubicaciones, controla salidas de Polo y genera las bases actualizadas de DARKINEL y POLO LOGISTICO."
)

with st.sidebar:
    st.header("Base de stock")
    if nube_disponible():
        st.success("Base en nube conectada")
    else:
        st.warning("Sin nube: guardado local SQLite")
        st.caption("Para compartir datos entre usuarios en Streamlit Cloud, configura Supabase en Secrets.")
    uploaded = st.file_uploader("Subi el archivo de stock de DARKINEL", type=["xls", "xlsx", "xlsm", "csv"])

    stock_guardado_sidebar = cargar_archivo_estado("stock_darkinel_actual")
    if stock_guardado_sidebar:
        st.caption(f"Stock guardado: {stock_guardado_sidebar.get('nombre', 'archivo')} | {fecha_estado_db('stock_darkinel_actual')}")
        if uploaded is not None and st.button("Guardar este stock ahora"):
            guardar_archivo_estado("stock_darkinel_actual", uploaded.name, uploaded.getvalue())
            st.success("Stock guardado.")
            st.rerun()
    elif uploaded is not None and st.button("Guardar este stock ahora"):
        guardar_archivo_estado("stock_darkinel_actual", uploaded.name, uploaded.getvalue())
        st.success("Stock guardado.")
        st.rerun()

    st.markdown("---")
    st.subheader("Frecuencia opcional")
    uploaded_frecuencia = st.file_uploader(
        "Subi archivo de frecuencia / meses de venta",
        type=["xls", "xlsx", "xlsm", "csv"],
        help="Debe tener una columna de Articulo/Codigo y una columna Frecuencia/Categoria o Meses.",
    )

    frecuencia_guardada_sidebar = cargar_archivo_estado("frecuencia_ventas_actual")
    usar_frecuencia_guardada = False
    if frecuencia_guardada_sidebar:
        usar_frecuencia_guardada = st.checkbox(
            f"Usar ventas guardadas ({frecuencia_guardada_sidebar.get('nombre', 'archivo')})",
            value=uploaded_frecuencia is None,
        )
        st.caption(f"Ventas guardadas: {fecha_estado_db('frecuencia_ventas_actual')}")
        if uploaded_frecuencia is not None and st.button("Guardar estas ventas ahora"):
            guardar_archivo_estado("frecuencia_ventas_actual", uploaded_frecuencia.name, uploaded_frecuencia.getvalue())
            st.success("Ventas guardadas.")
            st.rerun()
    elif uploaded_frecuencia is not None and st.button("Guardar estas ventas ahora"):
        guardar_archivo_estado("frecuencia_ventas_actual", uploaded_frecuencia.name, uploaded_frecuencia.getvalue())
        st.success("Ventas guardadas.")
        st.rerun()

    st.markdown("---")
    st.subheader("Base Polo anterior opcional")
    uploaded_polo = st.file_uploader(
        "Subi el ultimo control generado para seguir actualizando el POLO",
        type=["xls", "xlsx", "xlsm"],
        help="Opcional. Si lo subis, la app toma esa mudanza y ubicaciones para continuar el control del Polo Logistico.",
    )

    st.markdown("---")
    polo_guardado_sidebar = cargar_archivo_estado("control_polo_actual")
    usar_polo_guardado = False
    if polo_guardado_sidebar:
        usar_polo_guardado = st.checkbox(
            f"Usar control Polo guardado ({polo_guardado_sidebar.get('nombre', 'archivo')})",
            value=uploaded_polo is None,
        )
        st.caption(f"Control Polo guardado: {fecha_estado_db('control_polo_actual')}")
        if uploaded_polo is not None and st.button("Guardar este control Polo ahora"):
            guardar_archivo_estado("control_polo_actual", uploaded_polo.name, uploaded_polo.getvalue())
            st.success("Control Polo guardado.")
            st.rerun()
    elif uploaded_polo is not None and st.button("Guardar este control Polo ahora"):
        guardar_archivo_estado("control_polo_actual", uploaded_polo.name, uploaded_polo.getvalue())
        st.success("Control Polo guardado.")
        st.rerun()

    st.subheader("Datos de mudanza")
    deposito_origen = st.text_input("Deposito origen", value="DARKINEL")
    deposito_destino = st.text_input("Deposito destino", value="POLO LOGISTICO")
    pallet_activo = st.number_input("Pallet activo", min_value=1, value=1, step=1)
    cantidad_bultos_activo = st.number_input("Cantidad de cajas del pallet", min_value=1, value=1, step=1)
    bulto_activo = st.number_input("Caja activa", min_value=1, max_value=int(cantidad_bultos_activo), value=1, step=1)
    ubicacion_default = st.text_input(
        "Ubicacion base opcional",
        value="",
        help="Podes dejarla vacia al cargar la mudanza y completarla cuando llegue al Polo. Ejemplo final: 1-L-3",
    )

    st.markdown("---")
    if st.button("Vaciar mudanza actual", type="secondary"):
        limpiar_mudanza_actual()
        st.success("Mudanza actual vaciada.")
        st.rerun()

    st.caption(f"Base de avance: {fecha_estado_db('mudanza_actual') or 'sin guardado'}")

    st.markdown("---")
    st.subheader("Ejemplos reales")
    st.code(
        "Mazda: B6Y114302A  J\n"
        "Mazda: PE0110602   Y\n"
        "Kia: # 865141W200        JJ15\n"
        "Kia: 252122E820        JC25",
        language="text",
    )

stock_guardado = cargar_archivo_estado("stock_darkinel_actual")
if uploaded is not None:
    stock_bytes = uploaded.getvalue()
    stock_filename = uploaded.name
    guardar_archivo_si_cambio("stock_darkinel_actual", stock_filename, stock_bytes)
elif stock_guardado:
    stock_bytes = stock_guardado["contenido"]
    stock_filename = stock_guardado.get("nombre", "stock_guardado.xlsx")
    st.info(f"Usando stock guardado en la base: {stock_filename}")
else:
    st.info("Subi el Excel de stock de DARKINEL para empezar.")
    st.stop()

try:
    stock_df = cargar_stock(stock_bytes, stock_filename)
except ImportError as e:
    st.error("No se pudo leer el archivo .xls porque falta la libreria xlrd.")
    st.code("xlrd>=2.0.1", language="text")
    st.exception(e)
    st.stop()
except Exception as e:
    st.error("No se pudo leer el archivo de stock. Revisa que sea .xls, .xlsx o .csv valido.")
    st.exception(e)
    st.stop()

if stock_df.empty:
    st.error("No encontre articulos con cantidad mayor a cero en el archivo.")
    st.stop()

stock_consolidado = consolidar_por_codigo(stock_df)
frecuencia_guardada = cargar_archivo_estado("frecuencia_ventas_actual")
if uploaded_frecuencia is not None:
    try:
        frecuencia_bytes = uploaded_frecuencia.getvalue()
        frecuencia_filename = uploaded_frecuencia.name
        guardar_archivo_si_cambio("frecuencia_ventas_actual", frecuencia_filename, frecuencia_bytes)
        frecuencias_df = leer_frecuencias(frecuencia_bytes, frecuencia_filename)
        if frecuencias_df.empty:
            st.sidebar.warning("No pude leer codigos/frecuencia del archivo de frecuencia.")
        else:
            st.sidebar.success(f"Frecuencias cargadas: {len(frecuencias_df)} codigos")
    except Exception as e:
        frecuencias_df = pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])
        st.sidebar.error("No pude leer el archivo de frecuencia.")
        st.sidebar.exception(e)
elif frecuencia_guardada and usar_frecuencia_guardada:
    try:
        frecuencia_bytes = frecuencia_guardada["contenido"]
        frecuencia_filename = frecuencia_guardada.get("nombre", "ventas_guardadas.xlsx")
        frecuencias_df = leer_frecuencias(frecuencia_bytes, frecuencia_filename)
        if frecuencias_df.empty:
            st.sidebar.warning("No pude leer codigos/frecuencia de las ventas guardadas.")
        else:
            st.sidebar.info(f"Usando ventas guardadas: {frecuencia_filename}")
    except Exception as e:
        frecuencias_df = pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])
        st.sidebar.error("No pude leer las ventas guardadas.")
        st.sidebar.exception(e)
else:
    frecuencias_df = pd.DataFrame(columns=["codigo_normalizado", "frecuencia", "meses_venta"])

polo_guardado = cargar_archivo_estado("control_polo_actual")
if uploaded_polo is not None:
    polo_bytes = uploaded_polo.getvalue()
    polo_filename = uploaded_polo.name
    guardar_archivo_si_cambio("control_polo_actual", polo_filename, polo_bytes)
    stock_polo_anterior, ubicaciones_anteriores, historial_anterior, detalle_mudanza_anterior = leer_base_polo_anterior(polo_bytes, polo_filename)
elif polo_guardado and usar_polo_guardado:
    polo_bytes = polo_guardado["contenido"]
    polo_filename = polo_guardado.get("nombre", "control_polo_guardado.xlsx")
    stock_polo_anterior, ubicaciones_anteriores, historial_anterior, detalle_mudanza_anterior = leer_base_polo_anterior(polo_bytes, polo_filename)
else:
    stock_polo_anterior, ubicaciones_anteriores, historial_anterior, detalle_mudanza_anterior = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_pick = pick_items_df()
df_reimpresion = detalle_excel_a_pick_items(detalle_mudanza_anterior)
df_operativo = df_pick if not df_pick.empty else df_reimpresion
usando_control_anterior = df_pick.empty and not df_reimpresion.empty
mudanza_activa_es_control_anterior = misma_mudanza(df_pick, df_reimpresion)
ubicaciones_operativas = pd.DataFrame() if usando_control_anterior or mudanza_activa_es_control_anterior else ubicaciones_anteriores
salidas_polo_actual = salidas_polo_df()
stock_darkinel_metric = stock_darkinel_actualizado(stock_consolidado, df_operativo)
stock_polo_metric = stock_polo_actualizado(df_operativo, stock_polo_anterior, ubicaciones_operativas, salidas_polo_actual)
piezas_darkinel_metric = int(pd.to_numeric(stock_darkinel_metric.get("Stock restante Darkinel", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
piezas_polo_metric = int(pd.to_numeric(stock_polo_metric.get("Stock total Polo", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())

if (uploaded_polo is not None or (polo_guardado and usar_polo_guardado)) and not df_reimpresion.empty:
    st.info(f"El control anterior cargado trae {len(df_reimpresion)} lineas de mudanza.")
    if df_pick.empty:
        if st.button("Usar control anterior como mudanza activa", type="primary"):
            st.session_state.pick_items = df_reimpresion.to_dict("records")
            st.session_state.pick_seq = int(pd.to_numeric(df_reimpresion["item_id"], errors="coerce").fillna(0).max())
            guardar_mudanza_actual_db(fusionar_con_nube=False)
            st.success("Mudanza cargada desde el control anterior.")
            st.rerun()
    else:
        if st.button("Reemplazar mudanza actual por control anterior"):
            st.session_state.pick_items = df_reimpresion.to_dict("records")
            st.session_state.pick_seq = int(pd.to_numeric(df_reimpresion["item_id"], errors="coerce").fillna(0).max())
            guardar_mudanza_actual_db(fusionar_con_nube=False)
            st.success("Mudanza reemplazada por el control anterior.")
            st.rerun()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Codigos con stock", f"{len(stock_consolidado):,}".replace(",", "."))
col2.metric("Piezas en Darkinel", f"{piezas_darkinel_metric:,}".replace(",", "."))
col3.metric("Piezas en Polo Logistico", f"{piezas_polo_metric:,}".replace(",", "."))
col4.metric("Piezas en mudanza", f"{int(pd.to_numeric(df_operativo.get('cantidad_mudada', pd.Series(dtype=float)), errors='coerce').fillna(0).sum()):,}".replace(",", "."))

st.markdown("---")

tab_buscar, tab_pallets, tab_recepcion, tab_salidas, tab_bases, tab_stock = st.tabs(
    ["1) Buscar y pickear", "2) Pallets / mudanza", "3) Recepcion Polo", "4) Salidas Polo", "5) Bases actualizadas", "6) Consulta stock"]
)

with tab_buscar:
    modo = st.radio("Modo de busqueda", ["Un codigo", "Varios codigos"], horizontal=True)

    if modo == "Un codigo":
        codigo = st.text_input("Escanea o digita el codigo", placeholder="Ejemplo: B6Y114302A J")

        if codigo:
            exactos, info = buscar_exactos(stock_consolidado, codigo)

            with st.expander("Ver como interpreto el codigo", expanded=False):
                st.write("**Lectura original:**", info["lectura_original"])
                st.write("**Tokens limpios:**", info["tokens_limpios"])
                st.write("**Sufijos detectados:**", info["sufijos"])
                st.write("**Candidatos de busqueda:**", info["candidatos"])

            if not exactos.empty:
                st.success(f"Encontre {len(exactos)} articulo(s) con stock consolidado.")
                st.dataframe(limpiar_df_visible(preparar_resultado_para_mostrar(exactos)), use_container_width=True, hide_index=True)
                permitir_agregar_desde_base = True
                sugerencias = pd.DataFrame()
            else:
                st.warning("No encontre coincidencia exacta con stock. Te muestro sugerencias posibles.")
                sugerencias = buscar_sugerencias(stock_consolidado, info["candidatos"])
                if sugerencias.empty:
                    st.info("No hay sugerencias para esa lectura.")
                else:
                    st.dataframe(limpiar_df_visible(preparar_resultado_para_mostrar(sugerencias)), use_container_width=True, hide_index=True)
                permitir_agregar_desde_base = False
                st.info("Elegi una sugerencia si corresponde al articulo leido. Si ninguna sirve, cargalo como articulo nuevo/manual.")

            if permitir_agregar_desde_base and not exactos.empty:
                formulario_agregar_desde_base(
                    codigo,
                    exactos,
                    "Agregar a mudanza",
                    "form_agregar_un_codigo",
                    pallet_activo,
                    cantidad_bultos_activo,
                    bulto_activo,
                    ubicacion_default,
                    deposito_origen,
                    deposito_destino,
                )

            if not permitir_agregar_desde_base and not sugerencias.empty:
                formulario_agregar_desde_base(
                    codigo,
                    sugerencias,
                    "Usar una sugerencia",
                    "form_agregar_sugerencia",
                    pallet_activo,
                    cantidad_bultos_activo,
                    bulto_activo,
                    ubicacion_default,
                    deposito_origen,
                    deposito_destino,
                )

            if not permitir_agregar_desde_base:
                st.subheader("Agregar articulo manual")
                st.caption("Usalo cuando el articulo no existe en el Excel/base cargada. No descuenta stock de DARKINEL, pero si entra a la mudanza y al POLO.")
                with st.form("form_agregar_manual"):
                    m1, m2, m3 = st.columns([1.2, 2, 0.8])
                    articulo_manual = m1.text_input("Articulo", value=str(codigo).strip().upper())
                    descripcion_manual = m2.text_input("Descripcion", value="")
                    unidad_manual = m3.text_input("Unidad", value="uni")

                    m4, m5, m6, m7, m8, m9 = st.columns(6)
                    cantidad_manual = m4.number_input("Piezas a mudar", min_value=1.0, value=1.0, step=1.0, key="cantidad_manual")
                    stock_darkinel_manual = m5.number_input("Queda en Darkinel", min_value=0.0, value=0.0, step=1.0, key="stock_darkinel_manual")
                    pallet_manual = m6.number_input("Pallet", min_value=1, value=int(pallet_activo), step=1, key="pallet_manual")
                    cantidad_bultos_manual = m7.number_input("Cantidad de cajas", min_value=1, value=int(cantidad_bultos_activo), step=1, key="cantidad_bultos_manual")
                    bulto_manual = m8.number_input("Caja", min_value=1, max_value=int(cantidad_bultos_manual), value=min(int(bulto_activo), int(cantidad_bultos_manual)), step=1, key="bulto_manual")
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
                            bultos_item="",
                            cantidades_bulto=f"Caja {int(bulto_manual)} = Cantidad {formatear_numero(cantidad_manual)}",
                            ubicacion=ubicacion_manual,
                            deposito_origen=deposito_origen,
                            deposito_destino=deposito_destino,
                            observaciones=observaciones_manual,
                            validar_stock=False,
                        )
                        if ok:
                            guardar_mudanza_actual_db()
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    else:
        codigos_texto = st.text_area("Pega varios codigos, uno por linea", height=160)
        st.caption("En este modo la app busca y muestra el primer match de cada linea. Para registrar ubicacion exacta, conviene agregar de a un codigo.")
        col_buscar_varios, col_agregar_varios = st.columns([1, 2])
        buscar_varios = col_buscar_varios.button("Buscar varios")
        agregar_varios = col_agregar_varios.button("Buscar y agregar a mudanza", type="primary")
        if (buscar_varios or agregar_varios) and codigos_texto.strip():
            filas = []
            agregados = 0
            errores = []
            manual_pendientes = []
            for linea in codigos_texto.splitlines():
                linea = linea.strip()
                if not linea:
                    continue
                exactos, info = buscar_exactos(stock_consolidado, linea)
                if exactos.empty:
                    manual_pendientes.append(linea)
                    sugerencias = buscar_sugerencias(stock_consolidado, info["candidatos"], limite=1)
                    if sugerencias.empty:
                        filas.append({"Lectura": linea, "Resultado": "Sin exacto - cargar manual", "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": linea.strip().upper(), "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": "", "Stock total": ""})
                    else:
                        row_sug = sugerencias.iloc[0]
                        filas.append(
                            {
                                "Lectura": linea,
                                "Resultado": "Sugerencia no agregada",
                                "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": row_sug.get("articulo", ""),
                                "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": row_sug.get("descripcion", ""),
                                "Stock total": row_sug.get("cantidad", ""),
                            }
                        )
                    continue
                else:
                    base = exactos
                    tipo = "Exacto"
                if base.empty:
                    filas.append({"Lectura": linea, "Resultado": "Sin stock encontrado", "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": "", "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": "", "Stock total": ""})
                else:
                    row = base.iloc[0]
                    filas.append(
                        {
                            "Lectura": linea,
                            "Resultado": tipo,
                            "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo": row.get("articulo", ""),
                            "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n": row.get("descripcion", ""),
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
                            bultos_item=str(bulto_activo),
                            cantidades_bulto=f"Caja {int(bulto_activo)} = Cantidad 1",
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
            st.dataframe(limpiar_df_visible(pd.DataFrame(filas)), use_container_width=True, hide_index=True)
            st.session_state["lecturas_manual_pendientes"] = list(dict.fromkeys(manual_pendientes))
            if agregar_varios:
                if agregados:
                    st.success(f"Agregue {agregados} articulo(s) a la mudanza.")
                if errores:
                    st.warning("Algunas lineas no se pudieron agregar:")
                    st.write(errores)
                if agregados:
                    guardar_mudanza_actual_db()
                    st.rerun()

        lecturas_manual_pendientes = st.session_state.get("lecturas_manual_pendientes", [])
        if lecturas_manual_pendientes:
            st.markdown("---")
            st.info("Estas lecturas no tuvieron coincidencia exacta. Podes cargar una como articulo nuevo/manual.")
            lectura_manual_varios = st.selectbox("Lectura a cargar manualmente", lecturas_manual_pendientes, key="lectura_manual_varios")
            form_key_manual_varios = f"form_manual_varios_{normalizar_codigo(lectura_manual_varios)[:24] or 'sin_codigo'}"
            formulario_agregar_manual(
                lectura_manual_varios,
                "Agregar articulo manual",
                form_key_manual_varios,
                pallet_activo,
                cantidad_bultos_activo,
                bulto_activo,
                ubicacion_default,
                deposito_origen,
                deposito_destino,
                pendientes_key="lecturas_manual_pendientes",
            )

with tab_pallets:
    st.subheader("Control de pallets hechos")
    pallets_actuales = set(pd.to_numeric(df_operativo.get("pallet", pd.Series(dtype=float)), errors="coerce").dropna().astype(int).tolist()) if not df_operativo.empty else set()
    max_pallet_actual = max(pallets_actuales) if pallets_actuales else 0
    p_ctrl1, p_ctrl2, p_ctrl3 = st.columns([1, 1, 2])
    hasta_pallet = p_ctrl1.number_input("Ultimo pallet impreso", min_value=1, value=max(52, max_pallet_actual or 1), step=1)
    cajas_faltantes = p_ctrl2.number_input("Cajas por pallet faltante", min_value=1, value=int(cantidad_bultos_activo), step=1)
    faltantes = [p for p in range(1, int(hasta_pallet) + 1) if p not in pallets_actuales]
    p_ctrl3.write(f"Pallets faltantes: {', '.join(map(str, faltantes[:20]))}{'...' if len(faltantes) > 20 else ''}" if faltantes else "No hay pallets faltantes en ese rango.")
    if st.button("Registrar pallets faltantes sin detalle"):
        if not faltantes:
            st.info("No hay pallets faltantes para registrar.")
        else:
            for pallet_faltante in faltantes:
                registrar_pallet_sin_detalle(
                    pallet_faltante,
                    int(cajas_faltantes),
                    deposito_origen,
                    deposito_destino,
                    observaciones="Pallet impreso/hecho, pendiente completar articulos",
                )
            guardar_mudanza_actual_db()
            st.success(f"Registre {len(faltantes)} pallet(s) faltante(s) para no perder la numeracion.")
            st.rerun()

    with st.expander("Cargar pallet faltante con detalle de articulos", expanded=False):
        st.caption("Usalo cuando el pallet existe impreso pero no quedo en el sistema. Formato recomendado: codigo; descripcion; piezas. Tambien acepta: caja; codigo; descripcion; piezas.")
        fp1, fp2, fp3 = st.columns([1, 1, 1])
        pallet_faltante_detalle = fp1.number_input("Pallet faltante", min_value=1, value=max_pallet_actual + 1 if max_pallet_actual else 1, step=1, key="pallet_faltante_detalle")
        cajas_faltante_detalle = fp2.number_input("Cantidad de cajas", min_value=1, value=1, step=1, key="cajas_faltante_detalle")
        ubicacion_faltante_detalle = fp3.text_input("Ubicacion inicial", value="PENDIENTE", key="ubicacion_faltante_detalle")
        texto_faltante = st.text_area(
            "Lineas del pallet",
            height=140,
            placeholder="KDY3-62-31XA; ESPOLON; 2\nTKY0-52-31XD; ESPOLON; 1",
            key="texto_pallet_faltante",
        )
        lineas_faltante = parsear_lineas_pallet_faltante(texto_faltante)
        if lineas_faltante:
            st.dataframe(pd.DataFrame(lineas_faltante).rename(columns={"caja": "Caja", "codigo": "Articulo", "descripcion": "Descripcion", "piezas": "Piezas"}), use_container_width=True, hide_index=True)
        if st.button("Agregar este pallet faltante a la mudanza", type="primary"):
            if not lineas_faltante:
                st.error("No pude leer lineas validas. Usa por ejemplo: KDY3-62-31XA; ESPOLON; 2")
            else:
                agregados_faltante = 0
                for linea in lineas_faltante:
                    row_manual = pd.Series(
                        {
                            "articulo": linea["codigo"],
                            "descripcion": linea["descripcion"],
                            "estado": "MANUAL",
                            "unidad": "uni",
                            "cantidad": linea["piezas"],
                            "codigo_normalizado": normalizar_codigo(linea["codigo"]),
                        }
                    )
                    ok, _msg = agregar_item_a_mudanza(
                        lectura_original=linea["codigo"],
                        row=row_manual,
                        cantidad_mudada=linea["piezas"],
                        pallet=int(pallet_faltante_detalle),
                        cantidad_bultos=int(cajas_faltante_detalle),
                        bulto=min(int(linea["caja"]), int(cajas_faltante_detalle)),
                        bultos_item="",
                        cantidades_bulto=f"Caja {min(int(linea['caja']), int(cajas_faltante_detalle))} = Cantidad {formatear_numero(linea['piezas'])}",
                        ubicacion=ubicacion_faltante_detalle,
                        deposito_origen=deposito_origen,
                        deposito_destino=deposito_destino,
                        observaciones="Pallet faltante cargado desde hoja impresa",
                        validar_stock=False,
                    )
                    if ok:
                        agregados_faltante += 1
                guardar_mudanza_actual_db()
                st.success(f"Agregue {agregados_faltante} linea(s) del pallet {int(pallet_faltante_detalle)}.")
                st.rerun()

    st.subheader("Composicion por pallet")
    st.dataframe(limpiar_df_visible(resumen_pallets(df_operativo)), use_container_width=True, hide_index=True)

    st.subheader("Detalle de mudanza")
    detalle_display = preparar_detalle_mudanza(df_operativo)
    if df_pick.empty:
        st.dataframe(limpiar_df_visible(detalle_display), use_container_width=True, hide_index=True)
    else:
        detalle_editor_base = normalizar_df_pick(df_pick)
        detalle_editor_base["piezas_en_caja"] = detalle_editor_base.apply(lambda r: piezas_en_caja_de_fila(r), axis=1)
        detalle_editor = detalle_editor_base[
            [
                "item_id",
                "fecha_hora",
                "deposito_origen",
                "deposito_destino",
                "pallet",
                "cantidad_bultos",
                "bulto",
                "piezas_en_caja",
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
                "deposito_origen": "DepÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sito origen",
                "deposito_destino": "DepÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³sito destino",
                "pallet": "Pallet",
                "cantidad_bultos": "Cantidad de cajas",
                "bulto": "Caja",
                "piezas_en_caja": "Piezas en esta caja",
                "ubicacion": "UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
                "lectura_scanner": "Lectura scanner",
                "articulo": "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo",
                "descripcion": "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
                "unidad": "Unidad",
                "cantidad_mudada": "Piezas enviadas",
                "stock_total": "Stock original Darkinel",
                "stock_restante_darkinel": "Stock restante Darkinel",
                "codigo_normalizado": "CÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³digo normalizado",
                "observaciones": "Observaciones",
            }
        )
        detalle_editor = limpiar_df_visible(detalle_editor)
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
                row = {limpiar_columna_visible(k): v for k, v in row.items()}
                item_id = int(row.get("ID", 0))
                item = por_id.get(item_id)
                if not item:
                    continue
                item["fecha_hora"] = str(row.get("Fecha/Hora", "")).strip()
                item["deposito_origen"] = str(row.get("Deposito origen", "")).strip() or "DARKINEL"
                item["deposito_destino"] = str(row.get("Deposito destino", "")).strip() or "POLO LOGISTICO"
                item["pallet"] = entero_seguro(row.get("Pallet", 1), 1)
                item["cantidad_bultos"] = entero_seguro(row.get("Cantidad de cajas", row.get("Cantidad de bultos", 1)), 1)
                item["bulto"] = max(1, min(entero_seguro(row.get("Caja", row.get("Bulto", 1)), 1), int(item["cantidad_bultos"])))
                piezas_enviadas = row.get("Piezas en esta caja", row.get("Piezas enviadas", row.get("Cantidad mudada", 0)))
                item["cantidades_bulto"] = normalizar_cantidades_por_bulto(f"Caja {item['bulto']} = Cantidad {piezas_enviadas}", piezas_enviadas, item["bulto"])
                item["bultos_item"] = bultos_desde_distribucion(item["cantidades_bulto"], piezas_enviadas, item["bulto"])
                item["ubicacion"] = str(row.get("Ubicacion", "")).strip().upper() or "PENDIENTE"
                item["lectura_scanner"] = str(row.get("Lectura scanner", "")).strip()
                item["articulo"] = str(row.get("Articulo", "")).strip()
                item["descripcion"] = str(row.get("Descripcion", "")).strip()
                item["unidad"] = str(row.get("Unidad", "")).strip()
                item["cantidad_mudada"] = suma_cantidades_bulto(item["cantidades_bulto"], piezas_enviadas, item["bulto"]) or numero_seguro(piezas_enviadas, 0)
                item["codigo_normalizado"] = str(row.get("Codigo normalizado", "")).strip() or normalizar_codigo(item["articulo"])
                item["observaciones"] = str(row.get("Observaciones", "")).strip()
            guardar_mudanza_actual_db()
            st.success("Detalle actualizado.")
            st.rerun()

    if not df_operativo.empty:
        excel_bytes = generar_excel_control(stock_consolidado, df_operativo, stock_polo_anterior, ubicaciones_operativas, historial_anterior, salidas_polo_actual)
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
        fuentes_impresion = ["Mudanza actual"]
        if not df_reimpresion.empty:
            fuentes_impresion.append("Control anterior cargado")
        fuente_impresion = st.radio("Origen para imprimir", fuentes_impresion, horizontal=True)
        df_para_imprimir = df_reimpresion if fuente_impresion == "Control anterior cargado" else df_operativo
        pallets_disponibles = sorted(pd.to_numeric(df_para_imprimir["pallet"], errors="coerce").dropna().astype(int).unique().tolist())
        c_pdf1, c_pdf2, c_pdf3 = st.columns([1, 1, 1.4])
        pallet_pdf = c_pdf1.selectbox("Pallet para imprimir", pallets_disponibles)
        modo_pdf = c_pdf2.radio("Formato", ["Una hoja por pallet", "Una hoja por caja"], horizontal=True)
        corregir_guion_teclado = c_pdf3.checkbox(
            "Corregir guion del lector",
            value=True,
            help="Dejalo marcado si al escanear el guion sale como apostrofe. Si el lector ya lee bien los guiones, desmarcalo.",
        )
        modo_pdf_interno = "bultos" if modo_pdf == "Una hoja por caja" else "pallet"
        if REPORTLAB_DISPONIBLE:
            pdf_bytes = generar_pdf_pallet_bultos(df_para_imprimir, pallet_pdf, modo_pdf_interno, corregir_guion_teclado)
            st.download_button(
                "Descargar A4 pallet / cajas PDF",
                data=pdf_bytes,
                file_name=f"pallet_{int(pallet_pdf)}_{modo_pdf_interno}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                type="primary",
            )
        else:
            html_bytes = generar_html_pallet_bultos(df_para_imprimir, pallet_pdf, modo_pdf_interno, corregir_guion_teclado)
            st.warning("Reportlab no esta instalado en Streamlit Cloud. Mientras tanto podes descargar esta hoja HTML, abrirla e imprimirla en A4 o guardarla como PDF.")
            st.download_button(
                "Descargar A4 imprimible HTML",
                data=html_bytes,
                file_name=f"pallet_{int(pallet_pdf)}_{modo_pdf_interno}_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                type="primary",
            )
    else:
        st.info("Todavia no hay articulos agregados a la mudanza.")

        if not df_reimpresion.empty:
            st.markdown("---")
            st.subheader("Reimprimir hojas A4 de control anterior")
            pallets_disponibles = sorted(pd.to_numeric(df_reimpresion["pallet"], errors="coerce").dropna().astype(int).unique().tolist())
            c_pdf1, c_pdf2, c_pdf3 = st.columns([1, 1, 1.4])
            pallet_pdf = c_pdf1.selectbox("Pallet para reimprimir", pallets_disponibles)
            modo_pdf = c_pdf2.radio("Formato", ["Una hoja por pallet", "Una hoja por caja"], horizontal=True, key="modo_reimprimir_anterior")
            corregir_guion_teclado = c_pdf3.checkbox("Corregir guion del lector", value=True, key="guion_reimprimir_anterior")
            modo_pdf_interno = "bultos" if modo_pdf == "Una hoja por caja" else "pallet"
            if REPORTLAB_DISPONIBLE:
                pdf_bytes = generar_pdf_pallet_bultos(df_reimpresion, pallet_pdf, modo_pdf_interno, corregir_guion_teclado)
                st.download_button(
                    "Descargar A4 pallet / cajas PDF",
                    data=pdf_bytes,
                    file_name=f"pallet_{int(pallet_pdf)}_{modo_pdf_interno}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    type="primary",
                )
            else:
                html_bytes = generar_html_pallet_bultos(df_reimpresion, pallet_pdf, modo_pdf_interno, corregir_guion_teclado)
                st.download_button(
                    "Descargar A4 imprimible HTML",
                    data=html_bytes,
                    file_name=f"pallet_{int(pallet_pdf)}_{modo_pdf_interno}_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                    mime="text/html",
                    type="primary",
                )

    st.markdown("---")
    st.subheader("Completar ubicacion al llegar al Polo")
    if df_pick.empty:
        if usando_control_anterior:
            st.caption("El control anterior se muestra para consulta. Para completar ubicaciones, cargalo como mudanza activa.")
        else:
            st.caption("No hay lineas pendientes para ubicar.")
    else:
        opciones_ubicacion = [
            f"{r.item_id}) Pallet {r.pallet} | Caja {r.bulto} | {r.ubicacion} | {r.articulo} | Piezas {r.cantidad_mudada}"
            for r in df_pick.itertuples()
        ]
        linea_ubicacion = st.selectbox("Linea a actualizar", opciones_ubicacion)
        id_ubicacion = int(linea_ubicacion.split(")", 1)[0])
        ubicacion_actual = str(df_pick.loc[df_pick["item_id"] == id_ubicacion, "ubicacion"].iloc[0])
        nueva_ubicacion = st.text_input("Nueva ubicacion en Polo", value="" if ubicacion_actual == "PENDIENTE" else ubicacion_actual, placeholder="Ej: 1-L-3")
        if st.button("Guardar ubicacion"):
            ok, msg = actualizar_ubicacion_item(id_ubicacion, nueva_ubicacion)
            if ok:
                guardar_mudanza_actual_db()
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    st.markdown("---")
    st.subheader("Corregir / quitar lineas")
    if df_pick.empty:
        st.caption("No hay lineas para corregir.")
    else:
        opciones_corregir = [f"{r.item_id}) Pallet {r.pallet} | Caja {r.bulto} | {r.ubicacion} | {r.articulo} | Piezas {r.cantidad_mudada}" for r in df_pick.itertuples()]

        st.markdown("**Modificar linea**")
        linea_cantidad = st.selectbox("Linea para modificar", opciones_corregir, key="linea_modificar_cantidad")
        id_cantidad = int(linea_cantidad.split(")", 1)[0])
        fila_editar = df_pick.loc[df_pick["item_id"] == id_cantidad].iloc[0]
        cantidad_actual = float(pd.to_numeric(fila_editar["cantidad_mudada"], errors="coerce") or 0)
        pallet_actual = max(int(pd.to_numeric(fila_editar["pallet"], errors="coerce") or 1), 1)
        cantidad_bultos_actual = max(int(pd.to_numeric(fila_editar["cantidad_bultos"], errors="coerce") or 1), 1)
        bulto_actual = max(int(pd.to_numeric(fila_editar["bulto"], errors="coerce") or 1), 1)
        bultos_item_actual = str(fila_editar.get("bultos_item", bulto_actual))
        cantidades_bulto_actual = str(fila_editar.get("cantidades_bulto", f"{bulto_actual}={cantidad_actual}"))
        ubicacion_actual_editar = str(fila_editar["ubicacion"])
        stock_total_linea = float(pd.to_numeric(fila_editar["stock_total"], errors="coerce"))
        stock_restante_sugerido = max(stock_total_linea - cantidad_actual, 0)

        with st.form("form_modificar_linea"):
            e1, e2, e3, e4, e5 = st.columns(5)
            nueva_cantidad = e1.number_input("Piezas a mudar", min_value=0.0, value=max(cantidad_actual, 0.0), step=1.0)
            nuevo_pallet = e2.number_input("Pallet", min_value=1, value=pallet_actual, step=1)
            nueva_cantidad_bultos = e3.number_input("Cantidad de cajas", min_value=1, value=cantidad_bultos_actual, step=1)
            nuevo_bulto = e4.number_input("Caja", min_value=1, max_value=int(nueva_cantidad_bultos), value=min(bulto_actual, int(nueva_cantidad_bultos)), step=1)
            nueva_ubicacion_editar = e5.text_input("Ubicacion", value="" if ubicacion_actual_editar == "PENDIENTE" else ubicacion_actual_editar)

            aplicar_stock_real = st.checkbox(
                "Actualizar stock real que queda en Darkinel",
                value=str(fila_editar.get("estado", "")).strip().upper() == "MANUAL",
                help="Usalo si el Excel no tiene el stock real o si el artÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo fue creado manualmente.",
            )
            stock_darkinel_restante = st.number_input(
                "Cantidad que queda en Darkinel",
                min_value=0.0,
                value=float(stock_restante_sugerido),
                step=1.0,
                disabled=not aplicar_stock_real,
            )
            guardar_linea = st.form_submit_button("Guardar cambios de linea", type="primary")

        if guardar_linea:
            if float(nueva_cantidad) <= 0:
                st.error("Para guardar la linea, la cantidad a mudar tiene que ser mayor a cero.")
            else:
                ok, msg = actualizar_linea_item(
                    id_cantidad,
                    nueva_cantidad,
                    nuevo_pallet,
                    nueva_cantidad_bultos,
                    nuevo_bulto,
                    bultos_item_actual,
                    f"Caja {int(nuevo_bulto)} = Cantidad {formatear_numero(nueva_cantidad)}",
                    nueva_ubicacion_editar,
                    stock_darkinel_restante if aplicar_stock_real else None,
                )
                if ok:
                    guardar_mudanza_actual_db()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        st.markdown("**Quitar lineas**")
        opciones_quitar = [f"{r.item_id}) Pallet {r.pallet} | Caja {r.bulto} | {r.ubicacion} | {r.articulo} | Piezas {r.cantidad_mudada}" for r in df_pick.itertuples()]
        quitar = st.multiselect("Lineas para quitar", opciones_quitar)
        if st.button("Quitar lineas seleccionadas") and quitar:
            ids = {int(x.split(")", 1)[0]) for x in quitar}
            st.session_state.pick_items = [item for item in st.session_state.pick_items if int(item.get("item_id", 0)) not in ids]
            guardar_mudanza_actual_db(fusionar_con_nube=False)
            st.success("Lineas quitadas.")
            st.rerun()

with tab_recepcion:
    st.subheader("Recepcion en Polo")
    if df_operativo.empty:
        st.info("Todavia no hay articulos en la mudanza para recibir.")
    else:
        if usando_control_anterior:
            st.info("Mostrando recepcion del control anterior cargado. Para guardar cambios, usalo como mudanza activa.")
        st.caption("Selecciona el pallet, informa una ubicacion unica y desmarca solamente lo que tenga problema. Si hay algo desmarcado, ese pallet no se guarda.")
        trabajo_recepcion = normalizar_df_pick(df_operativo)
        pallets_recepcion = sorted(pd.to_numeric(trabajo_recepcion["pallet"], errors="coerce").dropna().astype(int).unique().tolist())
        pr1, pr2, pr3 = st.columns([1, 1.5, 1.5])
        pallet_recepcion = pr1.selectbox("Pallet a recibir", pallets_recepcion)
        lineas_pallet_recepcion = trabajo_recepcion[trabajo_recepcion["pallet"] == int(pallet_recepcion)].copy()
        ubicaciones_existentes = (
            lineas_pallet_recepcion["ubicacion_recepcion"]
            .where(lineas_pallet_recepcion["ubicacion_recepcion"].astype(str).str.strip() != "", lineas_pallet_recepcion["ubicacion"])
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )
        ubicaciones_reales = [u for u in ubicaciones_existentes.unique().tolist() if u and u not in ["PENDIENTE", "NAN"]]
        ubicacion_sugerida = ubicaciones_reales[0] if len(ubicaciones_reales) == 1 else ""
        ubicacion_pallet = pr2.text_input("Ubicacion unica del pallet", value=ubicacion_sugerida, placeholder="Ej: 1-L-3")
        receptor_pallet = pr3.text_input("Recibido por", placeholder="Nombre")

        recepcion_base = lineas_pallet_recepcion.copy()
        recepcion_base["ubicacion_recepcion"] = recepcion_base["ubicacion_recepcion"].where(
            recepcion_base["ubicacion_recepcion"].astype(str).str.strip() != "",
            recepcion_base["ubicacion"],
        )

        recepcion_editor = recepcion_base[
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
                "bulto": "Caja",
                "articulo": "ArtÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â­culo",
                "descripcion": "DescripciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
                "unidad": "Unidad",
                "cantidad_mudada": "Piezas enviadas",
                "cantidad_recibida": "Piezas recibidas",
                "recepcion_ok": "OK recepciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
                "ubicacion_recepcion": "UbicaciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n Polo",
                "receptor": "Recibido por",
                "fecha_recepcion": "Fecha recepciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
                "observaciones_recepcion": "Observaciones recepciÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â³n",
            }
        )
        recepcion_editor = limpiar_df_visible(recepcion_editor)
        recepcion_editor["OK recepcion"] = True

        recepcion_editada = st.data_editor(
            recepcion_editor,
            use_container_width=True,
            hide_index=True,
            disabled=["ID", "Pallet", "Caja", "Articulo", "Descripcion", "Unidad", "Piezas enviadas", "Ubicacion Polo", "Recibido por", "Fecha recepcion"],
            num_rows="fixed",
            key="recepcion_polo_editor",
        )

        if st.button("Guardar recepcion del pallet", type="primary", disabled=usando_control_anterior):
            if not str(ubicacion_pallet).strip():
                st.error("Informa la ubicacion del pallet antes de guardar.")
                st.stop()
            if not bool(recepcion_editada["OK recepcion"].astype(bool).all()):
                st.error("Hay lineas desmarcadas. Este pallet no se guarda hasta que todo este OK.")
                st.stop()

            por_id = {int(item.get("item_id", 0)): item for item in st.session_state.pick_items}
            ahora_recepcion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for row in recepcion_editada.to_dict("records"):
                item_id = int(row.get("ID", 0))
                item = por_id.get(item_id)
                if not item:
                    continue
                ubicacion_polo = str(ubicacion_pallet).strip().upper()
                item["cantidad_recibida"] = numero_seguro(row.get("Piezas recibidas", row.get("Cantidad recibida", item.get("cantidad_mudada", 0))), 0)
                item["recepcion_ok"] = True
                item["ubicacion_recepcion"] = ubicacion_polo
                item["ubicacion"] = ubicacion_polo
                item["receptor"] = str(receptor_pallet).strip()
                item["fecha_recepcion"] = ahora_recepcion
                item["observaciones_recepcion"] = str(row.get("Observaciones recepcion", "")).strip()
            guardar_mudanza_actual_db()
            st.success(f"Pallet {pallet_recepcion} recibido OK y ubicacion actualizada.")
            st.rerun()

        recepcion_actual = preparar_recepcion_polo(df_operativo)
        if not recepcion_actual.empty:
            pendientes = int((~recepcion_actual["OK recepcion"].astype(bool)).sum())
            diferencias = int((pd.to_numeric(recepcion_actual["Diferencia"], errors="coerce").fillna(0) != 0).sum())
            r1, r2, r3 = st.columns(3)
            r1.metric("Lineas recibidas OK", len(recepcion_actual) - pendientes)
            r2.metric("Lineas pendientes", pendientes)
            r3.metric("Diferencias cantidad", diferencias)

with tab_salidas:
    st.subheader("Salidas / ventas desde Polo")
    ubicaciones_disponibles = aplicar_salidas_a_ubicaciones(ubicacion_polo_logistico(df_operativo, ubicaciones_operativas), salidas_polo_actual)
    if ubicaciones_disponibles.empty:
        st.info("Todavia no hay stock con locacion en Polo para descontar.")
    else:
        codigo_salida = st.text_input("Codigo vendido / lectura scanner", placeholder="Ej: KCYB-50-22X", key="codigo_salida_polo")
        opciones_salida = buscar_en_inventario(
            inventario_para_buscar(pd.DataFrame(), df_operativo, ubicaciones_operativas, pd.DataFrame(), salidas_polo_actual),
            codigo_salida,
        ) if codigo_salida else pd.DataFrame()

        if codigo_salida and opciones_salida.empty:
            st.warning("No encontre ese codigo con stock disponible en Polo.")
        elif not opciones_salida.empty:
            opciones_polo = opciones_salida[opciones_salida["deposito"].eq("POLO LOGISTICO")].copy()
            if opciones_polo.empty:
                st.warning("El codigo existe, pero no tiene stock disponible en Polo.")
            else:
                opciones_polo = opciones_polo[opciones_polo["ubicacion"].apply(es_ubicacion_real)].copy()
                opciones_polo["cantidad_num"] = pd.to_numeric(opciones_polo["cantidad"], errors="coerce").fillna(0)
                opciones_polo = opciones_polo[opciones_polo["cantidad_num"] > 0].copy()
                if opciones_polo.empty:
                    st.warning("Ese codigo no tiene locacion real en Polo para descontar.")
                else:
                    opciones_txt = [
                        f"{r.codigo_normalizado} | {r.articulo} | {r.descripcion} | Locacion {r.ubicacion} | Disponible {formatear_numero(r.cantidad_num)}"
                        for r in opciones_polo.itertuples()
                    ]
                    seleccion = st.selectbox("Elegir locacion a descontar", opciones_txt, key="salida_locacion_select")
                    idx_sel = opciones_txt.index(seleccion)
                    fila_sel = opciones_polo.reset_index(drop=True).iloc[idx_sel]
                    disponible = float(fila_sel["cantidad_num"])
                    with st.form("form_salida_polo"):
                        c1, c2, c3 = st.columns(3)
                        cantidad_salida = c1.number_input("Cantidad a descontar", min_value=1.0, max_value=max(disponible, 1.0), value=1.0, step=1.0)
                        responsable = c2.text_input("Responsable", placeholder="Nombre")
                        observaciones = c3.text_input("Observaciones", placeholder="Venta / salida / ajuste")
                        guardar_salida = st.form_submit_button("Descontar de esta locacion", type="primary")

                    if guardar_salida:
                        st.session_state.salida_seq = int(st.session_state.get("salida_seq", 0) or 0) + 1
                        st.session_state.salidas_polo.append(
                            {
                                "salida_id": st.session_state.salida_seq,
                                "fecha_hora": ahora_texto(),
                                "codigo_normalizado": fila_sel["codigo_normalizado"],
                                "articulo": fila_sel["articulo"],
                                "descripcion": fila_sel["descripcion"],
                                "ubicacion": fila_sel["ubicacion"],
                                "cantidad": float(cantidad_salida),
                                "responsable": responsable,
                                "observaciones": observaciones,
                            }
                        )
                        guardar_salidas_polo_db()
                        st.success(f"Salida registrada. Se desconto {formatear_numero(cantidad_salida)} de {fila_sel['ubicacion']}.")
                        st.rerun()

    st.subheader("Historial de salidas Polo")
    st.dataframe(limpiar_df_visible(mostrar_salidas_polo(salidas_polo_actual)), use_container_width=True, hide_index=True)

with tab_bases:
    st.subheader("STOCK_DARKINEL_ACTUALIZADO")
    darkinel_actual = stock_darkinel_actualizado(stock_consolidado, df_operativo)
    st.dataframe(limpiar_df_visible(darkinel_actual), use_container_width=True, hide_index=True)

    st.subheader("STOCK_POLO_LOGISTICO")
    polo_actual = stock_polo_actualizado(df_operativo, stock_polo_anterior, ubicaciones_operativas, salidas_polo_actual)
    st.dataframe(limpiar_df_visible(polo_actual), use_container_width=True, hide_index=True)

    st.subheader("UBICACION_POLO_LOGISTICO")
    ubicacion_actual = aplicar_salidas_a_ubicaciones(ubicacion_polo_logistico(df_operativo, ubicaciones_operativas), salidas_polo_actual)
    st.dataframe(limpiar_df_visible(ubicacion_actual), use_container_width=True, hide_index=True)

    st.subheader("SALIDAS_POLO")
    st.dataframe(limpiar_df_visible(mostrar_salidas_polo(salidas_polo_actual)), use_container_width=True, hide_index=True)

with tab_stock:
    st.subheader("Consulta de stock por codigo")
    inventario_consulta = inventario_para_buscar(stock_consolidado, df_operativo, ubicaciones_operativas, frecuencias_df, salidas_polo_actual)
    stock_col1, stock_col2 = st.columns(2)
    stock_col1.metric("Piezas disponibles en Darkinel", f"{piezas_darkinel_metric:,}".replace(",", "."))
    stock_col2.metric("Piezas disponibles en Polo Logistico", f"{piezas_polo_metric:,}".replace(",", "."))
    codigo_consulta = st.text_input("Codigo / lectura scanner", placeholder="Ej: KCYB-50-22X")

    if codigo_consulta:
        resultado_consulta = buscar_en_inventario(inventario_consulta, codigo_consulta)
        if resultado_consulta.empty:
            st.warning("No encontre ese codigo en Darkinel ni en Polo.")
        else:
            st.dataframe(limpiar_df_visible(mostrar_inventario(resultado_consulta)), use_container_width=True, hide_index=True)
    else:
        st.dataframe(limpiar_df_visible(mostrar_inventario(inventario_consulta.head(100))), use_container_width=True, hide_index=True)

    st.caption("Frecuencia: A = 0 a 6 meses, B = 6,1 a 12, C = 12,1 a 18, E = 18,1 a 24, F = 24,1 a 38, Scrap = mas de 38 meses.")
