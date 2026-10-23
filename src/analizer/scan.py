"""Recoge los negocios de un municipio (OSM), localiza y analiza su web y guarda
las señales en DuckDB para el ranking de `ranking.sql`.

Uso:
    python -m analizer.scan --codigo-ine 46228
    python -m analizer.scan --municipio Serra --provincia Valencia
"""

import argparse
import asyncio
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import duckdb
import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "processed" / "analizer.duckdb"
RAW_DIR = ROOT / "data" / "raw"
SQL_PATH = Path(__file__).with_name("ranking.sql")
# Opcional: diccionario de municipios del INE (codigo_ine,municipio,provincia,comunidad) para actualizar la tabla
MUNICIPIOS_CSV = Path(__file__).with_name("municipios.csv")
# Tipos de las columnas no textuales que pueden llegar vacías en un escaneo (el resto es VARCHAR)
COLUMN_TYPES = {"jquery_version": "DOUBLE", "wp_version": "DOUBLE", "anio_copyright": "BIGINT",
                "anio_agencia": "BIGINT", "lat": "DOUBLE", "lon": "DOUBLE"}

UA = "Mozilla/5.0 (compatible; analizer/0.1)"
API_UA = "analizer/0.1"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
YEAR = datetime.now(UTC).year

# Categorías OSM que no son clientes potenciales (servicios públicos, mobiliario, naturaleza...)
EXCLUDED = {
    "drinking_water", "fountain", "toilets", "waste_basket", "bench", "information",
    "viewpoint", "picnic_site", "parking", "recycling", "place_of_worship", "shelter",
    "fire_station", "school", "townhall", "police", "post_office", "kindergarten",
    "library", "playground", "pitch", "park", "waste_disposal", "bbq", "firepit",
    "social_facility", "grave_yard", "community_centre", "atm", "artwork", "monastery",
    "wilderness_hut", "lavoir", "nature_reserve", "waste_transfer_station",
    "political_party", "religion", "government", "hospital", "childcare", "attraction",
    "camp_pitch", "bicycle_parking", "vending_machine", "telephone", "clock",
    "hunting_stand", "taxi", "bus_station", "dog_park", "swimming_pool", "track",
    "water_point", "charging_station", "motorcycle_parking", "public_bath",
}
CATEGORY_KEYS = ("shop", "amenity", "craft", "office", "tourism", "healthcare", "leisure")
# Palabras que no aportan al adivinar el dominio a partir del nombre
NAME_STOPWORDS = {
    "bar", "restaurante", "restaurant", "cafeteria", "horno", "farmacia", "clinica",
    "dental", "dr", "de", "del", "la", "el", "los", "las", "y", "i", "ca", "les", "els",
}

PARKED_RE = re.compile(
    r"dominio (est[aá] )?en venta|domain (is )?for sale|this domain|parked|"
    r"en construcci[oó]n|under construction|coming soon|pr[oó]ximamente|pr[oó]ximo lanzamiento|launching soon|"
    r"welcome to nginx|apache2? (ubuntu|debian) default|index of /|plesk|cpanel|"
    r"hosting (by|de)|sitio web en mantenimiento",
    re.I,
)
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", re.I)
AGENCY_RE = re.compile(
    r"(dise[ñn]ad[ao] por|dise[ñn]o web|desarrollad[ao] por|web by|designed by|powered by)"
    r"[^<]{0,80}?((?:19|20)\d{2})?",
    re.I,
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+34[\s.]?)?(?:[69]\d{2}[\s.]?\d{2,3}[\s.]?\d{2,3}[\s.]?\d{2,3})")
BOOKING_RE = re.compile(
    r"reserva|book(ing)?|cita previa|pide cita|calendly|thefork|eltenedor|covermanager|"
    r"doctoralia|booksy|treatwell|simplybook",
    re.I,
)


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", text)


def category(tags: dict) -> tuple[str | None, str | None]:
    for key in CATEGORY_KEYS:
        if key in tags:
            return key, tags[key]
    return None, None


def overpass_businesses(relation_id: int) -> list[dict]:
    query = f"""[out:json][timeout:90];
area({3600000000 + relation_id})->.a;
nwr(area.a)[~"^({'|'.join(CATEGORY_KEYS)})$"~"."];
out center tags;"""
    for endpoint in OVERPASS_ENDPOINTS * 2:
        try:
            r = httpx.post(endpoint, data={"data": query}, timeout=120, headers={"User-Agent": API_UA})
            r.raise_for_status()
            return r.json()["elements"]
        except httpx.HTTPError as exc:
            print(f"Overpass falló en {endpoint}: {exc}; reintentando...")
    raise SystemExit("Overpass no responde; prueba más tarde")


