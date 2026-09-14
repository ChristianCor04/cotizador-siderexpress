-- ============================================================================
-- 03 — Catálogo de productos, SKU y precios por sede
-- Requiere: 01_extensiones_utilidades.sql, 02_geografia_ferreterias.sql
-- ============================================================================

-- ============================== CATÁLOGO ====================================

create table m_categorias (
  id_categoria bigint generated always as identity,
  nombre       text not null,

  constraint pk_categorias       primary key (id_categoria),
  constraint uq_categoria_nombre unique (nombre)
);

create table m_marcas (
  id_marca bigint generated always as identity,
  nombre   text not null,
  activo   boolean not null default true,

  constraint pk_marcas       primary key (id_marca),
  constraint uq_marca_nombre unique (nombre)
);

create table m_unidades_medida (
  id_unidad_medida bigint generated always as identity,
  codigo           text not null,
  nombre           text not null,
  activo           boolean not null default true,

  constraint pk_unidades_medida primary key (id_unidad_medida),
  constraint uq_um_codigo       unique (codigo)
);

comment on table m_unidades_medida is
  'Unidad en que se vende el producto: VAR (varilla 9m), BOL (bolsa 42.5kg), KG, M3, UND.';

-- Producto genérico, sin marca. Ej. BC 1/2", PANDERETA.
create table m_productos (
  id_producto  bigint generated always as identity,
  id_categoria bigint not null,
  nombre       text not null,
  activo       boolean not null default true,

  constraint pk_productos        primary key (id_producto),
  constraint uq_producto_nombre  unique (nombre),
  constraint fk_producto_categoria foreign key (id_categoria)
    references m_categorias (id_categoria) on delete restrict
);


-- ================================= SKU ======================================
-- Producto + marca + unidad de medida. Es lo que el cliente realmente compra:
-- no pide "cemento marca PACASMAYO", pide "PACASMAYO EXTRAFORTE bolsa 42.5 kg".
-- Reemplaza a marca_categoria: aquí solo existen combinaciones válidas.

create table m_skus (
  id_sku           bigint generated always as identity,
  id_producto      bigint not null,
  id_marca         bigint not null,
  id_unidad_medida bigint not null,
  codigo           text,
  peso_kg          numeric(10,3),
  activo           boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  constraint pk_skus        primary key (id_sku),
  constraint uq_sku_codigo  unique (codigo),
  -- La combinación no se puede repetir: un solo SKU por producto-marca-unidad
  constraint uq_sku_combinacion unique (id_producto, id_marca, id_unidad_medida),
  constraint fk_sku_producto foreign key (id_producto)
    references m_productos (id_producto) on delete restrict,
  constraint fk_sku_marca    foreign key (id_marca)
    references m_marcas (id_marca) on delete restrict,
  constraint fk_sku_unidad   foreign key (id_unidad_medida)
    references m_unidades_medida (id_unidad_medida) on delete restrict,
  constraint chk_sku_peso    check (peso_kg is null or peso_kg > 0)
);

comment on column m_skus.peso_kg is
  'Peso por unidad de venta. Alimenta el cálculo de toneladas. '
  'Vacío para productos a granel (arena, piedra), que no suman toneladas.';


-- =============================== PRECIOS ====================================
-- Precio vigente por sede y SKU. Una fila por combinación: el precio anterior
-- se archiva solo en h_precios mediante trigger.

create table m_precios (
  id_precio           bigint generated always as identity,
  id_sede             bigint not null,
  id_sku              bigint not null,
  precio              numeric(12,4) not null,
  fecha_actualizacion timestamptz not null default now(),
  fuente              text,
  activo              boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  constraint pk_precios       primary key (id_precio),
  -- Evita el problema clásico: dos precios distintos del mismo producto en la misma sede
  constraint uq_precio_sede_sku unique (id_sede, id_sku),
  constraint fk_precio_sede   foreign key (id_sede)
    references m_sedes (id_sede) on delete restrict,
  constraint fk_precio_sku    foreign key (id_sku)
    references m_skus (id_sku) on delete restrict,
  constraint chk_precio_valor check (precio > 0),
  constraint chk_precio_fuente check (
    fuente is null or fuente in ('relevamiento', 'ferreteria', 'asesor')
  )
);

