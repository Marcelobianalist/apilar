import streamlit as st
import pandas as pd
from io import BytesIO
from typing import List, Optional, Tuple, Union
import unicodedata
import re
import chardet # <-- IMPORTANTE: Nueva librería

# --- Configuración de la página ---
st.set_page_config(page_title="Consolidador Universal", page_icon="⚙️", layout="wide")

# --- Constantes ---
# Lista de respaldo si chardet falla
FALLBACK_ENCODINGS = ['utf-8', 'latin1', 'windows-1252', 'iso-8859-1']
COMMON_DELIMITERS = [',', ';', '\t', '|'] 
ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")
CATEGORY_THRESHOLD = 0.5
DEFAULT_SHEET_NAME_INPUT = "0"


# --- Funciones Auxiliares (sin cambios) ---
def limpiar_caracteres_ilegales(valor: any) -> any:
    if isinstance(valor, str): return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

def normalizar_nombre_columna(col: any) -> str:
    if not isinstance(col, str): col = str(col)
    s = limpiar_caracteres_ilegales(col).lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = s.replace('°', 'nro').replace('º', 'nro')
    s = re.sub(r"[ ./\-]+", "_", s)
    s = re.sub(r'__+', '_', s)
    s = s.strip('_')
    return s if s else "columna_sin_nombre"

def optimizar_tipos_memoria(df: pd.DataFrame) -> pd.DataFrame:
    df_optimizado = df.copy()
    for col in df_optimizado.select_dtypes(include=['float']).columns:
        df_optimizado[col] = pd.to_numeric(df_optimizado[col], downcast='integer')
    for col in df_optimizado.select_dtypes(include=['object']).columns:
        if col == 'archivo_origen': continue
        num_unicos = df_optimizado[col].nunique()
        if len(df_optimizado) > 0 and (num_unicos / len(df_optimizado)) < CATEGORY_THRESHOLD:
            df_optimizado[col] = df_optimizado[col].astype('category')
    return df_optimizado

def crear_excel_en_memoria(df: pd.DataFrame) -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
    output.seek(0)
    return output

# --- LÓGICA DE LECTURA CON DETECCIÓN DE ENCODING Y SEPARADOR ---
def leer_archivo(file, sheet_name: Union[str, int, None]) -> Optional[pd.DataFrame]:
    """
    Lee un archivo subido de forma robusta, detectando automáticamente la codificación
    y el separador para archivos de texto.
    """
    nombre_archivo = file.name.lower()
    
    try:
        # --- Lógica para archivos Excel (sin cambios) ---
        if nombre_archivo.endswith(('.xlsx', '.xls')):
            file.seek(0)
            engine = 'openpyxl' if nombre_archivo.endswith('.xlsx') else 'xlrd'
            return pd.read_excel(file, sheet_name=sheet_name, engine=engine)
            
        # --- Lógica DEFINITIVA para archivos de Texto Plano ---
        elif nombre_archivo.endswith(('.csv', '.txt', '.tsv')):
            file.seek(0)
            # 1. Leer los bytes para detectar la codificación
            raw_data = file.read()
            if not raw_data:
                return pd.DataFrame() # Archivo vacío

            result = chardet.detect(raw_data)
            encoding_detectado = result['encoding']
            
            # Crear una lista de encodings a probar, con el detectado como prioridad
            encodings_to_try = [encoding_detectado] + FALLBACK_ENCODINGS
            # Eliminar duplicados manteniendo el orden
            encodings_to_try = list(dict.fromkeys(filter(None, encodings_to_try)))

            for encoding in encodings_to_try:
                try:
                    file.seek(0)
                    # Intentar leer con auto-detección de separador
                    df = pd.read_csv(file, sep=None, engine='python', encoding=encoding, on_bad_lines='skip')
                    
                    # Si solo tiene una columna, probar delimitadores comunes
                    if df.shape[1] == 1:
                        file.seek(0)
                        first_line = file.readline().decode(encoding)
                        file.seek(0)
                        for sep in COMMON_DELIMITERS:
                            if sep in first_line:
                                try:
                                    df_manual = pd.read_csv(file, sep=sep, encoding=encoding, on_bad_lines='skip')
                                    if df_manual.shape[1] > 1:
                                        return df_manual
                                except pd.errors.ParserError:
                                    file.seek(0)
                                    continue
                    return df # Si todo funciona, devolver el DataFrame

                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue # Probar el siguiente encoding de la lista

            # Si nada funcionó, es un caso muy raro.
            return None
            
    except Exception as e:
        st.error(f"Error crítico al leer '{file.name}': {e}")
        return None

    return None

