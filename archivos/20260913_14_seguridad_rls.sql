-- ============================================================================
-- 14 — Permisos y seguridad por fila (RLS)
-- Requiere: 01 a 13
--
-- Dos capas que trabajan juntas:
--   1. GRANT  -> a qué TABLAS puede entrar un usuario autenticado.
--   2. RLS    -> qué FILAS de esas tablas puede ver o modificar.
--
-- Sin la primera, la app recibe "permission denied".
-- Sin la segunda, cualquier asesor vería la cartera de los demás.
--
-- Reglas del negocio:
--   asesor     -> solo sus negociaciones, cotizaciones y ventas
--   supervisor -> todo lo de su zona
--   master     -> todo, y es el único que edita precios y ferreterías
-- ============================================================================

-- ============================== 1. PERMISOS =================================

grant usage on schema public to authenticated;

-- Los usuarios autenticados pueden LEER los catálogos.
grant select on
  m_departamentos, m_provincias, m_distritos, m_zonas,
  m_ferreterias, m_sedes, rel_sedes_tipos_pago,
  m_categorias, m_marcas, m_unidades_medida, m_productos, m_skus,
  m_precios, h_precios,
  m_promociones, m_promociones_tramos, h_promociones,
  rel_promociones_skus, rel_promociones_categorias,
  rel_promociones_sedes, rel_promociones_zonas, rel_promociones_tipos_cliente,
  m_tipos_pago, m_motivos_perdida, m_tipos_cliente,
  m_reglas_cotizacion, m_parametros, m_usuarios
to authenticated;

-- Solo el master escribe en los maestros. El RLS de más abajo lo verifica.
grant insert, update, delete on
  m_ferreterias, m_sedes, m_precios, m_skus, m_productos, m_marcas,
  m_promociones, m_promociones_tramos,
  rel_promociones_skus, rel_promociones_categorias,
  rel_promociones_sedes, rel_promociones_zonas, rel_promociones_tipos_cliente,
  rel_sedes_tipos_pago
to authenticated;

-- Tablas de trabajo: los asesores escriben, pero solo sus propias filas.
grant select, insert, update on
  m_clientes, m_clientes_crm,
  fact_negociaciones, rel_negociacion_tickets,
  fact_cotizaciones, fact_cotizaciones_detalle,
  fact_cotizaciones_ferreterias, fact_cotizaciones_promociones,
  fact_ventas, fact_ventas_detalle, fact_ventas_promociones
to authenticated;

-- Las secuencias de los id autoincrementales
grant usage on all sequences in schema public to authenticated;

-- Las vistas de análisis
grant select on
  v_cotizaciones_bi, v_ventas_bi, v_cotizaciones_flags, v_ventas_flags,
  v_cotizado_vs_vendido, v_funnel_negociaciones, v_funnel_por_segmento,
  v_motivos_perdida_resumen, v_competencia_ferreterias, v_cobertura_productos,
  v_promociones_uso, v_precios_desactualizados, v_precios_referenciales,
  v_promociones_vigentes, v_promociones_tramos, v_promociones_afiliacion
to authenticated;

-- Funciones que llama la aplicación
grant execute on function
  rol_actual(), zona_actual(),
  buscar_cliente(text), normalizar_telefono(text),
  calcular_beneficio_promocion(bigint, numeric),
  promociones_aplicables(bigint, numeric, bigint, text),
  beneficio_promocional(bigint, numeric, bigint, text),
  resumen_beneficios(bigint, numeric, bigint),
  sede_participa_en_promocion(bigint, bigint),
  cliente_cumple_promocion(bigint, bigint),
  compras_previas(bigint), dias_desde_ultima_compra(bigint)
to authenticated;

-- Nadie sin iniciar sesión entra a nada
revoke all on all tables in schema public from anon;


-- ===================== 2. FUNCIÓN AUXILIAR DE PERMISOS ======================
-- Decide si el usuario actual puede ver una negociación.
-- Se usa en casi todas las políticas, así que está en un solo lugar.

