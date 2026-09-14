-- ============================================================================
-- 04 — Promociones, tramos y beneficios
-- Requiere: 01_extensiones_utilidades.sql, 02_geografia_ferreterias.sql,
--           03_productos_precios.sql
--
-- Crea el CATÁLOGO de promociones. El registro de lo aplicado a cada
-- cotización o venta va en el archivo 06 (transaccionales).
-- ============================================================================

create table m_promociones (
  id_promocion     bigint generated always as identity,
  codigo           text not null,
  nombre           text not null,
  descripcion      text,

  -- CÓMO llega el beneficio al cliente
  --   descuento : baja el total que paga hoy
  --   devolucion: paga el total completo y se le devuelve después (cashback)
  modalidad        text not null default 'descuento',

  -- CÓMO se calcula
  --   porcentaje      : % del monto
  --   monto_fijo      : S/ X fijos
  --   precio_especial : fija el precio unitario (solo alcance = producto)
  --   escalonada      : por tramos de monto (ver m_promociones_tramos)
  --   por_bloques     : S/ X por cada bloque de S/ Y comprados
  tipo             text not null,
  valor            numeric(12,4),
  base_bloque      numeric(14,2),

  alcance          text not null,

  vigente_desde    timestamptz not null,
  vigente_hasta    timestamptz not null,

  -- CONDICIONES (null = sin condición)
  monto_minimo     numeric(14,2),
  cantidad_minima  numeric(12,2),
  tope_beneficio   numeric(14,2),

  acumulable       boolean not null default false,
  prioridad        smallint not null default 100,

  usos_maximos     integer,
  usos_por_cliente integer,

  financiado_por   text not null default 'siderexpress',

  -- true  : solo participan las sedes que la aceptaron explícitamente
  -- false : participan todas, salvo las que la rechazaron
  requiere_afiliacion boolean not null default true,

  -- Cómo llega la promoción al asesor cuando cotiza:
  --   automatica : se aplica sola, el asesor no la puede quitar
  --   sugerida   : viene marcada, pero el asesor puede desactivarla
  --   manual     : viene desmarcada, el asesor decide activarla
  aplicacion       text not null default 'sugerida',

  activo           boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  constraint pk_promociones      primary key (id_promocion),
  constraint uq_promocion_codigo unique (codigo),

  constraint chk_promo_modalidad check (modalidad in ('descuento', 'devolucion')),
  constraint chk_promo_tipo check (
    tipo in ('porcentaje', 'monto_fijo', 'precio_especial', 'escalonada', 'por_bloques')
  ),
  constraint chk_promo_alcance   check (alcance in ('cotizacion', 'producto')),
  constraint chk_promo_aplicacion check (
    aplicacion in ('automatica', 'sugerida', 'manual')
  ),
  constraint chk_promo_financiado check (
    financiado_por in ('siderexpress', 'ferreteria', 'proveedor', 'compartido')
  ),

  -- Cada tipo usa campos distintos; la regla cambia según el tipo.
  -- OJO: hay que comprobar "is not null" explícitamente. Una comparación con
  -- null da null, y un check que devuelve null NO bloquea la fila.
  constraint chk_promo_valor check (
    case tipo
      when 'porcentaje' then
        valor is not null and valor > 0 and valor <= 100 and base_bloque is null
      when 'monto_fijo' then
        valor is not null and valor > 0 and base_bloque is null
      when 'precio_especial' then
        valor is not null and valor > 0 and base_bloque is null
      -- escalonada: el valor vive en m_promociones_tramos, no aquí
      when 'escalonada' then
        valor is null and base_bloque is null
      -- por_bloques: valor = lo que se devuelve, base_bloque = cada cuánto
      when 'por_bloques' then
        valor is not null and valor > 0
        and base_bloque is not null and base_bloque > 0
    end
  ),
  -- precio_especial reemplaza el precio unitario: solo tiene sentido por producto
  constraint chk_promo_precio_especial check (
    tipo <> 'precio_especial' or alcance = 'producto'
  ),
  -- escalonada y por_bloques se calculan sobre el total de la canasta
  constraint chk_promo_alcance_total check (
    tipo not in ('escalonada', 'por_bloques') or alcance = 'cotizacion'
  ),
  constraint chk_promo_fechas  check (vigente_hasta > vigente_desde),
  constraint chk_promo_minimos check (
    (monto_minimo    is null or monto_minimo    > 0) and
    (cantidad_minima is null or cantidad_minima > 0) and
    (tope_beneficio  is null or tope_beneficio  > 0)
  ),
  constraint chk_promo_usos check (
    (usos_maximos     is null or usos_maximos     > 0) and
    (usos_por_cliente is null or usos_por_cliente > 0)
  )
);

