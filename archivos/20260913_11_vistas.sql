-- ============================================================================
-- 11 — Todas las vistas de análisis (reemplaza al archivo 08)
-- Requiere: 01 a 07, 09 y 10
--
-- El archivo 08 quedó obsoleto: sus vistas usaban es_contratista, columna que
-- el archivo 10 eliminó. Este archivo trae las mismas vistas ya corregidas,
-- con segmento y tipo de cliente.
--
-- NO ejecutes el 08. Ejecuta este en su lugar.
-- Se puede reejecutar cuantas veces quieras.
-- ============================================================================

drop view if exists v_cotizaciones_bi;
drop view if exists v_ventas_bi;

-- ====================== FLAGS DE COTIZACIONES ===============================
-- Reemplazan a las columnas flg_ de tu Excel. Se calculan, así que nunca
-- se desincronizan: flg_final cambia solo cuando sale una versión nueva.

create or replace view v_cotizaciones_flags as
with base as (
  select c.id_cotizacion,
         c.id_negociacion,
         n.id_cliente,
         row_number() over (partition by c.id_negociacion order by c.version)            as n_neg_asc,
         row_number() over (partition by c.id_negociacion order by c.version desc)       as n_neg_desc,
         row_number() over (partition by n.id_cliente order by c.fecha, c.id_cotizacion) as n_cliente
  from fact_cotizaciones c
  join fact_negociaciones n using (id_negociacion)
)
select
  id_cotizacion,
  id_negociacion,
  id_cliente,
  (n_neg_asc  = 1)::int as flg_primero,
  (n_neg_desc = 1)::int as flg_final,
  (n_cliente  = 1)::int as flg_primera_cot_cliente,
  (n_cliente  > 1)::int as flg_recompra_cot,
  n_neg_asc             as version_orden
from base;

comment on view v_cotizaciones_flags is
  'flg_primero y flg_final: primera y última cotización de la negociación. '
  'flg_primera_cot_cliente: primera del cliente en la historia. '
  'flg_recompra_cot: toda cotización que no es la primera del cliente.';


-- ========================= FLAGS DE VENTAS ==================================
-- Solo cuentan las ventas validadas. Las anuladas no reciben flags.

create or replace view v_ventas_flags as
with validadas as (
  select v.id_venta,
         v.id_negociacion,
         n.id_cliente,
         row_number() over (partition by n.id_cliente      order by v.fecha_venta, v.id_venta) as n_cliente,
         row_number() over (partition by v.id_negociacion  order by v.fecha_venta, v.id_venta) as n_neg
  from fact_ventas v
  join fact_negociaciones n using (id_negociacion)
  where v.estado = 'validada'
)
select
  id_venta,
  id_negociacion,
  id_cliente,
  (n_cliente = 1)::int                as flg_primera_venta,
  (n_neg = 1 and n_cliente > 1)::int  as flg_recompra
from validadas;

comment on view v_ventas_flags is
  'flg_recompra marca la primera venta de una negociación posterior. '
  'Los pagos o despachos parciales de la misma negociación quedan en 0.';


-- ==================== COTIZADO VS VENDIDO ===================================
-- Qué cambió entre lo que se cotizó y lo que el cliente realmente compró.

create or replace view v_cotizado_vs_vendido as
with lineas as (
  select
    v.id_venta,
    v.id_cotizacion,
    coalesce(vd.id_sku, cd.id_sku)                                as id_sku,
    cd.cantidad                                                    as cantidad_cotizada,
    vd.cantidad                                                    as cantidad_vendida,
    coalesce(cd.precio_modificado, cd.precio_unitario)             as precio_cotizado,
    vd.precio_unitario                                             as precio_vendido,
    cd.subtotal                                                    as subtotal_cotizado,
    vd.subtotal                                                    as subtotal_vendido
  from fact_ventas v
  join fact_cotizaciones_detalle cd on cd.id_cotizacion = v.id_cotizacion
  full outer join fact_ventas_detalle vd
    on vd.id_venta = v.id_venta and vd.id_sku = cd.id_sku
  where v.estado = 'validada'
)
select
  l.*,
  p.nombre  as producto,
  mar.nombre as marca,
  coalesce(l.subtotal_vendido, 0) - coalesce(l.subtotal_cotizado, 0) as diferencia_monto,
  case
    when l.cantidad_cotizada is null                     then 'producto agregado'
    when l.cantidad_vendida  is null                     then 'producto quitado'
    when l.cantidad_vendida  < l.cantidad_cotizada       then 'menos cantidad'
    when l.cantidad_vendida  > l.cantidad_cotizada       then 'mas cantidad'
    when l.precio_vendido   <> l.precio_cotizado         then 'cambio de precio'
    else 'igual'
  end as tipo_diferencia
