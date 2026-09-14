-- ============================================================================
-- 02 — Geografía, ferreterías y sedes
-- Requiere: 01_extensiones_utilidades.sql
-- ============================================================================

-- ============================ GEOGRAFÍA =====================================
-- Jerarquía: departamento > provincia > distrito.
-- El ubigeo es el código oficial del INEI; permite cruzar con fuentes externas
-- sin depender de cómo esté escrito el nombre.

create table m_departamentos (
  id_departamento bigint generated always as identity,
  ubigeo          text not null,
  nombre          text not null,

  constraint pk_departamentos     primary key (id_departamento),
  constraint uq_departamento_ubigeo unique (ubigeo),
  constraint chk_departamento_ubigeo check (ubigeo ~ '^[0-9]{2}$')
);

create table m_provincias (
  id_provincia    bigint generated always as identity,
  id_departamento bigint not null,
  ubigeo          text not null,
  nombre          text not null,

  constraint pk_provincias        primary key (id_provincia),
  constraint uq_provincia_ubigeo  unique (ubigeo),
  constraint fk_provincia_depto   foreign key (id_departamento)
    references m_departamentos (id_departamento) on delete restrict,
  constraint chk_provincia_ubigeo check (ubigeo ~ '^[0-9]{4}$')
);

-- Zona = plaza comercial donde opera un equipo de asesores.
-- Es lo que determina qué ve cada supervisor.
create table m_zonas (
  id_zona bigint generated always as identity,
  nombre  text not null,
  activo  boolean not null default true,

  constraint pk_zonas       primary key (id_zona),
  constraint uq_zona_nombre unique (nombre)
);

create table m_distritos (
  id_distrito    bigint generated always as identity,
  id_provincia   bigint not null,
  id_zona        bigint,
  ubigeo         text not null,
  nombre         text not null,
  con_cobertura  boolean not null default false,

  constraint pk_distritos         primary key (id_distrito),
  constraint uq_distrito_ubigeo   unique (ubigeo),
  constraint fk_distrito_provincia foreign key (id_provincia)
    references m_provincias (id_provincia) on delete restrict,
  -- set null: si se elimina una zona comercial, el distrito sobrevive sin zona
  constraint fk_distrito_zona     foreign key (id_zona)
    references m_zonas (id_zona) on delete set null,
  constraint chk_distrito_ubigeo  check (ubigeo ~ '^[0-9]{6}$')
);

comment on column m_distritos.con_cobertura is
  'True si SIDEREXPRESS atiende el distrito. Lo usa la lista desplegable del bot.';


-- ========================= FERRETERÍAS Y SEDES ==============================
-- La ferretería es la empresa; la sede es el local físico.
-- Precios y ubicación viven en la sede, no en la ferretería.

create table m_ferreterias (
  id_ferreteria   bigint generated always as identity,
  codigo_asociado text,
  nombre          text not null,
  ruc             text,
  activo          boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint pk_ferreterias      primary key (id_ferreteria),
  constraint uq_ferreteria_codigo unique (codigo_asociado),
  constraint uq_ferreteria_ruc   unique (ruc),
  constraint chk_ferreteria_ruc  check (ruc is null or ruc ~ '^[0-9]{11}$')
);

comment on table m_ferreterias is
  'Empresa ferretera afiliada. No se borra: se marca activo = false.';

create table m_sedes (
  id_sede       bigint generated always as identity,
  id_ferreteria bigint not null,
  codigo        text not null,
  nombre        text not null,
  id_distrito   bigint not null,
  direccion     text,
  latitud       double precision,
  longitud      double precision,
  encargado     text,
  telefono      telefono_pe,
  activo        boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint pk_sedes            primary key (id_sede),
  constraint uq_sede_codigo      unique (codigo),
  constraint fk_sede_ferreteria  foreign key (id_ferreteria)
    references m_ferreterias (id_ferreteria) on delete restrict,
  constraint fk_sede_distrito    foreign key (id_distrito)
    references m_distritos (id_distrito) on delete restrict,
  constraint chk_sede_latitud    check (latitud  between  -90 and  90),
  constraint chk_sede_longitud   check (longitud between -180 and 180),
  -- O tiene las dos coordenadas o no tiene ninguna: una sola no sirve para nada
  constraint chk_sede_coords     check (
    (latitud is null and longitud is null) or
    (latitud is not null and longitud is not null)
  )
);

comment on column m_sedes.codigo is
  'Código del relevamiento, ej. TRUJ001. Llave para cargar precios sin depender de nombres.';


-- ============================ TIPOS DE PAGO =================================

create table m_tipos_pago (
  id_tipo_pago bigint generated always as identity,
  nombre       text not null,
  activo       boolean not null default true,

  constraint pk_tipos_pago       primary key (id_tipo_pago),
  constraint uq_tipo_pago_nombre unique (nombre)
);

-- Qué medios de pago acepta cada sede.
-- Sirve para no ofrecer una sede que no acepta el pago que quiere el cliente,
-- uno de los motivos de fuga que ya tienes identificados.
create table rel_sedes_tipos_pago (
  id_sede      bigint not null,
  id_tipo_pago bigint not null,

  constraint pk_sedes_tipos_pago primary key (id_sede, id_tipo_pago),
  constraint fk_stp_sede         foreign key (id_sede)
    references m_sedes (id_sede) on delete cascade,
  constraint fk_stp_tipo_pago    foreign key (id_tipo_pago)
    references m_tipos_pago (id_tipo_pago) on delete restrict
);


-- ================================ ÍNDICES ===================================
-- PostgreSQL NO crea índices en las columnas FK automáticamente; hay que hacerlo.
create index idx_provincias_depto   on m_provincias (id_departamento);
create index idx_distritos_provincia on m_distritos (id_provincia);
create index idx_distritos_zona     on m_distritos (id_zona);
create index idx_sedes_ferreteria   on m_sedes (id_ferreteria);
create index idx_sedes_distrito     on m_sedes (id_distrito);
create index idx_stp_tipo_pago      on rel_sedes_tipos_pago (id_tipo_pago);

-- Índice parcial: solo indexa las sedes activas con coordenadas, que son las
-- únicas que participan en la búsqueda por distancia.
create index idx_sedes_activas_geo on m_sedes (id_distrito)
  where activo and latitud is not null;


-- =============================== TRIGGERS ===================================
create trigger trg_ferreterias_updated
  before update on m_ferreterias
  for each row execute function set_updated_at();

create trigger trg_sedes_updated
  before update on m_sedes
  for each row execute function set_updated_at();