comment on column m_promociones.modalidad is
  'descuento: baja el total a pagar. devolucion: el cliente paga completo y se le devuelve después.';
comment on column m_promociones.tope_beneficio is
  'Máximo a descontar o devolver. Ej. 300 en la promoción escalonada de 1% y 2%.';
comment on column m_promociones.base_bloque is
  'Solo para por_bloques: cada cuántos soles se otorga el beneficio. Ej. 1500.';
comment on column m_promociones.requiere_afiliacion is
  'true: la ferretería debe aceptar la promoción para que aplique en sus sedes. '
  'Úsalo cuando el descuento lo asume la ferretería.';
comment on column m_promociones.aplicacion is
  'automatica: el asesor no puede quitarla. sugerida: viene marcada y puede quitarla. '
  'manual: viene desmarcada y él decide activarla.';


-- ============================== TRAMOS ======================================
-- Para promociones escalonadas: distinto beneficio según cuánto compre.
-- Ej. de S/ 3,000 a S/ 5,999.99 -> 1% ; de S/ 6,000 en adelante -> 2%

create table m_promociones_tramos (
  id_tramo     bigint generated always as identity,
  id_promocion bigint not null,
  monto_desde  numeric(14,2) not null,
  monto_hasta  numeric(14,2),          -- null = sin límite superior
  tipo_valor   text not null,
  valor        numeric(12,4) not null,

  constraint pk_promociones_tramos primary key (id_tramo),
  constraint fk_tramo_promocion foreign key (id_promocion)
    references m_promociones (id_promocion) on delete cascade,
  constraint chk_tramo_tipo_valor check (tipo_valor in ('porcentaje', 'monto_fijo')),
  constraint chk_tramo_valor check (
    (tipo_valor = 'porcentaje' and valor > 0 and valor <= 100) or
    (tipo_valor = 'monto_fijo' and valor > 0)
  ),
  constraint chk_tramo_rango check (
    monto_desde >= 0 and (monto_hasta is null or monto_hasta > monto_desde)
  ),
  -- Impide tramos que se pisen: un mismo monto no puede caer en dos tramos.
  -- '[)' = incluye el desde, excluye el hasta.
  constraint excl_tramos_traslape exclude using gist (
    id_promocion with =,
    numrange(monto_desde, monto_hasta, '[)') with &&
  )
);

comment on table m_promociones_tramos is
  'Tramos de una promoción escalonada. El monto_desde es inclusivo y el monto_hasta exclusivo.';


-- ============================= ALCANCE ======================================
-- PRODUCTOS (skus y categorias): sin filas = aplica a todos los productos.
-- ZONAS: sin filas = aplica en todas las zonas.
-- SEDES: es distinto, es una AFILIACIÓN. Ver rel_promociones_sedes abajo.

create table rel_promociones_skus (
  id_promocion bigint not null,
  id_sku       bigint not null,
  constraint pk_promo_skus primary key (id_promocion, id_sku),
  constraint fk_ps_promo foreign key (id_promocion)
    references m_promociones (id_promocion) on delete cascade,
  constraint fk_ps_sku   foreign key (id_sku)
    references m_skus (id_sku) on delete restrict
);

create table rel_promociones_categorias (
  id_promocion bigint not null,
  id_categoria bigint not null,
  constraint pk_promo_categorias primary key (id_promocion, id_categoria),
  constraint fk_pc_promo foreign key (id_promocion)
    references m_promociones (id_promocion) on delete cascade,
  constraint fk_pc_categoria foreign key (id_categoria)
    references m_categorias (id_categoria) on delete restrict
);

