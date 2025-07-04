import streamlit as st
import pandas as pd
from io import BytesIO

st.title("📄 Consolidar Archivos Excel / CSV / TXT")

archivos = st.file_uploader(
    "📤 Sube archivos con las mismas columnas (en cualquier orden): .xlsx, .csv, .txt",
    type=['xlsx', 'xls', 'csv', 'txt'],
    accept_multiple_files=True
)

# Función para detectar delimitador automáticamente
def detectar_delimitador(sample):
    delimitadores = ['\t', ';', ',', '|']
    for sep in delimitadores:
        if sample.count(sep) >= 1:
            return sep
    return ','  # por defecto

# Función para leer archivos txt/csv con codificación y separador detectados
def leer_archivo_texto(archivo):
    posibles_codificaciones = ['utf-8', 'latin1', 'windows-1252']
    for codificacion in posibles_codificaciones:
        try:
            archivo.seek(0)
            muestra = archivo.read(2048).decode(codificacion)
            sep_detectado = detectar_delimitador(muestra)
            archivo.seek(0)
            return pd.read_csv(archivo, sep=sep_detectado, encoding=codificacion)
        except Exception:
            continue
    raise ValueError("No se pudo leer el archivo .txt o .csv con codificaciones comunes")

if archivos:
    dfs = []
    columnas_base = None
    errores = []

    for archivo in archivos:
        nombre = archivo.name
        try:
            if nombre.endswith('.csv') or nombre.endswith('.txt'):
                df = leer_archivo_texto(archivo)
            else:
                df = pd.read_excel(archivo)

            columnas_actuales = set(df.columns)

            if columnas_base is None:
                columnas_base = columnas_actuales
                orden_base = list(df.columns)
            elif columnas_actuales != columnas_base:
                errores.append(f"❌ {nombre} tiene columnas diferentes:\n{list(df.columns)}")
                continue

            df = df[orden_base]
            df['archivo_origen'] = nombre
            dfs.append(df)

        except Exception as e:
            errores.append(f"⚠️ Error al leer {nombre}: {str(e)}")

    if errores:
        st.error("❗ Archivos no consolidados:")
        for err in errores:
            st.text(err)

    if dfs:
        df_consolidado = pd.concat(dfs, ignore_index=True)

        # Optimización de tipos
        for col in df_consolidado.select_dtypes(include=['float']).columns:
            if (df_consolidado[col] % 1 == 0).all():
                df_consolidado[col] = df_consolidado[col].astype('Int64')

        for col in df_consolidado.select_dtypes(include=['object']).columns:
            if df_consolidado[col].nunique() / len(df_consolidado[col]) < 0.5:
                df_consolidado[col] = df_consolidado[col].astype('category')

        st.success(f"✅ Consolidación exitosa: {len(dfs)} archivos unidos.")
        st.dataframe(df_consolidado)

        # Función para generar el Excel
        def crear_excel(df):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Consolidado')
            output.seek(0)
            return output.getvalue()

        excel_bytes = crear_excel(df_consolidado)

        st.download_button(
            label="📥 Descargar Excel Consolidado",
            data=excel_bytes,
            file_name="consolidado.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
