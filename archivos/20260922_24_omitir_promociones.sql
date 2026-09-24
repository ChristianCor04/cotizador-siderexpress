-- ============================================================================
-- 24 — Cualquier promoción se puede no aplicar
-- Requiere: 01 a 22
--
-- Antes una promoción automática no se podía quitar: el trigger lo bloqueaba.
-- Ahora el asesor decide, incluidas las automáticas. Queda registrado cuál se
-- ofreció y cuál se aplicó, que es lo que sirve para analizar después.
-- ============================================================================

-- La tabla tenía una restricción que exigía el motivo al omitir una
-- promoción. Se quita: ahora el asesor puede omitir sin justificar.
alter table fact_cotizaciones_promociones drop constraint if exists chk_cp_motivo;
alter table fact_ventas_promociones      drop constraint if exists chk_vp_motivo;


create or replace function public.validar_promocion_omitida()
returns trigger
language plpgsql
as $$
begin
  -- El asesor puede omitir cualquier promoción. Solo se limpia el motivo
  -- cuando sí se aplica, para que no quede un texto viejo colgado.
  if new.aplicada then
    new.motivo_no_aplicada := null;
  end if;
  return new;
end $$;

comment on function public.validar_promocion_omitida is
  'El asesor puede omitir cualquier promoción, automática incluida.';


-- ============== QUÉ SE OFRECIÓ Y QUÉ SE APLICÓ ==============================

-- "create or replace" no permite cambiar las columnas de una vista
drop view if exists v_promociones_omitidas;

create view v_promociones_omitidas as
select
  p.codigo,
  p.nombre                                          as promocion,
  p.aplicacion,
  p.modalidad,
  count(*)                                          as veces_ofrecida,
  count(*) filter (where cp.aplicada)               as veces_aplicada,
  count(*) filter (where not cp.aplicada)           as veces_omitida,
  round(100.0 * count(*) filter (where cp.aplicada) / nullif(count(*), 0), 1)
                                                    as tasa_aplicacion_pct,
  sum(cp.monto_beneficio) filter (where cp.aplicada)     as beneficio_entregado,
  sum(cp.monto_beneficio) filter (where not cp.aplicada) as beneficio_no_entregado
from fact_cotizaciones_promociones cp
join m_promociones p using (id_promocion)
group by p.codigo, p.nombre, p.aplicacion, p.modalidad;

comment on view v_promociones_omitidas is
  'Cuántas veces se ofreció cada promoción y cuántas se aplicó. '
  'Una tasa baja indica una promoción que no convence o que la ferretería '
  'no reconoce en el mostrador.';

alter view v_promociones_omitidas set (security_invoker = true);
grant select on v_promociones_omitidas to authenticated;