comment on column m_precios.fecha_actualizacion is
  'Cuándo cambió el precio por última vez. Permite avisar si está desactualizado.';


-- Historial. No se escribe a mano: lo llena el trigger de abajo.
create table h_precios (
  id_h_precio   bigint generated always as identity,
  id_precio     bigint not null,
  id_sede       bigint not null,
  id_sku        bigint not null,
  precio        numeric(12,4) not null,
  vigente_desde timestamptz not null,
  vigente_hasta timestamptz not null,
  created_at    timestamptz not null default now(),

  constraint pk_h_precios     primary key (id_h_precio),
  constraint fk_h_precio      foreign key (id_precio)
    references m_precios (id_precio) on delete cascade,
  constraint fk_h_precio_sede foreign key (id_sede)
    references m_sedes (id_sede) on delete restrict,
  constraint fk_h_precio_sku  foreign key (id_sku)
    references m_skus (id_sku) on delete restrict,
  constraint chk_h_precio_valor check (precio > 0),
  constraint chk_h_precio_rango check (vigente_hasta > vigente_desde),
  -- Impide que dos vigencias del mismo precio se crucen en el tiempo.
  -- "=" compara sede y sku; "&&" detecta rangos de fecha traslapados.
  constraint excl_h_precio_traslape exclude using gist (
    id_sede with =,
    id_sku  with =,
    tstzrange(vigente_desde, vigente_hasta) with &&
  )
);


-- =============================== TRIGGERS ===================================

-- Archiva el precio anterior cada vez que cambia. Nadie tiene que acordarse:
-- da igual si el cambio vino de la app, de un script o del SQL Editor.
create or replace function public.archivar_precio_anterior()
returns trigger
language plpgsql
as $$
begin
  if new.precio is distinct from old.precio then
    insert into h_precios (id_precio, id_sede, id_sku, precio, vigente_desde, vigente_hasta)
    values (old.id_precio, old.id_sede, old.id_sku, old.precio,
            old.fecha_actualizacion, now());
    new.fecha_actualizacion := now();
  end if;
  return new;
end $$;

comment on function public.archivar_precio_anterior is
  'Trigger BEFORE UPDATE en m_precios: copia el precio anterior a h_precios.';

create trigger trg_precio_historial
  before update on m_precios
  for each row execute function archivar_precio_anterior();

create trigger trg_skus_updated
  before update on m_skus
  for each row execute function set_updated_at();

create trigger trg_precios_updated
  before update on m_precios
  for each row execute function set_updated_at();


-- ================================ ÍNDICES ===================================
create index idx_productos_categoria on m_productos (id_categoria);
create index idx_skus_producto       on m_skus (id_producto);
create index idx_skus_marca          on m_skus (id_marca);
create index idx_skus_unidad         on m_skus (id_unidad_medida);
create index idx_precios_sede        on m_precios (id_sede);
create index idx_h_precios_precio    on h_precios (id_precio);

-- El índice más importante del proyecto: cotizar_canasta busca, para cada SKU,
-- el precio en varias sedes. Sin esto lee la tabla completa en cada consulta.
create index idx_precios_sku_activo on m_precios (id_sku, id_sede)
  where activo;


-- ================================ VISTA =====================================
-- Reemplaza a la tabla de precios referenciales: se calcula sola, así que
-- nunca le falta un producto ni se desactualiza.
create or replace view v_precios_referenciales as
select
  p.id_producto,
  p.nombre                          as producto,
  round(avg(pr.precio), 2)          as precio_promedio,
  min(pr.precio)                    as precio_min,
  max(pr.precio)                    as precio_max,
  count(distinct pr.id_sede)        as n_sedes
from m_precios pr
join m_skus     s using (id_sku)
join m_productos p using (id_producto)
where pr.activo and s.activo and p.activo
group by p.id_producto, p.nombre;

comment on view v_precios_referenciales is
  'Precio promedio por producto. Lo usa monto_canasta para decidir el radio de búsqueda.';
