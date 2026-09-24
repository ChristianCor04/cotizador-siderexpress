-- ============================================================================
-- 21 — Flete en la cotización
-- Requiere: 01 a 20
--
-- Hay entregas que obligan a cobrar flete. Se guarda aparte del monto de los
-- productos para poder analizarlo después: cuánto se cobra de flete, en qué
-- zonas y si encarece tanto la canasta como para perder la venta.
-- ============================================================================

alter table fact_cotizaciones
  add column if not exists monto_flete numeric(14,2) not null default 0;
alter table fact_cotizaciones
  add column if not exists motivo_flete text;

alter table fact_ventas
  add column if not exists monto_flete numeric(14,2) not null default 0;
alter table fact_ventas
  add column if not exists motivo_flete text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'chk_cot_flete') then
    alter table fact_cotizaciones add constraint chk_cot_flete
      check (monto_flete >= 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'chk_ven_flete') then
    alter table fact_ventas add constraint chk_ven_flete
      check (monto_flete >= 0);
  end if;
end $$;

comment on column fact_cotizaciones.monto_flete is
  'Costo de entrega. Se suma al total; no forma parte del monto de productos.';
comment on column fact_cotizaciones.motivo_flete is
  'Por qué se cobra: distancia, volumen, entrega en obra…';


-- ==================== TOTALES CON FLETE =====================================
-- El total que paga el cliente = productos − descuento + flete.
-- El monto de productos (monto_bruto_sol) NO incluye el flete, para que los
-- análisis de canasta no se distorsionen.

create or replace function public.recalcular_totales_cotizacion(p_id_cotizacion bigint)
returns void
language plpgsql
as $$
declare
  v_bruto     numeric := 0;
  v_ton       numeric := 0;
  v_ton_total numeric := 0;
  v_desc      numeric := 0;
  v_dev       numeric := 0;
  v_flete     numeric := 0;
begin
  select coalesce(sum(d.subtotal), 0),
         coalesce(sum(d.cantidad * s.peso_kg)
                  filter (where cat.computa_toneladas and s.peso_kg is not null), 0) / 1000,
         coalesce(sum(d.cantidad * s.peso_kg)
                  filter (where s.peso_kg is not null), 0) / 1000
    into v_bruto, v_ton, v_ton_total
  from fact_cotizaciones_detalle d
  join m_skus       s   on s.id_sku        = d.id_sku
  join m_productos  p   on p.id_producto   = s.id_producto
  join m_categorias cat on cat.id_categoria = p.id_categoria
  where d.id_cotizacion = p_id_cotizacion;

  select coalesce(sum(monto_beneficio) filter (where aplicada and modalidad = 'descuento'), 0),
         coalesce(sum(monto_beneficio) filter (where aplicada and modalidad = 'devolucion'), 0)
    into v_desc, v_dev
  from fact_cotizaciones_promociones
  where id_cotizacion = p_id_cotizacion;

  select coalesce(monto_flete, 0) into v_flete
  from fact_cotizaciones where id_cotizacion = p_id_cotizacion;

  v_desc := least(v_desc, v_bruto);

  update fact_cotizaciones
     set monto_bruto_sol  = round(v_bruto, 2),
         monto_descuento  = round(v_desc, 2),
         monto_total_sol  = round(v_bruto - v_desc + v_flete, 2),
         monto_devolucion = round(v_dev, 2),
         toneladas        = round(v_ton, 3),
         toneladas_total  = round(v_ton_total, 3),
         monto_total_dol  = case
                              when tipo_cambio is not null and tipo_cambio > 0
                              then round((v_bruto - v_desc + v_flete) / tipo_cambio, 2)
                            end
   where id_cotizacion = p_id_cotizacion;
end $$;


create or replace function public.recalcular_totales_venta(p_id_venta bigint)
returns void
language plpgsql
as $$
declare
  v_bruto     numeric := 0;
  v_ton       numeric := 0;
  v_ton_total numeric := 0;
  v_desc      numeric := 0;
  v_dev       numeric := 0;
  v_flete     numeric := 0;
