# Campos del visor de Analizer

Qué significa cada campo que aparece en la app (`streamlit run src/analizer/app.py`) y en el Excel descargado. Los datos salen de [scan.py](src/analizer/scan.py) (OpenStreetMap + análisis de la web) y los cálculos de [ranking.sql](src/analizer/ranking.sql).

## Filtros de la barra lateral

| Filtro | Qué hace |
|---|---|
| **Municipio** | Municipios escaneados que se muestran. Cada municipio tiene su propio ranking. |
| **Prioridad** | Filtra por `prioridad` (ver abajo). Por defecto oculta los `frio`. |
| **Estado web** | Filtra por `estado_web`: `sin_web`, `aparcada` u `ok`. |
| **Solo con teléfono o email** | Oculta los negocios sin ningún dato de contacto. |
| **Probabilidad mínima** | Oculta los negocios con `probabilidad` inferior al valor elegido (0 a 1). |
| **⬇️ Descargar Excel** | Descarga lo que se ve con los filtros aplicados, más el resumen por municipio, los criterios de puntuación y la fecha de cada escaneo. |

## Métricas

| Métrica | Significado |
|---|---|
| **Negocios filtrados** | Número de filas que pasan los filtros. |
| **Calientes** | Cuántos de ellos tienen prioridad `caliente`. |
| **Leads esperados (Σp)** | Suma de las probabilidades. Es el número de clientes que se espera conseguir si se contacta a todos los filtrados: 10 negocios con p = 0,3 equivalen a unos 3 clientes. |
| **Sin web** | Cuántos no tienen web. |

## Resumen por municipio

| Columna | Significado |
|---|---|
| `negocios` | Negocios encontrados en OSM (se excluyen fuentes, bancos, colegios, ayuntamiento, etc.). |
| `sin_web` | Sin web localizada. |
| `con_web` | Con web, ya sea real (`ok`) o aparcada. |
| `calientes` | Con prioridad `caliente`. |
| `probabilidad_media` | Media de `probabilidad` en el municipio. |
| `leads_esperados` | Suma de `probabilidad`: clientes esperados en el municipio. |
| `valor_esperado_eur` | Facturación esperada: suma de probabilidad × precio orientativo según el ticket (alto 1.500 €, medio 800 €, bajo 400 €). |

## Ranking

| Columna | Significado |
|---|---|
| `posicion` | Puesto dentro de su municipio, de mayor a menor puntuación. |
| `codigo_ine` | Código INE de 5 cifras del municipio. Es lo que distingue a dos municipios que se llaman igual. |
| `municipio` | Municipio del escaneo, con el nombre oficial del INE. |
| `provincia` | Provincia del municipio. |
| `nombre` | Nombre del negocio en OpenStreetMap. |
| `tipo` | Categoría OSM en inglés (`restaurant`, `dentist`, `hairdresser`, `car_repair`…). Determina el `ticket` y si el negocio necesita reservas. |
| `probabilidad` | Estimación de 0 a 1 de que el negocio acepte una web nueva o un rediseño. Se calcula como `1 / (1 + e^-(−1,5 + p_necesidad + p_pago + p_penalizacion + p_contacto))`. Los pesos son una estimación inicial: hay que recalibrarlos con los resultados reales de contacto. |
| `prioridad` | Tramo de la probabilidad: `caliente` si es ≥ 0,75, `templado` si es ≥ 0,5 y `frio` por debajo. |
| `estado_web` | `sin_web`: no tiene web o la registrada no responde. `aparcada`: el dominio existe pero muestra "en construcción", "dominio en venta", la página por defecto del servidor, o menos de 200 caracteres de texto. `ok`: tiene una web real, que se analiza. |
| `web` | URL final tras las redirecciones, o la que figura en OSM. |
| `observaciones` | Propuestas de mejora concretas, ordenadas por impacto y recortadas a unas 60 palabras. Sirven de guion para la llamada. |
| `telefono` | El de OSM o, si no hay, los encontrados en la web. |
| `email` | El de OSM o, si no hay, los encontrados en la web. |
| `direccion` | Calle y número según OSM. |
| `argumentos_venta` | Problemas detectados en su web (o la falta de web) para usar en la conversación. Ver la tabla siguiente. |
| `frenos` | Motivos por los que el lead podría no salir. Ver la tabla siguiente. |

