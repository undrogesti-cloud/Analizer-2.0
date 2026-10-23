-- Ranking probabilístico de negocios propensos a contratar una web nueva o un rediseño.
-- Principio: puntuar el desfase entre la vitalidad del negocio y el abandono de su web.
--   P(acepta) ≈ sigmoide(necesidad + capacidad_pago + contactabilidad + urgencia)
-- Los pesos son de arranque en frío: recalibrar con resultados reales de contacto.

-- Ticket/propensión por sector (tipo OSM). Lo no listado cuenta como 'medio'.
CREATE OR REPLACE TABLE sectores AS
SELECT * FROM (VALUES
    ('dentist', 'alto', true), ('doctors', 'alto', true), ('clinic', 'alto', true),
    ('physiotherapist', 'alto', true), ('veterinary', 'alto', true), ('beauty', 'alto', true),
    ('hairdresser', 'medio', true), ('estate_agent', 'alto', false), ('lawyer', 'alto', false),
    ('accountant', 'alto', false), ('hotel', 'alto', true), ('guest_house', 'alto', true),
    ('hostel', 'alto', true), ('apartment', 'alto', true), ('camp_site', 'alto', true),
    ('restaurant', 'medio', true), ('car_repair', 'alto', true), ('driving_school', 'alto', true),
    ('carpenter', 'alto', false), ('builder', 'alto', false), ('electrician', 'alto', false),
    ('plumber', 'alto', false), ('fitness_centre', 'medio', true), ('sports_centre', 'medio', true),
    ('optician', 'medio', true), ('pharmacy', 'medio', false), ('bakery', 'medio', false),
    ('butcher', 'medio', false), ('agricultural_cooperative', 'medio', false),
    ('appliance', 'medio', false), ('pub', 'bajo', false), ('bar', 'bajo', false),
    ('cafe', 'bajo', false), ('fast_food', 'bajo', true), ('lottery', 'bajo', false),
    ('convenience', 'bajo', false), ('kiosk', 'bajo', false)
) AS t(tipo, ticket, necesita_reserva);

