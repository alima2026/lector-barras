# Lector Mazda contra stock

Aplicación Streamlit para leer códigos de barra Mazda tal como vienen del proveedor, normalizarlos y buscarlos contra una base de stock/inventario.

## Qué hace

- Lee códigos digitados o escaneados con lector de código de barra.
- Limpia espacios, guiones y símbolos raros del lector.
- Respeta variantes reales pegadas al código, por ejemplo `KD4767UC5A62'` busca `KD47-67-UC5A62`.
- Busca solamente artículos con cantidad mayor a cero.
- Permite buscar un código o muchos códigos, uno por línea.
- Permite subir archivo `.xls`, `.xlsx`, `.xlsm` o `.csv`.

## Archivos importantes

```text
app.py
requirements.txt
runtime.txt
.streamlit/config.toml
```

## Cómo correr localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Cómo subirlo a GitHub

1. Crear un repositorio nuevo en GitHub.
2. Subir estos archivos al repositorio:
   - `app.py`
   - `requirements.txt`
   - `runtime.txt`
   - carpeta `.streamlit`
   - `README.md`
3. Si el repositorio es público, no subir el archivo real de stock.
4. Si el repositorio es privado y querés que la app cargue una base por defecto, podés subir el stock dentro de:

```text
data/Stock_07052026.xls
```

## Cómo publicarlo en Streamlit Community Cloud

1. Entrar a Streamlit Community Cloud.
2. Conectar tu cuenta de GitHub.
3. Elegir el repositorio.
4. En **Main file path**, poner:

```text
app.py
```

5. Deploy.

## Nota sobre GitHub

GitHub guarda el código. Para que la app quede funcionando como página web, lo recomendado es usar Streamlit Community Cloud conectado a GitHub. GitHub Pages no sirve para esta app porque es Python/Streamlit, no una página HTML estática.
