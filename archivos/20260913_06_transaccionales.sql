-- ============================================================================
-- 06 — Negociaciones, cotizaciones y ventas
-- Requiere: 01, 02, 03, 04, 05
--
-- Solo tablas, restricciones e índices. Los triggers de negocio van en el 07.
-- ============================================================================

-- ============================ NEGOCIACIONES =================================
-- Una negociación = un pedido. Agrupa todas las versiones de cotización
-- y las ventas que salgan de ese pedido.

create table fact_negociaciones (
  id_negociacion    bigint generated always as identity,
  id_cliente        bigint not null,
  id_usuario        uuid,
  id_zona           bigint,
  id_distrito       bigint,
  distrito_texto    text,
  referencia_obra   text,
  fuente_origen     text,
  estado            text not null default 'abierta',
  id_motivo_perdida bigint,
  fecha_inicio      timestamptz not null default now(),
  fecha_cierre      timestamptz,
  observaciones     text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  constraint pk_negociaciones primary key (id_negociacion),
  constraint fk_neg_cliente foreign key (id_cliente)
    references m_clientes (id_cliente) on delete restrict,
  constraint fk_neg_usuario foreign key (id_usuario)
    references m_usuarios (id_usuario) on delete set null,
  constraint fk_neg_zona foreign key (id_zona)
    references m_zonas (id_zona) on delete set null,
  constraint fk_neg_distrito foreign key (id_distrito)
    references m_distritos (id_distrito) on delete set null,
  constraint fk_neg_motivo foreign key (id_motivo_perdida)
    references m_motivos_perdida (id_motivo_perdida) on delete restrict,

  -- por_cerrar: la cotización venció y espera que el asesor ponga el motivo
  constraint chk_neg_estado check (
    estado in ('abierta', 'por_cerrar', 'ganada', 'perdida')
  ),
  -- Una negociación perdida siempre tiene motivo
  constraint chk_neg_motivo check (
    estado <> 'perdida' or id_motivo_perdida is not null
  ),
  -- La fecha de cierre solo existe si está cerrada
  constraint chk_neg_cierre check (
    (estado in ('ganada', 'perdida') and fecha_cierre is not null) or
    (estado in ('abierta', 'por_cerrar') and fecha_cierre is null)
  )
);

comment on table fact_negociaciones is
  'Un pedido del cliente. Si vuelve por otra obra o etapa, es otra negociación.';
comment on column fact_negociaciones.distrito_texto is
  'Lo que escribió el cliente cuando eligió "Otro" en el bot.';
comment on column fact_negociaciones.referencia_obra is
  'Opcional. Permite agrupar después las compras de una misma obra.';


-- Tickets del CRM. El bot cierra el ticket a las 2 horas, así que una misma
-- negociación puede tener varios si el cliente vuelve después.
create table rel_negociacion_tickets (
  id_negociacion bigint not null,
  ticket         text not null,
  fecha_ticket   timestamptz,
  tipo           text not null default 'seguimiento',

  constraint pk_negociacion_tickets primary key (id_negociacion, ticket),
  constraint fk_nt_negociacion foreign key (id_negociacion)
    references fact_negociaciones (id_negociacion) on delete cascade,
  constraint chk_nt_tipo check (tipo in ('origen', 'seguimiento', 'cierre'))
);


-- ============================= COTIZACIONES =================================
-- Se registra al ENVIARLA al cliente, no al explorar ferreterías en pantalla.

