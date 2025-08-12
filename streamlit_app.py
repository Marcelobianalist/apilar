import streamlit as st
import pandas as pd
from io import BytesIO
from typing import List, Optional, Tuple, Union
import unicodedata
import re

# --- Configuración de la página de Streamlit ---
st.set_page_config(page_title="Consolidador de Archivos", page_icon="📄", layout="wide")

# --- Constantes ---
# Lista de codificaciones a intentar para archivos de texto plano.
ENCODINGS = ['utf-8-sig', 'utf-8', 'latin1', 'windows-1252', 'iso-8859-1']
# Regex para encontrar y eliminar caracteres de control ilegales en XML/strings.
ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")
# Umbral para convertir una columna de tipo 'object' a 'category' para optimizar memoria.
# Si el número de valores únicos es menor al 50% del total, se convierte.
CATEGORY_THRESHOLD = 0.5


# --- Funciones Auxiliares ---

def limpiar_caracteres_ilegales(valor: any) -> any:
    """Elimina caracteres ilegales de un string."""
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub('', valor)
    return valor

def normalizar_nombre_columna(col: any) -> str:
    """
    Normaliza el nombre de una columna para que sea consistente.
    Convierte a minúsculas, elimina acentos, reemplaza espacios y guiones
    por guiones bajos y elimina caracteres especiales.
    """
    if not isinstance(col, str):
        col = str(col)

    # 1. Limpiar caracteres ilegales y normalizar a minúsculas
    s = limpiar_caracteres_ilegales(col).lower().strip()
    # 2. Descomponer caracteres con acentos (e.g., 'á' -> 'a' + ´)
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    # 3. Reemplazar caracteres especiales y espacios
    s = s.replace('°', 'nro').replace('º', 'nro')
    s = re.sub(r"[ ./\-]+", "_", s) # Reemplaza espacio, punto, slash, guion con _
    # 4. Limpiar guiones bajos duplicados
    s = re.sub(r'__+', '_', s)
    s = s.strip('_')
    return s

