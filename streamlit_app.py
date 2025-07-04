import streamlit as st
import pandas as pd
from io import BytesIO
from streamlit.runtime.uploaded_file_manager import UploadedFile
from typing import List, Tuple, Optional

# --- Configuración de la Página de Streamlit ---
st.set_page_config(
    page_title="Consolidador de Archivos",
    page_icon="📄",
    layout="wide"
)

# --- Funciones (sin cambios) ---
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

def leer_archivo(file: UploadedFile) -> pd.DataFrame:
    nombre_archivo = file.name
    if nombre_archivo.endswith(('.csv', '.txt')):
        posibles_codificaciones = ['utf-8-sig', 'utf-8', 'utf-16', 'latin1', 'windows-1252']
        for encoding in posibles_codificaciones:
            try:
                file.seek(0)
                try:
                    return pd.read_csv(file, encoding=encoding, sep=None, engine='python')
                except (pd.errors.ParserError, ValueError):
                    file.seek(0)
                    muestra = file.read(2048).decode(encoding)
                    separador = detectar_delimitador(muestra)
                    file.seek(0)
                    return pd.read_csv(file, encoding=encoding, sep=separador)
            except Exception:
                continue
        raise ValueError(f"No se pudo leer el archivo '{nombre_archivo}' con las codificaciones probadas.")
    elif nombre_archivo.endswith(('.xlsx', '.xls')):
        engine = 'openpyxl' if nombre_archivo.endswith('.xlsx') else 'xlrd'
        return pd.read_excel(file, engine=engine)
    else:
        raise ValueError(f"Formato de archivo no soportado: {nombre_archivo}")

# --- Función de Procesamiento con Diagnósticos ---
def procesar_archivos_cargados(files: List[UploadedFile]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    dataframes = []
    errores = []
    columnas_base = None
    orden_columnas_base = []

    st.subheader("🕵️‍♂️ Diagnóstico de Archivos")
    st.info("Revisando las columnas de cada archivo antes de consolidar...")

    for file in files:
        try:
            df = leer_archivo(file)

            # ----- INICIO DE LA SECCIÓN DE DIAGNÓSTICO -----
            # Mostramos las columnas de CADA archivo en un desplegable
            with st.expander(f"Análisis de '{file.name}'", expanded=True):
                if df.empty:
                    st.warning("El archivo se leyó como vacío. ¿La cabecera y los datos son correctos?")
                else:
                    st.write("**Columnas detectadas:**")
                    # Mostramos las columnas como una lista para una fácil comparación
                    st.code(sorted(list(df.columns)))
                    st.write("**Muestra de datos (primeras 2 filas):**")
                    st.dataframe(df.head(2))
            # ----- FIN DE LA SECCIÓN DE DIAGNÓSTICO -----
            
            if df.empty:
                errores.append(f"⚠️ El archivo '{file.name}' se leyó como vacío y fue ignorado.")
                continue

            if columnas_base is None:
                st.write(f"➡️ Estableciendo columnas base con el primer archivo: **'{file.name}'**")
                columnas_base = set(df.columns)
                orden_columnas_base = list(df.columns)
            
            if set(df.columns) != columnas_base:
                columnas_faltantes = columnas_base - set(df.columns)
                columnas_adicionales = set(df.columns) - columnas_base
                msg = f"'{file.name}' RECHAZADO. Columnas no coinciden. "
                if columnas_faltantes:
                    msg += f"Faltan: {list(columnas_faltantes)}. "
                if columnas_adicionales:
                    msg += f"Sobran: {list(columnas_adicionales)}."
                errores.append(msg)
                continue

            df = df[orden_columnas_base]
            df['archivo_origen'] = file.name
            dataframes.append(df)

        except Exception as e:
            errores.append(f"❌ Error CRÍTICO al procesar '{file.name}': {e}")

    if not dataframes:
        return None, errores

    df_consolidado = pd.concat(dataframes, ignore_index=True)

    # Optimización de tipos (sin cambios)
    for col in df_consolidado.select_dtypes(include=['object']).columns:
        if df_consolidado[col].nunique() / len(df_consolidado) < 0.5:
            df_consolidado[col] = df_consolidado[col].astype('category')
    for col in df_consolidado.select_dtypes(include=['float']).columns:
        if (df_consolidado[col].dropna() % 1 == 0).all():
            df_consolidado[col] = df_consolidado[col].astype('Int64')

    return df_consolidado, errores

# --- Interfaz de Usuario (UI) ---
st.title("📄 Consolidador Inteligente de Archivos")
st.markdown("""
Sube múltiples archivos **Excel (.xlsx, .xls)**, **CSV (.csv)** o **Texto (.txt)**.
La aplicación los unirá en una única tabla, siempre y cuando compartan las mismas columnas.
""")

archivos_cargados = st.file_uploader(
    "📤 Selecciona tus archivos aquí",
    type=['xlsx', 'xls', 'csv', 'txt'],
    accept_multiple_files=True
)

if archivos_cargados:
    with st.spinner("Procesando archivos..."):
        df_final, lista_errores = procesar_archivos_cargados(archivos_cargados)

    st.subheader("📊 Resultados de la Consolidación")
    
    if lista_errores:
        st.error("Se encontraron problemas durante el proceso:")
        for err in lista_errores:
            st.warning(err)

    if df_final is not None:
        if not df_final.empty:
            st.success(f"✅ ¡Consolidación exitosa! Se unieron {len(df_final['archivo_origen'].unique())} archivos, resultando en {df_final.shape[0]} filas y {df_final.shape[1]} columnas.")
            st.dataframe(df_final)
            excel_bytes = convertir_a_excel(df_final)
            st.download_button(
                label="📥 Descargar Excel Consolidado",
                data=excel_bytes,
                file_name="consolidado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("❌ La consolidación resultó en una tabla vacía. Revisa los diagnósticos y errores de arriba.")
    else:
         st.error("❌ No se pudo consolidar ningún archivo. Revisa los mensajes de error para entender por qué fueron rechazados.")
else:
    st.info("Esperando a que subas los archivos para comenzar...")