create table fact_cotizaciones (
  id_cotizacion     bigint generated always as identity,
  id_negociacion    bigint not null,
  version           smallint not null,
  id_usuario        uuid,
  ticket            text,

  fecha             timestamptz not null default now(),
  fecha_vencimiento timestamptz,

  -- Dónde está la obra (puede corregirse entre versiones)
  latitud           double precision,
  longitud          double precision,
  id_distrito       bigint,

  -- Cómo se eligieron las ferreterías
  id_regla          bigint,
  monto_referencial numeric(14,2),
  distancia_km      numeric(8,2),

  -- Ferretería elegida
  id_sede           bigint not null,
  id_tipo_pago      bigint,

  -- Montos. Los recalcula el trigger del archivo 07 a partir del detalle.
  monto_bruto_sol   numeric(14,2) not null default 0,
  monto_descuento   numeric(14,2) not null default 0,
  monto_total_sol   numeric(14,2) not null default 0,
  monto_devolucion  numeric(14,2) not null default 0,
  tipo_cambio       numeric(8,4),
  monto_total_dol   numeric(14,2),
  toneladas         numeric(12,3) not null default 0,

  estado            text not null default 'enviada',
  url_pdf           text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  constraint pk_cotizaciones primary key (id_cotizacion),
  constraint uq_cotizacion_version unique (id_negociacion, version),
  constraint fk_cot_negociacion foreign key (id_negociacion)
    references fact_negociaciones (id_negociacion) on delete cascade,
  constraint fk_cot_usuario foreign key (id_usuario)
    references m_usuarios (id_usuario) on delete set null,
  constraint fk_cot_distrito foreign key (id_distrito)
    references m_distritos (id_distrito) on delete set null,
  constraint fk_cot_regla foreign key (id_regla)
    references m_reglas_cotizacion (id_regla) on delete set null,
  constraint fk_cot_sede foreign key (id_sede)
    references m_sedes (id_sede) on delete restrict,
  constraint fk_cot_tipo_pago foreign key (id_tipo_pago)
    references m_tipos_pago (id_tipo_pago) on delete restrict,

  constraint chk_cot_version check (version > 0),
  constraint chk_cot_estado check (
    estado in ('enviada', 'reemplazada', 'aceptada', 'rechazada', 'vencida')
  ),
  constraint chk_cot_montos check (
    monto_bruto_sol >= 0 and monto_descuento >= 0 and
    monto_total_sol >= 0 and monto_devolucion >= 0 and toneladas >= 0
  ),
  constraint chk_cot_vencimiento check (
    fecha_vencimiento is null or fecha_vencimiento > fecha
  ),
  constraint chk_cot_coords check (
    (latitud is null and longitud is null) or
    (latitud is not null and longitud is not null)
  ),
  constraint chk_cot_latitud  check (latitud  between  -90 and  90),
  constraint chk_cot_longitud check (longitud between -180 and 180),
  -- Si hay monto en dólares tiene que haber tipo de cambio
  constraint chk_cot_dolares check (
    monto_total_dol is null or tipo_cambio is not null
  )
);

comment on column fact_cotizaciones.monto_devolucion is
  'Beneficios de modalidad devolución. NO se resta del total: el cliente paga completo.';
comment on column fact_cotizaciones.id_regla is
  'Qué regla decidió el radio de búsqueda. Permite auditar por qué salió esa ferretería.';

-- Solo puede haber UNA cotización aceptada por negociación.
-- Un índice único parcial impone la regla sin bloquear las demás versiones.
create unique index uq_cot_una_aceptada
  on fact_cotizaciones (id_negociacion)
  where estado = 'aceptada';


-- --------------------------------------------------------------- detalle ---
create table fact_cotizaciones_detalle (
  id_cotizacion_detalle bigint generated always as identity,
  id_cotizacion         bigint not null,
  id_sku                bigint not null,
  cantidad              numeric(12,2) not null,

  -- Precio de m_precios al momento de cotizar. No cambia después.
  precio_unitario       numeric(12,4) not null,

  -- Precio negociado con la ferretería para este caso puntual.
  -- Si existe, es el que se cobra.
  precio_modificado     numeric(12,4),
  motivo_modificacion   text,
  autorizado_por        text,

  -- Descuento de una promoción con alcance = producto
  descuento_unitario    numeric(12,4),
  id_promocion          bigint,

  subtotal numeric(14,2) generated always as (
    round(
      cantidad * (coalesce(precio_modificado, precio_unitario)
                  - coalesce(descuento_unitario, 0)),
      2)
  ) stored,

  id_precio             bigint,

  constraint pk_cotizaciones_detalle primary key (id_cotizacion_detalle),
  constraint uq_cot_detalle_sku unique (id_cotizacion, id_sku),
  constraint fk_cd_cotizacion foreign key (id_cotizacion)
    references fact_cotizaciones (id_cotizacion) on delete cascade,
  constraint fk_cd_sku foreign key (id_sku)
    references m_skus (id_sku) on delete restrict,
  constraint fk_cd_promocion foreign key (id_promocion)
    references m_promociones (id_promocion) on delete restrict,
  constraint fk_cd_precio foreign key (id_precio)
    references m_precios (id_precio) on delete set null,

  constraint chk_cd_cantidad check (cantidad > 0),
  constraint chk_cd_precio   check (precio_unitario > 0),
  -- Un precio negociado siempre tiene que estar justificado
  constraint chk_cd_modificado check (
    precio_modificado is null or
    (precio_modificado > 0 and motivo_modificacion is not null)
  ),
  constraint chk_cd_descuento check (
    descuento_unitario is null or
    (descuento_unitario > 0 and id_promocion is not null)
  )
);