def find_municipality(name: str, province: str) -> dict:
    r = httpx.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{name}, {province}, España", "format": "json", "limit": 5},
        headers={"User-Agent": API_UA},
        timeout=30,
    )
    r.raise_for_status()
    for hit in r.json():
        if hit["osm_type"] == "relation":
            return hit
    raise SystemExit(f"No encuentro el municipio {name} ({province}) en OSM")


def to_rows(elements: list[dict], municipio: str, codigo_ine: str) -> list[dict]:
    rows = []
    for e in elements:
        tags = e.get("tags", {})
        key, value = category(tags)
        if not tags.get("name") or value in EXCLUDED:
            continue
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        rows.append({
            "osm_id": f"{e['type']}/{e['id']}",
            "nombre": tags["name"],
            "categoria_osm": key,
            "tipo": value,
            "web_osm": tags.get("website") or tags.get("contact:website") or tags.get("url"),
            "telefono_osm": tags.get("phone") or tags.get("contact:phone"),
            "email_osm": tags.get("email") or tags.get("contact:email"),
            "direccion": " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])) or None,
            "cp": tags.get("addr:postcode"),
            "marca": tags.get("brand") or tags.get("operator"),
            "municipio": municipio,
            "codigo_ine": codigo_ine,
            "lat": lat,
            "lon": lon,
        })
    return rows


def name_words(name: str, municipio: str) -> list[str]:
    """Palabras distintivas del nombre: sin genéricos ni el nombre del municipio."""
    town = set(slug(municipio).split())
    return [w for w in slug(name).split() if w not in NAME_STOPWORDS and w not in town]


def candidate_domains(name: str, municipio: str) -> list[str]:
    words = slug(name).split()
    core = name_words(name, municipio)
    if not core:
        # "Farmacia Serra" no tiene nada propio que buscar: adivinar daría la web del ayuntamiento
        return []
    bases = {"".join(core), "".join(words), "-".join(core)}
    return [f"{b}.{tld}" for b in bases if len(b) >= 5 for tld in ("com", "es")]


async def fetch(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response | None, str | None]:
    try:
        return await client.get(url), None
    except httpx.ConnectError as exc:
        return None, "ssl" if "SSL" in str(exc) or "certificate" in str(exc).lower() else "conexion"
    except httpx.HTTPError as exc:
        return None, type(exc).__name__


async def robots_allows(client: httpx.AsyncClient, base: str) -> bool:
    r, _ = await fetch(client, base.rstrip("/") + "/robots.txt")
    if r is None or r.status_code != 200:
        return True
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(UA, base)


async def wayback_last_change(client: httpx.AsyncClient, domain: str) -> tuple[str | None, str | None]:
    """Primera captura y última captura con contenido distinto en archive.org."""
    r, _ = await fetch(
        client,
        f"https://web.archive.org/cdx/search/cdx?url={domain}&output=json&fl=timestamp&collapse=digest&filter=statuscode:200",
    )
    try:
        rows = r.json()[1:] if r is not None and r.status_code == 200 else []
    except json.JSONDecodeError:
        rows = []
    if not rows:
        return None, None
    return rows[0][0][:8], rows[-1][0][:8]


