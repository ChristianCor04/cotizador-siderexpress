-- ============================================================================
-- 20 — Unidades de venta definitivas por categoría
-- Requiere: 01 a 19
--
-- Fierro      : unidad (la varilla) y tonelada
-- Ladrillo    : unidad y millar
-- Cemento     : bolsa
-- Agregados   : metro cúbico y bolsa
-- Clavos      : kilo, caja de 25 kg y caja de 30 kg
-- Alambre     : kilo y rollo
--
-- SUPUESTO: para el fierro, «unidad» es la varilla de 9 m que ya está
-- cargada con todos sus precios. Solo se le cambia el nombre visible; crear
-- una unidad aparte habría partido el relevamiento en dos.
-- ============================================================================

-- ======================= UNIDADES NUEVAS ====================================

insert into m_unidades_medida (codigo, nombre) values
  ('CJ25',  'Caja de 25 kg'),
  ('CJ30',  'Caja de 30 kg'),
  ('ROLLO', 'Rollo'),
  -- La bolsa de agregados no es la de cemento: el código BOL dice
  -- "Bolsa de 42.5 kg" y confundiría en arena o piedra.
  ('BLS',   'Bolsa')
on conflict (codigo) do nothing;

-- El fierro se pide por unidad; la unidad del fierro es la varilla
update m_unidades_medida
   set nombre = 'Unidad (varilla de 9 m)'
 where codigo = 'VAR';


-- ==================== HABILITAR POR CATEGORÍA ===============================
-- generar_skus_por_unidad crea los SKU que falten. Se puede reejecutar.

select generar_skus_por_unidad('CLAVOS',    'CJ25');
select generar_skus_por_unidad('CLAVOS',    'CJ30');
select generar_skus_por_unidad('ALAMBRE',   'ROLLO');
select generar_skus_por_unidad('AGREGADOS', 'BLS');


-- ==================== PESOS DE LAS UNIDADES NUEVAS ==========================
-- El peso alimenta el indicador de toneladas, así que hay que corregirlo:
-- la función solo sabe calcular tonelada, kilo y millar.

update m_skus s set peso_kg = 25
  from m_unidades_medida u
 where u.id_unidad_medida = s.id_unidad_medida and u.codigo = 'CJ25';

update m_skus s set peso_kg = 30
  from m_unidades_medida u
 where u.id_unidad_medida = s.id_unidad_medida and u.codigo = 'CJ30';

-- El rollo de alambre queda SIN peso a propósito: varía según la marca y el
-- calibre. Mientras esté vacío, esos kilos no suman al indicador de toneladas.
-- Cuando confirmes el peso por marca, se completa con un update como los de arriba.
update m_skus s set peso_kg = null
  from m_unidades_medida u
 where u.id_unidad_medida = s.id_unidad_medida and u.codigo = 'ROLLO';

-- La bolsa de agregados tampoco tiene peso fijo y los agregados no suman
-- toneladas, así que se deja vacía.

-- Si una corrida anterior había usado la bolsa de cemento para agregados,
-- se desactiva para que no quede duplicada.
update m_skus s set activo = false
  from m_unidades_medida u, m_productos p, m_categorias c
 where u.id_unidad_medida = s.id_unidad_medida
   and p.id_producto  = s.id_producto
   and c.id_categoria = p.id_categoria
   and u.codigo = 'BOL'
   and c.nombre = 'AGREGADOS';


-- ==================== QUITAR LO QUE NO SE USA ===============================
-- El cemento se vende solo por bolsa: el kilo que se había habilitado se
-- desactiva. No se borra, para no perder las cotizaciones que lo referencien.

update m_skus s set activo = false
  from m_unidades_medida u, m_productos p, m_categorias c
 where u.id_unidad_medida = s.id_unidad_medida
   and p.id_producto  = s.id_producto
   and c.id_categoria = p.id_categoria
   and u.codigo = 'KG'
   and c.nombre = 'CEMENTO';


-- ========================== CÓMO QUEDÓ ======================================
-- Ejecuta esto para ver el resultado. Las unidades sin precios se habilitan
-- cargándolos desde la pantalla de Precios.

select c.nombre                       as categoria,
       u.nombre                       as unidad,
       count(distinct s.id_sku)       as skus,
       count(distinct pr.id_sede) filter (where pr.activo) as sedes_con_precio
from m_skus s
join m_productos  p on p.id_producto  = s.id_producto
join m_categorias c on c.id_categoria = p.id_categoria
join m_unidades_medida u on u.id_unidad_medida = s.id_unidad_medida
left join m_precios pr on pr.id_sku = s.id_sku
where s.activo
group by c.nombre, u.nombre
order by c.nombre, u.nombre;