comment on column fact_cotizaciones_detalle.precio_modificado is
  'Precio acordado con la ferretería para esta cotización (ej. rebaja del fierro). '
  'Reemplaza al precio de lista en el subtotal.';
comment on column fact_cotizaciones_detalle.autorizado_por is
  'Quién en la ferretería autorizó el precio negociado.';
comment on column fact_cotizaciones_detalle.id_precio is
  'Solo trazabilidad: apunta al precio de lista usado. El monto cobrado está congelado arriba.';


-- ------------------------------------------------- ferreterías evaluadas ---
-- Todas las sedes que compitieron, no solo la elegida.
-- Es la base para analizar competencia y cobertura.
create table fact_cotizaciones_ferreterias (
  id_cotizacion    bigint not null,
  id_sede          bigint not null,
  distancia_km     numeric(8,2),
  canasta_completa boolean not null,
  monto_canasta    numeric(14,2),
  beneficio_promo  numeric(14,2) not null default 0,
  ranking          smallint,
  elegida          boolean not null default false,

  constraint pk_cot_ferreterias primary key (id_cotizacion, id_sede),
  constraint fk_cf_cotizacion foreign key (id_cotizacion)
    references fact_cotizaciones (id_cotizacion) on delete cascade,
  constraint fk_cf_sede foreign key (id_sede)
    references m_sedes (id_sede) on delete restrict,
  -- Si no tiene la canasta completa no hay monto que comparar
  constraint chk_cf_monto check (
    (canasta_completa and monto_canasta is not null) or not canasta_completa
  )
);


-- ----------------------------------------------- promociones aplicadas -----
-- Se guarda aunque el asesor no la aplique: saber que estaba disponible
-- y no se usó es información de negocio.
create table fact_cotizaciones_promociones (
  id_cotizacion      bigint not null,
  id_promocion       bigint not null,

  -- Copia congelada de la promoción al momento de cotizar
  modalidad          text not null,
  tipo               text not null,
  valor              numeric(12,4),
  monto_beneficio    numeric(14,2) not null,
  id_tramo           bigint,
  financiado_por     text not null,

  -- Decisión del asesor
  aplicada           boolean not null default true,
  motivo_no_aplicada text,
  decidida_por       uuid,

  constraint pk_cot_promociones primary key (id_cotizacion, id_promocion),
  constraint fk_cp_cotizacion foreign key (id_cotizacion)
    references fact_cotizaciones (id_cotizacion) on delete cascade,
  constraint fk_cp_promocion foreign key (id_promocion)
    references m_promociones (id_promocion) on delete restrict,
  constraint fk_cp_tramo foreign key (id_tramo)
    references m_promociones_tramos (id_tramo) on delete set null,
  constraint fk_cp_usuario foreign key (decidida_por)
    references m_usuarios (id_usuario) on delete set null,
  constraint chk_cp_beneficio check (monto_beneficio >= 0),
  constraint chk_cp_modalidad check (modalidad in ('descuento', 'devolucion')),
  constraint chk_cp_motivo check (aplicada or motivo_no_aplicada is not null)
);


-- ================================ VENTAS ====================================
-- Nace de una cotización aceptada. Tabla aparte porque tiene datos propios:
-- comprobante, pago real y validación.

