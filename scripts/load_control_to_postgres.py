from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import Json


EXCEL_PATH = Path(r"C:\Users\Adrian\Desktop\Pedidos Magna\Mudanza_2026\control_depositos_darkinel_polo_20260527_2146.xlsx")


def clean_text(value: object, default: str = "") -> str:
    if pd.isna(value):
        return default
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def clean_loc(value: object) -> str:
    text = clean_text(value).upper()
    return text or "PENDIENTE"


def num(value: object, default: float = 0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)


def integer(value: object, default: int = 0) -> int:
    return int(num(value, default))


def boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = clean_text(value).lower()
    if text in {"true", "1", "si", "sí", "ok", "x"}:
        return True
    if text in {"false", "0", "no", ""}:
        return False
    return bool(value)


def build_items() -> list[dict]:
    detalle = pd.read_excel(EXCEL_PATH, sheet_name="DETALLE_MUDANZA", dtype=object)
    recepcion = pd.read_excel(EXCEL_PATH, sheet_name="RECEPCION_POLO", dtype=object)
    if len(detalle) == len(recepcion):
        for col in [
            "Piezas recibidas",
            "OK recepcion",
            "Ubicacion informada",
            "Receptor",
            "Fecha recepcion",
            "Observaciones recepcion",
        ]:
            if col in recepcion.columns:
                detalle[col] = recepcion[col].values

    items: list[dict] = []
    for idx, row in detalle.iterrows():
        cantidad = num(row.get("Piezas enviadas"), 0)
        bulto = integer(row.get("Caja"), 1) or 1
        item = {
            "item_id": idx + 1,
            "fecha_hora": clean_text(row.get("Fecha/Hora")),
            "deposito_origen": clean_text(row.get("Deposito origen"), "DARKINEL"),
            "deposito_destino": clean_text(row.get("Deposito destino"), "POLO LOGISTICO"),
            "pallet": integer(row.get("Pallet"), 1) or 1,
            "cantidad_bultos": integer(row.get("Cantidad de cajas"), 1) or 1,
            "bulto": bulto,
            "bultos_item": str(bulto),
            "cantidades_bulto": f"Caja {bulto} = Cantidad {cantidad:g}",
            "ubicacion": clean_loc(row.get("Ubicacion")),
            "lectura_scanner": clean_text(row.get("Lectura scanner")),
            "articulo": clean_text(row.get("Articulo")),
            "descripcion": clean_text(row.get("Descripcion")),
            "unidad": clean_text(row.get("Unidad"), "uni"),
            "cantidad_mudada": cantidad,
            "cantidad_recibida": num(row.get("Piezas recibidas"), cantidad),
            "stock_total": num(row.get("Stock original Darkinel"), 0),
            "stock_restante_darkinel": num(row.get("Stock restante Darkinel"), 0),
            "codigo_normalizado": clean_text(row.get("Codigo normalizado")).upper(),
            "observaciones": clean_text(row.get("Observaciones")),
            "recepcion_ok": boolean(row.get("OK recepcion")),
            "ubicacion_recepcion": clean_loc(row.get("Ubicacion informada")) if clean_text(row.get("Ubicacion informada")) else "",
            "receptor": clean_text(row.get("Receptor")),
            "fecha_recepcion": clean_text(row.get("Fecha recepcion")),
            "observaciones_recepcion": clean_text(row.get("Observaciones recepcion")),
        }
        items.append(item)
    return items


def build_salidas(sheet_name: str, darkinel: bool = False) -> list[dict]:
    df = pd.read_excel(EXCEL_PATH, sheet_name=sheet_name, dtype=object)
    salidas: list[dict] = []
    for idx, row in df.iterrows():
        if not clean_text(row.get("Codigo normalizado")) and not clean_text(row.get("Articulo")):
            continue
        salida_id = idx + 1
        salida = {
            "salida_id": salida_id,
            "remito_num": clean_text(row.get("Remito"), f"{'RD' if darkinel else 'R'}{salida_id:06d}"),
            "fecha_hora": clean_text(row.get("Fecha/Hora")),
            "solicitado_por": clean_text(row.get("Solicitado por")),
            "codigo_normalizado": clean_text(row.get("Codigo normalizado")).upper(),
            "codigo_barra": clean_text(row.get("Codigo de barras")),
            "articulo": clean_text(row.get("Articulo")),
            "descripcion": clean_text(row.get("Descripcion")),
            "ubicacion": clean_loc(row.get("Locacion")),
            "cantidad": num(row.get("Cantidad"), 0),
            "responsable": clean_text(row.get("Responsable")),
            "observaciones": clean_text(row.get("Observaciones")),
        }
        if not darkinel:
            salida["estado"] = clean_text(row.get("Estado"), "VENDIDO").upper()
        salidas.append(salida)
    return salidas


