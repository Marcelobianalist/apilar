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
    return s

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

def leer_archivo(file, sheet_name: Union[str, int, None] = 0) -> Optional[pd.DataFrame]:
    nombre_archivo = file.name.lower()
    file.seek(0)
    try:
        if nombre_archivo.endswith(('.csv', '.txt', '.tsv')):
            sep = '\t' if nombre_archivo.endswith('.tsv') else ','
            for encoding in ENCODINGS:
                try:
                    file.seek(0)
                    return pd.read_csv(file, sep=sep, encoding=encoding, low_memory=False)
                except (UnicodeDecodeError, pd.errors.ParserError): continue
            st.warning(f"No se pudo decodificar '{file.name}'.")
            return None
        elif nombre_archivo.endswith(('.xlsx', '.xls')):
            engine = 'openpyxl' if nombre_archivo.endswith('.xlsx') else 'xlrd'
            return pd.read_excel(file, sheet_name=sheet_name, engine=engine)
    except Exception as e:
        st.error(f"Error crítico al leer '{file.name}': {e}")
    return None

def crear_excel_en_memoria(df: pd.DataFrame) -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
    output.seek(0)
    return output

# --- Función de Procesamiento (sin cambios) ---

def procesar_archivos(files: List, sheet_name: Union[str, int, None]) -> Tuple[Optional[pd.DataFrame], List[str]]:
    dataframes, logs = [], []
    for file in files:
        logs.append(f"⏳ Procesando '{file.name}'...")
        df = leer_archivo(file, sheet_name)
        if df is None:
            logs.append(f"💥 Error: No se pudo leer el archivo '{file.name}'.")
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
    df_final = optimizar_tipos_memoria(df_final)
    return df_final, logs

# --- Interfaz Principal (CON LA SOLUCIÓN DEFINITIVA) ---

def main():
    st.title("📄 Consolidador Inteligente de Archivos")
    st.markdown(
        "Sube múltiples archivos (Excel, CSV, TXT, TSV) para unificarlos en uno solo. "
        "El sistema **unirá todas las columnas de todos los archivos** de forma automática."
    )
    
    with st.expander("Opciones avanzadas"):
        sheet_input = st.text_input("Nombre u hoja de Excel a leer", "0", help="Escribe el nombre de la hoja o el número (empezando en 0).")
        try: sheet_name = int(sheet_input)
        except ValueError: sheet_name = sheet_input
            
    archivos = st.file_uploader(
        "📤 Sube tus archivos aquí",
        type=['xlsx', 'xls', 'csv', 'txt', 'tsv'],
        accept_multiple_files=True
    )

    if archivos:
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
            df_display = df_consolidado.head(500).astype(str)
            st.dataframe(df_display, use_container_width=True)

            st.subheader("⬇️ Descarga")
            # --- INICIO DE LA SOLUCIÓN DEFINITIVA ---
            try:
                # 1. INTENTAR GENERAR EL ARCHIVO EXCEL
                with st.spinner("⏳ Preparando archivo Excel (puede tardar o fallar con archivos muy grandes)..."):
                    excel_bytes = crear_excel_en_memoria(df_consolidado)
                
                st.success("✅ ¡Archivo Excel generado con éxito!")
                st.download_button(
                    label="📥 Descargar Excel Consolidado (.xlsx)",
                    data=excel_bytes,
                    file_name="consolidado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception as e:
                # 2. SI FALLA, OFRECER EL PLAN B: CSV
                st.error(
                    "💥 **Error al generar el archivo Excel.** "
                    f"Esto suele ocurrir por falta de memoria al procesar un archivo muy grande. (Error: {e})"
                )
                st.info(
                    "**Como alternativa, puedes descargar todos tus datos en formato CSV, que es mucho más eficiente en memoria.**"
                )
                
                with st.spinner("⏳ Generando archivo CSV de respaldo..."):
                    # Usar utf-8-sig para compatibilidad con caracteres especiales en Excel
                    csv_bytes = df_consolidado.to_csv(index=False).encode('utf-8-sig')

                st.download_button(
                    label="📥 Descargar datos en formato CSV (.csv)",
                    data=csv_bytes,
                    file_name="consolidado.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            # --- FIN DE LA SOLUCIÓN DEFINITIVA ---
        else:
            st.error("❌ No se pudo generar un archivo consolidado. Revisa los registros de errores de arriba.")
    else:
        st.info("A la espera de archivos para iniciar el proceso de consolidación.")

if __name__ == "__main__":
    main()
