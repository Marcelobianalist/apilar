import streamlit as st
import pandas as pd
from io import BytesIO
from typing import List, Optional, Tuple, Union
import unicodedata
import re

# --- Configuración de la página de Streamlit ---
st.set_page_config(page_title="Consolidador de Archivos", page_icon="📄", layout="wide")

# --- Constantes ---
ENCODINGS = ['utf-8-sig', 'utf-8', 'latin1', 'windows-1252', 'iso-8859-1']
ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")
CATEGORY_THRESHOLD = 0.5


# --- Funciones Auxiliares (sin cambios) ---

def limpiar_caracteres_ilegales(valor: any) -> any:
    """Elimina caracteres ilegales de un string."""
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

def normalizar_nombre_columna(col: any) -> str:
    """Normaliza el nombre de una columna para que sea consistente."""
    if not isinstance(col, str): col = str(col)
    s = limpiar_caracteres_ilegales(col).lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = s.replace('°', 'nro').replace('º', 'nro')
    s = re.sub(r"[ ./\-]+", "_", s)
    s = re.sub(r'__+', '_', s)
    s = s.strip('_')
    return s

def optimizar_tipos_memoria(df: pd.DataFrame) -> pd.DataFrame:
    """Optimiza los tipos de datos de un DataFrame para reducir el uso de memoria."""
    df_optimizado = df.copy()
    for col in df_optimizado.select_dtypes(include=['float']).columns:
        df_optimizado[col] = pd.to_numeric(df_optimizado[col], downcast='integer')
    for col in df_optimizado.select_dtypes(include=['object']).columns:
        if col == 'archivo_origen': continue
        num_valores_unicos = df_optimizado[col].nunique()
        num_total = len(df_optimizado[col])
        if num_total > 0 and (num_valores_unicos / num_total) < CATEGORY_THRESHOLD:
            df_optimizado[col] = df_optimizado[col].astype('category')
    return df_optimizado

def leer_archivo(file, sheet_name: Union[str, int, None] = 0) -> Optional[pd.DataFrame]:
    """Lee un archivo subido y lo devuelve como un DataFrame."""
    nombre_archivo = file.name.lower()
    file.seek(0)
    try:
        if nombre_archivo.endswith(('.csv', '.txt', '.tsv')):
            sep = '\t' if nombre_archivo.endswith('.tsv') else ','
            for encoding in ENCODINGS:
                try:
                    file.seek(0)
                    return pd.read_csv(file, sep=sep, encoding=encoding, low_memory=False)
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
            st.warning(f"No se pudo decodificar '{file.name}' con las codificaciones probadas.")
            return None
        elif nombre_archivo.endswith('.xlsx'):
            return pd.read_excel(file, sheet_name=sheet_name, engine='openpyxl')
        elif nombre_archivo.endswith('.xls'):
            return pd.read_excel(file, sheet_name=sheet_name, engine='xlrd')
    except Exception as e:
        st.error(f"Error crítico al leer '{file.name}': {e}")
        return None
    return None

def procesar_archivos(files: List, sheet_name: Union[str, int, None]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """Procesa una lista de archivos, los consolida y devuelve un registro."""
    dataframes, logs = [], []
    for file in files:
        logs.append(f"⏳ Procesando '{file.name}'...")
        df = leer_archivo(file, sheet_name)
        if df is None:
            logs.append(f"💥 Error: No se pudo leer el archivo '{file.name}'.")
            continue
        if df.empty:
            logs.append(f"⚠️ Aviso: El archivo '{file.name}' está vacío.")
            continue
        df.dropna(how='all', inplace=True)
        df.columns = [normalizar_nombre_columna(c) for c in df.columns]
        df = df.loc[:, ~df.columns.str.contains('^unnamed', na=False)]
        df['archivo_origen'] = file.name
        dataframes.append(df)
        logs.append(f"✅ Éxito: '{file.name}' añadido a la consolidación.")
    if not dataframes: return None, logs
    df_final = pd.concat(dataframes, ignore_index=True)
    cols = df_final.columns.tolist()
    if 'archivo_origen' in cols:
        cols.insert(0, cols.pop(cols.index('archivo_origen')))
        df_final = df_final[cols]
    df_final = optimizar_tipos_memoria(df_final)
    return df_final, logs

def crear_excel_en_memoria(df: pd.DataFrame) -> BytesIO:
    """Convierte un DataFrame a un objeto Excel en memoria (BytesIO)."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
    output.seek(0)
    return output


# --- Interfaz Principal (con los cambios) ---

def main():
    """Función principal que ejecuta la interfaz de Streamlit."""
    st.title("📄 Consolidador Inteligente de Archivos")
    st.markdown(
        "Sube múltiples archivos (Excel, CSV, TXT, TSV) para unificarlos en uno solo. "
        "El sistema **unirá todas las columnas de todos los archivos** de forma automática."
    )
    
    with st.expander("Opciones avanzadas"):
        sheet_input = st.text_input(
            "Nombre u hoja de Excel a leer", "0",
            help="Escribe el nombre de la hoja (ej. 'Ventas') o el número (empezando en 0)."
        )
        try:
            sheet_name = int(sheet_input)
        except ValueError:
            sheet_name = sheet_input
            
    archivos = st.file_uploader(
        "📤 Sube tus archivos aquí",
        type=['xlsx', 'xls', 'csv', 'txt', 'tsv'],
        accept_multiple_files=True
    )

    if archivos:
        with st.spinner("🔄 Procesando y consolidando archivos... Por favor, espera."):
            df_consolidado, logs = procesar_archivos(archivos, sheet_name)

        st.subheader("📜 Registro de Procesamiento")
        for log in logs:
            if "✅" in log: st.success(log)
            elif "⚠️" in log: st.warning(log)
            elif "💥" in log: st.error(log)
            else: st.info(log)
        
        st.markdown("---")

        if df_consolidado is not None and not df_consolidado.empty:
            st.header("🎉 Consolidación completada")
            st.success(f"Se han consolidado **{df_consolidado.shape[0]:,}** filas y **{df_consolidado.shape[1]}** columnas.")
            
            st.subheader("📊 Previsualización de los primeros 500 registros")
            df_display = df_consolidado.head(500).astype(str)
            st.dataframe(df_display, use_container_width=True)

            # --- INICIO DEL CAMBIO ---
            st.subheader("⬇️ Descarga")
            try:
                # Mostrar un spinner MIENTRAS se genera el archivo Excel en memoria
                with st.spinner("⏳ Preparando el archivo Excel para la descarga..."):
                    excel_bytes = crear_excel_en_memoria(df_consolidado)
                
                # Una vez generado, el spinner desaparece y el botón aparece
                st.download_button(
                    label="📥 Descargar Excel Consolidado",
                    data=excel_bytes,
                    file_name="consolidado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"💥 Error al generar el archivo Excel para descarga: {e}")
            # --- FIN DEL CAMBIO ---
        else:
            st.error("❌ No se pudo generar un archivo consolidado. Revisa los registros de errores de arriba.")
    else:
        st.info("A la espera de archivos para iniciar el proceso de consolidación.")

if __name__ == "__main__":
    main()
