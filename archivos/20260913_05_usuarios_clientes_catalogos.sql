-- ============================================================================
-- 05 — Usuarios, clientes y catálogos comerciales
-- Requiere: 01, 02, 03, 04
-- ============================================================================

-- ============================== USUARIOS ====================================
-- Se apoya en auth.users de Supabase: ahí viven el correo y la contraseña.
-- Esta tabla agrega lo que el negocio necesita: rol y zona.

create table m_usuarios (
  id_usuario uuid not null,
  nombre     text not null,
  email      text not null,
  rol        text not null,
  empresa    text,
  id_zona    bigint,
  activo     boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint pk_usuarios     primary key (id_usuario),
  constraint fk_usuario_auth foreign key (id_usuario)
    references auth.users (id) on delete cascade,
  constraint uq_usuario_email unique (email),
  constraint fk_usuario_zona foreign key (id_zona)
    references m_zonas (id_zona) on delete set null,
  constraint chk_usuario_rol check (rol in ('asesor', 'supervisor', 'master')),
  -- Un asesor o supervisor siempre pertenece a una zona; el master ve todo
  constraint chk_usuario_zona check (rol = 'master' or id_zona is not null)
);

comment on table m_usuarios is
  'Perfil de los asesores. Base de las políticas RLS: define qué puede ver cada uno.';
comment on column m_usuarios.empresa is
  'Empresa tercera a la que pertenece el asesor. Null si es personal propio.';


-- Rol del usuario autenticado. La usan las políticas RLS.
-- security definer: consulta m_usuarios saltándose su propio RLS; si no,
-- la política que la llama entraría en un bucle infinito.
create or replace function public.rol_actual()
returns text
language sql
stable
security definer
set search_path = public
as $$
  select rol from m_usuarios where id_usuario = auth.uid() and activo
$$;

create or replace function public.zona_actual()
returns bigint
language sql
stable
security definer
set search_path = public
as $$
  select id_zona from m_usuarios where id_usuario = auth.uid() and activo
$$;


-- =============================== CLIENTES ===================================

create table m_clientes (
  id_cliente          bigint generated always as identity,
  telefono            telefono_pe not null,
  nombre              text,
  apellido            text,
  tipo_documento      text,
  numero_documento    text,
  tipo_cliente        text,
  es_contratista      boolean not null default false,
  id_distrito_origen  bigint,
  fuente_origen       text,
  fecha_llegada       timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  constraint pk_clientes        primary key (id_cliente),
  -- El teléfono es la llave real del negocio: por ahí entra al bot
  constraint uq_cliente_telefono unique (telefono),
  constraint uq_cliente_documento unique (tipo_documento, numero_documento),
  constraint fk_cliente_distrito foreign key (id_distrito_origen)
    references m_distritos (id_distrito) on delete set null,
  constraint chk_cliente_tipo_doc check (
    tipo_documento is null or tipo_documento in ('DNI', 'RUC', 'CE', 'PASAPORTE')
  ),
  -- Si hay tipo de documento tiene que haber número, y al revés
  constraint chk_cliente_documento check (
    (tipo_documento is null and numero_documento is null) or
    (tipo_documento is not null and numero_documento is not null)
  ),
  constraint chk_cliente_dni check (
    tipo_documento <> 'DNI' or numero_documento ~ '^[0-9]{8}$'
  ),
  constraint chk_cliente_ruc check (
    tipo_documento <> 'RUC' or numero_documento ~ '^[0-9]{11}$'
  )
);

comment on column m_clientes.es_contratista is
  'Contratistas y constructoras: compran más, repiten y pueden tener obras en varias zonas.';

-- Datos crudos del CRM, separados de los validados.
-- Así el CRM puede sobrescribir sin pisar lo que el asesor corrigió a mano.
create table m_clientes_crm (
  id_cliente           bigint not null,
  telefono_crm         text,
  nombre_crm           text,
  apellido_crm         text,
  fecha_sincronizacion timestamptz,

  constraint pk_clientes_crm primary key (id_cliente),
  constraint fk_cliente_crm  foreign key (id_cliente)
    references m_clientes (id_cliente) on delete cascade
);


-- ======================== CATÁLOGOS COMERCIALES =============================

