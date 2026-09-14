-- ============================================================================
-- 07 — Triggers y funciones de negocio
-- Requiere: 01 a 06
--
-- Aquí vive la lógica que debe cumplirse SIEMPRE, venga de la app,
-- de un script o del SQL Editor.
-- ============================================================================

-- ================= AJUSTE: QUÉ CATEGORÍAS SUMAN TONELADAS ===================
-- El archivo 03 ya está aplicado, así que no se edita: se agrega la columna aquí.
-- Marca en true solo las categorías cuyo peso te interesa medir.

alter table m_categorias
  add column if not exists computa_toneladas boolean not null default false;

comment on column m_categorias.computa_toneladas is
  'true si los productos de esta categoría suman al indicador de toneladas. '
  'Normalmente solo el acero: fierro, alambre y clavos.';

update m_categorias
set computa_toneladas = true
where nombre in ('FIERRO', 'ALAMBRE', 'CLAVOS', 'ACERO');


-- Dos medidas distintas de peso, porque responden preguntas distintas:
--   toneladas       -> solo las categorías marcadas arriba. Es el KPI del negocio.
--   toneladas_total -> todo lo que tenga peso. Sirve para flete y logística.
alter table fact_cotizaciones
  add column if not exists toneladas_total numeric(12,3) not null default 0;

alter table fact_ventas
  add column if not exists toneladas_total numeric(12,3) not null default 0;

comment on column fact_cotizaciones.toneladas is
  'Toneladas de las categorías con computa_toneladas = true (acero). Indicador del negocio.';
comment on column fact_cotizaciones.toneladas_total is
  'Peso total de la cotización, incluyendo cemento y ladrillos. Para logística.';
comment on column fact_ventas.toneladas is
  'Toneladas de acero vendidas. Indicador del negocio.';
comment on column fact_ventas.toneladas_total is
  'Peso total despachado. Para logística.';


-- ==================== VENCIMIENTO POR DEFECTO ===============================
-- Si el asesor no define una fecha, se toma de m_parametros (hoy: 1 día).

create or replace function public.set_vencimiento_cotizacion()
returns trigger
language plpgsql
as $$
begin
  if new.fecha_vencimiento is null then
    new.fecha_vencimiento :=
      new.fecha + (coalesce(parametro_num('dias_vigencia_cotizacion'), 1) || ' days')::interval;
  end if;
  return new;
end $$;

drop trigger if exists trg_cot_vencimiento on fact_cotizaciones;
create trigger trg_cot_vencimiento
  before insert on fact_cotizaciones
  for each row execute function set_vencimiento_cotizacion();


-- ======================= TOTALES DE LA COTIZACIÓN ===========================
-- Recalcula montos y toneladas desde el detalle. Nunca se escriben a mano.

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
begin
  -- Montos y peso del detalle, en dos medidas:
  -- v_ton solo cuenta las categorías marcadas; v_ton_total cuenta todo.
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

  -- Beneficios efectivamente aplicados, separados por modalidad
  select coalesce(sum(monto_beneficio) filter (where aplicada and modalidad = 'descuento'), 0),
         coalesce(sum(monto_beneficio) filter (where aplicada and modalidad = 'devolucion'), 0)
    into v_desc, v_dev
  from fact_cotizaciones_promociones
  where id_cotizacion = p_id_cotizacion;

  -- El descuento nunca puede dejar el total en negativo
  v_desc := least(v_desc, v_bruto);

  update fact_cotizaciones
     set monto_bruto_sol  = round(v_bruto, 2),
         monto_descuento  = round(v_desc, 2),
         monto_total_sol  = round(v_bruto - v_desc, 2),
         -- La devolución NO baja el total: el cliente paga completo
         monto_devolucion = round(v_dev, 2),
         toneladas        = round(v_ton, 3),
         toneladas_total  = round(v_ton_total, 3),
         monto_total_dol  = case
                              when tipo_cambio is not null and tipo_cambio > 0
                              then round((v_bruto - v_desc) / tipo_cambio, 2)
                            end
   where id_cotizacion = p_id_cotizacion;
end $$;


create or replace function public.trg_recalcular_cotizacion()
returns trigger
language plpgsql
as $$
begin
  perform recalcular_totales_cotizacion(
    coalesce(new.id_cotizacion, old.id_cotizacion)
  );
  return null;   -- trigger AFTER: el valor de retorno se ignora
end $$;

drop trigger if exists trg_cot_detalle_totales on fact_cotizaciones_detalle;
create trigger trg_cot_detalle_totales
  after insert or update or delete on fact_cotizaciones_detalle
  for each row execute function trg_recalcular_cotizacion();

