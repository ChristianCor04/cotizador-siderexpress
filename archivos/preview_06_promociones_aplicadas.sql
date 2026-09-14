-- ============================================================================
-- VISTA PREVIA — no ejecutar todavía
-- Estas tablas y columnas van DENTRO del archivo 06 (transaccionales),
-- porque necesitan que fact_cotizaciones y fact_ventas ya existan.
-- Te las adelanto para que veas cómo se conecta la promoción con el negocio.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Columnas que se agregan a las cabeceras
-- ---------------------------------------------------------------------------
-- En fact_cotizaciones y en fact_ventas:
--
--   monto_bruto_sol    numeric(14,2)  -- suma del detalle, sin beneficios
--   monto_descuento    numeric(14,2)  -- beneficios de modalidad 'descuento'
--   monto_total_sol    numeric(14,2)  -- lo que paga el cliente (bruto - descuento)
--   monto_devolucion   numeric(14,2)  -- beneficios de modalidad 'devolucion'
--
-- Los tres montos suman SOLO las promociones con aplicada = true.
--
-- Diferencia clave: el descuento baja monto_total_sol; la devolución NO.
-- El cliente paga el total completo y el cashback se le entrega después.
--
-- IMPORTANTE: monto_referencial (el que decide el radio de búsqueda) se calcula
-- ANTES de aplicar promociones. Si no, una promoción podría bajar la canasta de
-- S/ 5,100 a S/ 4,590 y cambiar la regla de 1.2 a 1.1, reduciendo el radio de
-- búsqueda de 4 km a 2 km. El descuento no debe alterar qué ferreterías compiten.


-- ---------------------------------------------------------------------------
-- 2. Qué promociones se aplicaron a cada cotización
-- ---------------------------------------------------------------------------
create table fact_cotizaciones_promociones (
  id_cotizacion   bigint not null,
  id_promocion    bigint not null,

  -- Copia congelada de la promoción al momento de cotizar.
  -- Si mañana cambia el 10% a 5%, esta cotización sigue diciendo 10%.
  modalidad       text not null,          -- descuento o devolucion
  tipo            text not null,
  valor           numeric(12,4),           -- null en escalonada
  monto_beneficio numeric(14,2) not null,  -- lo que calculó calcular_beneficio_promocion()
  id_tramo        bigint,                  -- qué tramo aplicó, si fue escalonada
  financiado_por  text not null,

  -- DECISIÓN DEL ASESOR
  -- La fila se guarda aunque no se aplique: saber que la promoción estaba
  -- disponible y el asesor no la usó es un dato valioso para el análisis.
  aplicada        boolean not null default true,
  motivo_no_aplicada text,
  decidida_por    uuid,

  constraint pk_cot_promociones primary key (id_cotizacion, id_promocion),
  constraint fk_cp_cotizacion foreign key (id_cotizacion)
    references fact_cotizaciones (id_cotizacion) on delete cascade,
  constraint fk_cp_promocion  foreign key (id_promocion)
    references m_promociones (id_promocion) on delete restrict,
  constraint chk_cp_beneficio check (monto_beneficio >= 0),
  constraint chk_cp_modalidad check (modalidad in ('descuento', 'devolucion')),
  -- Si no se aplicó, hay que decir por qué
  constraint chk_cp_motivo check (aplicada or motivo_no_aplicada is not null)
);


-- ---------------------------------------------------------------------------
-- 3. Lo mismo para las ventas
-- ---------------------------------------------------------------------------
create table fact_ventas_promociones (
  id_venta        bigint not null,
  id_promocion    bigint not null,
  modalidad       text not null,
  tipo            text not null,
  valor           numeric(12,4),
  monto_beneficio numeric(14,2) not null,
  id_tramo        bigint,
  financiado_por  text not null,
  aplicada        boolean not null default true,
  motivo_no_aplicada text,
  decidida_por    uuid,

  constraint pk_venta_promociones primary key (id_venta, id_promocion),
  constraint fk_vp_venta     foreign key (id_venta)
    references fact_ventas (id_venta) on delete cascade,
  constraint fk_vp_promocion foreign key (id_promocion)
    references m_promociones (id_promocion) on delete restrict,
  constraint chk_vp_beneficio check (monto_beneficio >= 0),
  constraint chk_vp_modalidad check (modalidad in ('descuento', 'devolucion')),
  constraint chk_vp_motivo check (aplicada or motivo_no_aplicada is not null)
);


-- ---------------------------------------------------------------------------
-- 4. Descuento a nivel de línea (para promociones con alcance = 'producto')
-- ---------------------------------------------------------------------------
-- En fact_cotizaciones_detalle y fact_ventas_detalle se agregan:
--
--   id_promocion        bigint         -- FK a m_promociones, null si no hubo
--   descuento_unitario  numeric(12,4)  -- cuánto se descontó por unidad
--
-- Y el subtotal pasa a ser:
--
--   subtotal numeric(14,2) generated always as (
--     round(cantidad * (coalesce(precio_modificado, precio_unitario)
--                       - coalesce(descuento_unitario, 0)), 2)
--   ) stored
--
-- Así el descuento por producto queda dentro del subtotal y no hay que
-- recalcularlo nunca.


-- ---------------------------------------------------------------------------
-- 5. Regla: una promoción automática no se puede desactivar
-- ---------------------------------------------------------------------------
-- El check no puede consultar m_promociones (solo ve su propia fila),
-- así que esta regla necesita un trigger.

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

create trigger trg_validar_promocion_cotizacion
  before insert or update on fact_cotizaciones_promociones
  for each row execute function validar_promocion_omitida();


-- ---------------------------------------------------------------------------
-- 6. Vista de análisis: promociones ofrecidas vs aplicadas
-- ---------------------------------------------------------------------------
-- Responde: ¿qué promociones están disponibles pero los asesores no usan?
-- create or replace view v_promociones_uso as
-- select p.codigo, p.nombre,
--        count(*)                                   as veces_disponible,
--        count(*) filter (where cp.aplicada)         as veces_aplicada,
--        round(100.0 * count(*) filter (where cp.aplicada) / count(*), 1) as tasa_uso,
--        sum(cp.monto_beneficio) filter (where cp.aplicada) as beneficio_otorgado
-- from fact_cotizaciones_promociones cp
-- join m_promociones p using (id_promocion)
-- group by p.codigo, p.nombre;
