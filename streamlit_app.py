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
# Pre-compilamos la expresión regular para máxima eficiencia.
# Esta regex busca TODOS los caracteres de control XML/Excel ilegales.
ILLEGAL_CHARACTERS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')

def limpiar_caracteres_ilegales(valor):
    """
    Elimina los caracteres de control no válidos para XML/Excel de un string
    usando una expresión regular pre-compilada y robusta.
    Si el valor no es un string, lo devuelve sin cambios.
    """
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

# --- Funciones de Utilidad ---

@st.cache_data
def convertir_a_excel(df: pd.DataFrame) -> bytes:
    """
    Convierte un DataFrame a un archivo Excel en formato de bytes.
    Asume que el DataFrame de entrada ya está limpio.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
    return output.getvalue()

def detectar_delimitador(sample: str) -> str:
    """Detecta el delimitador más probable en una muestra de texto."""
    delimitadores = [';', ',', '\t', '|']
    conteo = {sep: sample.count(sep) for sep in delimitadores}
    # Si hay al menos un delimitador con conteo positivo, devuelve el de mayor frecuencia
    if max(conteo.values()) > 0:
        return max(conteo, key=conteo.get)
    # Si no, devuelve coma como valor por defecto
    return ','

def normalizar_nombre_columna(col_name: str) -> str:
    """Normaliza un nombre de columna para consistencia."""
    if not isinstance(col_name, str):
        col_name = str(col_name)
    s = col_name.lower().strip()
    s = s.replace('�', '') # Elimina el caracter de reemplazo Unicode
    s = s.replace('°', 'nro').replace('º', 'nro')
    # Elimina tildes y diacríticos
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = s.replace(' ', '_').replace('-', '_')
    # Reemplaza múltiples guiones bajos con uno solo
    s = re.sub(r'__+', '_', s)
    return s

def leer_archivo(file: UploadedFile) -> Optional[pd.DataFrame]:
    """
    Lee un archivo subido (CSV, TXT, XLS, XLSX) y lo convierte en un DataFrame.
    Maneja diferentes codificaciones y formatos "sucios".
    """
    nombre_archivo = file.name
    posibles_codificaciones = ['utf-8-sig', 'utf-8', 'latin1', 'windows-1252']

    if nombre_archivo.lower().endswith(('.csv', '.txt')):
        for encoding in posibles_codificaciones:
            try:
                file.seek(0)
                # Intento de lectura automática de separador
                return pd.read_csv(file, encoding=encoding, sep=None, engine='python', header=0)
            except (pd.errors.ParserError, ValueError):
                # Si falla, intentamos detectar el separador manualmente
                file.seek(0)
                muestra = file.read(2048).decode(encoding, errors='ignore')
                separador = detectar_delimitador(muestra)
                file.seek(0)
                try:
                    return pd.read_csv(file, encoding=encoding, sep=separador, header=0)
                except Exception:
                    continue # Intenta con la siguiente codificación
        st.warning(f"No se pudo leer el archivo de texto '{nombre_archivo}' con las codificaciones probadas.")
        return None

    elif nombre_archivo.lower().endswith(('.xlsx', '.xls')):
        try:
            file.seek(0)
            engine = 'openpyxl' if nombre_archivo.lower().endswith('.xlsx') else 'xlrd'
            return pd.read_excel(file, engine=engine, header=0)
        except Exception as e:
            # Manejo del error común de archivos XLS que son en realidad tablas HTML
            if 'Expected BOF record' in str(e):
                st.info(f"'{nombre_archivo}' parece ser una tabla HTML. Intentando leerla como tal...")
                file.seek(0)
                for encoding in posibles_codificaciones:
                    try:
                        dfs = pd.read_html(file, encoding=encoding, header=0)
                        if dfs: return dfs[0]
                    except Exception:
                        continue
                st.warning(f"El archivo '{nombre_archivo}' parecía HTML pero no se pudo leer con las codificaciones comunes.")
                return None
            else:
                raise e # Lanza otras excepciones de Excel
    
    st.warning(f"Formato de archivo no soportado: {nombre_archivo}")
    return None

def procesar_archivos_cargados(files: List[UploadedFile]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    Procesa una lista de archivos subidos, los consolida, limpia y optimiza.
    Devuelve el DataFrame consolidado y una lista de mensajes de error/estado.
    """
    dataframes, mensajes_log, columnas_base, orden_columnas_base = [], [], None, []

    for file in files:
        try:
            df = leer_archivo(file)
            if df is None:
                mensajes_log.append(f"⚠️ El archivo '{file.name}' no pudo ser leído o está en un formato no compatible y fue ignorado."); continue

            df.columns = [normalizar_nombre_columna(col) for col in df.columns]
            df = df.loc[:, ~df.columns.str.match('unnamed')]
            
            if df.empty:
                mensajes_log.append(f"⚠️ El archivo '{file.name}' se leyó como vacío y fue ignorado."); continue

            if columnas_base is None:
                columnas_base = set(df.columns)
                orden_columnas_base = sorted(list(df.columns))
            
            if set(df.columns) != columnas_base:
                faltantes = sorted(list(columnas_base - set(df.columns)))
                adicionales = sorted(list(set(df.columns) - columnas_base))
                msg = f"❌ '{file.name}' RECHAZADO. Las columnas no coinciden con el primer archivo. "
                if faltantes: msg += f"Faltan: {faltantes}. "
                if adicionales: msg += f"Sobran: {adicionales}."
                mensajes_log.append(msg); continue

            df = df[orden_columnas_base]
            df['archivo_origen'] = file.name
            dataframes.append(df)
            mensajes_log.append(f"✅ '{file.name}' procesado correctamente.")

        except Exception as e:
            mensajes_log.append(f"❌ Error CRÍTICO al procesar '{file.name}': {e}")

    if not dataframes:
        return None, mensajes_log

    # --- Consolidación, Limpieza y Optimización Centralizada ---
    df_consolidado = pd.concat(dataframes, ignore_index=True)
    
    # 1. Limpieza de caracteres ilegales en todas las columnas de texto
    for col in df_consolidado.select_dtypes(include=['object', 'category']).columns:
        df_consolidado[col] = df_consolidado[col].astype(str).apply(limpiar_caracteres_ilegales)

    # 2. Optimización de tipos de datos
    for col in df_consolidado.select_dtypes(include=['object']).columns:
        # Convertir a 'category' si la cardinalidad es baja, para ahorrar memoria
        if df_consolidado[col].nunique() / len(df_consolidado) < 0.5:
            df_consolidado[col] = df_consolidado[col].astype('category')
    
    for col in df_consolidado.select_dtypes(include=['float']).columns:
        # Convertir a entero nullable si no hay decimales
        if (df_consolidado[col].dropna() % 1 == 0).all():
            df_consolidado[col] = df_consolidado[col].astype('Int64')

    return df_consolidado, mensajes_log