create table m_motivos_perdida (
  id_motivo_perdida bigint generated always as identity,
  etapa             text not null,
  nombre            text not null,
  automatico        boolean not null default false,
  activo            boolean not null default true,

  constraint pk_motivos_perdida primary key (id_motivo_perdida),
  constraint uq_motivo_nombre   unique (nombre),
  constraint chk_motivo_etapa   check (etapa in ('bot', 'asesor', 'cotizado'))
);

comment on column m_motivos_perdida.automatico is
  'true si lo pone el sistema al cerrar por inactividad. Permite separar '
  'las pérdidas reales de las que son falta de seguimiento.';


-- ======================= PARÁMETROS DEL NEGOCIO =============================
-- Valores que cambian sin necesidad de tocar código ni desplegar nada.

create table m_parametros (
  clave       text not null,
  valor       text not null,
  descripcion text,
  updated_at  timestamptz not null default now(),

  constraint pk_parametros primary key (clave)
);

insert into m_parametros (clave, valor, descripcion) values
  ('dias_vigencia_cotizacion', '1',
   'Días que vale una cotización por defecto. El asesor puede cambiarlo por cotización.'),
  ('dias_para_cerrar_negociacion', '7',
   'Días tras vencer la cotización antes de cerrar la negociación automáticamente.'),
  ('top_n_sedes', '5',
   'Cuántas sedes cercanas se evalúan al cotizar.');


-- ====================== REGLAS DE COTIZACIÓN ================================
-- Los umbrales de tu lógica 1.x y 2.x, en tabla en vez de en el código.

create table m_reglas_cotizacion (
  id_regla        bigint generated always as identity,
  codigo          text not null,
  usa_coordenadas boolean not null,
  monto_desde     numeric(14,2) not null,
  monto_hasta     numeric(14,2),
  alcance         text not null,
  radio_km        numeric(8,2),
  activo          boolean not null default true,

  constraint pk_reglas_cotizacion primary key (id_regla),
  constraint uq_regla_codigo      unique (codigo),
  constraint chk_regla_alcance    check (alcance in ('radio', 'distrito', 'provincia')),
  constraint chk_regla_rango      check (
    monto_desde >= 0 and (monto_hasta is null or monto_hasta > monto_desde)
  ),
  -- Si el alcance es por radio, el radio es obligatorio
  constraint chk_regla_radio check (
    (alcance = 'radio' and radio_km is not null and radio_km > 0) or
    (alcance <> 'radio' and radio_km is null)
  ),
  -- Dos reglas del mismo tipo no pueden cubrir el mismo monto
  constraint excl_reglas_traslape exclude using gist (
    usa_coordenadas with =,
    numrange(monto_desde, monto_hasta, '[)') with &&
  )
);

insert into m_reglas_cotizacion (codigo, usa_coordenadas, monto_desde, monto_hasta, alcance, radio_km) values
  ('1.1', true,      0,  5000, 'radio',       2),
  ('1.2', true,   5000, 10000, 'radio',       4),
  ('1.3', true,  10000,  null, 'radio',     100),
  ('2.1', false,     0,  5000, 'distrito',  null),
  ('2.2', false,  5000,  null, 'provincia', null);


-- =============================== TRIGGERS ===================================
create trigger trg_usuarios_updated
  before update on m_usuarios
  for each row execute function set_updated_at();

create trigger trg_clientes_updated
  before update on m_clientes
  for each row execute function set_updated_at();

create trigger trg_parametros_updated
  before update on m_parametros
  for each row execute function set_updated_at();


-- ================================ ÍNDICES ===================================
create index idx_usuarios_zona      on m_usuarios (id_zona) where activo;
create index idx_clientes_documento on m_clientes (numero_documento);
create index idx_clientes_distrito  on m_clientes (id_distrito_origen);
create index idx_clientes_contratista on m_clientes (id_cliente) where es_contratista;


-- ================================ FUNCIÓN ===================================
-- Devuelve un parámetro como número. Evita repetir el cast en cada consulta.
create or replace function public.parametro_num(p_clave text)
returns numeric
language sql
stable
as $$
  select valor::numeric from m_parametros where clave = p_clave
$$;