# --- El resto del código (procesar_archivos, main) NO NECESITA CAMBIOS ---

def procesar_archivos(files: List, sheet_name: Union[str, int, None]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    dataframes, logs = [], []
    sheet_option_used = str(sheet_name) != DEFAULT_SHEET_NAME_INPUT
    for file in files:
        logs.append(f"⏳ Procesando '{file.name}'...")
        is_excel = file.name.lower().endswith(('.xlsx', '.xls'))
        if sheet_option_used and not is_excel:
            logs.append(f"ℹ️  Opción de hoja '{sheet_name}' ignorada para el archivo de texto '{file.name}'.")
        df = leer_archivo(file, sheet_name)
        if df is None:
            logs.append(f"💥 Error: No se pudo leer o decodificar el archivo '{file.name}'.")
            continue
        df.dropna(how='all', inplace=True)
        if df.empty:
            logs.append(f"⚠️ Aviso: El archivo '{file.name}' está vacío o no contiene datos válidos.")
            continue
        df.columns = [normalizar_nombre_columna(c) for c in df.columns]
        df = df.loc[:, ~df.columns.str.contains('^unnamed', na=False)]
        df['archivo_origen'] = file.name
        dataframes.append(df)
        logs.append(f"✅ Éxito: '{file.name}' añadido a la consolidación.")
    if not dataframes: return None, logs
    df_final = pd.concat(dataframes, ignore_index=True, sort=False)
    cols = df_final.columns.tolist()
    if 'archivo_origen' in cols:
        cols.insert(0, cols.pop(cols.index('archivo_origen')))
        df_final = df_final[cols]
    return optimizar_tipos_memoria(df_final), logs

def main():
    st.title("⚙️ Consolidador Universal de Archivos")
    st.markdown("Sube tus archivos (`Excel`, `CSV`, `TXT`, `TSV`). El sistema auto-detectará el formato, **codificación** y **separador** para unirlos.")
    st.info("Para que esta aplicación funcione, la librería `chardet` debe estar instalada (`pip install chardet`).")
    with st.expander("Opciones avanzadas"):
        sheet_input = st.text_input("Nombre u hoja de Excel (solo .xlsx/.xls)", DEFAULT_SHEET_NAME_INPUT, help="Escribe el nombre de la hoja o el número (empezando en 0).")
        try: sheet_name = int(sheet_input)
        except ValueError: sheet_name = sheet_input
    archivos = st.file_uploader("📤 Sube tus archivos aquí", type=['xlsx', 'xls', 'csv', 'txt', 'tsv'], accept_multiple_files=True)
    if archivos:
        # El resto de la función main es idéntica
        with st.spinner("🔄 Procesando y consolidando archivos..."):
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
            st.subheader("📊 Previsualización (primeros 500 registros)")
            st.dataframe(df_consolidado.head(500).astype(str), use_container_width=True)
            st.subheader("⬇️ Descarga")
            try:
                with st.spinner("⏳ Preparando archivo Excel..."):
                    excel_bytes = crear_excel_en_memoria(df_consolidado)
                st.success("✅ ¡Archivo Excel listo!")
                st.download_button("📥 Descargar Excel Consolidado (.xlsx)", excel_bytes, "consolidado.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            except Exception as e:
                st.error(f"💥 **Error al generar Excel:** {e}")
                st.info("**Plan B:** Descargando como CSV, formato más rápido para archivos grandes.")
                with st.spinner("⏳ Generando archivo CSV de respaldo..."):
                    csv_bytes = df_consolidado.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 Descargar Datos en CSV (.csv)", csv_bytes, "consolidado.csv", "text/csv", use_container_width=True)
        else:
            st.error("❌ No se pudo generar un archivo consolidado. Revisa los registros.")
    else:
        st.info("A la espera de archivos para iniciar el proceso de consolidación.")

if __name__ == "__main__":
    main()
