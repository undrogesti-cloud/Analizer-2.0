# Analizer

Busca los negocios de un municipio en OpenStreetMap, localiza y analiza su web y los ordena por la probabilidad de que necesiten una web nueva o un rediseño. El resultado se consulta en una app de Streamlit y se descarga a Excel.

- [scan.py](src/analizer/scan.py): escanea un municipio y guarda los datos en DuckDB.
- [ranking.sql](src/analizer/ranking.sql): calcula la puntuación, la prioridad y los argumentos de venta.
- [app.py](src/analizer/app.py): visor del ranking con filtros, mapa y descarga a Excel.
- [field-docs.md](field-docs.md): qué significa cada campo de la app y del Excel.

## Requisitos

- Python 3.12 o superior.
- [uv](https://docs.astral.sh/uv/) para gestionar el entorno y las dependencias.
- Conexión a internet: el escaneo consulta Nominatim, Overpass, las webs de los negocios y archive.org.

No hace falta ninguna clave de API ni fichero `.env`.

## Instalación

```bash
git clone <url-del-repo>
cd Analizer-2.0
uv sync
```

`uv sync` crea el entorno virtual e instala las dependencias de [pyproject.toml](pyproject.toml), incluidas las de desarrollo (Jupyter, ruff). Por defecto el entorno se crea en `.venv/`. Si quieres tenerlo fuera del proyecto, define `UV_PROJECT_ENVIRONMENT` antes de ejecutar `uv sync`:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/analizer"
```

[.vscode/settings.json](.vscode/settings.json) apunta a esa ruta como intérprete; si usas `.venv/`, cámbialo allí o selecciona el intérprete desde VS Code.

## Uso

### 1. Escanear un municipio

```bash
uv run python -m analizer.scan --municipio Serra --provincia Valencia
```

Tarda unos minutos según el número de negocios. Guarda:

- `data/raw/negocios_<municipio>.json` y `data/raw/webs_<municipio>.json`: datos en bruto.
- `data/processed/analizer.duckdb`: base de datos con las tablas `negocios`, `webs` y `escaneos`, y las vistas `ranking` y `ranking_municipio`.

Puedes escanear varios municipios, uno por ejecución; se acumulan en la misma base de datos. Volver a escanear un municipio sustituye sus datos anteriores.

Si Overpass no responde, el script prueba varios servidores y, si todos fallan, termina con `Overpass no responde; prueba más tarde`.

### 2. Abrir el visor

```bash
uv run streamlit run src/analizer/app.py
```

Se abre en <http://localhost:8501>. Si todavía no hay datos, la app muestra el comando de escaneo que hay que lanzar primero.

> La app abre la base de datos en solo lectura. Si un escaneo está escribiendo en ese momento, recarga la página cuando termine.

## Datos

`data/raw/` y `data/processed/` no se suben al repositorio (ver [.gitignore](.gitignore)): tras clonar hay que lanzar el escaneo al menos una vez.

Para consultar la base de datos directamente:

```bash
uv run python -c "import duckdb; print(duckdb.connect('data/processed/analizer.duckdb', read_only=True).sql('SELECT * FROM ranking_municipio'))"
```

Desde VS Code, las extensiones recomendadas en [.vscode/extensions.json](.vscode/extensions.json) incluyen SQLTools con el driver de DuckDB, ya configurado en modo solo lectura. Si clonas el proyecto en otra ruta, actualiza `database` en `sqltools.connections` de [.vscode/settings.json](.vscode/settings.json).

## Desarrollo

```bash
uv run ruff check .        # lint
uv run ruff format .       # formato
uv run jupyter lab         # notebooks en notebooks/
```

Para añadir una dependencia: `uv add <paquete>` (o `uv add --dev <paquete>` si es solo de desarrollo).