CREATE OR REPLACE VIEW ranking AS
WITH base AS (
    SELECT
        n.*,
        w.* EXCLUDE (osm_id),
        coalesce(s.ticket, 'medio') AS ticket,
        coalesce(s.necesita_reserva, false) AS necesita_reserva,
        year(current_date) AS anio
    FROM negocios n
    LEFT JOIN webs w USING (osm_id)
    LEFT JOIN sectores s USING (tipo)
),
senales AS (
    SELECT
        *,
        estado = 'sin_web' AS sin_web,
        estado = 'aparcada' AS aparcada,
        estado = 'ok' AND (
            flash OR tablas_layout OR jquery_version < 1.9 OR wp_version < 5
            OR regexp_matches(coalesce(generator, ''), 'Joomla! (1|2)\.|Drupal 7', 'i')
        ) AS tecnologia_obsoleta,
        anio - anio_copyright AS antiguedad_copyright,
        anio - try_cast(left(wayback_ultimo_cambio, 4) AS INTEGER) AS anios_sin_cambios,
        anio_agencia >= anio - 2 AS agencia_reciente,
        agencia IS NOT NULL AND coalesce(anio_agencia, 0) < anio - 4 AS agencia_antigua,
        marca IS NOT NULL
            OR regexp_matches(nombre, 'consum|charter|mercadona|dia\b|tien21|loter[ií]as|repsol|cepsa|shell|bp\b|caixa|santander|bbva|sabadell', 'i')
            OR regexp_matches(nombre, 'consultori|centro de salud|centre de salut|ajuntament|ayuntamiento|municipal', 'i')
            OR coalesce(dominio, '') ~ '.*(consum|gva|edu\.gva|parquesnaturales)\..*' AS cadena,
        coalesce(telefono_osm, telefonos, email_osm, emails) IS NOT NULL AS contactable
    FROM base
),
puntos AS (
    SELECT
        *,
        -- Necesidad
          CASE WHEN sin_web THEN 2.0 ELSE 0 END
        + CASE WHEN aparcada THEN 2.5 ELSE 0 END
        + CASE WHEN estado = 'ok' AND NOT https THEN 1.2 ELSE 0 END
        + CASE WHEN error_ssl THEN 1.0 ELSE 0 END
        + CASE WHEN estado = 'ok' AND NOT viewport THEN 1.2 ELSE 0 END
        + CASE WHEN tecnologia_obsoleta THEN 0.8 ELSE 0 END
        + CASE WHEN antiguedad_copyright >= 5 THEN 1.0 WHEN antiguedad_copyright >= 2 THEN 0.4 ELSE 0 END
        + CASE WHEN anios_sin_cambios >= 4 THEN 0.8 ELSE 0 END
        + CASE WHEN estado = 'ok' AND necesita_reserva AND NOT reserva_online THEN 0.4 ELSE 0 END
        + CASE WHEN estado = 'ok' AND NOT (aviso_legal AND privacidad AND cookies) THEN 0.5 ELSE 0 END
        + CASE WHEN estado = 'ok' AND NOT (whatsapp OR formulario) THEN 0.3 ELSE 0 END
        + CASE WHEN constructor_diy THEN 0.4 ELSE 0 END
            AS p_necesidad,
        -- Capacidad de pago
          CASE ticket WHEN 'alto' THEN 1.0 WHEN 'medio' THEN 0.3 ELSE -0.5 END
        + CASE WHEN analitica THEN 0.2 ELSE 0 END
        + CASE WHEN redes THEN 0.2 ELSE 0 END
        + CASE WHEN agencia_antigua THEN 0.3 ELSE 0 END
            AS p_pago,
        -- Penalizaciones
          CASE WHEN cadena THEN -2.5 ELSE 0 END
        + CASE WHEN stack_moderno THEN -1.5 ELSE 0 END
        + CASE WHEN agencia_reciente THEN -2.0 ELSE 0 END
            AS p_penalizacion,
        -- Contactabilidad
        CASE WHEN contactable THEN 0.3 ELSE -0.5 END AS p_contacto
    FROM senales
),
-- Propuestas de mejora para la web, de mayor a menor impacto
propuestas AS (
    SELECT
        *,
        list_filter([
            CASE WHEN sin_web AND web_osm IS NOT NULL THEN 'La web registrada no responde: recuperarla o rehacerla.' END,
            CASE WHEN sin_web THEN 'Crear web profesional adaptada a móvil con servicios, teléfono, WhatsApp y mapa'
                || CASE WHEN necesita_reserva THEN ', y reserva online.' ELSE '.' END END,
            CASE WHEN aparcada THEN 'Sustituir la página aparcada por una web real con servicios, contacto y mapa.' END,
            CASE WHEN error_ssl THEN 'Renovar el certificado SSL caducado.'
                 WHEN estado = 'ok' AND NOT https THEN 'Activar HTTPS para quitar el aviso "No seguro".' END,
            CASE WHEN estado = 'ok' AND NOT viewport THEN 'Rediseño responsive: no se ve bien en móvil.' END,
            CASE WHEN tecnologia_obsoleta THEN 'Migrar a un CMS actual: la tecnología usada está obsoleta y es vulnerable.' END,
            CASE WHEN constructor_diy THEN 'Pasar del constructor DIY a una web propia más profesional.' END,
            -- Contenido clave según el sector, para webs nuevas o rediseños
            CASE WHEN sin_web OR aparcada OR (estado = 'ok' AND NOT viewport) THEN
                CASE
                    WHEN tipo IN ('restaurant', 'bar', 'cafe', 'pub', 'fast_food')
                        THEN 'Incluir carta con fotos, horarios y reseñas de Google.'
                    WHEN tipo IN ('dentist', 'doctors', 'clinic', 'physiotherapist', 'veterinary', 'beauty', 'hairdresser', 'optician')
                        THEN 'Mostrar tratamientos, equipo, precios orientativos y reseñas de clientes.'
                    WHEN tipo IN ('carpenter', 'builder', 'electrician', 'plumber', 'car_repair', 'appliance')
                        THEN 'Incluir galería de trabajos realizados y formulario de presupuesto.'
                    WHEN tipo IN ('hotel', 'guest_house', 'hostel', 'apartment', 'camp_site')
                        THEN 'Galería de fotos y reserva directa sin comisiones de Booking.'
                    WHEN tipo IN ('bakery', 'butcher', 'convenience', 'agricultural_cooperative', 'pharmacy')
                        THEN 'Mostrar productos, horarios y pedidos por WhatsApp.'
                    WHEN tipo IN ('estate_agent', 'lawyer', 'accountant')
                        THEN 'Mostrar servicios o inmuebles destacados y formulario de consulta.'
                END
            END,
            CASE WHEN antiguedad_copyright >= 2 OR anios_sin_cambios >= 4 THEN 'Renovar contenidos, fotos y textos desactualizados.' END,
            CASE WHEN estado = 'ok' AND necesita_reserva AND NOT reserva_online THEN 'Añadir reserva o cita online.' END,
            CASE WHEN estado = 'ok' AND NOT (whatsapp OR formulario) THEN 'Añadir botón de WhatsApp y formulario de contacto.' END,
            CASE WHEN estado = 'ok' AND NOT (aviso_legal AND privacidad AND cookies) THEN 'Añadir aviso legal, privacidad y cookies (RGPD/LSSI).' END,
            CASE WHEN estado = 'ok' AND NOT mapa THEN 'Insertar mapa de ubicación.' END,
            CASE WHEN estado = 'ok' AND NOT redes THEN 'Enlazar redes sociales.' END,
            CASE WHEN estado = 'ok' AND NOT analitica THEN 'Instalar analítica para medir visitas.' END
        ], lambda x: x IS NOT NULL) AS lista_propuestas
    FROM puntos
),
-- Recorta a frases completas sin pasar de 60 palabras
observaciones AS (
    SELECT
        *,
        list_transform(lista_propuestas, lambda x: len(string_split(x, ' '))) AS palabras
    FROM propuestas
)
SELECT
    row_number() OVER (PARTITION BY municipio ORDER BY puntos_total DESC, nombre) AS posicion,
    municipio,
    nombre,
    tipo,
    ticket,
    round(probabilidad, 3) AS probabilidad,
    CASE WHEN probabilidad >= 0.75 THEN 'caliente' WHEN probabilidad >= 0.5 THEN 'templado' ELSE 'frio' END AS prioridad,
    estado AS estado_web,
    coalesce(url_final, web_osm) AS web,
    CASE WHEN cadena THEN 'Cadena o entidad pública: la web depende de la central, lead poco probable.'
    ELSE coalesce(nullif(array_to_string(list_filter(lista_propuestas,
        lambda x, i: list_sum(palabras[1:i]) <= 60), ' '), ''),
        CASE WHEN estado = 'ok' THEN 'Web en buen estado: ofrecer mantenimiento y SEO local.' END)
    END AS observaciones,
    origen_web,
    coalesce(telefono_osm, telefonos) AS telefono,
    coalesce(email_osm, emails) AS email,
    direccion,
    concat_ws(' · ',
        CASE WHEN sin_web THEN 'No tiene web' END,
        CASE WHEN aparcada THEN 'Dominio aparcado / en construcción' END,
        CASE WHEN estado = 'ok' AND NOT https THEN 'Sin HTTPS: el navegador la marca "No seguro"' END,
        CASE WHEN error_ssl THEN 'Certificado SSL roto o caducado' END,
        CASE WHEN estado = 'ok' AND NOT viewport THEN 'No adaptada a móvil' END,
        CASE WHEN tecnologia_obsoleta THEN 'Tecnología obsoleta (' || coalesce(generator, 'jQuery/Flash/tablas') || ')' END,
        CASE WHEN antiguedad_copyright >= 2 THEN '© ' || anio_copyright END,
        CASE WHEN anios_sin_cambios >= 4 THEN anios_sin_cambios || ' años sin cambios (Wayback)' END,
        CASE WHEN estado = 'ok' AND necesita_reserva AND NOT reserva_online THEN 'Sin reserva/cita online' END,
        CASE WHEN estado = 'ok' AND NOT (aviso_legal AND privacidad AND cookies) THEN 'Faltan textos legales RGPD/LSSI' END,
        CASE WHEN estado = 'ok' AND NOT (whatsapp OR formulario) THEN 'Sin WhatsApp ni formulario' END,
        CASE WHEN constructor_diy THEN 'Hecha con constructor DIY' END
    ) AS argumentos_venta,
    concat_ws(' · ',
        CASE WHEN cadena THEN 'Cadena/franquicia o entidad pública' END,
        CASE WHEN stack_moderno THEN 'Stack moderno' END,
        CASE WHEN agencia_reciente THEN 'Agencia reciente: ' || agencia END,
        CASE WHEN NOT contactable THEN 'Sin datos de contacto' END
    ) AS frenos,
    round(p_necesidad, 2) AS p_necesidad,
    round(p_pago, 2) AS p_pago,
    round(p_penalizacion, 2) AS p_penalizacion,
    round(p_contacto, 2) AS p_contacto,
    lat,
    lon,
    osm_id
FROM (
    SELECT *,
        -1.5 + p_necesidad + p_pago + p_penalizacion + p_contacto AS puntos_total,
        1 / (1 + exp(-(-1.5 + p_necesidad + p_pago + p_penalizacion + p_contacto))) AS probabilidad
    FROM observaciones
)
ORDER BY municipio, posicion;

CREATE OR REPLACE VIEW ranking_municipio AS
SELECT
    municipio,
    count(*) AS negocios,
    count(*) FILTER (estado_web = 'sin_web') AS sin_web,
    count(*) FILTER (estado_web IN ('ok', 'aparcada')) AS con_web,
    count(*) FILTER (prioridad = 'caliente') AS calientes,
    round(avg(probabilidad), 3) AS probabilidad_media,
    round(sum(probabilidad), 1) AS leads_esperados,
    round(sum(probabilidad * CASE ticket WHEN 'alto' THEN 1500 WHEN 'medio' THEN 800 ELSE 400 END)) AS valor_esperado_eur
FROM ranking
GROUP BY municipio
ORDER BY leads_esperados DESC;
