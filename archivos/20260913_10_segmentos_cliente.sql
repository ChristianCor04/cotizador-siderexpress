-- ============================================================================
-- 10 — Segmento y tipo de cliente (B2B / B2C)
-- Requiere: 01 a 09
--
-- Reemplaza el booleano es_contratista por una estructura de dos niveles:
--   segmento     -> B2B o B2C (pocos, estables, sirven para reportes)
--   tipo_cliente -> constructora, dueño de obra, contratista... (crecen con el tiempo)
-- El tipo define el segmento, así no puede haber una constructora marcada B2C.
-- ============================================================================

-- ========================== CATÁLOGO DE TIPOS ===============================

create table if not exists m_tipos_cliente (
  id_tipo_cliente bigint generated always as identity,
  segmento        text not null,
  nombre          text not null,
  descripcion     text,
  activo          boolean not null default true,

  constraint pk_tipos_cliente     primary key (id_tipo_cliente),
  constraint uq_tipo_cliente_nombre unique (nombre),
  constraint chk_tipo_cliente_segmento check (segmento in ('B2B', 'B2C'))
);

comment on table m_tipos_cliente is
  'Subtipos de cliente y a qué segmento pertenece cada uno. Agregar uno nuevo es un insert.';

insert into m_tipos_cliente (segmento, nombre, descripcion) values
  ('B2B', 'Constructora',   'Empresa constructora con obras en curso'),
  ('B2B', 'Contratista',    'Contratista independiente, compra recurrente'),
  ('B2B', 'Ferretero',      'Ferretería que compra para revender'),
  ('B2B', 'Empresa',        'Otras empresas'),
  ('B2C', 'Dueño de obra',  'Persona que construye su vivienda'),
  ('B2C', 'Maestro de obra','Maestro que compra para la obra de un tercero'),
  ('B2C', 'Consumidor final','Compra puntual, poco volumen')
on conflict (nombre) do nothing;


-- ====================== CLIENTES: NUEVO CAMPO ===============================

alter table m_clientes add column if not exists id_tipo_cliente bigint;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'fk_cliente_tipo') then
    alter table m_clientes add constraint fk_cliente_tipo
      foreign key (id_tipo_cliente) references m_tipos_cliente (id_tipo_cliente)
      on delete restrict;
  end if;
end $$;

-- Migrar lo que ya existía. Va dentro de un bloque condicional para que el
-- archivo se pueda reejecutar: en la segunda corrida esas columnas ya no existen.
do $$
begin
  if exists (select 1 from information_schema.columns
             where table_name = 'm_clientes' and column_name = 'tipo_cliente') then
    execute $q$
      update m_clientes c
         set id_tipo_cliente = t.id_tipo_cliente
        from m_tipos_cliente t
       where c.id_tipo_cliente is null
         and c.tipo_cliente is not null
         and upper(trim(c.tipo_cliente)) = upper(t.nombre)
    $q$;
  end if;

  if exists (select 1 from information_schema.columns
             where table_name = 'm_clientes' and column_name = 'es_contratista') then
    execute $q$
      update m_clientes
         set id_tipo_cliente = (select id_tipo_cliente from m_tipos_cliente where nombre = 'Contratista')
       where id_tipo_cliente is null and es_contratista
    $q$;
  end if;
end $$;


-- Las vistas del archivo 08 usan es_contratista, así que hay que rehacerlas
-- antes de poder eliminar esa columna.
drop view if exists v_cotizaciones_bi;
drop view if exists v_ventas_bi;
drop index if exists idx_clientes_contratista;

alter table m_clientes drop column if exists es_contratista;
alter table m_clientes drop column if exists tipo_cliente;

create index if not exists idx_clientes_tipo on m_clientes (id_tipo_cliente);


-- ================= PROMOCIONES: SEGMENTO Y TIPO =============================

alter table m_promociones drop column if exists solo_contratistas;
alter table m_promociones add column if not exists segmento_cliente text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'chk_promo_segmento') then
    alter table m_promociones add constraint chk_promo_segmento
      check (segmento_cliente is null or segmento_cliente in ('B2B', 'B2C'));
  end if;
end $$;

comment on column m_promociones.segmento_cliente is
  'B2B o B2C para acotar la promoción. Null = ambos segmentos.';

-- Para acotar a subtipos concretos. Sin filas = todos los tipos del segmento.
create table if not exists rel_promociones_tipos_cliente (
  id_promocion    bigint not null,
  id_tipo_cliente bigint not null,

  constraint pk_promo_tipos_cliente primary key (id_promocion, id_tipo_cliente),
  constraint fk_ptc_promo foreign key (id_promocion)
    references m_promociones (id_promocion) on delete cascade,
  constraint fk_ptc_tipo foreign key (id_tipo_cliente)
    references m_tipos_cliente (id_tipo_cliente) on delete restrict
);

create index if not exists idx_ptc_tipo on rel_promociones_tipos_cliente (id_tipo_cliente);


-- =================== CONDICIONES DEL CLIENTE, ACTUALIZADAS ==================

create or replace function public.cliente_cumple_promocion(
  p_id_promocion bigint,
  p_id_cliente   bigint
)
returns boolean
language plpgsql
stable
as $$
declare
  v_promo    m_promociones%rowtype;
  v_compras  integer;
  v_dias     integer;
  v_segmento text;
  v_tipo     bigint;
  v_tiene_tipos boolean;
begin
  select * into v_promo from m_promociones where id_promocion = p_id_promocion;
  if not found then
    return false;
  end if;

  select exists (
    select 1 from rel_promociones_tipos_cliente where id_promocion = p_id_promocion
  ) into v_tiene_tipos;

  -- Sin ninguna condición de cliente: aplica siempre
  if v_promo.compras_previas_min is null
     and v_promo.compras_previas_max is null
     and v_promo.dias_sin_comprar_min is null
     and v_promo.segmento_cliente is null
     and not v_tiene_tipos then
    return true;
  end if;

  if p_id_cliente is null then
    return false;
  end if;

  -- Segmento y tipo
  select t.segmento, t.id_tipo_cliente into v_segmento, v_tipo
  from m_clientes c
  left join m_tipos_cliente t on t.id_tipo_cliente = c.id_tipo_cliente
  where c.id_cliente = p_id_cliente;

  if v_promo.segmento_cliente is not null
     and coalesce(v_segmento, '') <> v_promo.segmento_cliente then
    return false;
  end if;

  if v_tiene_tipos then
    if v_tipo is null or not exists (
      select 1 from rel_promociones_tipos_cliente
      where id_promocion = p_id_promocion and id_tipo_cliente = v_tipo
    ) then
      return false;
    end if;
  end if;

  -- Historial de compras
  v_compras := compras_previas(p_id_cliente);

  if v_promo.compras_previas_min is not null and v_compras < v_promo.compras_previas_min then
    return false;
  end if;
  if v_promo.compras_previas_max is not null and v_compras > v_promo.compras_previas_max then
    return false;
  end if;

  if v_promo.dias_sin_comprar_min is not null then
    v_dias := dias_desde_ultima_compra(p_id_cliente);
    if v_dias is null or v_dias < v_promo.dias_sin_comprar_min then
      return false;
    end if;
  end if;

  return true;
end $$;


-- ===================== VISTAS DE BI, ACTUALIZADAS ===========================

create view v_cotizaciones_bi as
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


create view v_ventas_bi as
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