drop trigger if exists trg_cot_promo_totales on fact_cotizaciones_promociones;
create trigger trg_cot_promo_totales
  after insert or update or delete on fact_cotizaciones_promociones
  for each row execute function trg_recalcular_cotizacion();


-- ========================= TOTALES DE LA VENTA ==============================

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

  v_desc := least(v_desc, v_bruto);

  update fact_ventas
     set monto_bruto_sol  = round(v_bruto, 2),
         monto_descuento  = round(v_desc, 2),
         monto_total_sol  = round(v_bruto - v_desc, 2),
         monto_devolucion = round(v_dev, 2),
         toneladas        = round(v_ton, 3),
         toneladas_total  = round(v_ton_total, 3),
         monto_total_dol  = case
                              when tipo_cambio is not null and tipo_cambio > 0
                              then round((v_bruto - v_desc) / tipo_cambio, 2)
                            end
   where id_venta = p_id_venta;
end $$;


create or replace function public.trg_recalcular_venta()
returns trigger
language plpgsql
as $$
begin
  perform recalcular_totales_venta(coalesce(new.id_venta, old.id_venta));
  return null;
end $$;

drop trigger if exists trg_venta_detalle_totales on fact_ventas_detalle;
create trigger trg_venta_detalle_totales
  after insert or update or delete on fact_ventas_detalle
  for each row execute function trg_recalcular_venta();

drop trigger if exists trg_venta_promo_totales on fact_ventas_promociones;
create trigger trg_venta_promo_totales
  after insert or update or delete on fact_ventas_promociones
  for each row execute function trg_recalcular_venta();


-- ====================== VERSIÓN ANTERIOR REEMPLAZADA ========================
-- Al emitir la versión n, las anteriores pasan a 'reemplazada'.
-- No se permite si la anterior ya generó una venta.

create or replace function public.marcar_version_reemplazada()
returns trigger
language plpgsql
as $$
begin
  if exists (
    select 1
    from fact_cotizaciones c
    join fact_ventas v on v.id_cotizacion = c.id_cotizacion
    where c.id_negociacion = new.id_negociacion
      and c.id_cotizacion <> new.id_cotizacion
      and v.estado <> 'anulada'
  ) then
    raise exception
      'La negociación % ya tiene una venta registrada; no se puede emitir otra versión.',
      new.id_negociacion;
  end if;

  update fact_cotizaciones
     set estado = 'reemplazada'
   where id_negociacion = new.id_negociacion
     and id_cotizacion <> new.id_cotizacion
     and estado in ('enviada', 'aceptada');

  return null;
end $$;

drop trigger if exists trg_cot_reemplazar_version on fact_cotizaciones;
create trigger trg_cot_reemplazar_version
  after insert on fact_cotizaciones
  for each row execute function marcar_version_reemplazada();


-- ==================== NEGOCIACIÓN GANADA / REABIERTA ========================
-- Al validar una venta la negociación queda ganada.
-- Si después se anulan todas, vuelve a estar abierta.

create or replace function public.sincronizar_estado_negociacion()
returns trigger
language plpgsql
as $$
declare
  v_negociacion bigint := coalesce(new.id_negociacion, old.id_negociacion);
  v_validadas   integer;
begin
  select count(*) into v_validadas
  from fact_ventas
  where id_negociacion = v_negociacion and estado = 'validada';

  if v_validadas > 0 then
    update fact_negociaciones
       set estado            = 'ganada',
           fecha_cierre      = coalesce(fecha_cierre, now()),
           id_motivo_perdida = null
     where id_negociacion = v_negociacion
       and estado <> 'ganada';
  else
    -- Se anularon todas: la negociación vuelve a estar viva
    update fact_negociaciones
       set estado       = 'abierta',
           fecha_cierre = null
     where id_negociacion = v_negociacion
       and estado = 'ganada';
  end if;

  return null;
end $$;

drop trigger if exists trg_venta_estado_negociacion on fact_ventas;
create trigger trg_venta_estado_negociacion
  after insert or update of estado or delete on fact_ventas
  for each row execute function sincronizar_estado_negociacion();


-- ================ LA VENTA NACE DE UNA COTIZACIÓN ACEPTADA ==================
-- Un check no puede consultar otra tabla, así que esta regla va en trigger.

create or replace function public.validar_origen_venta()
returns trigger
language plpgsql
as $$
declare
  v_estado         text;
  v_id_negociacion bigint;
begin
  select estado, id_negociacion into v_estado, v_id_negociacion
  from fact_cotizaciones
  where id_cotizacion = new.id_cotizacion;

  if v_estado <> 'aceptada' then
    raise exception
      'La cotización % está en estado "%"; solo se puede vender desde una aceptada.',
      new.id_cotizacion, v_estado;
  end if;

  if v_id_negociacion <> new.id_negociacion then
    raise exception
      'La cotización % pertenece a la negociación %, no a la %.',
      new.id_cotizacion, v_id_negociacion, new.id_negociacion;
  end if;

  return new;