def extract(html: str, final_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    low = html.lower()
    gen = soup.find("meta", attrs={"name": re.compile("generator", re.I)})
    generator = gen.get("content") if gen else None
    jq = re.search(r"jquery[.-]?(\d+\.\d+)", low)
    wp = re.search(r"wordpress (\d+\.\d+)", (generator or "").lower())
    years = [int(y) for y in COPYRIGHT_RE.findall(html) if int(y) <= YEAR]
    agency = AGENCY_RE.search(text)
    hrefs = " ".join(a.get("href", "") for a in soup.find_all("a")).lower()

    return {
        "url_final": final_url,
        "https": final_url.startswith("https://"),
        "titulo": (soup.title.string or "").strip()[:200] if soup.title else None,
        "bytes": len(html.encode()),
        "aparcado": bool(PARKED_RE.search(text[:3000])) or len(text) < 200,
        "viewport": soup.find("meta", attrs={"name": "viewport"}) is not None,
        "generator": generator,
        "jquery_version": float(jq.group(1)) if jq else None,
        "wp_version": float(wp.group(1)) if wp else None,
        "flash": ".swf" in low,
        "tablas_layout": len(soup.find_all("table")) >= 3 and not soup.find_all(["section", "nav", "header"]),
        "anio_copyright": max(years) if years else None,
        "agencia": agency.group(0)[:120] if agency else None,
        "anio_agencia": int(agency.group(2)) if agency and agency.group(2) else None,
        "stack_moderno": bool(re.search(r"__next|_nuxt|webflow|cdn\.shopify|squarespace|gatsby", low)),
        "constructor_diy": bool(re.search(r"wix\.com|wixstatic|jimdo|site123|webnode|go daddy website builder|godaddy\.com/websites", low)),
        "reserva_online": bool(BOOKING_RE.search(text)) or bool(BOOKING_RE.search(hrefs)),
        "formulario": soup.find("form") is not None,
        "whatsapp": "wa.me" in low or "api.whatsapp" in low,
        "mapa": "google.com/maps" in low or "maps.google" in low or "openstreetmap" in low,
        "redes": bool(re.search(r"facebook\.com|instagram\.com|tiktok\.com", hrefs)),
        "analitica": bool(re.search(r"gtag\(|googletagmanager|fbq\(|google-analytics", low)),
        "aviso_legal": "aviso legal" in text.lower() or "aviso-legal" in hrefs,
        "privacidad": "privacidad" in text.lower() or "privacy" in hrefs,
        "cookies": "cookie" in low,
        "emails": ", ".join(sorted({m for m in EMAIL_RE.findall(text) if not m.endswith((".png", ".jpg"))}))[:300] or None,
        "telefonos": ", ".join(sorted({re.sub(r"\D", "", p)[-9:] for p in PHONE_RE.findall(text)}))[:200] or None,
        "texto_slug": f" {' '.join(slug(text).split())} ",
    }


async def analyze(client: httpx.AsyncClient, sem: asyncio.Semaphore, row: dict, municipio: str) -> dict:
    async with sem:
        urls, origen = ([row["web_osm"]], "osm") if row["web_osm"] else (
            [f"https://{d}" for d in candidate_domains(row["nombre"], municipio)], "deducida")
        result = {"osm_id": row["osm_id"], "origen_web": None, "estado": "sin_web", "error_ssl": False}
        for url in urls:
            if not url.startswith("http"):
                url = "https://" + url
            r, err = await fetch(client, url)
            ssl_error = err == "ssl"
            if r is None and ssl_error:
                # La web existe pero con certificado roto: la leemos sin verificar
                async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=15,
                                             headers={"User-Agent": UA}) as insecure:
                    r, err = await fetch(insecure, url)
            if r is None and url.startswith("https://"):
                r, err = await fetch(client, "http://" + url[8:])
            if r is None or r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
                continue
            feats = extract(r.text, str(r.url))
            texto = feats.pop("texto_slug")
            # Un dominio deducido solo vale si el texto visible nombra al negocio y al municipio
            if origen == "deducida" and not (
                all(f" {w} " in texto for w in name_words(row["nombre"], municipio))
                and f" {' '.join(slug(municipio).split())} " in texto
            ):
                continue
            domain = urlparse(str(r.url)).netloc
            first, last = await wayback_last_change(client, domain)
            result |= feats | {
                "origen_web": origen,
                "estado": "aparcada" if feats["aparcado"] else "ok",
                "error_ssl": ssl_error,
                "robots_permite": await robots_allows(client, f"{urlparse(str(r.url)).scheme}://{domain}/"),
                "dominio": domain,
                "wayback_primera": first,
                "wayback_ultimo_cambio": last,
            }
            break
        return result


async def analyze_all(rows: list[dict], municipio: str) -> list[dict]:
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers={"User-Agent": UA}) as client:
        return await asyncio.gather(*(analyze(client, sem, r, municipio) for r in rows))


def load_municipios(con: duckdb.DuckDBPyConnection) -> None:
    """Crea la tabla `municipios`; si hay un `municipios.csv` nuevo del INE, aplica sus altas y cambios de nombre."""
    con.execute("""CREATE TABLE IF NOT EXISTS municipios (
        codigo_ine VARCHAR PRIMARY KEY, municipio VARCHAR NOT NULL,
        provincia VARCHAR NOT NULL, comunidad VARCHAR NOT NULL)""")
    if MUNICIPIOS_CSV.exists():
        con.execute("INSERT OR REPLACE INTO municipios SELECT * FROM read_csv(?, header=true, all_varchar=true)",
                    [str(MUNICIPIOS_CSV)])
    elif not con.execute("SELECT count(*) FROM municipios").fetchall()[0][0]:
        raise RuntimeError(f"La tabla municipios está vacía: copia el diccionario del INE en {MUNICIPIOS_CSV}")