def optimizar_tipos_memoria(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimiza los tipos de datos de un DataFrame para reducir el uso de memoria.
    - Convierte 'float' a 'integer' si es posible.
    - Convierte 'object' a 'category' si la cardinalidad es baja.
    """
    df_optimizado = df.copy()
    for col in df_optimizado.select_dtypes(include=['float']).columns:
        # Usamos 'pd.to_numeric' que es más robusto y idiomático.
        df_optimizado[col] = pd.to_numeric(df_optimizado[col], downcast='integer')

    for col in df_optimizado.select_dtypes(include=['object']).columns:
        # No convertir la columna de origen del archivo
        if col == 'archivo_origen':
            continue
        num_valores_unicos = df_optimizado[col].nunique()
        num_total = len(df_optimizado[col])
        if num_total > 0 and (num_valores_unicos / num_total) < CATEGORY_THRESHOLD:
            df_optimizado[col] = df_optimizado[col].astype('category')
            
    return df_optimizado

def leer_archivo(file, sheet_name: Union[str, int, None] = 0) -> Optional[pd.DataFrame]:
    """
    Lee un archivo subido (CSV, TSV, TXT, XLSX, XLS) y lo devuelve como un DataFrame.
    Prueba múltiples codificaciones para archivos de texto.
    """
    nombre_archivo = file.name.lower()
    file.seek(0) # Asegurar que el puntero del archivo está al inicio

    try:
        if nombre_archivo.endswith(('.csv', '.txt', '.tsv')):
            # Para archivos de texto, probamos varias codificaciones comunes
            sep = '\t' if nombre_archivo.endswith('.tsv') else ','
            for encoding in ENCODINGS:
                try:
                    file.seek(0)
                    return pd.read_csv(file, sep=sep, encoding=encoding, low_memory=False)
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
            # Si ninguna codificación funcionó
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
    """
    Procesa una lista de archivos, los consolida en un único DataFrame
    y devuelve un registro de las operaciones.
    
    MEJORA CLAVE: En lugar de forzar a todos los archivos a tener las columnas
    del primero, esta función crea una unión de TODAS las columnas de TODOS los
    archivos, rellenando con NA donde sea necesario.
    """
    dataframes = []
    logs = []
    
    for file in files:
        logs.append(f"⏳ Procesando '{file.name}'...")
        df = leer_archivo(file, sheet_name)
        
        if df is None:
            logs.append(f"💥 Error: No se pudo leer el archivo '{file.name}'.")
            continue
        
        if df.empty:
            logs.append(f"⚠️ Aviso: El archivo '{file.name}' está vacío o no contiene datos legibles.")
            continue
        
        # Limpieza inicial
        df.dropna(how='all', inplace=True) # Elimina filas completamente vacías
        df.columns = [normalizar_nombre_columna(c) for c in df.columns]
        df = df.loc[:, ~df.columns.str.contains('^unnamed', na=False)] # Elimina columnas 'unnamed'
        
        # Añadir columna de origen para trazabilidad
        df['archivo_origen'] = file.name
        
        dataframes.append(df)
        logs.append(f"✅ Éxito: '{file.name}' añadido a la consolidación.")

    if not dataframes:
        return None, logs

    # pd.concat es inteligente y manejará la unión de columnas automáticamente.
    # Rellenará con NaN las columnas que no existan en algunos de los DataFrames.
    df_final = pd.concat(dataframes, ignore_index=True)

    # Reordenar columnas para que 'archivo_origen' aparezca primero
    cols = df_final.columns.tolist()
    if 'archivo_origen' in cols:
        cols.insert(0, cols.pop(cols.index('archivo_origen')))
        df_final = df_final[cols]
    
    # Optimizar tipos de datos en el DataFrame final y grande, es más eficiente
    df_final = optimizar_tipos_memoria(df_final)

    return df_final, logs

def crear_excel_en_memoria(df: pd.DataFrame) -> BytesIO:
    """Convierte un DataFrame a un objeto Excel en memoria (BytesIO)."""
    output = BytesIO()
    # Usar 'xlsxwriter' puede ser más rápido para archivos grandes
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Consolidado')
    output.seek(0)
    return output

def main():
    """Función principal que ejecuta la interfaz de Streamlit."""
    st.title("📄 Consolidador Inteligente de Archivos")
    st.markdown(
        "Sube múltiples archivos (Excel, CSV, TXT, TSV) para unificarlos en uno solo. "
        "El sistema **unirá todas las columnas de todos los archivos** de forma automática."
    )
    
    with st.expander("Opciones avanzadas"):
        sheet_input = st.text_input(
            "Nombre u hoja de Excel a leer", 
            "0",
            help="Escribe el nombre de la hoja (ej. 'Ventas') o el número de la hoja (empezando en 0) a leer de los archivos Excel. Por defecto es la primera (0)."
        )
        # Intentar convertir a entero, si falla, usar como string.
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
            if "✅" in log:
                st.success(log)
            elif "⚠️" in log:
                st.warning(log)
            elif "💥" in log:
                st.error(log)
            else:
                st.info(log)
        
        st.markdown("---")

        if df_consolidado is not None and not df_consolidado.empty:
            st.header("🎉 Consolidación completada")
            st.success(f"Se han consolidado **{df_consolidado.shape[0]:,}** filas y **{df_consolidado.shape[1]}** columnas.")
            
            # Mostrar una previsualización segura para st.dataframe
            st.dataframe(df_consolidado.head(500))

            try:
                excel_bytes = crear_excel_en_memoria(df_consolidado)
                st.download_button(
                    label="📥 Descargar Excel Consolidado",
                    data=excel_bytes,
                    file_name="consolidado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"💥 Error al generar el archivo Excel para descarga: {e}")
        else:
            st.error("❌ No se pudo generar un archivo consolidado. Revisa los registros de errores de arriba.")
    else:
        st.info("A la espera de archivos para iniciar el proceso de consolidación.")

if __name__ == "__main__":
    main()
