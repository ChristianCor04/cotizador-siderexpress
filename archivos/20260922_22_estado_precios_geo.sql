-- ============================================================================
-- 22 — La vista de estado de precios entrega también la geografía
-- Requiere: 01 a 21
--
-- La pantalla de Precios filtra por departamento, provincia y distrito.
-- Antes había que cruzar por NOMBRE de distrito, que es frágil: basta un
-- guion bajo o una tilde para que no encuentre nada. Ahora la vista entrega
-- los identificadores y el cruce es exacto.
-- ============================================================================

-- "create or replace" no permite cambiar el orden ni el nombre de las
-- columnas de una vista: hay que borrarla y volver a crearla.
drop view if exists v_estado_precios;

create view v_estado_precios as
select
  f.id_ferreteria,
  f.nombre                                   as ferreteria,
  s.id_sede,
  s.codigo                                   as sede_codigo,
  s.nombre                                   as sede,
  d.id_distrito,
  d.nombre                                   as distrito,
  pr_geo.id_provincia,
  pr_geo.nombre                              as provincia,
  dep.id_departamento,
  dep.nombre                                 as departamento,
  count(*) filter (where p.activo)           as productos,
  max(p.fecha_confirmacion)                  as ultima_confirmacion,
  max(p.fecha_actualizacion)                 as ultimo_cambio,
  extract(day from now() - max(p.fecha_confirmacion))::int as dias_sin_confirmar,
  case
    when max(p.fecha_confirmacion) >= date_trunc('day', now()) then 'hoy'
    when max(p.fecha_confirmacion) >= date_trunc('day', now()) - interval '1 day' then 'ayer'
    when max(p.fecha_confirmacion) >= now() - interval '7 days' then 'esta semana'
    else 'desactualizado'
  end                                        as estado,
  u.nombre                                   as actualizado_por
from m_sedes s
join m_ferreterias f   on f.id_ferreteria = s.id_ferreteria
join m_distritos   d   on d.id_distrito   = s.id_distrito
join m_provincias  pr_geo on pr_geo.id_provincia = d.id_provincia
join m_departamentos dep  on dep.id_departamento = pr_geo.id_departamento
left join m_precios p  on p.id_sede = s.id_sede
left join m_usuarios u on u.id_usuario = (
  select actualizado_por from m_precios
  where id_sede = s.id_sede and actualizado_por is not null
  order by fecha_confirmacion desc limit 1
)
where s.activo and f.activo
group by f.id_ferreteria, f.nombre, s.id_sede, s.codigo, s.nombre,
         d.id_distrito, d.nombre, pr_geo.id_provincia, pr_geo.nombre,
         dep.id_departamento, dep.nombre, u.nombre;

alter view v_estado_precios set (security_invoker = true);
grant select on v_estado_precios to authenticated;
