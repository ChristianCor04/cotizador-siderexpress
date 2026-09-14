-- ============================================================================
-- 15 — Guardar una cotización completa en una sola operación
-- Requiere: 01 a 14
--
-- ¿Por qué una función y no varios inserts desde la app?
-- Porque una cotización son 4 tablas (cabecera, detalle, ferreterías
-- evaluadas y promociones). Si la app las guardara una por una y fallara
-- a la mitad, quedaría una cotización sin productos.
-- Dentro de esta función es todo o nada.
-- ============================================================================

create or replace function public.registrar_cotizacion(p jsonb)
returns bigint
language plpgsql
security invoker          -- respeta el RLS del asesor que la llama
as $$
declare
  v_id_negociacion bigint := (p->'cabecera'->>'id_negociacion')::bigint;
  v_version        smallint;
  v_id_cotizacion  bigint;
  v_item           jsonb;
begin
  if v_id_negociacion is null then
    raise exception 'Falta id_negociacion.';
  end if;
  if jsonb_array_length(coalesce(p->'lineas', '[]'::jsonb)) = 0 then
    raise exception 'La cotización no tiene productos.';
  end if;

  -- La versión se calcula aquí, no en la app: si dos asesores guardaran
  -- a la vez, la base garantiza que no se repita.
  select coalesce(max(version), 0) + 1 into v_version
  from fact_cotizaciones where id_negociacion = v_id_negociacion;

  insert into fact_cotizaciones (
    id_negociacion, version, id_usuario, ticket,
    latitud, longitud, id_distrito,
    id_regla, monto_referencial, distancia_km,
    id_sede, id_tipo_pago, tipo_cambio, fecha_vencimiento
  ) values (
    v_id_negociacion,
    v_version,
    auth.uid(),
    p->'cabecera'->>'ticket',
    (p->'cabecera'->>'latitud')::double precision,
    (p->'cabecera'->>'longitud')::double precision,
    (p->'cabecera'->>'id_distrito')::bigint,
    (p->'cabecera'->>'id_regla')::bigint,
    (p->'cabecera'->>'monto_referencial')::numeric,
    (p->'cabecera'->>'distancia_km')::numeric,
    (p->'cabecera'->>'id_sede')::bigint,
    (p->'cabecera'->>'id_tipo_pago')::bigint,
    (p->'cabecera'->>'tipo_cambio')::numeric,
    (p->'cabecera'->>'fecha_vencimiento')::timestamptz
  )
  returning id_cotizacion into v_id_cotizacion;

  -- Detalle
  for v_item in select * from jsonb_array_elements(p->'lineas') loop
    insert into fact_cotizaciones_detalle (
      id_cotizacion, id_sku, cantidad, precio_unitario,
      precio_modificado, motivo_modificacion, autorizado_por, id_precio
    ) values (
      v_id_cotizacion,
      (v_item->>'id_sku')::bigint,
      (v_item->>'cantidad')::numeric,
      (v_item->>'precio_unitario')::numeric,
      (v_item->>'precio_modificado')::numeric,
      v_item->>'motivo_modificacion',
      v_item->>'autorizado_por',
      (v_item->>'id_precio')::bigint
    );
  end loop;

  -- Ferreterías que compitieron (para análisis de competencia)
  for v_item in select * from jsonb_array_elements(coalesce(p->'ferreterias', '[]'::jsonb)) loop
    insert into fact_cotizaciones_ferreterias (
      id_cotizacion, id_sede, distancia_km, canasta_completa,
      monto_canasta, ranking, elegida
    ) values (
      v_id_cotizacion,
      (v_item->>'id_sede')::bigint,
      (v_item->>'distancia_km')::numeric,
      (v_item->>'canasta_completa')::boolean,
      (v_item->>'monto_canasta')::numeric,
      (v_item->>'ranking')::smallint,
      coalesce((v_item->>'elegida')::boolean, false)
    )
    on conflict (id_cotizacion, id_sede) do nothing;
  end loop;

  -- Promociones: se guardan también las que el asesor decidió no aplicar
  for v_item in select * from jsonb_array_elements(coalesce(p->'promociones', '[]'::jsonb)) loop
    insert into fact_cotizaciones_promociones (
      id_cotizacion, id_promocion, modalidad, tipo, valor,
      monto_beneficio, financiado_por, aplicada, motivo_no_aplicada, decidida_por
    ) values (
      v_id_cotizacion,
      (v_item->>'id_promocion')::bigint,
      v_item->>'modalidad',
      v_item->>'tipo',
      (v_item->>'valor')::numeric,
      (v_item->>'monto_beneficio')::numeric,
      v_item->>'financiado_por',
      coalesce((v_item->>'aplicada')::boolean, true),
      v_item->>'motivo_no_aplicada',
      auth.uid()
    )
    on conflict (id_cotizacion, id_promocion) do nothing;
  end loop;

  return v_id_cotizacion;
end $$;

comment on function public.registrar_cotizacion is
  'Guarda cabecera, detalle, ferreterías evaluadas y promociones en una sola '
  'transacción. Devuelve el id de la cotización creada.';


-- ================= GUARDAR EL PDF EN LA COTIZACIÓN ==========================

create or replace function public.guardar_url_pdf(
  p_id_cotizacion bigint,
  p_url text
)
returns void
language sql
security invoker
as $$
  update fact_cotizaciones set url_pdf = p_url where id_cotizacion = p_id_cotizacion
$$;


grant execute on function registrar_cotizacion(jsonb) to authenticated;
grant execute on function guardar_url_pdf(bigint, text) to authenticated;
