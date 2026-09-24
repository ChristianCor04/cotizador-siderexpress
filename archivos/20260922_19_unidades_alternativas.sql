-- ============================================================================
-- 19 — Vender el mismo producto en varias unidades
-- Requiere: 01 a 18
--
-- La ferretería puede cotizar el fierro por varilla Y por tonelada, con
-- precios distintos. Si no manda precio por tonelada, simplemente no compite
-- en esa unidad.
--
-- No es una conversión: cada unidad es un SKU con su propio precio. Así el
-- asesor no hace cuentas fuera del cotizador.
-- ============================================================================

-- ========================= UNIDADES QUE FALTABAN ============================

insert into m_unidades_medida (codigo, nombre) values
  ('TON', 'Tonelada'),
  ('MLL', 'Millar')
on conflict (codigo) do nothing;


-- ============== CREAR LOS SKU DE LA UNIDAD ALTERNATIVA ======================
-- Toma los SKU que ya existen de una categoría y crea el equivalente en otra
-- unidad, calculando su peso a partir del original.
--
-- El peso importa porque alimenta el indicador de toneladas:
--   Tonelada   -> 1000 kg por unidad vendida
--   Kilogramo  -> 1 kg
--   Millar     -> mil veces el peso de la unidad suelta

create or replace function public.generar_skus_por_unidad(
  p_categoria      text,
  p_unidad_destino text
)
returns integer
language plpgsql
as $$
declare
  v_id_unidad bigint;
  v_creados   integer;
begin
  select id_unidad_medida into v_id_unidad
  from m_unidades_medida where codigo = p_unidad_destino;

  if v_id_unidad is null then
    raise exception 'No existe la unidad %', p_unidad_destino;
  end if;

  insert into m_skus (id_producto, id_marca, id_unidad_medida, peso_kg, activo)
  select s.id_producto,
         s.id_marca,
         v_id_unidad,
         case p_unidad_destino
           when 'TON' then 1000
           when 'KG'  then 1
           when 'MLL' then s.peso_kg * 1000
           else s.peso_kg
         end,
         true
  from m_skus s
  join m_productos  p   on p.id_producto   = s.id_producto
  join m_categorias c   on c.id_categoria  = p.id_categoria
  join m_unidades_medida u on u.id_unidad_medida = s.id_unidad_medida
  where c.nombre = p_categoria
    and s.activo
    and u.codigo <> p_unidad_destino     -- no duplicar la unidad base
  on conflict (id_producto, id_marca, id_unidad_medida) do nothing;

  get diagnostics v_creados = row_count;
  return v_creados;
end $$;

comment on function public.generar_skus_por_unidad is
  'Crea los SKU de una categoría en otra unidad de venta. Para habilitar una '
  'unidad nueva basta con llamarla: no hace falta tocar código.';


-- ===================== UNIDADES POR TIPO DE PRODUCTO ========================
-- Esto es lo que se cotiza hoy. Para agregar otra combinación, una línea más.

select generar_skus_por_unidad('FIERRO',   'TON');   -- varilla o tonelada
select generar_skus_por_unidad('CEMENTO',  'KG');    -- bolsa o kilo
select generar_skus_por_unidad('LADRILLO', 'MLL');   -- unidad o millar


-- ==================== CATÁLOGO CON COBERTURA DE PRECIOS =====================
-- Le dice a la app en qué unidades hay precio de verdad, para que el asesor
-- no elija una que nadie cotiza.

create or replace view v_catalogo_skus as
select
  s.id_sku,
  s.peso_kg,
  p.id_producto,
  p.nombre                               as producto,
  c.nombre                               as categoria,
  m.id_marca,
  m.nombre                               as marca,
  u.codigo                               as unidad,
  u.nombre                               as unidad_nombre,
  count(distinct pr.id_sede) filter (where pr.activo) as n_sedes
from m_skus s
join m_productos  p on p.id_producto  = s.id_producto
join m_categorias c on c.id_categoria = p.id_categoria
join m_marcas     m on m.id_marca     = s.id_marca
join m_unidades_medida u on u.id_unidad_medida = s.id_unidad_medida
left join m_precios pr on pr.id_sku = s.id_sku
where s.activo
group by s.id_sku, s.peso_kg, p.id_producto, p.nombre, c.nombre,
         m.id_marca, m.nombre, u.codigo, u.nombre;

comment on view v_catalogo_skus is
  'Catálogo con la cantidad de sedes que tienen precio para cada SKU. '
  'La app ordena las unidades por esa cobertura: primero la más cotizada.';

alter view v_catalogo_skus set (security_invoker = true);
grant select on v_catalogo_skus to authenticated;
grant execute on function generar_skus_por_unidad(text, text) to authenticated;
