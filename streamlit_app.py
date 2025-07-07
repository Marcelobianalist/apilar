import streamlit as st
import pandas as pd
from io import BytesIO
from streamlit.runtime.uploaded_file_manager import UploadedFile
from typing import List, Tuple, Optional
import unicodedata
import re
import numpy as np # Necesario para el reemplazo a NaN

# --- Configuración de la Página ---
st.set_page_config(page_title="Consolidador de Archivos", page_icon="📄", layout="wide")

# ----- FUNCIÓN DE LIMPIEZA DE CARACTERES "NUCLEAR" Y DEFINITIVA -----
ILLEGAL_CHARACTERS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')

def limpiar_caracteres_ilegales(valor):
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

# --- Funciones de Utilidad ---

@st.cache_data
def convertir_a_excel(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    # Se aplica una limpieza final por si acaso, aunque el df ya debería venir limpio.
    df_clean = df.applymap(limpiar_caracteres_ilegales)
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_clean.to_excel(writer, index=False, sheet_name='Consolidado')
    return output.getvalue()

def detectar_delimitador(sample: str) -> str:
    delimitadores = [';', ',', '\t', '|']
    conteo = {sep: sample.count(sep) for sep in delimitadores}
    if max(conteo.values()) > 0: return max(conteo, key=conteo.get)
    return ','

def normalizar_nombre_columna(col_name: str) -> str:
    if not isinstance(col_name, str): col_name = str(col_name)
    s = col_name.lower().strip()
    s = s.replace('�', '')
    s = s.replace('°', 'nro').replace('º', 'nro')
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = s.replace(' ', '_').replace('-', '_')
    s = re.sub(r'__+', '_', s)
    # --- SOLUCIÓN 1: Limpieza final de caracteres ilegales en el nombre de la columna ---
    s = limpiar_caracteres_ilegales(s)
    return s

def leer_archivo(file: UploadedFile) -> Optional[pd.DataFrame]:
    nombre_archivo = file.name.lower()
    posibles_codificaciones = ['utf-8-sig', 'utf-8', 'latin1', 'windows-1252']

    if nombre_archivo.endswith(('.csv', '.txt')):
        for encoding in posibles_codificaciones:
            try:
                file.seek(0)
                return pd.read_csv(file, encoding=encoding, sep=None, engine='python', header=0, skip_blank_lines=True)
            except Exception:
                continue # Intenta con la siguiente codificación/método
        # Si todo falla
        st.warning(f"No se pudo leer el archivo de texto '{file.name}' con las configuraciones automáticas.")
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
                raise e # Lanza otras excepciones de Excel
    
    st.warning(f"Formato de archivo no soportado: {file.name}")
    return None

def procesar_archivos_cargados(files: List[UploadedFile]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    dataframes, mensajes_log, columnas_base, orden_columnas_base = [], [], None, None

    for file in files:
        try:
            df = leer_archivo(file)
            if df is None: continue

            # --- SOLUCIÓN 2: LIMPIEZA AGRESIVA DE FILAS VACÍAS / CON ESPACIOS ---
            # Reemplaza celdas que solo contienen espacios en blanco con NaN.
            df.replace(r'^\s*$', np.nan, regex=True, inplace=True)
            # Reemplaza representaciones de texto comunes de nulos con NaN real.
            # `na_values` en read_csv podría hacer esto, pero hacerlo aquí es más universal.
            df.replace(['nan', 'None', 'NULL', 'NA'], np.nan, inplace=True)
            
            # Ahora, con los NaN estandarizados, elimina filas que son completamente nulas.
            df.dropna(how='all', inplace=True)
            df.reset_index(drop=True, inplace=True)

            if df.empty:
                mensajes_log.append(f"ℹ️ El archivo '{file.name}' resultó estar vacío tras la limpieza y fue ignorado."); continue

            df.columns = [normalizar_nombre_columna(col) for col in df.columns]
            df = df.loc[:, ~df.columns.str.match('unnamed')]

            if columnas_base is None:
                if all(col.isdigit() for col in df.columns):
                    mensajes_log.append(f"⚠️ Se ignoró '{file.name}' para establecer la plantilla porque no parece tener un encabezado válido (columnas numéricas).")
                    continue
                
                columnas_base = set(df.columns)
                orden_columnas_base = sorted(list(df.columns))
                mensajes_log.append(f"✅ Estructura base establecida desde '{file.name}'.")
            
            if set(df.columns) != columnas_base:
                faltantes = sorted(list(columnas_base - set(df.columns)))
                adicionales = sorted(list(set(df.columns) - columnas_base))
                msg = f"❌ '{file.name}' RECHAZADO. Las columnas no coinciden. "
                if faltantes: msg += f"Faltan: {faltantes}. "
                if adicionales: msg += f"Sobran: {adicionales}."
                mensajes_log.append(msg); continue
            
            df = df[orden_columnas_base]
            df['archivo_origen'] = file.name
            dataframes.append(df)
            mensajes_log.append(f"✅ '{file.name}' procesado correctamente.")

        except Exception as e:
            mensajes_log.append(f"💥 Error CRÍTICO al procesar '{file.name}': {e}")

    if not dataframes:
        return None, mensajes_log

    df_consolidado = pd.concat(dataframes, ignore_index=True)
    
    # La limpieza de datos ahora se puede simplificar porque ya se hizo mucho trabajo antes
    for col in df_consolidado.select_dtypes(include=['object']).columns:
        if df_consolidado[col].nunique() / len(df_consolidado[col].dropna()) < 0.5:
            df_consolidado[col] = df_consolidado[col].astype('category')
    
    for col in df_consolidado.select_dtypes(include=['float']).columns:
        if (df_consolidado[col].dropna() % 1 == 0).all():
            df_consolidado[col] = df_consolidado[col].astype('Int64')

    return df_consolidado, mensajes_log

# --- Interfaz de Usuario (UI) ---
st.title("📄 Consolidador de Archivos (Versión Blindada v3)")
st.markdown("Suba múltiples archivos (`xlsx`, `xls`, `csv`, `txt`). La aplicación los unificará, realizando una limpieza profunda de datos, encabezados y filas vacías.")

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
        with st.expander("Registro de Procesamiento (haga clic para ver detalles)", expanded=True):
            for log in lista_logs:
                if "❌" in log or "💥" in log or "RECHAZADO" in log: st.error(log)
                elif "⚠️" in log: st.warning(log)
                else: st.info(log)

    if df_final is not None and not df_final.empty:
        archivos_ok = df_final['archivo_origen'].nunique()
        st.success(f"✅ ¡Consolidación exitosa! Se unieron {archivos_ok} archivos, resultando en {df_final.shape[0]} filas y {df_final.shape[1]} columnas.")
        
        # Para la visualización, reemplazamos NaN con una cadena vacía para que no se muestre "NaN"
        st.dataframe(df_final.fillna(''))
        
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
            st.info("Este error puede ocurrir si quedan caracteres incompatibles. La herramienta intenta eliminarlos, pero algunos pueden persistir. Revise los nombres de columna y los datos en los archivos originales.")
    else:
        st.error("❌ No se pudo consolidar ningún archivo. Por favor, revise los mensajes en el registro de procesamiento.")
else:
    st.info("Esperando a que suba los archivos para comenzar el proceso...")