end $$;

drop trigger if exists trg_venta_validar_origen on fact_ventas;
create trigger trg_venta_validar_origen
  before insert on fact_ventas
  for each row execute function validar_origen_venta();


-- =============== PROMOCIÓN AUTOMÁTICA NO SE PUEDE OMITIR ====================

create or replace function public.validar_promocion_omitida()
returns trigger
language plpgsql
as $$
declare
  v_aplicacion text;
begin
  if not new.aplicada then
    select aplicacion into v_aplicacion
    from m_promociones where id_promocion = new.id_promocion;

    if v_aplicacion = 'automatica' then
      raise exception
        'La promoción % es automática y no puede desactivarse.', new.id_promocion;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists trg_validar_promo_cotizacion on fact_cotizaciones_promociones;
create trigger trg_validar_promo_cotizacion
  before insert or update on fact_cotizaciones_promociones
  for each row execute function validar_promocion_omitida();

drop trigger if exists trg_validar_promo_venta on fact_ventas_promociones;
create trigger trg_validar_promo_venta
  before insert or update on fact_ventas_promociones
  for each row execute function validar_promocion_omitida();


-- ============================== updated_at ==================================
drop trigger if exists trg_negociaciones_updated on fact_negociaciones;
create trigger trg_negociaciones_updated
  before update on fact_negociaciones
  for each row execute function set_updated_at();

drop trigger if exists trg_cotizaciones_updated on fact_cotizaciones;
create trigger trg_cotizaciones_updated
  before update on fact_cotizaciones
  for each row execute function set_updated_at();

drop trigger if exists trg_ventas_updated on fact_ventas;
create trigger trg_ventas_updated
  before update on fact_ventas
  for each row execute function set_updated_at();


-- ==================== VENCIMIENTO AUTOMÁTICO (pg_cron) ======================
-- Vence las cotizaciones y deja la negociación lista para que el asesor
-- registre el motivo. No la cierra: eso lo decide una persona.

create or replace function public.vencer_cotizaciones()
returns integer
language plpgsql
as $$
declare
  v_vencidas integer;
begin
  update fact_cotizaciones
     set estado = 'vencida'
   where estado = 'enviada'
     and fecha_vencimiento < now();
  get diagnostics v_vencidas = row_count;

  update fact_negociaciones n
     set estado = 'por_cerrar'
   where n.estado = 'abierta'
     and not exists (
       select 1 from fact_cotizaciones c
       where c.id_negociacion = n.id_negociacion
         and c.estado in ('enviada', 'aceptada')
     )
     and exists (
       select 1 from fact_cotizaciones c
       where c.id_negociacion = n.id_negociacion
     );

  return v_vencidas;
end $$;

comment on function public.vencer_cotizaciones is
  'Tarea nocturna: vence cotizaciones y marca negociaciones como por_cerrar.';


-- Cierra las negociaciones que llevan demasiados días en por_cerrar
-- sin que el asesor registre el motivo.
create or replace function public.cerrar_negociaciones_sin_respuesta()
returns integer
language plpgsql
as $$
declare
  v_motivo integer;
  v_dias   numeric := coalesce(parametro_num('dias_para_cerrar_negociacion'), 7);
  v_filas  integer;
begin
  select id_motivo_perdida into v_motivo
  from m_motivos_perdida
  where automatico and activo
  order by id_motivo_perdida
  limit 1;

  if v_motivo is null then
    return 0;   -- sin motivo automático configurado, no se cierra nada
  end if;

  -- Se mide desde que venció la última cotización, no desde updated_at:
  -- ese campo se reinicia con cualquier edición y el cierre nunca llegaría.
  update fact_negociaciones n
     set estado            = 'perdida',
         id_motivo_perdida = v_motivo,
         fecha_cierre      = now()
   where n.estado = 'por_cerrar'
     and (
       select max(c.fecha_vencimiento)
       from fact_cotizaciones c
       where c.id_negociacion = n.id_negociacion
     ) < now() - (v_dias || ' days')::interval;

  get diagnostics v_filas = row_count;
  return v_filas;
end $$;

-- Programar en Supabase (Database > Cron), todos los días a las 3 a.m.:
--   select cron.schedule('vencer-cotizaciones', '0 3 * * *',
--                        $$select vencer_cotizaciones()$$);
--   select cron.schedule('cerrar-negociaciones', '15 3 * * *',
--                        $$select cerrar_negociaciones_sin_respuesta()$$);