from lineas l
left join m_skus sk  on sk.id_sku = l.id_sku
left join m_productos p on p.id_producto = sk.id_producto
left join m_marcas mar  on mar.id_marca  = sk.id_marca;

comment on view v_cotizado_vs_vendido is
  'Diferencias línea por línea entre la cotización aceptada y la venta validada.';


-- ======================= FUNNEL DE NEGOCIACIONES ============================
-- El embudo comercial, desde la base de datos y no desde el texto del chat.

create or replace view v_funnel_negociaciones as
select
  date_trunc('month', n.fecha_inicio)::date as mes,
  z.nombre                                  as zona,
  u.nombre                                  as asesor,
  count(*)                                              as negociaciones,
  count(*) filter (where n.estado = 'abierta')          as abiertas,
  count(*) filter (where n.estado = 'por_cerrar')       as por_cerrar,
  count(*) filter (where n.estado = 'ganada')           as ganadas,
  count(*) filter (where n.estado = 'perdida')          as perdidas,
  round(100.0 * count(*) filter (where n.estado = 'ganada')
        / nullif(count(*) filter (where n.estado in ('ganada','perdida')), 0), 1)
                                                        as tasa_conversion,
  -- Cuántas versiones hicieron falta en promedio
  round(avg((select count(*) from fact_cotizaciones c
             where c.id_negociacion = n.id_negociacion)), 2) as cotizaciones_promedio
from fact_negociaciones n
left join m_zonas z    on z.id_zona    = n.id_zona
left join m_usuarios u on u.id_usuario = n.id_usuario
group by 1, 2, 3;

comment on view v_funnel_negociaciones is
  'Conversión por mes, zona y asesor. La tasa solo considera negociaciones cerradas.';


-- ==================== MOTIVOS DE PÉRDIDA ====================================

create or replace view v_motivos_perdida_resumen as
select
  date_trunc('month', n.fecha_cierre)::date as mes,
  z.nombre     as zona,
  m.etapa,
  m.nombre     as motivo,
  m.automatico,
  count(*)     as casos,
  -- Cuánto dinero se dejó de vender
  coalesce(sum((select c.monto_total_sol from fact_cotizaciones c
                where c.id_negociacion = n.id_negociacion
                order by c.version desc limit 1)), 0) as monto_perdido
from fact_negociaciones n
join m_motivos_perdida m using (id_motivo_perdida)
left join m_zonas z on z.id_zona = n.id_zona
where n.estado = 'perdida'
group by 1, 2, 3, 4, 5;


-- ================== COMPETENCIA ENTRE FERRETERÍAS ===========================
-- De todas las sedes que compitieron: cuántas veces fueron la más barata
-- y cuántas veces las eligieron. La brecha entre ambas es el insight.

create or replace view v_competencia_ferreterias as
select
  f.nombre                                          as ferreteria,
  s.codigo                                          as sede_codigo,
  s.nombre                                          as sede,
  d.nombre                                          as distrito,
  count(*)                                          as veces_evaluada,
  count(*) filter (where cf.canasta_completa)       as veces_con_stock_completo,
  count(*) filter (where cf.ranking = 1)            as veces_mas_barata,
  count(*) filter (where cf.elegida)                as veces_elegida,
  round(100.0 * count(*) filter (where cf.canasta_completa)
        / nullif(count(*), 0), 1)                   as tasa_cobertura,
  round(100.0 * count(*) filter (where cf.elegida)
        / nullif(count(*) filter (where cf.canasta_completa), 0), 1) as tasa_eleccion,
  round(avg(cf.distancia_km), 2)                    as distancia_promedio_km
from fact_cotizaciones_ferreterias cf
join m_sedes s        on s.id_sede       = cf.id_sede
join m_ferreterias f  on f.id_ferreteria = s.id_ferreteria
join m_distritos d    on d.id_distrito   = s.id_distrito
group by 1, 2, 3, 4;

