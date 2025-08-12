# app.py
import re
import io
import unicodedata
import pandas as pd
import streamlit as st
from typing import Tuple, Optional, List, Dict

# ==========================
# Posiciones FIJAS (0-index)
# ==========================
EMPRESA_SLICE   = (0, 40)     # 1–40
CUENTA_SLICE    = (286, 300)  # 287–300
DESCRIPCION_SL  = (383, 460)  # 384–460 (end exclusivo)
# Crédito: 670–687 inclusive => (669, 688)
# Débito : 688–708 inclusive => (687, 709)
CREDITO_SLICE   = (669, 688)
DEBITO_SLICE    = (687, 709)

# Fecha tolerante (1-2 dígitos y / o -)
FECHA_RE = r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b'
# Monto AR dentro del slice (con o sin miles, opcional signo)
MONTO_RE_IN_SLICE = r'-?\d[\d\.]*,\d{2}'

def slice_text(line: str, sl: Tuple[int, int]) -> str:
    need = sl[1]
    if len(line) < need:
        line = line.ljust(need)
    return line[sl[0]:sl[1]]

def ar_to_float(s: str) -> float:
    s = (s or "").strip().replace(" ", "")
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def pick_amount_from_slice(txt_slice: str) -> float:
    # Busca el primer monto válido dentro del slice (ignora espacios/alineación)
    s = txt_slice.replace(" ", "")
    m = re.search(MONTO_RE_IN_SLICE, s)
    return ar_to_float(m.group(0)) if m else 0.0

def parse_line_fixed(line: str) -> Optional[dict]:
    ln = line.rstrip("\n")

    empresa = slice_text(ln, EMPRESA_SLICE).strip()
    cuenta  = slice_text(ln, CUENTA_SLICE).strip()
    descr   = slice_text(ln, DESCRIPCION_SL).strip()

    # Fecha por regex en toda la línea (más tolerante)
    m_fecha = re.search(FECHA_RE, ln)
    if not m_fecha:
        return None
    fecha_txt = m_fecha.group(1)

    # Montos desde los slices fijos (tolera espacios)
    credito = pick_amount_from_slice(slice_text(ln, CREDITO_SLICE))
    debito  = pick_amount_from_slice(slice_text(ln, DEBITO_SLICE))
    movimiento = credito - debito

    return {
        "Empresa": empresa,
        "Cuenta": cuenta,
        "Fecha": fecha_txt,
        "Descripción": descr,
        "Crédito": credito,
        "Débito": debito,
        "Movimiento": movimiento,
    }

def parse_rec_text(text: str) -> pd.DataFrame:
    rows: List[Dict] = []
    for ln in text.splitlines():
        r = parse_line_fixed(ln)
        if r:
            rows.append(r)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], dayfirst=True, errors="coerce")
        df = df[["Empresa","Cuenta","Fecha","Descripción","Crédito","Débito","Movimiento"]]
    return df

def slugify_filename_part(s: str, maxlen: int = 60) -> str:
    """Convierte 'Empresa de Prueba S.A.' -> 'Empresa_de_Prueba_SA' (seguro para nombre de archivo)."""
    s = (s or "").strip()
    # remover tildes/acentos
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # dejar letras, numeros, espacios, guion y underscore
    s = re.sub(r'[^A-Za-z0-9\-_ ]+', '', s)
    # espacios -> underscore
    s = re.sub(r'\s+', '_', s)
    s = s.strip('_')
    return s[:maxlen] or "empresa"

# ==========================
# App
# ==========================
st.set_page_config(page_title="Reportes Bejerman", layout="wide")
st.title("🏦 Reportes Bejerman")

with st.sidebar:
    st.header("Opciones")
    encoding = st.selectbox("Encoding", ["latin-1", "utf-8", "utf-16"], index=0)
    st.caption("Las posiciones son fijas. Cambiá el encoding si aparecen caracteres raros.")

archivos = st.file_uploader(
    "Subí hasta 3 archivos .rec",
    type=["rec","txt"],
    accept_multiple_files=True
)

if not archivos:
    st.info("📤 Subí entre 1 y 3 archivos para ver la vista previa y consolidar.")
    st.stop()

if len(archivos) > 3:
    st.warning("⚠️ Solo se procesarán los primeros 3 archivos.")
    archivos = archivos[:3]

dfs = []
resumen = []

for up in archivos:
    content = up.read()
    text = content.decode(encoding, errors="ignore")
    df_i = parse_rec_text(text)
    resumen.append({
        "Archivo": up.name,
        "Registros OK": 0 if df_i.empty else len(df_i),
    })
    if not df_i.empty:
        df_i["Archivo"] = up.name
        dfs.append(df_i)

st.write("### Resultado por archivo")
st.dataframe(pd.DataFrame(resumen), use_container_width=True)

if not dfs:
    st.warning("No se obtuvieron registros válidos en ninguno de los archivos.")
    st.stop()

# Merge + dedupe (silencioso) + ordenar
merged = pd.concat(dfs, ignore_index=True)

# Dedupe incluye 'Archivo' para no borrar líneas iguales provenientes de archivos distintos
merged = merged.drop_duplicates(
    subset=["Archivo","Empresa","Cuenta","Fecha","Descripción","Crédito","Débito","Movimiento"],
    keep="first"
)

merged = merged.sort_values(["Fecha","Cuenta","Descripción"], na_position="last").reset_index(drop=True)

st.write("### Vista previa consolidada")
st.dataframe(merged.head(100), use_container_width=True)

# KPIs
col1, col2, col3 = st.columns(3)
with col1: st.metric("Archivos procesados", len(dfs))
with col2: st.metric("Registros totales", len(merged))
with col3: st.metric("Cuentas únicas", merged["Cuenta"].nunique())

# ===== Resumen por Empresa =====
resumen_empresa = (
    merged
    .groupby("Empresa", as_index=False)
    .agg({
        "Crédito": "sum",
        "Débito": "sum",
        "Movimiento": "sum",
    })
    .sort_values("Empresa")
)

st.write("### Resumen por Empresa")
st.dataframe(resumen_empresa, use_container_width=True)

# ===== Nombre de archivo con primera Cuenta =====
primera_cuenta = (
    merged["Cuenta"]
    .dropna()
    .astype(str)
    .str.strip()
    .iloc[0]
    if not merged.empty else "cuenta"
)
cuenta_slug = slugify_filename_part(primera_cuenta)
excel_filename = f"movimientos_consolidados_{cuenta_slug}.xlsx"

# ===== Descarga en EXCEL con dos hojas =====
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    # Hoja 1: Movimientos (sin columna Archivo)
    merged.drop(columns=["Archivo"], errors="ignore").to_excel(
        writer, index=False, sheet_name="Movimientos"
    )
    # Hoja 2: Resumen por Empresa
    resumen_empresa.to_excel(writer, index=False, sheet_name="Resumen por Empresa")
buffer.seek(0)

st.download_button(
    "⬇️ Descargar Excel",
    data=buffer,
    file_name=excel_filename,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