-- Afiliación: qué sedes aceptaron la promoción y cuáles la rechazaron.
-- Es la tabla que decide si una ferretería participa cuando el asesor cotiza.
create table rel_promociones_sedes (
  id_promocion    bigint not null,
  id_sede         bigint not null,
  acepta          boolean not null default true,
  fecha_respuesta timestamptz not null default now(),
  registrado_por  text,
  observacion     text,

  constraint pk_promo_sedes primary key (id_promocion, id_sede),
  constraint fk_pse_promo foreign key (id_promocion)
    references m_promociones (id_promocion) on delete cascade,
  constraint fk_pse_sede  foreign key (id_sede)
    references m_sedes (id_sede) on delete restrict
);

comment on table rel_promociones_sedes is
  'Respuesta de cada sede a una promoción. Sin fila = no respondió; '
  'lo que pasa entonces lo define requiere_afiliacion de la promoción.';

create table rel_promociones_zonas (
  id_promocion bigint not null,
  id_zona      bigint not null,
  constraint pk_promo_zonas primary key (id_promocion, id_zona),
  constraint fk_pz_promo foreign key (id_promocion)
    references m_promociones (id_promocion) on delete cascade,
  constraint fk_pz_zona  foreign key (id_zona)
    references m_zonas (id_zona) on delete restrict
);


-- ============================== HISTORIAL ===================================

create table h_promociones (
  id_h_promocion bigint generated always as identity,
  id_promocion   bigint not null,
  modalidad      text not null,
  tipo           text not null,
  valor          numeric(12,4),
  base_bloque    numeric(14,2),
  tope_beneficio numeric(14,2),
  vigente_desde  timestamptz not null,
  vigente_hasta  timestamptz not null,
  archivado_en   timestamptz not null default now(),

  constraint pk_h_promociones primary key (id_h_promocion),
  constraint fk_h_promocion foreign key (id_promocion)
    references m_promociones (id_promocion) on delete cascade
);

create or replace function public.archivar_promocion_anterior()
returns trigger
language plpgsql
as $$
begin
  if (new.modalidad, new.tipo, new.valor, new.base_bloque,
      new.tope_beneficio, new.vigente_desde, new.vigente_hasta)
     is distinct from
     (old.modalidad, old.tipo, old.valor, old.base_bloque,
      old.tope_beneficio, old.vigente_desde, old.vigente_hasta) then
    insert into h_promociones (id_promocion, modalidad, tipo, valor, base_bloque,
                               tope_beneficio, vigente_desde, vigente_hasta)
    values (old.id_promocion, old.modalidad, old.tipo, old.valor, old.base_bloque,
            old.tope_beneficio, old.vigente_desde, old.vigente_hasta);
  end if;
  return new;
end $$;

create trigger trg_promocion_historial
  before update on m_promociones
  for each row execute function archivar_promocion_anterior();

create trigger trg_promociones_updated
  before update on m_promociones
  for each row execute function set_updated_at();


-- ======================= CÁLCULO DEL BENEFICIO ==============================
-- Una sola función resuelve los cinco tipos. La app no calcula nada:
-- pregunta a la base cuánto corresponde y guarda el resultado.

create or replace function public.calcular_beneficio_promocion(
  p_id_promocion bigint,
  p_monto        numeric
)
returns numeric
language plpgsql
stable
as $$
declare
  v_promo     m_promociones%rowtype;
  v_tramo     m_promociones_tramos%rowtype;
  v_beneficio numeric := 0;
begin
  select * into v_promo from m_promociones where id_promocion = p_id_promocion;

  if not found or not v_promo.activo then
    return 0;
  end if;
  if now() not between v_promo.vigente_desde and v_promo.vigente_hasta then
    return 0;
  end if;
  if v_promo.monto_minimo is not null and p_monto < v_promo.monto_minimo then
    return 0;
  end if;

  case v_promo.tipo
    when 'porcentaje' then
      v_beneficio := p_monto * v_promo.valor / 100;

    when 'monto_fijo' then
      v_beneficio := v_promo.valor;

    when 'por_bloques' then
      -- floor: solo cuentan los bloques completos.
      -- S/ 2,900 con bloque de 1,500 -> 1 bloque -> S/ 50
      -- S/ 3,100 con bloque de 1,500 -> 2 bloques -> S/ 100
      v_beneficio := floor(p_monto / v_promo.base_bloque) * v_promo.valor;

    when 'escalonada' then
      select * into v_tramo
      from m_promociones_tramos
      where id_promocion = v_promo.id_promocion
        and p_monto >= monto_desde
        and (monto_hasta is null or p_monto < monto_hasta)
      limit 1;

      if found then
        v_beneficio := case v_tramo.tipo_valor
          when 'porcentaje' then p_monto * v_tramo.valor / 100
          else v_tramo.valor
        end;
      end if;

    else
      -- precio_especial se resuelve línea por línea, no sobre el total
      v_beneficio := 0;
  end case;

  if v_promo.tope_beneficio is not null then
    v_beneficio := least(v_beneficio, v_promo.tope_beneficio);
  end if;

  return round(greatest(v_beneficio, 0), 2);