begin
  select coalesce(sum(d.subtotal), 0),
         coalesce(sum(d.cantidad * s.peso_kg)
                  filter (where cat.computa_toneladas and s.peso_kg is not null), 0) / 1000,
         coalesce(sum(d.cantidad * s.peso_kg)
                  filter (where s.peso_kg is not null), 0) / 1000
    into v_bruto, v_ton, v_ton_total
  from fact_ventas_detalle d
  join m_skus       s   on s.id_sku        = d.id_sku
  join m_productos  p   on p.id_producto   = s.id_producto
  join m_categorias cat on cat.id_categoria = p.id_categoria
  where d.id_venta = p_id_venta;

  select coalesce(sum(monto_beneficio) filter (where aplicada and modalidad = 'descuento'), 0),
         coalesce(sum(monto_beneficio) filter (where aplicada and modalidad = 'devolucion'), 0)
    into v_desc, v_dev
  from fact_ventas_promociones
  where id_venta = p_id_venta;

  select coalesce(monto_flete, 0) into v_flete
  from fact_ventas where id_venta = p_id_venta;

  v_desc := least(v_desc, v_bruto);

  update fact_ventas
     set monto_bruto_sol  = round(v_bruto, 2),
         monto_descuento  = round(v_desc, 2),
         monto_total_sol  = round(v_bruto - v_desc + v_flete, 2),
         monto_devolucion = round(v_dev, 2),
         toneladas        = round(v_ton, 3),
         toneladas_total  = round(v_ton_total, 3),
         monto_total_dol  = case
                              when tipo_cambio is not null and tipo_cambio > 0
                              then round((v_bruto - v_desc + v_flete) / tipo_cambio, 2)
                            end
   where id_venta = p_id_venta;
end $$;


-- Si se edita el flete, hay que recalcular el total
create or replace function public.trg_flete_cotizacion()
returns trigger
language plpgsql
as $$
begin
  if new.monto_flete is distinct from old.monto_flete then
    perform recalcular_totales_cotizacion(new.id_cotizacion);
  end if;
  return null;
end $$;

drop trigger if exists trg_cot_flete on fact_cotizaciones;
create trigger trg_cot_flete
  after update of monto_flete on fact_cotizaciones
  for each row execute function trg_flete_cotizacion();


-- ==================== GUARDAR EL FLETE AL COTIZAR ===========================

create or replace function public.registrar_cotizacion(p jsonb)
returns bigint
language plpgsql
security invoker
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

  select coalesce(max(version), 0) + 1 into v_version
  from fact_cotizaciones where id_negociacion = v_id_negociacion;

  insert into fact_cotizaciones (
    id_negociacion, version, id_usuario, ticket,
    latitud, longitud, id_distrito,
    id_regla, monto_referencial, distancia_km,
    id_sede, id_tipo_pago, tipo_cambio, fecha_vencimiento,
    monto_flete, motivo_flete
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
    (p->'cabecera'->>'fecha_vencimiento')::timestamptz,
    coalesce((p->'cabecera'->>'monto_flete')::numeric, 0),
    p->'cabecera'->>'motivo_flete'
  )
  returning id_cotizacion into v_id_cotizacion;

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

  -- El flete se guardó antes que el detalle, así que el total todavía no lo
  -- incluye: se fuerza el recálculo al final.
  perform recalcular_totales_cotizacion(v_id_cotizacion);

  return v_id_cotizacion;
end $$;


-- La venta hereda el flete de la cotización que le dio origen
create or replace function public.copiar_flete_a_venta()
returns trigger
language plpgsql
as $$
begin
  if coalesce(new.monto_flete, 0) = 0 then
    select coalesce(monto_flete, 0), motivo_flete
      into new.monto_flete, new.motivo_flete
    from fact_cotizaciones where id_cotizacion = new.id_cotizacion;
  end if;
  return new;
end $$;

drop trigger if exists trg_venta_flete on fact_ventas;
create trigger trg_venta_flete
  before insert on fact_ventas
  for each row execute function copiar_flete_a_venta();


-- ==================== EL FLETE EN LOS REPORTES ==============================

create or replace view v_flete_resumen as
select
  date_trunc('month', c.fecha)::date as mes,
  z.nombre                           as zona,
  d.nombre                           as distrito,
  count(*) filter (where c.monto_flete > 0)  as cotizaciones_con_flete,
  count(*)                                   as cotizaciones,
  round(avg(c.monto_flete) filter (where c.monto_flete > 0), 2) as flete_promedio,
  sum(c.monto_flete)                         as flete_total,
  round(100.0 * sum(c.monto_flete) / nullif(sum(c.monto_bruto_sol), 0), 1)
                                             as flete_sobre_productos_pct
from fact_cotizaciones c
join fact_negociaciones n using (id_negociacion)
left join m_zonas z     on z.id_zona     = n.id_zona
left join m_distritos d on d.id_distrito = c.id_distrito
group by 1, 2, 3;

comment on view v_flete_resumen is
  'Cuánto flete se cobra por zona y cuánto pesa sobre el monto de productos.';

alter view v_flete_resumen set (security_invoker = true);
grant select on v_flete_resumen to authenticated;