create table fact_ventas (
  id_venta             bigint generated always as identity,
  id_negociacion       bigint not null,
  id_cotizacion        bigint not null,
  id_sede              bigint not null,
  id_usuario           uuid,
  ticket               text,
  fecha_venta          timestamptz not null default now(),
  id_tipo_pago         bigint not null,

  monto_bruto_sol      numeric(14,2) not null default 0,
  monto_descuento      numeric(14,2) not null default 0,
  monto_total_sol      numeric(14,2) not null default 0,
  monto_devolucion     numeric(14,2) not null default 0,
  tipo_cambio          numeric(8,4),
  monto_total_dol      numeric(14,2),
  toneladas            numeric(12,3) not null default 0,

  url_comprobante_pago text,
  tipo_comprobante     text,
  numero_comprobante   text,

  estado               text not null default 'pendiente_validacion',
  validado_por         uuid,
  fecha_validacion     timestamptz,
  motivo_anulacion     text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),

  constraint pk_ventas primary key (id_venta),
  constraint fk_ven_negociacion foreign key (id_negociacion)
    references fact_negociaciones (id_negociacion) on delete restrict,
  constraint fk_ven_cotizacion foreign key (id_cotizacion)
    references fact_cotizaciones (id_cotizacion) on delete restrict,
  constraint fk_ven_sede foreign key (id_sede)
    references m_sedes (id_sede) on delete restrict,
  constraint fk_ven_usuario foreign key (id_usuario)
    references m_usuarios (id_usuario) on delete set null,
  constraint fk_ven_tipo_pago foreign key (id_tipo_pago)
    references m_tipos_pago (id_tipo_pago) on delete restrict,
  constraint fk_ven_validador foreign key (validado_por)
    references m_usuarios (id_usuario) on delete set null,

  constraint chk_ven_estado check (
    estado in ('pendiente_validacion', 'validada', 'anulada')
  ),
  constraint chk_ven_montos check (
    monto_bruto_sol >= 0 and monto_descuento >= 0 and
    monto_total_sol >= 0 and monto_devolucion >= 0 and toneladas >= 0
  ),
  constraint chk_ven_comprobante check (
    tipo_comprobante is null or tipo_comprobante in ('boleta', 'factura')
  ),
  constraint chk_ven_anulacion check (
    estado <> 'anulada' or motivo_anulacion is not null
  ),
  constraint chk_ven_validacion check (
    estado <> 'validada' or (validado_por is not null and fecha_validacion is not null)
  ),
  constraint chk_ven_dolares check (
    monto_total_dol is null or tipo_cambio is not null
  )
);

comment on table fact_ventas is
  'Compra real. Una negociación puede tener varias ventas (pagos o despachos parciales).';


create table fact_ventas_detalle (
  id_venta_detalle      bigint generated always as identity,
  id_venta              bigint not null,
  id_sku                bigint not null,
  cantidad              numeric(12,2) not null,
  precio_unitario       numeric(12,4) not null,
  descuento_unitario    numeric(12,4),
  id_promocion          bigint,

  subtotal numeric(14,2) generated always as (
    round(cantidad * (precio_unitario - coalesce(descuento_unitario, 0)), 2)
  ) stored,

  -- De qué línea cotizada viene. Null si el cliente lo agregó en tienda.
  id_cotizacion_detalle bigint,

  constraint pk_ventas_detalle primary key (id_venta_detalle),
  constraint uq_venta_detalle_sku unique (id_venta, id_sku),
  constraint fk_vd_venta foreign key (id_venta)
    references fact_ventas (id_venta) on delete cascade,
  constraint fk_vd_sku foreign key (id_sku)
    references m_skus (id_sku) on delete restrict,
  constraint fk_vd_promocion foreign key (id_promocion)
    references m_promociones (id_promocion) on delete restrict,
  constraint fk_vd_cotizacion_detalle foreign key (id_cotizacion_detalle)
    references fact_cotizaciones_detalle (id_cotizacion_detalle) on delete set null,
  constraint chk_vd_cantidad check (cantidad > 0),
  constraint chk_vd_precio   check (precio_unitario > 0)
);