create or replace function public.puede_ver_negociacion(
  p_id_usuario uuid,
  p_id_zona    bigint
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select case rol_actual()
    when 'master'     then true
    when 'supervisor' then p_id_zona = zona_actual()
    else                   p_id_usuario = auth.uid()
  end
$$;

grant execute on function puede_ver_negociacion(uuid, bigint) to authenticated;


-- ============================ 3. ACTIVAR RLS ================================
-- Una vez activado, NADIE ve nada hasta que exista una política que lo permita.

do $$
declare t text;
begin
  foreach t in array array[
    'm_departamentos','m_provincias','m_distritos','m_zonas',
    'm_ferreterias','m_sedes','rel_sedes_tipos_pago',
    'm_categorias','m_marcas','m_unidades_medida','m_productos','m_skus',
    'm_precios','h_precios',
    'm_promociones','m_promociones_tramos','h_promociones',
    'rel_promociones_skus','rel_promociones_categorias',
    'rel_promociones_sedes','rel_promociones_zonas','rel_promociones_tipos_cliente',
    'm_tipos_pago','m_motivos_perdida','m_tipos_cliente',
    'm_reglas_cotizacion','m_parametros','m_usuarios',
    'm_clientes','m_clientes_crm',
    'fact_negociaciones','rel_negociacion_tickets',
    'fact_cotizaciones','fact_cotizaciones_detalle',
    'fact_cotizaciones_ferreterias','fact_cotizaciones_promociones',
    'fact_ventas','fact_ventas_detalle','fact_ventas_promociones'
  ] loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;


-- ======================== 4. POLÍTICAS: CATÁLOGOS ===========================
-- Todos los autenticados LEEN. Solo el master ESCRIBE.

do $$
declare t text;
begin
  foreach t in array array[
    'm_departamentos','m_provincias','m_distritos','m_zonas',
    'm_ferreterias','m_sedes','rel_sedes_tipos_pago',
    'm_categorias','m_marcas','m_unidades_medida','m_productos','m_skus',
    'm_precios','h_precios',
    'm_promociones','m_promociones_tramos','h_promociones',
    'rel_promociones_skus','rel_promociones_categorias',
    'rel_promociones_sedes','rel_promociones_zonas','rel_promociones_tipos_cliente',
    'm_tipos_pago','m_motivos_perdida','m_tipos_cliente',
    'm_reglas_cotizacion','m_parametros'
  ] loop
    execute format('drop policy if exists leer_catalogo on %I', t);
    execute format(
      'create policy leer_catalogo on %I for select to authenticated using (true)', t);

    execute format('drop policy if exists escribir_catalogo on %I', t);
    execute format(
      'create policy escribir_catalogo on %I for all to authenticated '
      'using (rol_actual() = ''master'') with check (rol_actual() = ''master'')', t);
  end loop;
end $$;


-- ========================= 5. POLÍTICAS: USUARIOS ===========================

drop policy if exists ver_usuarios on m_usuarios;
create policy ver_usuarios on m_usuarios
  for select to authenticated
  using (
    id_usuario = auth.uid()                       -- su propio perfil
    or rol_actual() in ('supervisor', 'master')   -- los jefes ven al equipo
  );


-- ========================= 6. POLÍTICAS: CLIENTES ===========================
-- Los clientes se comparten: un contratista puede tener obras en varias zonas
-- y ser atendido por asesores distintos.

drop policy if exists ver_clientes on m_clientes;
create policy ver_clientes on m_clientes
  for select to authenticated using (true);

drop policy if exists crear_clientes on m_clientes;
create policy crear_clientes on m_clientes
  for insert to authenticated with check (true);

drop policy if exists editar_clientes on m_clientes;
create policy editar_clientes on m_clientes
  for update to authenticated using (true) with check (true);

drop policy if exists ver_clientes_crm on m_clientes_crm;
create policy ver_clientes_crm on m_clientes_crm
  for select to authenticated using (true);


-- ====================== 7. POLÍTICAS: NEGOCIACIONES =========================

drop policy if exists ver_negociaciones on fact_negociaciones;
create policy ver_negociaciones on fact_negociaciones
  for select to authenticated
  using (puede_ver_negociacion(id_usuario, id_zona));

drop policy if exists crear_negociaciones on fact_negociaciones;
create policy crear_negociaciones on fact_negociaciones
  for insert to authenticated
  with check (id_usuario = auth.uid() or rol_actual() = 'master');

drop policy if exists editar_negociaciones on fact_negociaciones;
create policy editar_negociaciones on fact_negociaciones
  for update to authenticated
  using (puede_ver_negociacion(id_usuario, id_zona))
  with check (puede_ver_negociacion(id_usuario, id_zona));

drop policy if exists tickets_negociacion on rel_negociacion_tickets;
create policy tickets_negociacion on rel_negociacion_tickets
  for all to authenticated
  using (exists (select 1 from fact_negociaciones n
                 where n.id_negociacion = rel_negociacion_tickets.id_negociacion))
  with check (exists (select 1 from fact_negociaciones n
                      where n.id_negociacion = rel_negociacion_tickets.id_negociacion));


-- ====================== 8. POLÍTICAS: COTIZACIONES ==========================
-- Se apoyan en la negociación: si puedes verla, puedes ver sus cotizaciones.
-- El "exists" ya pasa por el RLS de fact_negociaciones.

drop policy if exists ver_cotizaciones on fact_cotizaciones;
create policy ver_cotizaciones on fact_cotizaciones
  for all to authenticated
  using (exists (select 1 from fact_negociaciones n
                 where n.id_negociacion = fact_cotizaciones.id_negociacion))
  with check (exists (select 1 from fact_negociaciones n
                      where n.id_negociacion = fact_cotizaciones.id_negociacion));

do $$
declare t text;
begin
  foreach t in array array[
    'fact_cotizaciones_detalle','fact_cotizaciones_ferreterias','fact_cotizaciones_promociones'
  ] loop
    execute format('drop policy if exists por_cotizacion on %I', t);
    execute format(
      'create policy por_cotizacion on %I for all to authenticated '
      'using (exists (select 1 from fact_cotizaciones c where c.id_cotizacion = %I.id_cotizacion)) '
      'with check (exists (select 1 from fact_cotizaciones c where c.id_cotizacion = %I.id_cotizacion))',
      t, t, t);
  end loop;
end $$;


-- ========================= 9. POLÍTICAS: VENTAS =============================

drop policy if exists ver_ventas on fact_ventas;
create policy ver_ventas on fact_ventas
  for all to authenticated
  using (exists (select 1 from fact_negociaciones n
                 where n.id_negociacion = fact_ventas.id_negociacion))
  with check (exists (select 1 from fact_negociaciones n
                      where n.id_negociacion = fact_ventas.id_negociacion));

do $$
declare t text;
begin
  foreach t in array array['fact_ventas_detalle','fact_ventas_promociones'] loop
    execute format('drop policy if exists por_venta on %I', t);
    execute format(
      'create policy por_venta on %I for all to authenticated '
      'using (exists (select 1 from fact_ventas v where v.id_venta = %I.id_venta)) '
      'with check (exists (select 1 from fact_ventas v where v.id_venta = %I.id_venta))',
      t, t, t);
  end loop;
end $$;


-- ==================== 10. VISTAS: QUE RESPETEN EL RLS =======================
-- Por defecto una vista se ejecuta con los permisos de quien la creó, y eso
-- se saltaría el RLS. Con security_invoker se ejecuta con los permisos de
-- quien la consulta.

do $$
declare v text;
begin
  foreach v in array array[
    'v_cotizaciones_bi','v_ventas_bi','v_cotizaciones_flags','v_ventas_flags',
    'v_cotizado_vs_vendido','v_funnel_negociaciones','v_funnel_por_segmento',
    'v_motivos_perdida_resumen','v_competencia_ferreterias','v_cobertura_productos',
    'v_promociones_uso','v_precios_desactualizados','v_precios_referenciales',
    'v_promociones_vigentes','v_promociones_tramos','v_promociones_afiliacion'
  ] loop
    execute format('alter view %I set (security_invoker = true)', v);
  end loop;
end $$;