end $$;

comment on function public.calcular_beneficio_promocion is
  'Cuánto corresponde descontar o devolver por una promoción, dado el monto de la canasta.';


-- ======================= AFILIACIÓN DE FERRETERÍAS ==========================
-- Normalmente la promoción se negocia con la empresa, no local por local.
-- Esta función registra la respuesta para todas las sedes activas de una ferretería.

create or replace function public.afiliar_ferreteria_a_promocion(
  p_id_promocion bigint,
  p_id_ferreteria bigint,
  p_acepta boolean default true,
  p_registrado_por text default null
)
returns integer
language plpgsql
as $$
declare
  v_filas integer;
begin
  insert into rel_promociones_sedes (id_promocion, id_sede, acepta, registrado_por)
  select p_id_promocion, s.id_sede, p_acepta, p_registrado_por
  from m_sedes s
  where s.id_ferreteria = p_id_ferreteria and s.activo
  on conflict (id_promocion, id_sede) do update
    set acepta          = excluded.acepta,
        fecha_respuesta = now(),
        registrado_por  = excluded.registrado_por;

  get diagnostics v_filas = row_count;
  return v_filas;
end $$;

comment on function public.afiliar_ferreteria_a_promocion is
  'Registra la respuesta de una ferretería a una promoción en todas sus sedes activas.';


-- ¿Esta sede participa de esta promoción? Resuelve afiliación y zona.
create or replace function public.sede_participa_en_promocion(
  p_id_promocion bigint,
  p_id_sede      bigint
)
returns boolean
language sql
stable
as $$
  select
    -- 1. Afiliación de la sede
    case
      when p.requiere_afiliacion then coalesce(r.acepta, false)
      else coalesce(r.acepta, true)
    end
    -- 2. Zona: si la promoción no lista zonas, aplica en todas
    and (
      not exists (select 1 from rel_promociones_zonas z where z.id_promocion = p.id_promocion)
      or exists (
        select 1
        from rel_promociones_zonas z
        join m_distritos d on d.id_zona = z.id_zona
        join m_sedes     se on se.id_distrito = d.id_distrito
        where z.id_promocion = p.id_promocion and se.id_sede = p_id_sede
      )
    )
  from m_promociones p
  left join rel_promociones_sedes r
    on r.id_promocion = p.id_promocion and r.id_sede = p_id_sede
  where p.id_promocion = p_id_promocion
$$;


-- ==================== PROMOCIONES APLICABLES A UNA SEDE =====================
-- Lo que consulta el cotizador: dada una sede y el monto de su canasta,
-- qué promociones corresponden y cuánto beneficio dan.

create or replace function public.promociones_aplicables(
  p_id_sede bigint,
  p_monto   numeric
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
  aplicacion     text
)
language sql
stable
as $$
  select
    p.id_promocion,
    p.codigo,
    p.nombre,
    p.modalidad,
    calcular_beneficio_promocion(p.id_promocion, p_monto) as beneficio,
    p.acumulable,
    p.prioridad,
    p.financiado_por,
    p.aplicacion
  from m_promociones p
  where p.activo
    and now() between p.vigente_desde and p.vigente_hasta
    and p.alcance = 'cotizacion'
    and sede_participa_en_promocion(p.id_promocion, p_id_sede)
    and calcular_beneficio_promocion(p.id_promocion, p_monto) > 0
  order by p.prioridad, beneficio desc
$$;

comment on function public.promociones_aplicables is
  'Promociones que aplican a una sede para un monto dado. Ya filtra afiliación, zona y vigencia.';


-- ==================== BENEFICIO FINAL POR SEDE ==============================
-- Resuelve la combinación: suma todas las acumulables y, entre las que no lo
-- son, se queda con la de mayor beneficio.