### Solo en el Excel

| Columna | Significado |
|---|---|
| `ticket` | Cuánto suele gastar ese sector en una web: `alto` (clínicas, hoteles, abogados, talleres, reformas…), `medio` (restaurantes, peluquerías, panaderías…, y todo sector no listado) o `bajo` (bares, cafeterías, quioscos…). |
| `origen_web` | `osm` si la web venía en OpenStreetMap. `deducida` si se ha adivinado el dominio a partir del nombre (`nombrenegocio.com/.es`); solo se acepta cuando la página menciona el negocio y el municipio. Vacío si no tiene web. |
| `p_necesidad` | Puntos por lo mal que está (o lo que le falta a) su presencia web. |
| `p_pago` | Puntos por capacidad de pago: ticket del sector, uso de analítica o redes, y si su agencia lleva años sin tocar la web. |
| `p_penalizacion` | Puntos negativos: cadena o entidad pública, web moderna o agencia reciente. |
| `p_contacto` | +0,3 si hay teléfono o email y −0,5 si no hay ninguno. |
| `osm_id` | Identificador en OpenStreetMap (`node/…`, `way/…`). Se puede buscar en openstreetmap.org. |

## Argumentos de venta y frenos

| Texto | Significado | Puntos |
|---|---|---|
| No tiene web | No se encontró web. | +2,0 |
| Dominio aparcado / en construcción | Tiene dominio pero no hay web real. | +2,5 |
| Sin HTTPS | El navegador la marca como "No seguro". | +1,2 |
| Certificado SSL roto o caducado | La web da error de seguridad al abrirla. | +1,0 |
| No adaptada a móvil | No tiene la etiqueta `viewport`, así que en el móvil se ve como la versión de ordenador en pequeño. | +1,2 |
| Tecnología obsoleta | Usa Flash, maquetación con tablas, jQuery anterior a 1.9, WordPress anterior a 5, Joomla 1/2 o Drupal 7. | +0,8 |
| © año | El copyright del pie tiene 5 años o más (+1,0) o entre 2 y 4 (+0,4). Indica que nadie actualiza la web. | +1,0 / +0,4 |
| N años sin cambios (Wayback) | Según archive.org, el contenido no cambia desde hace 4 años o más. | +0,8 |
| Sin reserva/cita online | El sector suele trabajar con reservas (clínicas, restaurantes, hoteles…) y la web no permite reservar. | +0,4 |
| Faltan textos legales RGPD/LSSI | Falta el aviso legal, la política de privacidad o el aviso de cookies. | +0,5 |
| Sin WhatsApp ni formulario | No hay botón de WhatsApp ni formulario de contacto. | +0,3 |
| Hecha con constructor DIY | Hecha con Wix, Jimdo, Site123, Webnode o GoDaddy Builder. | +0,4 |
| *Cadena/franquicia o entidad pública* (freno) | Tiene marca u operador en OSM, o el nombre o dominio corresponde a una cadena (Consum, Mercadona, bancos, gasolineras…) o a un organismo público. La web la gestiona la central. | −2,5 |
| *Stack moderno* (freno) | Web hecha con Next.js, Nuxt, Webflow, Shopify, Squarespace o Gatsby: probablemente ya está bien atendida. | −1,5 |
| *Agencia reciente* (freno) | El pie dice "diseñado por…" con un año de hace 2 años o menos. | −2,0 |
| *Sin datos de contacto* (freno) | No hay teléfono ni email. | −0,5 |

Otras señales que suben la puntuación aunque no salgan como argumento: ticket del sector (alto +1,0, medio +0,3, bajo −0,5), analítica instalada (+0,2), enlaces a redes sociales (+0,2) y crédito a una agencia de hace más de 4 años (+0,3).