def init_db(con: duckdb.DuckDBPyConnection) -> None:
    """Deja la base de datos al día: municipios, columna `codigo_ine` y vistas del ranking."""
    load_municipios(con)
    con.execute("CREATE TABLE IF NOT EXISTS escaneos (municipio VARCHAR, codigo_ine VARCHAR, fecha TIMESTAMP)")
    # Una columna vacía en el primer escaneo se crea con tipo NULL y rechazaría los datos de los siguientes
    vacias = con.execute("""SELECT table_name, column_name FROM duckdb_columns()
        WHERE table_name IN ('negocios', 'webs') AND trim(data_type, '"') = 'NULL'""").fetchall()
    for table, column in vacias:
        con.execute(f'ALTER TABLE {table} ALTER "{column}" TYPE {COLUMN_TYPES.get(column, "VARCHAR")}')
    tablas = {t for (t,) in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    for table in {"negocios", "escaneos"} & tablas:
        con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS codigo_ine VARCHAR")
        # Filas de antes del código INE: se enlazan por nombre solo si no hay otro municipio que se llame igual
        con.execute(f"""UPDATE {table} t SET codigo_ine = m.codigo_ine
            FROM (SELECT municipio, any_value(codigo_ine) AS codigo_ine FROM municipios
                  GROUP BY municipio HAVING count(*) = 1) m
            WHERE t.codigo_ine IS NULL AND t.municipio = m.municipio""")
    if {"negocios", "webs"} <= tablas:
        con.execute(SQL_PATH.read_text())


def resolve_municipio(codigo_ine: str | None, nombre: str | None, provincia: str | None) -> dict:
    """Busca el municipio en la tabla del INE por código o por nombre (sin tildes ni mayúsculas)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(DB_PATH) as con:
        load_municipios(con)
        # Los nombres bilingües ("Alicante/Alacant") valen por cualquiera de sus partes
        hits = con.execute("""SELECT codigo_ine, municipio, provincia FROM municipios
            WHERE codigo_ine = $codigo
               OR (list_contains(string_split(strip_accents(lower(municipio)), '/'), strip_accents(lower($nombre)))
                   AND ($provincia IS NULL OR list_contains(string_split(strip_accents(lower(provincia)), '/'),
                                                            strip_accents(lower($provincia)))))
            ORDER BY codigo_ine""", {"codigo": codigo_ine, "nombre": nombre, "provincia": provincia}).fetchall()
    if not hits:
        raise SystemExit(f"No encuentro el municipio {codigo_ine or nombre} en la lista del INE")
    if len(hits) > 1:
        raise SystemExit("Hay varios municipios con ese nombre; usa --codigo-ine:\n"
                         + "\n".join(f"  {c}  {m} ({p})" for c, m, p in hits))
    return dict(zip(("codigo_ine", "municipio", "provincia"), hits[0]))


def save(rows: list[dict], webs: list[dict], mun: dict) -> None:
    con = duckdb.connect(DB_PATH)
    neg_json = RAW_DIR / f"negocios_{mun['codigo_ine']}.json"
    web_json = RAW_DIR / f"webs_{mun['codigo_ine']}.json"
    neg_json.write_text(json.dumps(rows, ensure_ascii=False))
    web_json.write_text(json.dumps(webs, ensure_ascii=False))
    for table, path in (("negocios", neg_json), ("webs", web_json)):
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_json_auto(?) LIMIT 0", [str(path)])
    init_db(con)
    # Re-escanear un municipio sustituye todas sus filas anteriores, también las de negocios que ya no están en OSM
    viejos = "SELECT osm_id FROM negocios WHERE codigo_ine = $codigo UNION SELECT osm_id FROM read_json_auto($path)"
    con.execute(f"DELETE FROM webs WHERE osm_id IN ({viejos})", {"codigo": mun["codigo_ine"], "path": str(neg_json)})
    con.execute(f"DELETE FROM negocios WHERE osm_id IN ({viejos})", {"codigo": mun["codigo_ine"], "path": str(neg_json)})
    for table, path in (("negocios", neg_json), ("webs", web_json)):
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM read_json_auto(?, union_by_name=true)", [str(path)])
    con.execute("INSERT INTO escaneos BY NAME SELECT ? AS municipio, ? AS codigo_ine, now() AS fecha",
                [mun["municipio"], mun["codigo_ine"]])
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codigo-ine", help="código INE de 5 cifras; evita confusiones entre municipios homónimos")
    ap.add_argument("--municipio")
    ap.add_argument("--provincia")
    args = ap.parse_args()
    if not (args.codigo_ine or args.municipio):
        ap.error("indica --codigo-ine o --municipio")

    mun = resolve_municipio(args.codigo_ine, args.municipio, args.provincia)
    # Para Nominatim y para reconocer el municipio en las webs basta con el primer nombre de los bilingües
    nombre, provincia = mun["municipio"].split("/")[0], mun["provincia"].split("/")[0]
    hit = find_municipality(nombre, provincia)
    print(f"Municipio: {mun['codigo_ine']} · {hit['display_name']}")
    rows = to_rows(overpass_businesses(int(hit["osm_id"])), mun["municipio"], mun["codigo_ine"])
    print(f"{len(rows)} negocios en OSM; analizando webs...")
    webs = asyncio.run(analyze_all(rows, nombre))
    print(f"{sum(w['estado'] != 'sin_web' for w in webs)} webs encontradas")
    save(rows, webs, mun)
    print(f"Guardado en {DB_PATH}")


if __name__ == "__main__":
    main()
