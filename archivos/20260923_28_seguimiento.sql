-- ============================================================================
-- 28 — Consultas de la pantalla Seguimiento
-- Requiere: 01 a 22 y 24 a 27
--
-- Todas reciben un rango de fechas y son "security invoker": el RLS decide
-- qué ve cada quien. El supervisor obtiene los mismos números pero solo de
-- sus zonas, sin que la pantalla tenga que filtrar nada.
--
-- Las ventas anuladas no cuentan en ningún indicador.
-- ============================================================================

-- ======================= EL PULSO DEL PERIODO ===============================

create or replace function public.seguimiento_resumen(
  p_desde date,
  p_hasta date
)
returns table (
  activas            bigint,
  por_cerrar         bigint,
  ganadas            bigint,
  perdidas           bigint,
  cerradas           bigint,
  conversion_pct     numeric,
  ventas             bigint,
  facturacion        numeric,
  ventas_por_validar bigint
)
language sql
stable
security invoker
as $$
  with negociaciones as (
    select n.*,
           exists (select 1 from fact_ventas v
                   where v.id_negociacion = n.id_negociacion
                     and v.estado <> 'anulada') as tiene_venta
    from fact_negociaciones n
    where n.fecha_inicio::date between p_desde and p_hasta
  ),
  ventas as (
    select v.* from fact_ventas v
    join negociaciones n using (id_negociacion)
    where v.estado <> 'anulada'
  )
  select
    count(*) filter (where estado = 'abierta' and not tiene_venta),
    count(*) filter (where estado = 'por_cerrar'),
    -- Se cuenta como ganada en cuanto hay una venta registrada, sin esperar
    -- la validación: si no, el tablero mostraría cero conversión mientras
    -- las ventas esperan que alguien las confirme.
    count(*) filter (where tiene_venta),
    count(*) filter (where estado = 'perdida' and not tiene_venta),
    count(*) filter (where tiene_venta or estado = 'perdida'),
    round(100.0 * count(*) filter (where tiene_venta)
          / nullif(count(*) filter (where tiene_venta or estado = 'perdida'), 0), 1),
    (select count(*) from ventas),
    coalesce((select sum(monto_total_sol) from ventas), 0),
    (select count(*) from ventas where estado = 'pendiente_validacion')
  from negociaciones
$$;

comment on function public.seguimiento_resumen is
  'Estado de las negociaciones abiertas en el periodo. Una negociación cuenta '
  'como ganada en cuanto tiene una venta no anulada, aunque todavía no esté '
  'validada. La conversión se calcula solo sobre las cerradas.';


-- ==================== EVOLUTIVO DE APERTURAS ================================

create or replace function public.seguimiento_aperturas(
  p_desde date,
  p_hasta date
)
returns table (dia date, negociaciones bigint)
language sql
stable
security invoker
as $$
  select d::date, count(n.id_negociacion)
  from generate_series(p_desde, p_hasta, interval '1 day') d
  left join fact_negociaciones n on n.fecha_inicio::date = d::date
  group by d
  order by d
$$;

comment on function public.seguimiento_aperturas is
  'Una fila por día, incluidos los días sin aperturas: así el gráfico no '
  'esconde los domingos ni los feriados.';


-- ========================= POR ASESOR =======================================

create or replace function public.seguimiento_asesores(
  p_desde date,
  p_hasta date
)
returns table (
  asesor              text,
  negociaciones       bigint,
  cotizaciones        bigint,
  ventas              bigint,
  facturacion         numeric,
  conversion_pct      numeric,
  cotiz_por_negociacion numeric
)
language sql
stable
security invoker
as $$
  with negociaciones as (
    select n.*, coalesce(u.nombre, 'Sin asignar') as nombre_asesor
    from fact_negociaciones n
    left join m_usuarios u on u.id_usuario = n.id_usuario
    where n.fecha_inicio::date between p_desde and p_hasta
  ),
  cotizaciones as (
    select c.id_negociacion, count(*) as n_cot
    from fact_cotizaciones c
    join negociaciones ng using (id_negociacion)
    group by c.id_negociacion
  ),
  ventas as (
    select v.id_negociacion, count(*) as n_ven, sum(v.monto_total_sol) as monto
    from fact_ventas v
    join negociaciones ng using (id_negociacion)
    where v.estado <> 'anulada'
    group by v.id_negociacion
  )
  select
    n.nombre_asesor,
    count(*),
    coalesce(sum(c.n_cot), 0),
    coalesce(sum(v.n_ven), 0),
    coalesce(sum(v.monto), 0),
    round(100.0 * count(*) filter (where v.n_ven > 0)
          / nullif(count(*) filter (where v.n_ven > 0 or n.estado = 'perdida'), 0), 1),
    round(coalesce(sum(c.n_cot), 0)::numeric / nullif(count(*), 0), 1)
  from negociaciones n
  left join cotizaciones c using (id_negociacion)
  left join ventas v using (id_negociacion)
  group by n.nombre_asesor
  order by 5 desc
