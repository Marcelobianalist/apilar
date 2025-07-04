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
# Esta regex busca TODOS los caracteres de control XML ilegales.
ILLEGAL_CHARACTERS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')

def limpiar_caracteres_ilegales(valor):
    """
    Elimina los caracteres de control no válidos para XML/Excel de un string
    usando una expresión regular pre-compilada y robusta.
    """
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

# --- Funciones de Utilidad ---
@st.cache_data
def convertir_a_excel(df: pd.DataFrame) -> bytes:
    df_limpio = df.copy()
    for col in df_limpio.select_dtypes(include=['object', 'category']).columns:
        # Aseguramos que todo sea string antes de limpiar
        df_limpio[col] = df_limpio[col].astype(str).apply(limpiar_caracteres_ilegales)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_limpio.to_excel(writer, index=False, sheet_name='Consolidado')
    return output.getvalue()

# --- El resto del código es idéntico al anterior y ya es robusto ---
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

def leer_archivo(file: UploadedFile) -> pd.DataFrame:
    nombre_archivo = file.name
    posibles_codificaciones_texto = ['utf-8-sig', 'utf-8', 'latin1', 'windows-1252']
    if nombre_archivo.endswith(('.csv', '.txt')):
        for encoding in posibles_codificaciones_texto:
            try:
                file.seek(0)
                try: return pd.read_csv(file, encoding=encoding, sep=None, engine='python', header=0)
                except (pd.errors.ParserError, ValueError):
                    file.seek(0)
                    muestra = file.read(2048).decode(encoding)
                    separador = detectar_delimitador(muestra)
                    file.seek(0)
                    return pd.read_csv(file, encoding=encoding, sep=separador, header=0)
            except Exception: continue
        raise ValueError(f"No se pudo leer el archivo de texto '{nombre_archivo}'.")
    elif nombre_archivo.endswith(('.xlsx', '.xls')):
        try:
            file.seek(0)
            engine = 'openpyxl' if nombre_archivo.endswith('.xlsx') else 'xlrd'
            return pd.read_excel(file, engine=engine, header=0)
        except Exception as e:
            if 'Expected BOF record' in str(e):
                st.warning(f"'{nombre_archivo}' parece ser una tabla HTML. Intentando leerla como tal...")
                for encoding in posibles_codificaciones_texto:
                    try:
                        file.seek(0)
                        dfs = pd.read_html(file, encoding=encoding, header=0)
                        if dfs: return dfs[0]
                    except Exception: continue
                raise ValueError(f"El archivo '{nombre_archivo}' parecía HTML pero no se pudo leer con codificaciones comunes.")
            else: raise e
    else: raise ValueError(f"Formato de archivo no soportado: {nombre_archivo}")

def procesar_archivos_cargados(files: List[UploadedFile]) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], List[str]]:
    dataframes, errores, columnas_base, orden_columnas_base = [], [], None, []
    for file in files:
        try:
            df = leer_archivo(file)
            df.columns = [normalizar_nombre_columna(col) for col in df.columns]
            df = df.loc[:, ~df.columns.str.match('unnamed')]
            if df.empty:
                errores.append(f"⚠️ El archivo '{file.name}' se leyó como vacío y fue ignorado."); continue
            if columnas_base is None:
                columnas_base, orden_columnas_base = set(df.columns), sorted(list(df.columns))
            if set(df.columns) != columnas_base:
                faltantes = sorted(list(columnas_base - set(df.columns)))
                adicionales = sorted(list(set(df.columns) - columnas_base))
                msg = f"'{file.name}' RECHAZADO. Columnas no coinciden. "
                if faltantes: msg += f"Faltan: {faltantes}. "
                if adicionales: msg += f"Sobran: {adicionales}."
                errores.append(msg); continue
            df = df[orden_columnas_base]
            df['archivo_origen'] = file.name; dataframes.append(df)
        except Exception as e:
            errores.append(f"❌ Error CRÍTICO al procesar '{file.name}': {e}")
    if not dataframes: return None, None, errores
    df_consolidado = pd.concat(dataframes, ignore_index=True)
    for col in df_consolidado.select_dtypes(include=['object']).columns:
        if df_consolidado[col].nunique() / len(df_consolidado) < 0.5: df_consolidado[col] = df_consolidado[col].astype('category')
    for col in df_consolidado.select_dtypes(include=['float']).columns:
        if (df_consolidado[col].dropna() % 1 == 0).all(): df_consolidado[col] = df_consolidado[col].astype('Int64')
    df_para_mostrar = df_consolidado.copy()
    for col in df_para_mostrar.select_dtypes(include=['object', 'category']).columns:
        df_para_mostrar[col] = df_para_mostrar[col].astype(str).apply(limpiar_caracteres_ilegales)
    return df_consolidado, df_para_mostrar, errores

# --- Interfaz de Usuario (UI) ---
st.title("📄 Consolidador de Archivos (Versión Blindada)")
st.markdown("Sube múltiples archivos y la aplicación los unirá. Los nombres de columnas y los datos se limpian para máxima compatibilidad.")
archivos_cargados = st.file_uploader("📤 Selecciona tus archivos aquí", type=['xlsx', 'xls', 'csv', 'txt'], accept_multiple_files=True)
if archivos_cargados:
    with st.spinner("Procesando y normalizando archivos..."):
        df_original, df_para_display, lista_errores = procesar_archivos_cargados(archivos_cargados)
    st.subheader("📊 Resultados de la Consolidación")
    if lista_errores:
        with st.expander("⚠️ Se encontraron algunos problemas (haz clic para ver)", expanded=True):
            for err in lista_errores: st.warning(err)
    if df_para_display is not None and not df_para_display.empty:
        st.success(f"✅ ¡Consolidación exitosa! Se unieron {len(df_original['archivo_origen'].unique())} archivos, resultando en {df_original.shape[0]} filas y {df_original.shape[1]} columnas.")
        st.dataframe(df_para_display)
        try:
            excel_bytes = convertir_a_excel(df_original)
            st.download_button("📥 Descargar Excel Consolidado", data=excel_bytes, file_name="consolidado.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(f"💥 Error final al generar el archivo Excel. El error fue: {e}")
            st.info("Esto puede ocurrir si el caché de la aplicación está corrupto. Intenta limpiar el caché usando el menú (☰) en la esquina superior derecha.")
    else:
        st.error("❌ No se pudo consolidar ningún archivo o la tabla resultante está vacía. Revisa los mensajes de error.")
else:
    st.info("Esperando a que subas los archivos para comenzar...")