create or replace function public.beneficio_promocional(
  p_id_sede bigint,
  p_monto   numeric
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
    select * from promociones_aplicables(p_id_sede, p_monto)
  ),
  mejor_no_acumulable as (
    select a.*
    from aplicables a
    where not a.acumulable
    order by a.beneficio desc, a.prioridad
    limit 1
  )
  select a.id_promocion, a.codigo, a.nombre, a.modalidad, a.beneficio,
         a.aplicacion, 'acumulable'::text as elegida_por
  from aplicables a
  where a.acumulable
  union all
  select m.id_promocion, m.codigo, m.nombre, m.modalidad, m.beneficio,
         m.aplicacion, 'mejor beneficio'::text
  from mejor_no_acumulable m
$$;

comment on function public.beneficio_promocional is
  'Promociones finalmente aplicadas a una sede: todas las acumulables más la mejor no acumulable.';


-- ================================ ÍNDICES ===================================

create index idx_promo_tramos_promo    on m_promociones_tramos (id_promocion);
create index idx_promo_skus_sku        on rel_promociones_skus (id_sku);
create index idx_promo_categorias_cat  on rel_promociones_categorias (id_categoria);
create index idx_promo_sedes_sede      on rel_promociones_sedes (id_sede);
create index idx_promo_zonas_zona      on rel_promociones_zonas (id_zona);
create index idx_h_promociones_promo   on h_promociones (id_promocion);

create index idx_promociones_vigentes on m_promociones (vigente_desde, vigente_hasta)
  where activo;


-- ================================ VISTAS ====================================

create or replace view v_promociones_vigentes as
select
  p.id_promocion,
  p.codigo,
  p.nombre,
  p.modalidad,
  p.tipo,
  p.valor,
  p.base_bloque,
  p.alcance,
  p.monto_minimo,
  p.tope_beneficio,
  p.vigente_hasta,
  p.acumulable,
  p.prioridad,
  p.financiado_por,
  p.aplicacion,
  coalesce(
    nullif(array_to_string(array(
      select c.nombre from rel_promociones_categorias rc
      join m_categorias c on c.id_categoria = rc.id_categoria
      where rc.id_promocion = p.id_promocion
    ), ', '), ''),
    'Todos los productos'
  ) as alcance_productos
from m_promociones p
where p.activo
  and now() between p.vigente_desde and p.vigente_hasta;

-- Tramos en texto legible, para mostrarlos al asesor y en el PDF
create or replace view v_promociones_tramos as
select
  t.id_promocion,
  p.codigo,
  t.monto_desde,
  t.monto_hasta,
  t.tipo_valor,
  t.valor,
  'Desde S/ ' || to_char(t.monto_desde, 'FM999,999,990.00') ||
  coalesce(' hasta S/ ' || to_char(t.monto_hasta, 'FM999,999,990.00'), ' a más') || ': ' ||
  case t.tipo_valor
    when 'porcentaje' then trim_scale(t.valor)::text || '%'
    else 'S/ ' || to_char(t.valor, 'FM999,999,990.00')
  end as descripcion
from m_promociones_tramos t
join m_promociones p using (id_promocion)
order by t.id_promocion, t.monto_desde;


-- Control de afiliación: qué respondió cada sede a cada promoción.
create or replace view v_promociones_afiliacion as
select
  p.codigo                        as promocion,
  p.nombre,
  p.requiere_afiliacion,
  f.nombre                        as ferreteria,
  s.codigo                        as sede_codigo,
  s.nombre                        as sede,
  d.nombre                        as distrito,
  case
    when r.id_sede is null and p.requiere_afiliacion then 'Sin respuesta (no participa)'
    when r.id_sede is null                           then 'Sin respuesta (participa)'
    when r.acepta                                    then 'Aceptó'
    else                                                  'Rechazó'
  end                             as estado,
  r.fecha_respuesta
from m_promociones p
cross join m_sedes s
join m_ferreterias f on f.id_ferreteria = s.id_ferreteria
join m_distritos   d on d.id_distrito   = s.id_distrito
left join rel_promociones_sedes r
  on r.id_promocion = p.id_promocion and r.id_sede = s.id_sede
where p.activo and s.activo;

comment on view v_promociones_afiliacion is
  'Tablero de control: estado de cada sede frente a cada promoción vigente.';
