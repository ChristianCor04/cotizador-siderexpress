-- ============================================================================
-- 25 — La venta respeta los bonos que eligió el asesor
-- Requiere: 01 a 22 y 24
--
-- El asesor puede elegir, por ejemplo, entre un descuento directo en la
-- cotización o un bono que se entrega después de comprar. Esa decisión queda
-- guardada en la cotización.
--
-- Antes registrar_venta volvía a calcular TODOS los bonos vigentes, así que
-- ignoraba la elección: el cliente terminaba recibiendo un bono que el asesor
-- había descartado. Ahora se respeta lo decidido y solo se recalcula el monto
-- sobre lo realmente pagado.
-- ============================================================================

create or replace function public.registrar_venta(p jsonb)
returns bigint
language plpgsql
security invoker
as $$
declare
  v_id_cotizacion  bigint := (p->>'id_cotizacion')::bigint;
  v_id_negociacion bigint;
  v_id_sede        bigint;
  v_id_venta       bigint;
  v_item           jsonb;
  v_lineas         jsonb := coalesce(p->'lineas', '[]'::jsonb);
  v_hubo_decision  boolean;
begin
  select id_negociacion, id_sede
    into v_id_negociacion, v_id_sede
  from fact_cotizaciones
  where id_cotizacion = v_id_cotizacion;

  if v_id_negociacion is null then
    raise exception 'La cotización % no existe o no tienes acceso.', v_id_cotizacion;
  end if;

  update fact_cotizaciones
     set estado = 'reemplazada'
   where id_negociacion = v_id_negociacion
     and id_cotizacion <> v_id_cotizacion
     and estado in ('enviada', 'aceptada');

  update fact_cotizaciones
     set estado = 'aceptada'
   where id_cotizacion = v_id_cotizacion;

  insert into fact_ventas (
    id_negociacion, id_cotizacion, id_sede, id_usuario, ticket,
    fecha_venta, id_tipo_pago, tipo_cambio,
    url_comprobante_pago, tipo_comprobante, numero_comprobante
  ) values (
    v_id_negociacion,
    v_id_cotizacion,
    coalesce((p->>'id_sede')::bigint, v_id_sede),
    auth.uid(),
    p->>'ticket',
    coalesce((p->>'fecha_venta')::timestamptz, now()),
    (p->>'id_tipo_pago')::bigint,
    (p->>'tipo_cambio')::numeric,
    p->>'url_comprobante_pago',
    p->>'tipo_comprobante',
    p->>'numero_comprobante'
  )
  returning id_venta into v_id_venta;

  -- Detalle
  if jsonb_array_length(v_lineas) = 0 then
    insert into fact_ventas_detalle (
      id_venta, id_sku, cantidad, precio_unitario,
      descuento_unitario, id_promocion, id_cotizacion_detalle
    )
    select v_id_venta, d.id_sku, d.cantidad,
           coalesce(d.precio_modificado, d.precio_unitario),
           d.descuento_unitario, d.id_promocion, d.id_cotizacion_detalle
    from fact_cotizaciones_detalle d
    where d.id_cotizacion = v_id_cotizacion;
  else
    for v_item in select * from jsonb_array_elements(v_lineas) loop
      insert into fact_ventas_detalle (
        id_venta, id_sku, cantidad, precio_unitario, id_cotizacion_detalle
      ) values (
        v_id_venta,
        (v_item->>'id_sku')::bigint,
        (v_item->>'cantidad')::numeric,
        (v_item->>'precio_unitario')::numeric,
        (v_item->>'id_cotizacion_detalle')::bigint
      );
    end loop;
  end if;

  -- Descuentos que sí se aplicaron en la cotización
  insert into fact_ventas_promociones (
    id_venta, id_promocion, modalidad, tipo, valor,
    monto_beneficio, financiado_por, aplicada, decidida_por
  )
  select v_id_venta, cp.id_promocion, cp.modalidad, cp.tipo, cp.valor,
         cp.monto_beneficio, cp.financiado_por, true, auth.uid()
  from fact_cotizaciones_promociones cp
  join m_promociones pr using (id_promocion)
  where cp.id_cotizacion = v_id_cotizacion
    and cp.aplicada
    and pr.momento = 'cotizacion'
  on conflict (id_venta, id_promocion) do nothing;

  -- ¿El asesor decidió algo sobre los bonos post venta?
  select exists (
    select 1
    from fact_cotizaciones_promociones cp
    join m_promociones pr using (id_promocion)
    where cp.id_cotizacion = v_id_cotizacion and pr.momento = 'venta'
  ) into v_hubo_decision;

  if v_hubo_decision then
    -- Se respeta la elección: solo los marcados, con el monto recalculado
    -- sobre lo que el cliente realmente pagó.
    insert into fact_ventas_promociones (
      id_venta, id_promocion, modalidad, tipo, valor,
      monto_beneficio, financiado_por, aplicada, decidida_por
    )
    select v_id_venta, cp.id_promocion, cp.modalidad, pr.tipo, pr.valor,
           calcular_beneficio_promocion(cp.id_promocion, v.monto_total_sol),
           pr.financiado_por, true, auth.uid()
    from fact_cotizaciones_promociones cp
    join m_promociones pr using (id_promocion)
    join fact_ventas v on v.id_venta = v_id_venta
    where cp.id_cotizacion = v_id_cotizacion
      and cp.aplicada
      and pr.momento = 'venta'
      and calcular_beneficio_promocion(cp.id_promocion, v.monto_total_sol) > 0
    on conflict (id_venta, id_promocion) do nothing;
  else
    -- Cotización antigua, sin decisión registrada: se calculan los vigentes
    insert into fact_ventas_promociones (
      id_venta, id_promocion, modalidad, tipo, valor,
      monto_beneficio, financiado_por, aplicada, decidida_por
    )
    select v_id_venta, b.id_promocion, b.modalidad, pr.tipo, pr.valor,
           b.beneficio, pr.financiado_por, true, auth.uid()
    from fact_ventas v
    join fact_negociaciones n using (id_negociacion)
    cross join lateral beneficio_promocional(
          v.id_sede, v.monto_total_sol, n.id_cliente, 'venta') b
    join m_promociones pr on pr.id_promocion = b.id_promocion
    where v.id_venta = v_id_venta
    on conflict (id_venta, id_promocion) do nothing;
  end if;

  return v_id_venta;
end $$;

comment on function public.registrar_venta is
  'Crea la venta desde una cotización. Respeta los bonos que el asesor eligió '
  'y recalcula su monto sobre lo realmente pagado.';