create table fact_ventas_promociones (
  id_venta           bigint not null,
  id_promocion       bigint not null,
  modalidad          text not null,
  tipo               text not null,
  valor              numeric(12,4),
  monto_beneficio    numeric(14,2) not null,
  id_tramo           bigint,
  financiado_por     text not null,
  aplicada           boolean not null default true,
  motivo_no_aplicada text,
  decidida_por       uuid,

  constraint pk_venta_promociones primary key (id_venta, id_promocion),
  constraint fk_vp_venta foreign key (id_venta)
    references fact_ventas (id_venta) on delete cascade,
  constraint fk_vp_promocion foreign key (id_promocion)
    references m_promociones (id_promocion) on delete restrict,
  constraint fk_vp_tramo foreign key (id_tramo)
    references m_promociones_tramos (id_tramo) on delete set null,
  constraint fk_vp_usuario foreign key (decidida_por)
    references m_usuarios (id_usuario) on delete set null,
  constraint chk_vp_beneficio check (monto_beneficio >= 0),
  constraint chk_vp_modalidad check (modalidad in ('descuento', 'devolucion')),
  constraint chk_vp_motivo check (aplicada or motivo_no_aplicada is not null)
);


-- ================================ ÍNDICES ===================================
create index idx_neg_cliente   on fact_negociaciones (id_cliente);
create index idx_neg_usuario   on fact_negociaciones (id_usuario);
create index idx_neg_zona      on fact_negociaciones (id_zona);
create index idx_neg_distrito  on fact_negociaciones (id_distrito);
create index idx_neg_motivo    on fact_negociaciones (id_motivo_perdida);
create index idx_neg_fecha     on fact_negociaciones (fecha_inicio desc);
-- La bandeja del asesor consulta justo esto
create index idx_neg_abiertas  on fact_negociaciones (id_usuario, estado)
  where estado in ('abierta', 'por_cerrar');

create index idx_nt_ticket on rel_negociacion_tickets (ticket);

create index idx_cot_negociacion on fact_cotizaciones (id_negociacion);
create index idx_cot_usuario     on fact_cotizaciones (id_usuario);
create index idx_cot_sede        on fact_cotizaciones (id_sede);
create index idx_cot_distrito    on fact_cotizaciones (id_distrito);
create index idx_cot_regla       on fact_cotizaciones (id_regla);
create index idx_cot_tipo_pago   on fact_cotizaciones (id_tipo_pago);
create index idx_cot_fecha       on fact_cotizaciones (fecha desc);
-- La tarea nocturna busca exactamente estas
create index idx_cot_por_vencer  on fact_cotizaciones (fecha_vencimiento)
  where estado = 'enviada';

create index idx_cd_cotizacion on fact_cotizaciones_detalle (id_cotizacion);
create index idx_cd_sku        on fact_cotizaciones_detalle (id_sku);
create index idx_cd_promocion  on fact_cotizaciones_detalle (id_promocion);
create index idx_cd_precio     on fact_cotizaciones_detalle (id_precio);

create index idx_cf_sede on fact_cotizaciones_ferreterias (id_sede);
create index idx_cp_promocion on fact_cotizaciones_promociones (id_promocion);

create index idx_ven_negociacion on fact_ventas (id_negociacion);
create index idx_ven_cotizacion  on fact_ventas (id_cotizacion);
create index idx_ven_sede        on fact_ventas (id_sede);
create index idx_ven_usuario     on fact_ventas (id_usuario);
create index idx_ven_tipo_pago   on fact_ventas (id_tipo_pago);
create index idx_ven_validador   on fact_ventas (validado_por);
create index idx_ven_fecha       on fact_ventas (fecha_venta desc);
create index idx_ven_pendientes  on fact_ventas (estado)
  where estado = 'pendiente_validacion';

create index idx_vd_venta      on fact_ventas_detalle (id_venta);
create index idx_vd_sku        on fact_ventas_detalle (id_sku);
create index idx_vd_promocion  on fact_ventas_detalle (id_promocion);
create index idx_vd_cot_detalle on fact_ventas_detalle (id_cotizacion_detalle);
create index idx_vp_promocion  on fact_ventas_promociones (id_promocion);
