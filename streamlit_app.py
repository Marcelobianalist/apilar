import streamlit as st
import pandas as pd
from io import BytesIO
from streamlit.runtime.uploaded_file_manager import UploadedFile
from typing import List, Tuple, Optional
import unicodedata
import re

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
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
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
    return s

def leer_archivo(file: UploadedFile) -> Optional[pd.DataFrame]:
    nombre_archivo = file.name.lower()
    posibles_codificaciones = ['utf-8-sig', 'utf-8', 'latin1', 'windows-1252']

    if nombre_archivo.endswith(('.csv', '.txt')):
        for encoding in posibles_codificaciones:
            try:
                file.seek(0)
                # Añadido skip_blank_lines=True para evitar filas vacías desde el origen
                return pd.read_csv(file, encoding=encoding, sep=None, engine='python', header=0, skip_blank_lines=True)
            except (pd.errors.ParserError, ValueError, UnicodeDecodeError):
                try:
                    file.seek(0)
                    muestra = file.read(2048).decode(encoding, errors='ignore')
                    separador = detectar_delimitador(muestra)
                    file.seek(0)
                    return pd.read_csv(file, encoding=encoding, sep=separador, header=0, skip_blank_lines=True)
                except Exception:
                    continue
        st.warning(f"No se pudo leer el archivo de texto '{file.name}' con las configuraciones probadas.")
        return None

    elif nombre_archivo.endswith(('.xlsx', '.xls')):
        try:
            file.seek(0)
            engine = 'openpyxl' if nombre_archivo.endswith('.xlsx') else 'xlrd'
            return pd.read_excel(file, engine=engine, header=0)
        except Exception as e:
            if 'Expected BOF record' in str(e):
                st.info(f"'{file.name}' parece ser una tabla HTML. Intentando leerla como tal...")
                file.seek(0)
                try:
                    dfs = pd.read_html(file, header=0)
                    if dfs: return dfs[0]
                except Exception:
                    pass
                st.warning(f"El archivo '{file.name}' parecía HTML pero no se pudo leer.")
                return None
            else:
                raise e
    
    st.warning(f"Formato de archivo no soportado: {file.name}")
    return None

def procesar_archivos_cargados(files: List[UploadedFile]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    dataframes, mensajes_log, columnas_base, orden_columnas_base = [], [], None, None

    for file in files:
        try:
            df = leer_archivo(file)
            
            if df is None:
                # El mensaje ya fue emitido por leer_archivo
                continue

            # --- NUEVO: Limpieza crucial post-lectura ---
            # 1. Elimina filas que son completamente nulas. Esto resuelve el problema de las "filas nulas" entre datos.
            df.dropna(how='all', inplace=True)
            
            # 2. Resetea el índice si después de borrar filas queda desordenado.
            df.reset_index(drop=True, inplace=True)

            if df.empty:
                mensajes_log.append(f"ℹ️ El archivo '{file.name}' está vacío o solo contenía filas en blanco. Se ignorará."); continue

            df.columns = [normalizar_nombre_columna(col) for col in df.columns]
            df = df.loc[:, ~df.columns.str.match('unnamed')]

            # --- LÓGICA MEJORADA PARA ESTABLECER LAS COLUMNAS BASE ---
            if columnas_base is None:
                # Heurística: si las columnas son solo números, es probable que Pandas no haya encontrado el encabezado.
                # Saltamos este archivo y buscamos uno mejor para usar como plantilla.
                if all(col.isdigit() for col in df.columns):
                    mensajes_log.append(f"⚠️ El archivo '{file.name}' parece no tener un encabezado válido (columnas numéricas). Se saltará para establecer la estructura base.")
                    continue
                
                # Este archivo parece bueno, lo usamos como plantilla
                columnas_base = set(df.columns)
                orden_columnas_base = sorted(list(df.columns))
                mensajes_log.append(f"✅ Estructura de columnas establecida a partir de '{file.name}'.")
                
                # Añadimos el primer archivo válido a la lista
                df['archivo_origen'] = file.name
                dataframes.append(df)
            
            else: # Ya tenemos una estructura base, comparamos con ella
                if set(df.columns) != columnas_base:
                    faltantes = sorted(list(columnas_base - set(df.columns)))
                    adicionales = sorted(list(set(df.columns) - columnas_base))
                    msg = f"❌ '{file.name}' RECHAZADO. Las columnas no coinciden con la plantilla. "
                    if faltantes: msg += f"Faltan: {faltantes}. "
                    if adicionales: msg += f"Sobran: {adicionales}."
                    mensajes_log.append(msg)
                    continue
                
                # Las columnas coinciden, añadimos el dataframe
                df = df[orden_columnas_base]
                df['archivo_origen'] = file.name
                dataframes.append(df)
                mensajes_log.append(f"✅ '{file.name}' procesado y añadido a la consolidación.")

        except Exception as e:
            mensajes_log.append(f"💥 Error CRÍTICO al procesar '{file.name}': {e}")

    if not dataframes:
        return None, mensajes_log

    df_consolidado = pd.concat(dataframes, ignore_index=True)
    
    for col in df_consolidado.select_dtypes(include=['object', 'category']).columns:
        df_consolidado[col] = df_consolidado[col].astype(str).apply(limpiar_caracteres_ilegales)

    for col in df_consolidado.select_dtypes(include=['object']).columns:
        if df_consolidado[col].nunique() / len(df_consolidado) < 0.5:
            df_consolidado[col] = df_consolidado[col].astype('category')
    
    for col in df_consolidado.select_dtypes(include=['float']).columns:
        if (df_consolidado[col].dropna() % 1 == 0).all():
            df_consolidado[col] = df_consolidado[col].astype('Int64')

    return df_consolidado, mensajes_log

# --- Interfaz de Usuario (UI) ---
st.title("📄 Consolidador de Archivos (Versión Fortalecida)")
st.markdown("Suba múltiples archivos (`xlsx`, `xls`, `csv`, `txt`). La aplicación los unificará, manejando inteligentemente encabezados y filas vacías.")

archivos_cargados = st.file_uploader(
    "📤 Seleccione sus archivos aquí",
    type=['xlsx', 'xls', 'csv', 'txt'],
    accept_multiple_files=True
)

if archivos_cargados:
    with st.spinner("Procesando, validando y consolidando archivos..."):
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
        
        st.dataframe(df_final)
        
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
            st.info("Intente limpiar el caché de la aplicación (Menú ☰ -> Clear cache) y vuelva a cargar los archivos.")
    elif not lista_logs:
        st.info("No se han subido archivos válidos para procesar.")
    else:
        st.error("❌ No se pudo consolidar ningún archivo. Por favor, revise los mensajes en el registro de procesamiento.")
else:
    st.info("Esperando a que suba los archivos para comenzar el proceso...")