comment on view v_competencia_ferreterias is
  'Si una sede es la más barata seguido pero casi nunca la eligen, hay algo que revisar.';


-- ================== PRODUCTOS SIN COBERTURA =================================
-- Qué productos hacen fallar la canasta: los que ninguna ferretería tiene.

create or replace view v_cobertura_productos as
select
  p.nombre                                       as producto,
  mar.nombre                                     as marca,
  cat.nombre                                     as categoria,
  count(distinct pr.id_sede)                     as sedes_con_precio,
  (select count(*) from m_sedes where activo)    as sedes_totales,
  round(100.0 * count(distinct pr.id_sede)
        / nullif((select count(*) from m_sedes where activo), 0), 1) as cobertura_pct,
  round(avg(pr.precio), 2)                       as precio_promedio,
  min(pr.precio)                                 as precio_min,
  max(pr.precio)                                 as precio_max,
  max(pr.fecha_actualizacion)                    as ultima_actualizacion
from m_skus sk
join m_productos p    on p.id_producto   = sk.id_producto
join m_marcas mar     on mar.id_marca    = sk.id_marca
join m_categorias cat on cat.id_categoria = p.id_categoria
left join m_precios pr on pr.id_sku = sk.id_sku and pr.activo
where sk.activo
group by 1, 2, 3;


-- ==================== USO DE PROMOCIONES ====================================
-- Promociones disponibles vs efectivamente aplicadas por los asesores.

create or replace view v_promociones_uso as
select
  pr.codigo,
  pr.nombre,
  pr.modalidad,
  pr.aplicacion,
  pr.financiado_por,
  count(*)                                          as veces_disponible,
  count(*) filter (where cp.aplicada)               as veces_aplicada,
  round(100.0 * count(*) filter (where cp.aplicada)
        / nullif(count(*), 0), 1)                   as tasa_uso,
  coalesce(sum(cp.monto_beneficio) filter (where cp.aplicada), 0) as beneficio_otorgado
from fact_cotizaciones_promociones cp
join m_promociones pr using (id_promocion)
group by 1, 2, 3, 4, 5;


-- ================= PRECIOS DESACTUALIZADOS ==================================
-- Control operativo: qué sedes tienen precios viejos.
-- Con cotizaciones que valen 1 día, un precio de hace un mes es un riesgo.

create or replace view v_precios_desactualizados as
select
  f.nombre                                  as ferreteria,
  s.codigo                                  as sede_codigo,
  s.nombre                                  as sede,
  count(*)                                  as skus_con_precio,
  min(pr.fecha_actualizacion)::date         as precio_mas_antiguo,
  max(pr.fecha_actualizacion)::date         as precio_mas_reciente,
  count(*) filter (
    where pr.fecha_actualizacion < now() - interval '30 days'
  )                                         as skus_sin_actualizar_30d
from m_precios pr
join m_sedes s       on s.id_sede       = pr.id_sede
join m_ferreterias f on f.id_ferreteria = s.id_ferreteria
where pr.activo and s.activo
group by 1, 2, 3;


-- ===================== VISTAS DE BI, ACTUALIZADAS ===========================

create or replace view v_cotizaciones_bi as
select
  c.id_cotizacion, c.id_negociacion, c.version,
  c.fecha, c.fecha::date as fecha_dia, c.fecha_vencimiento,
  c.estado as estado_cotizacion,

  cl.id_cliente, cl.nombre as cliente, cl.telefono,
  tc.segmento, tc.nombre as tipo_cliente,

  u.nombre as asesor, u.empresa as empresa_asesor, z.nombre as zona,
  d.nombre as distrito, pr.nombre as provincia, dep.nombre as departamento,
  f.nombre as ferreteria, s.codigo as sede_codigo, s.nombre as sede, c.distancia_km,
  r.codigo as regla_aplicada, c.monto_referencial,

  c.monto_bruto_sol, c.monto_descuento, c.monto_total_sol, c.monto_devolucion,
  c.toneladas, c.toneladas_total, tp.nombre as tipo_pago,

  fl.flg_primero, fl.flg_final, fl.flg_primera_cot_cliente, fl.flg_recompra_cot,

  n.estado as estado_negociacion, mp.nombre as motivo_perdida,
  n.referencia_obra, n.fuente_origen,

  (select count(*) from fact_cotizaciones_detalle cd
    where cd.id_cotizacion = c.id_cotizacion)        as n_productos,
  exists (select 1 from fact_ventas v
           where v.id_cotizacion = c.id_cotizacion
             and v.estado = 'validada')              as termino_en_venta
