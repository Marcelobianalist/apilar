import streamlit as st
import pandas as pd
from io import BytesIO
from typing import List, Optional, Tuple
import unicodedata
import re

# --- Configuración de la página ---
st.set_page_config(page_title="Consolidador Archivos Grandes", page_icon="📄", layout="wide")

# --- Regex para limpiar caracteres ilegales ---
ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")
ENCODINGS = ['utf-8-sig', 'utf-8', 'latin1', 'windows-1252', 'utf-16']

# --- Funciones auxiliares ---
def limpiar_caracteres_ilegales(valor):
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

def normalizar_nombre_columna(col):
    if not isinstance(col, str):
        col = str(col)
    s = col.lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r"[ \-]+", "_", s)
    s = s.replace('°', 'nro').replace('º', 'nro')
    s = re.sub(r'__+', '_', s)
    return limpiar_caracteres_ilegales(s)

def optimizar_tipos(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.select_dtypes(include=['float']).columns:
        if (df[col].dropna() % 1 == 0).all():
            try:
                df[col] = df[col].astype('Int32')
            except:
                pass
    for col in df.select_dtypes(include=['object']).columns:
        if df[col].nunique() / max(len(df[col]), 1) < 0.5:
            try:
                df[col] = df[col].astype('category')
            except:
                pass
    return df

def leer_archivo(file) -> Optional[pd.DataFrame]:
    nombre = file.name.lower()
    if nombre.endswith(('.csv', '.txt', '.tsv')):
        for encoding in ENCODINGS:
            try:
                sep = '\t' if nombre.endswith('.tsv') else None
                file.seek(0)
                return pd.read_csv(file, encoding=encoding, sep=sep, low_memory=False)
            except Exception:
                continue
        return None
    elif nombre.endswith(('.xlsx', '.xls')):
        try:
            file.seek(0)
            return pd.read_excel(file, engine='openpyxl' if nombre.endswith('.xlsx') else 'xlrd')
        except Exception:
            return None
    return None

def procesar_archivos(files: List) -> Tuple[Optional[pd.DataFrame], List[str]]:
    dataframes = []
    logs = []
    columnas_base = None
    orden_columnas = None
    for file in files:
        try:
            df = leer_archivo(file)
            if df is None or df.empty:
                logs.append(f"⚠️ '{file.name}' vacío o ilegible.")
                continue
            df.dropna(how='all', inplace=True)
            df.reset_index(drop=True, inplace=True)
            df.columns = [normalizar_nombre_columna(c) for c in df.columns]
            df = df.loc[:, ~df.columns.str.contains('^unnamed')]
            if columnas_base is None:
                columnas_base = set(df.columns)
                orden_columnas = list(df.columns)
                logs.append(f"✅ Plantilla establecida desde '{file.name}'.")
            else:
                for col in columnas_base - set(df.columns):
                    df[col] = pd.NA
                df = df[[c for c in orden_columnas if c in df.columns]]
            df = optimizar_tipos(df)
            df['archivo_origen'] = file.name
            dataframes.append(df[orden_columnas + ['archivo_origen']])
            logs.append(f"✅ '{file.name}' procesado correctamente.")
        except Exception as e:
            logs.append(f"💥 Error en '{file.name}': {e}")
    dataframes_filtrados = [df for df in dataframes if df is not None and not df.empty and not df.isnull().all().all()]
    if not dataframes_filtrados:
        return None, logs
    df_final = pd.concat(dataframes_filtrados, ignore_index=True)
    return df_final, logs

def crear_excel_en_memoria(df: pd.DataFrame) -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
    output.seek(0)
    return output

# --- Interfaz ---
st.title("📄 Consolidador Optimizado para Archivos Grandes")
st.markdown("Procesa y unifica archivos grandes de manera eficiente, sin rechazar archivos por columnas faltantes o sobrantes.")

archivos = st.file_uploader("📤 Suba sus archivos", type=['xlsx', 'xls', 'csv', 'txt', 'tsv'], accept_multiple_files=True)

if archivos:
    with st.spinner("🔄 Procesando archivos..."):
        df, logs = procesar_archivos(archivos)

    st.subheader("📜 Registro de Procesamiento")
    for log in logs:
        if "💥" in log:
            st.error(log)
        elif "⚠️" in log:
            st.warning(log)
        else:
            st.info(log)

    if df is not None and not df.empty:
        st.success(f"✅ Consolidación completada: {df.shape[0]} filas, {df.shape[1]} columnas.")
        st.dataframe(df.head(500).astype(str).fillna(''))
        try:
            excel_bytes = crear_excel_en_memoria(df)
            st.download_button(
                label="📥 Descargar Excel Consolidado",
                data=excel_bytes,
                file_name="consolidado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.error(f"💥 Error exportando a Excel: {e}")
    else:
        st.error("❌ No se generó ningún consolidado válido.")
else:
    st.info("Cargue archivos para comenzar.")
