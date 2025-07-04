import streamlit as st
import pandas as pd
from io import BytesIO
from streamlit.runtime.uploaded_file_manager import UploadedFile
from typing import List, Tuple, Optional
import unicodedata  # Importamos la librería para manejar caracteres unicode

# --- Configuración de la Página de Streamlit ---
st.set_page_config(
    page_title="Consolidador de Archivos",
    page_icon="📄",
    layout="wide"
)

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
    if max(conteo.values()) > 0:
        return max(conteo, key=conteo.get)
    return ','

# ----- NUEVA FUNCIÓN DE NORMALIZACIÓN -----
def normalizar_nombre_columna(col_name: str) -> str:
    """
    Limpia y estandariza un nombre de columna:
    - Convierte a minúsculas.
    - Quita tildes y acentos.
    - Reemplaza 'N°' por 'nro'.
    - Elimina espacios al inicio/final.
    - Reemplaza espacios intermedios con guiones bajos.
    """
    if not isinstance(col_name, str):
        col_name = str(col_name) # Asegurarse de que sea string
        
    s = col_name.lower().strip()
    s = s.replace('°', 'nro').replace('º', 'nro')
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = s.replace(' ', '_')
    return s

def leer_archivo(file: UploadedFile) -> pd.DataFrame:
    nombre_archivo = file.name
    if nombre_archivo.endswith(('.csv', '.txt')):
        posibles_codificaciones = ['utf-8-sig', 'utf-8', 'utf-16', 'latin1', 'windows-1252']
        for encoding in posibles_codificaciones:
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
                file.seek(0)
                dfs = pd.read_html(file, encoding='utf-8', header=0)
                if dfs: return dfs[0]
                else: raise ValueError(f"'{nombre_archivo}' parecía HTML pero no se encontraron tablas.")
            else: raise e
    else: raise ValueError(f"Formato de archivo no soportado: {nombre_archivo}")

# --- FUNCIÓN DE PROCESAMIENTO CON NORMALIZACIÓN INTEGRADA ---
def procesar_archivos_cargados(files: List[UploadedFile]) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], List[str]]:
    dataframes = []
    errores = []
    columnas_base = None
    orden_columnas_base = []

    for file in files:
        try:
            df = leer_archivo(file)
            
            # ----- PASO CLAVE: NORMALIZAR COLUMNAS INMEDIATAMENTE DESPUÉS DE LEER -----
            df.columns = [normalizar_nombre_columna(col) for col in df.columns]
            
            if df.empty:
                errores.append(f"⚠️ El archivo '{file.name}' se leyó como vacío y fue ignorado.")
                continue

            if columnas_base is None:
                columnas_base = set(df.columns)
                orden_columnas_base = list(df.columns)
            
            if set(df.columns) != columnas_base:
                columnas_faltantes = columnas_base - set(df.columns)
                columnas_adicionales = set(df.columns) - columnas_base
                msg = f"'{file.name}' RECHAZADO. Columnas no coinciden (después de normalizar). "
                if columnas_faltantes: msg += f"Faltan: {list(columnas_faltantes)}. "
                if columnas_adicionales: msg += f"Sobran: {list(columnas_adicionales)}."
                errores.append(msg)
                continue

            df = df[orden_columnas_base]
            df['archivo_origen'] = file.name
            dataframes.append(df)
        except Exception as e:
            errores.append(f"❌ Error CRÍTICO al procesar '{file.name}': {e}")

    if not dataframes:
        return None, None, errores

    df_consolidado = pd.concat(dataframes, ignore_index=True)

    # El resto de la lógica no cambia
    for col in df_consolidado.select_dtypes(include=['object']).columns:
        if df_consolidado[col].nunique() / len(df_consolidado) < 0.5:
            df_consolidado[col] = df_consolidado[col].astype('category')
    for col in df_consolidado.select_dtypes(include=['float']).columns:
        if (df_consolidado[col].dropna() % 1 == 0).all():
            df_consolidado[col] = df_consolidado[col].astype('Int64')

    df_para_mostrar = df_consolidado.copy()
    for col in df_para_mostrar.select_dtypes(include=['object', 'category']).columns:
        df_para_mostrar[col] = df_para_mostrar[col].astype(str)

    return df_consolidado, df_para_mostrar, errores

# --- Interfaz de Usuario (UI) ---
st.title("📄 Consolidador Inteligente de Archivos")
st.markdown("""
Sube múltiples archivos y la aplicación los unirá automáticamente.
**Nueva mejora:** Los nombres de las columnas se limpian (se quitan tildes, espacios, etc.) para asegurar la compatibilidad.
""")

archivos_cargados = st.file_uploader(
    "📤 Selecciona tus archivos aquí",
    type=['xlsx', 'xls', 'csv', 'txt'],
    accept_multiple_files=True
)

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
        excel_bytes = convertir_a_excel(df_original)
        st.download_button(
            label="📥 Descargar Excel Consolidado",
            data=excel_bytes,
            file_name="consolidado.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.error("❌ No se pudo consolidar ningún archivo o la tabla resultante está vacía. Revisa los mensajes de error.")
else:
    st.info("Esperando a que subas los archivos para comenzar...")
