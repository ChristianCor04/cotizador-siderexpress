-- ============================================================================
-- 09 — Condiciones de cliente y momento de aplicación en promociones
-- Requiere: 01 a 08
--
-- Se puede ejecutar aunque ya hayas corrido una versión anterior de este
-- archivo: migra los datos existentes y no duplica nada.
--
-- En vez de etiquetas fijas (primera compra / recompra), las condiciones son
-- RANGOS. Así una promoción nueva es un insert, no código:
--   Primera compra      -> compras_previas_max = 0
--   Recompra            -> compras_previas_min = 1
--   Cliente fiel        -> compras_previas_min = 3
--   Reactivación        -> dias_sin_comprar_min = 90
--   Solo contratistas   -> solo_contratistas = true
-- Los campos en null no filtran nada.
-- ============================================================================

-- =============================== CAMPOS NUEVOS ==============================

alter table m_promociones add column if not exists compras_previas_min  integer;
alter table m_promociones add column if not exists compras_previas_max  integer;
alter table m_promociones add column if not exists dias_sin_comprar_min integer;
alter table m_promociones add column if not exists solo_contratistas    boolean;
alter table m_promociones add column if not exists momento text not null default 'cotizacion';

-- Migrar desde la versión anterior de este archivo, si existía
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_name = 'm_promociones' and column_name = 'condicion_cliente'
  ) then
    update m_promociones set compras_previas_max = 0 where condicion_cliente = 'primera_compra';
    update m_promociones set compras_previas_min = 1 where condicion_cliente = 'recompra';
    alter table m_promociones drop constraint if exists chk_promo_condicion_cliente;
    alter table m_promociones drop column condicion_cliente;
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'chk_promo_momento') then
    alter table m_promociones add constraint chk_promo_momento
      check (momento in ('cotizacion', 'venta'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'chk_promo_condiciones') then
    alter table m_promociones add constraint chk_promo_condiciones check (
      (compras_previas_min  is null or compras_previas_min  >= 0) and
      (compras_previas_max  is null or compras_previas_max  >= 0) and
      (dias_sin_comprar_min is null or dias_sin_comprar_min >  0) and
      (compras_previas_min is null or compras_previas_max is null
        or compras_previas_max >= compras_previas_min)
    );
  end if;
end $$;

comment on column m_promociones.compras_previas_min is
  'Mínimo de compras validadas del cliente. 1 = solo recompras. Null = sin mínimo.';
comment on column m_promociones.compras_previas_max is
  'Máximo de compras validadas. 0 = solo primera compra. Null = sin máximo.';
comment on column m_promociones.dias_sin_comprar_min is
  'Días desde la última compra. Para campañas de reactivación. Null = no aplica.';
comment on column m_promociones.solo_contratistas is
  'true: solo contratistas. false: solo no contratistas. Null: todos.';
comment on column m_promociones.momento is
  'cotizacion: se evalúa al cotizar y se muestra al cliente. '
  'venta: se evalúa sobre lo realmente pagado, después de la compra.';


-- ===================== HISTORIAL DE COMPRAS DEL CLIENTE =====================

create or replace function public.compras_previas(p_id_cliente bigint)
returns integer
language sql
stable
as $$
  select count(*)::int
  from fact_ventas v
  join fact_negociaciones n using (id_negociacion)
  where n.id_cliente = p_id_cliente and v.estado = 'validada'
$$;

create or replace function public.dias_desde_ultima_compra(p_id_cliente bigint)
returns integer
language sql
stable
as $$
  select case
    when max(v.fecha_venta) is null then null
    else extract(day from now() - max(v.fecha_venta))::int
  end
  from fact_ventas v
  join fact_negociaciones n using (id_negociacion)
  where n.id_cliente = p_id_cliente and v.estado = 'validada'
$$;

comment on function public.compras_previas is
  'Cuántas ventas validadas tiene el cliente. Una cotización sin compra no cuenta.';


-- ¿El cliente cumple las condiciones de esta promoción?
create or replace function public.cliente_cumple_promocion(
  p_id_promocion bigint,
  p_id_cliente   bigint
)
returns boolean
language plpgsql
stable
as $$
declare
  v_promo   m_promociones%rowtype;
  v_compras integer;
  v_dias    integer;
  v_contra  boolean;
begin
  select * into v_promo from m_promociones where id_promocion = p_id_promocion;
  if not found then
    return false;
  end if;

  -- Promoción sin condiciones de cliente: aplica siempre
  if v_promo.compras_previas_min is null
     and v_promo.compras_previas_max is null
     and v_promo.dias_sin_comprar_min is null
     and v_promo.solo_contratistas is null then
    return true;
  end if;

  -- Con condiciones pero sin cliente identificado, no se puede verificar
  if p_id_cliente is null then
    return false;
  end if;

  v_compras := compras_previas(p_id_cliente);

  if v_promo.compras_previas_min is not null and v_compras < v_promo.compras_previas_min then
    return false;
  end if;
  if v_promo.compras_previas_max is not null and v_compras > v_promo.compras_previas_max then
    return false;
  end if;

  if v_promo.dias_sin_comprar_min is not null then
    v_dias := dias_desde_ultima_compra(p_id_cliente);
    -- Sin compras previas no hay reactivación posible
    if v_dias is null or v_dias < v_promo.dias_sin_comprar_min then
      return false;
    end if;
  end if;

  if v_promo.solo_contratistas is not null then
    select es_contratista into v_contra from m_clientes where id_cliente = p_id_cliente;
    if coalesce(v_contra, false) <> v_promo.solo_contratistas then
      return false;
    end if;
  end if;

  return true;
end $$;


-- ================ PROMOCIONES APLICABLES, CON CONDICIONES ===================

drop function if exists public.promociones_aplicables(bigint, numeric);
drop function if exists public.promociones_aplicables(bigint, numeric, bigint, text);
drop function if exists public.beneficio_promocional(bigint, numeric);
drop function if exists public.beneficio_promocional(bigint, numeric, bigint, text);

create function public.promociones_aplicables(
  p_id_sede    bigint,
  p_monto      numeric,
  p_id_cliente bigint default null,
  p_momento    text    default 'cotizacion'
)
returns table (
  id_promocion   bigint,
  codigo         text,
  nombre         text,
  modalidad      text,
  beneficio      numeric,
  acumulable     boolean,
  prioridad      smallint,
  financiado_por text,
  aplicacion     text,
  momento        text
)
language sql
stable
as $$
  select
    p.id_promocion, p.codigo, p.nombre, p.modalidad,
    calcular_beneficio_promocion(p.id_promocion, p_monto) as beneficio,
    p.acumulable, p.prioridad, p.financiado_por, p.aplicacion, p.momento
  from m_promociones p
  where p.activo
    and now() between p.vigente_desde and p.vigente_hasta
    and p.alcance = 'cotizacion'
    and p.momento = p_momento
    and sede_participa_en_promocion(p.id_promocion, p_id_sede)
    and cliente_cumple_promocion(p.id_promocion, p_id_cliente)
    and calcular_beneficio_promocion(p.id_promocion, p_monto) > 0
  order by p.prioridad, beneficio desc
$$;

create function public.beneficio_promocional(
  p_id_sede    bigint,
  p_monto      numeric,
  p_id_cliente bigint default null,
  p_momento    text    default 'cotizacion'
)
returns table (
  id_promocion bigint,
  codigo       text,
  nombre       text,
  modalidad    text,
  beneficio    numeric,
  aplicacion   text,
  elegida_por  text
)
language sql
stable
as $$
  with aplicables as (
    select * from promociones_aplicables(p_id_sede, p_monto, p_id_cliente, p_momento)
  ),
  mejor_no_acumulable as (
    select a.* from aplicables a
    where not a.acumulable
    order by a.beneficio desc, a.prioridad
    limit 1
  )
  select a.id_promocion, a.codigo, a.nombre, a.modalidad, a.beneficio,
         a.aplicacion, 'acumulable'::text
  from aplicables a where a.acumulable
  union all
  select m.id_promocion, m.codigo, m.nombre, m.modalidad, m.beneficio,
         m.aplicacion, 'mejor beneficio'::text
  from mejor_no_acumulable m
$$;


-- ==================== RESUMEN PARA LA PANTALLA ==============================

create or replace function public.resumen_beneficios(
  p_id_sede    bigint,
  p_monto      numeric,
  p_id_cliente bigint default null
)
returns table (
  descuento_cotizacion  numeric,
  devolucion_post_venta numeric,
  total_a_pagar         numeric
)
language sql
stable
as $$
  with cot as (
    select coalesce(sum(beneficio) filter (where modalidad = 'descuento'), 0) as desc_cot
    from beneficio_promocional(p_id_sede, p_monto, p_id_cliente, 'cotizacion')
  ),
  ven as (
    select coalesce(sum(beneficio), 0) as dev_post
    from beneficio_promocional(p_id_sede, p_monto, p_id_cliente, 'venta')
  )
  select round(cot.desc_cot, 2), round(ven.dev_post, 2), round(p_monto - cot.desc_cot, 2)
  from cot, ven
$$;


-- ======================= LAS DOS PROMOCIONES REALES =========================

insert into m_promociones
  (codigo, nombre, descripcion, modalidad, tipo, valor, base_bloque, alcance,
   vigente_desde, vigente_hasta, financiado_por, requiere_afiliacion,
   aplicacion, acumulable, momento, compras_previas_max)
values
  ('BONO-PRIMERA', 'Bono de primera compra',
   'S/ 30 por cada S/ 3,000 pagados. Solo clientes sin compras previas. Se entrega después de la compra.',
   'devolucion', 'por_bloques', 30, 3000, 'cotizacion',
   now(), now() + interval '1 year', 'siderexpress', false,
   'automatica', true, 'venta', 0)
on conflict (codigo) do nothing;

insert into m_promociones
  (codigo, nombre, descripcion, modalidad, tipo, valor, base_bloque, alcance,
   vigente_desde, vigente_hasta, financiado_por, requiere_afiliacion,
   aplicacion, acumulable, momento)
values
  ('DESC-DIRECTO', 'Descuento directo en cotización',
   'Baja el monto que paga el cliente. SIDEREXPRESS reembolsa el descuento a la ferretería.',
   'descuento', 'por_bloques', 50, 1500, 'cotizacion',
   now(), now() + interval '1 year', 'siderexpress', true,
   'sugerida', true, 'cotizacion')
on conflict (codigo) do nothing;