# --- Interfaz de Usuario (UI) ---
st.title("📄 Consolidador de Archivos (Versión Refinada)")
st.markdown("Suba múltiples archivos (`xlsx`, `xls`, `csv`, `txt`). La aplicación los unificará, limpiando y normalizando los datos para máxima compatibilidad.")

archivos_cargados = st.file_uploader(
    "📤 Seleccione sus archivos aquí",
    type=['xlsx', 'xls', 'csv', 'txt'],
    accept_multiple_files=True
)

if archivos_cargados:
    with st.spinner("Procesando, normalizando y consolidando archivos..."):
        df_final, lista_logs = procesar_archivos_cargados(archivos_cargados)
    
    st.subheader("📊 Resultados de la Consolidación")
    
    if lista_logs:
        with st.expander("Registro de Procesamiento (haga clic para ver detalles)", expanded=True):
            for log in lista_logs:
                if "❌" in log or "RECHAZADO" in log:
                    st.error(log)
                elif "⚠️" in log:
                    st.warning(log)
                else:
                    st.info(log)

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
            st.error(f"💥 Error final al generar el archivo Excel. El error fue: {e}")
            st.info("Esto puede ocurrir si el caché de la aplicación está corrupto. Intente limpiar el caché usando el menú (☰) en la esquina superior derecha y vuelva a cargar los archivos.")
    else:
        st.error("❌ No se pudo consolidar ningún archivo o la tabla resultante está vacía. Por favor, revise los mensajes en el registro de procesamiento.")
else:
    st.info("Esperando a que suba los archivos para comenzar el proceso...")