def build_conteos() -> list[dict]:
    df = pd.read_excel(EXCEL_PATH, sheet_name="CONTEO_DARKINEL", dtype=object)
    conteos: list[dict] = []
    for _, row in df.iterrows():
        if not clean_text(row.get("codigo_normalizado")):
            continue
        conteos.append(
            {
                "codigo_normalizado": clean_text(row.get("codigo_normalizado")).upper(),
                "articulo": clean_text(row.get("articulo")),
                "descripcion": clean_text(row.get("descripcion")),
                "ubicacion": clean_loc(row.get("ubicacion")).replace("PENDIENTE", "SIN LOCACION"),
                "sububicacion": clean_text(row.get("sububicacion"), "SIN SUBDIVISION").upper(),
                "cantidad_contada": num(row.get("cantidad_contada"), 0),
                "contado_por": clean_text(row.get("contado_por")),
                "fecha_hora": clean_text(row.get("fecha_hora")),
                "observaciones": clean_text(row.get("observaciones")),
            }
        )
    return conteos


def main() -> None:
    items = build_items()
    salidas_polo = build_salidas("SALIDAS_POLO")
    salidas_darkinel = build_salidas("SALIDAS_DARKINEL", darkinel=True)
    conteos_darkinel = build_conteos()
    pallets = sorted({int(item["pallet"]) for item in items if int(item["pallet"]) > 0})
    estado = {
        "pick_items": items,
        "pick_seq": len(items),
        "pallet_seq": max(pallets or [0]),
    }

    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="deposito",
        user="deposito_user",
        password="deposito_pass_cambiar",
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS estado_app (clave TEXT PRIMARY KEY, valor JSONB NOT NULL, actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        cur.execute("SELECT valor FROM estado_app WHERE clave = %s", ("mudanza_actual",))
        row = cur.fetchone()
        if row and row[0]:
            cur.execute("SELECT valor FROM estado_app WHERE clave = %s", ("mudanza_backups",))
            backups_row = cur.fetchone()
            backups = backups_row[0] if backups_row and isinstance(backups_row[0], list) else []
            backups.append(
                {
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "motivo": "backup automatico antes de cargar control 20260527_2146",
                    "estado": row[0],
                }
            )
            cur.execute(
                """
                INSERT INTO estado_app (clave, valor, actualizado_en)
                VALUES (%s, %s, now())
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado_en = now()
                """,
                ("mudanza_backups", Json(backups[-30:])),
            )

        cur.execute(
            """
            INSERT INTO estado_app (clave, valor, actualizado_en)
            VALUES (%s, %s, now())
            ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado_en = now()
            """,
            ("mudanza_actual", Json(estado)),
        )
        estados_operativos = {
            "salidas_polo": {
                "salidas": salidas_polo,
                "salida_seq": max([int(x.get("salida_id", 0) or 0) for x in salidas_polo] or [0]),
                "remito_seq": max([int(str(x.get("remito_num", "")).replace("R", "") or 0) for x in salidas_polo] or [0]),
            },
            "salidas_darkinel": {
                "salidas": salidas_darkinel,
                "salida_darkinel_seq": max([int(x.get("salida_id", 0) or 0) for x in salidas_darkinel] or [0]),
                "remito_darkinel_seq": max([int(str(x.get("remito_num", "")).replace("RD", "") or 0) for x in salidas_darkinel] or [0]),
            },
            "conteo_darkinel": {
                "conteos": conteos_darkinel,
            },
        }
        for clave, valor in estados_operativos.items():
            cur.execute(
                """
                INSERT INTO estado_app (clave, valor, actualizado_en)
                VALUES (%s, %s, now())
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado_en = now()
                """,
                (clave, Json(valor)),
            )

    print(
        json.dumps(
            {
                "lineas": len(items),
                "pallets": len(pallets),
                "max_pallet": max(pallets or [0]),
                "salidas_polo": len(salidas_polo),
                "salidas_darkinel": len(salidas_darkinel),
                "conteos_darkinel": len(conteos_darkinel),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
