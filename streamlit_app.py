import streamlit as st
import pandas as pd
from io import BytesIO
from streamlit.runtime.uploaded_file_manager import UploadedFile
from typing import List, Tuple, Optional
import unicodedata
import re
import numpy as np

# --- Configuración de la Página ---
st.set_page_config(page_title="Consolidador de Archivos", page_icon="📄", layout="wide")

# ----- FUNCIÓN DE LIMPIEZA DE CARACTERES -----
ILLEGAL_CHARACTERS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')

def limpiar_caracteres_ilegales(valor):
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

# --- Funciones de Utilidad ---

@st.cache_data
def convertir_a_excel(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
    return output.getvalue()

def normalizar_nombre_columna(col_name: str) -> str:
    if not isinstance(col_name, str): col_name = str(col_name)
    s = col_name.lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = s.replace(' ', '_').replace('-', '_').replace('°', 'nro').replace('º', 'nro')
    s = re.sub(r'__+', '_', s)
    s = limpiar_caracteres_ilegales(s)
    return s

def leer_archivo(file: UploadedFile) -> Optional[pd.DataFrame]:
    nombre_archivo = file.name.lower()
    
    if nombre_archivo.endswith(('.csv', '.txt')):
        posibles_codificaciones = ['utf-16', 'utf-8-sig', 'utf-8', 'latin1', 'windows-1252']
        for encoding in posibles_codificaciones:
            try:
                file.seek(0)
                return pd.read_csv(file, encoding=encoding, sep=None, engine='python', header=0, skip_blank_lines=True)
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        st.warning(f"No se pudo leer el archivo de texto '{file.name}' con ninguna de las codificaciones probadas.")
        return None

    elif nombre_archivo.endswith(('.xlsx', '.xls')):
        try:
            file.seek(0)
            engine = 'openpyxl' if nombre_archivo.endswith('.xlsx') else 'xlrd'
            return pd.read_excel(file, engine=engine, header=0)
        except Exception as e:
            if 'Expected BOF record' in str(e):
                st.info(f"'{file.name}' parece ser una tabla HTML. Intentando leerla como tal...")
                try:
                    file.seek(0)
                    dfs = pd.read_html(file, header=0, encoding='utf-8')
                    if dfs: return dfs[0]
                except Exception:
                    st.warning(f"El archivo '{file.name}' parecía HTML pero no se pudo leer.")
                    return None
            else:
                st.error(f"Error al leer el archivo Excel '{file.name}': {e}")
                return None
    
    st.warning(f"Formato de archivo no soportado: {file.name}")
    return None


def procesar_archivos_cargados(files: List[UploadedFile]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    dataframes, mensajes_log, columnas_base, orden_columnas_base = [], [], None, None

    for file in files:
        try:
            df = leer_archivo(file)
            if df is None: continue

            filas_originales = len(df)
            df = df[~df.isnull().all(axis=1)]
            filas_eliminadas = filas_originales - len(df)
            
            if df.empty:
                mensajes_log.append(f"ℹ️ El archivo '{file.name}' resultó estar vacío tras la limpieza y fue ignorado."); continue

            df.reset_index(drop=True, inplace=True)
            df.columns = [normalizar_nombre_columna(col) for col in df.columns]
            df = df.loc[:, ~df.columns.str.contains('^unnamed')]

            if columnas_base is None:
                if any(col.isdigit() for col in df.columns):
                    mensajes_log.append(f"⚠️ '{file.name}' ignorado para plantilla (encabezado no válido).")
                    continue
                columnas_base = set(df.columns)
                
                # --- CAMBIO CLAVE: Se elimina sorted() para respetar el orden original ---
                orden_columnas_base = list(df.columns)
                
                mensajes_log.append(f"✅ Estructura base establecida desde '{file.name}'.")

            if set(df.columns) != columnas_base:
                faltantes = sorted(list(columnas_base - set(df.columns)))
                adicionales = sorted(list(set(df.columns) - columnas_base))
                msg = f"❌ '{file.name}' RECHAZADO. Columnas no coinciden. "
                if faltantes: msg += f"Faltan: {faltantes}. "
                if adicionales: msg += f"Sobran: {adicionales}."
                mensajes_log.append(msg); continue

            df = df[orden_columnas_base]
            for col in df.select_dtypes(include=['object']).columns:
                df[col] = df[col].astype(str).apply(limpiar_caracteres_ilegales)
            
            df['archivo_origen'] = file.name
            dataframes.append(df)
            log_msg = f"✅ '{file.name}' procesado."
            if filas_eliminadas > 0:
                log_msg += f" Se eliminaron {filas_eliminadas} filas en blanco."
            mensajes_log.append(log_msg)

        except Exception as e:
            mensajes_log.append(f"💥 Error CRÍTICO al procesar '{file.name}': {e}")

    if not dataframes:
        return None, mensajes_log

    df_consolidado = pd.concat(dataframes, ignore_index=True)

    for col in df_consolidado.select_dtypes(include=['object']).columns:
        if len(df_consolidado) > 0 and df_consolidado[col].nunique() / len(df_consolidado[col].dropna()) < 0.5:
            df_consolidado[col] = df_consolidado[col].astype('category')
    for col in df_consolidado.select_dtypes(include=['float']).columns:
        if (df_consolidado[col].dropna() % 1 == 0).all():
            df_consolidado[col] = df_consolidado[col].astype('Int64')

    return df_consolidado, mensajes_log

# --- Interfaz de Usuario (UI) ---
st.title("📄 Consolidador de Archivos")
st.markdown("Suba múltiples archivos (`xlsx`, `xls`, `csv`, `txt`). La aplicación los unificará, detectando automáticamente la codificación, eliminando filas en blanco y normalizando los datos.")

archivos_cargados = st.file_uploader(
    "📤 Seleccione sus archivos aquí",
    type=['xlsx', 'xls', 'csv', 'txt'],
    accept_multiple_files=True
)

if archivos_cargados:
    with st.spinner("Realizando limpieza profunda y consolidación..."):
        df_final, lista_logs = procesar_archivos_cargados(archivos_cargados)

    st.subheader("📊 Resultados de la Consolidación")

    if lista_logs:
        with st.expander("Registro de Procesamiento", expanded=True):
            for log in lista_logs:
                if "❌" in log or "💥" in log or "RECHAZADO" in log: st.error(log)
                elif "⚠️" in log: st.warning(log)
                else: st.info(log)

    if df_final is not None and not df_final.empty:
        archivos_ok = df_final['archivo_origen'].nunique()
        st.success(f"✅ ¡Consolidación exitosa! Se unieron {archivos_ok} archivos, resultando en {df_final.shape[0]} filas y {df_final.shape[1]} columnas.")
        
        st.dataframe(df_final.astype(object).fillna(''))
        
        try:
            excel_bytes = convertir_a_excel(df_final)
            st.download_button(
                label="📥 Descargar Excel Consolidado",
                data=excel_bytes,
                file_name="consolidado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.error(f"💥 Error al generar el archivo Excel: {e}")
    else:
        st.error("❌ No se pudo consolidar ningún archivo. Revise los mensajes en el registro.")
else:
    st.info("Esperando a que suba los archivos para comenzar el proceso...")