from fact_cotizaciones c
join fact_negociaciones n     using (id_negociacion)
join m_clientes cl            on cl.id_cliente      = n.id_cliente
left join m_tipos_cliente tc  on tc.id_tipo_cliente = cl.id_tipo_cliente
left join m_usuarios u        on u.id_usuario       = c.id_usuario
left join m_zonas z           on z.id_zona          = n.id_zona
left join m_distritos d       on d.id_distrito      = c.id_distrito
left join m_provincias pr     on pr.id_provincia    = d.id_provincia
left join m_departamentos dep on dep.id_departamento = pr.id_departamento
join m_sedes s                on s.id_sede          = c.id_sede
join m_ferreterias f          on f.id_ferreteria    = s.id_ferreteria
left join m_reglas_cotizacion r on r.id_regla       = c.id_regla
left join m_tipos_pago tp     on tp.id_tipo_pago    = c.id_tipo_pago
left join m_motivos_perdida mp on mp.id_motivo_perdida = n.id_motivo_perdida
left join v_cotizaciones_flags fl on fl.id_cotizacion = c.id_cotizacion;


create or replace view v_ventas_bi as
select
  v.id_venta, v.id_negociacion, v.id_cotizacion,
  v.fecha_venta, v.fecha_venta::date as fecha_dia, v.estado as estado_venta,

  cl.id_cliente, cl.nombre as cliente,
  tc.segmento, tc.nombre as tipo_cliente,

  u.nombre as asesor, z.nombre as zona,
  f.nombre as ferreteria, s.codigo as sede_codigo,

  v.monto_bruto_sol, v.monto_descuento, v.monto_total_sol, v.monto_devolucion,
  v.toneladas, v.toneladas_total, tp.nombre as tipo_pago, v.tipo_comprobante,

  fl.flg_primera_venta, fl.flg_recompra,
  round(extract(epoch from (v.fecha_venta - c.fecha)) / 3600, 1) as horas_hasta_compra
from fact_ventas v
join fact_negociaciones n    using (id_negociacion)
join fact_cotizaciones c     on c.id_cotizacion    = v.id_cotizacion
join m_clientes cl           on cl.id_cliente      = n.id_cliente
left join m_tipos_cliente tc on tc.id_tipo_cliente = cl.id_tipo_cliente
left join m_usuarios u       on u.id_usuario       = v.id_usuario
left join m_zonas z          on z.id_zona          = n.id_zona
join m_sedes s               on s.id_sede          = v.id_sede
join m_ferreterias f         on f.id_ferreteria    = s.id_ferreteria
left join m_tipos_pago tp    on tp.id_tipo_pago    = v.id_tipo_pago
left join v_ventas_flags fl  on fl.id_venta        = v.id_venta;


-- Conversión por segmento: el corte que más vas a mirar
create or replace view v_funnel_por_segmento as
select
  date_trunc('month', n.fecha_inicio)::date as mes,
  coalesce(tc.segmento, 'Sin clasificar')   as segmento,
  tc.nombre                                 as tipo_cliente,
  z.nombre                                  as zona,
  count(*)                                            as negociaciones,
  count(*) filter (where n.estado = 'ganada')         as ganadas,
  count(*) filter (where n.estado = 'perdida')        as perdidas,
  round(100.0 * count(*) filter (where n.estado = 'ganada')
        / nullif(count(*) filter (where n.estado in ('ganada','perdida')), 0), 1) as tasa_conversion,
  round(avg(c.monto_total_sol), 2)                    as ticket_promedio
from fact_negociaciones n
join m_clientes cl            on cl.id_cliente      = n.id_cliente
left join m_tipos_cliente tc  on tc.id_tipo_cliente = cl.id_tipo_cliente
left join m_zonas z           on z.id_zona          = n.id_zona
left join lateral (
  select monto_total_sol from fact_cotizaciones
  where id_negociacion = n.id_negociacion
  order by version desc limit 1
) c on true
group by 1, 2, 3, 4;