$$;

comment on function public.seguimiento_asesores is
  'Cotizaciones por negociación es el indicador que más dice: recotizar '
  'mucho y cerrar poco señala un problema de precio o de calificación.';


-- ========================== POR ZONA ========================================

create or replace function public.seguimiento_zonas(
  p_desde date,
  p_hasta date
)
returns table (
  zona           text,
  negociaciones  bigint,
  ventas         bigint,
  facturacion    numeric,
  conversion_pct numeric
)
language sql
stable
security invoker
as $$
  with negociaciones as (
    select n.*, coalesce(z.nombre, 'Sin zona') as nombre_zona
    from fact_negociaciones n
    left join m_zonas z on z.id_zona = n.id_zona
    where n.fecha_inicio::date between p_desde and p_hasta
  ),
  ventas as (
    select v.id_negociacion, count(*) as n_ven, sum(v.monto_total_sol) as monto
    from fact_ventas v
    join negociaciones ng using (id_negociacion)
    where v.estado <> 'anulada'
    group by v.id_negociacion
  )
  select
    n.nombre_zona,
    count(*),
    coalesce(sum(v.n_ven), 0),
    coalesce(sum(v.monto), 0),
    round(100.0 * count(*) filter (where v.n_ven > 0)
          / nullif(count(*) filter (where v.n_ven > 0 or n.estado = 'perdida'), 0), 1)
  from negociaciones n
  left join ventas v using (id_negociacion)
  group by n.nombre_zona
  order by 2 desc
$$;


-- ===================== POR QUÉ SE PIERDEN ===================================

create or replace function public.seguimiento_perdidas(
  p_desde date,
  p_hasta date
)
returns table (
  motivo      text,
  automatico  boolean,
  casos       bigint,
  monto       numeric
)
language sql
stable
security invoker
as $$
  select
    coalesce(m.nombre, 'Sin motivo registrado'),
    coalesce(m.automatico, false),
    count(*),
    -- El monto sale de la última cotización: si nunca cotizó, no suma
    coalesce(sum(ultima.monto_total_sol), 0)
  from fact_negociaciones n
  left join m_motivos_perdida m on m.id_motivo_perdida = n.id_motivo_perdida
  left join lateral (
    select monto_total_sol from fact_cotizaciones
    where id_negociacion = n.id_negociacion
    order by version desc limit 1
  ) ultima on true
  where n.estado = 'perdida'
    and n.fecha_cierre::date between p_desde and p_hasta
  group by 1, 2
  order by 3 desc
$$;

comment on function public.seguimiento_perdidas is
  'Se agrupa por fecha de CIERRE, no de apertura: interesa qué se perdió en '
  'el periodo, aunque la negociación se haya abierto antes.';


-- ================== FERRETERÍAS: COMPITIÓ VS GANÓ ===========================

create or replace function public.seguimiento_ferreterias(
  p_desde date,
  p_hasta date
)
returns table (
  ferreteria      text,
  compitio        bigint,
  elegida         bigint,
  vendida         bigint,
  tasa_elegida_pct numeric,
  conversion_pct   numeric
)
language sql
stable
security invoker
as $$
  with evaluadas as (
    select cf.*, s.id_ferreteria, c.id_negociacion
    from fact_cotizaciones_ferreterias cf
    join fact_cotizaciones c using (id_cotizacion)
    join m_sedes s on s.id_sede = cf.id_sede
    where c.fecha::date between p_desde and p_hasta
  ),
  ventas as (
    select distinct v.id_cotizacion
    from fact_ventas v
    join fact_cotizaciones c using (id_cotizacion)
    where v.estado <> 'anulada'
      and c.fecha::date between p_desde and p_hasta
  )
  select
    f.nombre,
    count(*),
    count(*) filter (where e.elegida),
    count(*) filter (where e.elegida and e.id_cotizacion in (select id_cotizacion from ventas)),
    round(100.0 * count(*) filter (where e.elegida) / nullif(count(*), 0), 1),
    round(100.0 * count(*) filter (where e.elegida and e.id_cotizacion in (select id_cotizacion from ventas))
          / nullif(count(*) filter (where e.elegida), 0), 1)
  from evaluadas e
  join m_ferreterias f on f.id_ferreteria = e.id_ferreteria
  group by f.nombre
  order by 2 desc
$$;

comment on function public.seguimiento_ferreterias is
  'compitio = veces que apareció en una cotización. elegida = veces que el '
  'asesor la eligió. Una ferretería que compite mucho y se elige poco tiene '
  'precios fuera de mercado.';


grant execute on function seguimiento_resumen(date, date)      to authenticated;
grant execute on function seguimiento_aperturas(date, date)    to authenticated;
grant execute on function seguimiento_asesores(date, date)     to authenticated;
grant execute on function seguimiento_zonas(date, date)        to authenticated;
grant execute on function seguimiento_perdidas(date, date)     to authenticated;
grant execute on function seguimiento_ferreterias(date, date)  to authenticated;
