-- ============================================================================
-- 17 — Confirmación diaria de precios y permisos para actualizarlos
-- Requiere: 01 a 16
--
-- Dos necesidades del negocio:
--   1. La ferretería a veces dice "los precios se mantienen". Hay que poder
--      registrar esa confirmación SIN cambiar los montos, para distinguir
--      un precio vigente de uno que nadie revisa hace dos semanas.
--   2. Los precios los actualiza un asesor o un supervisor, no solo el master.
-- ============================================================================

-- ========================= CAMPOS NUEVOS ====================================

alter table m_precios
  add column if not exists fecha_confirmacion timestamptz;

alter table m_precios
  add column if not exists actualizado_por uuid;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'fk_precio_usuario') then
    alter table m_precios add constraint fk_precio_usuario
      foreign key (actualizado_por) references m_usuarios (id_usuario)
      on delete set null;
  end if;
end $$;

-- Los precios que ya existen se consideran confirmados cuando se cargaron
update m_precios
   set fecha_confirmacion = fecha_actualizacion
 where fecha_confirmacion is null;

comment on column m_precios.fecha_actualizacion is
  'Cuándo cambió el MONTO por última vez.';
comment on column m_precios.fecha_confirmacion is
  'Cuándo la ferretería confirmó que el precio sigue vigente, haya cambiado o no. '
  'Es la fecha que usa el semáforo.';

create index if not exists idx_precios_confirmacion
  on m_precios (fecha_confirmacion desc) where activo;


-- El trigger del archivo 03 ya archiva el precio anterior.
-- Se amplía por dos motivos:
--   1. Un cambio de monto cuenta también como confirmación.
--   2. security definer: el historial NO debe ser escribible por los usuarios,
--      pero el trigger sí tiene que poder escribir en él. Sin esto, al guardar
--      un precio sale "permission denied for table h_precios".
create or replace function public.archivar_precio_anterior()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.precio is distinct from old.precio then
    insert into h_precios (id_precio, id_sede, id_sku, precio, vigente_desde, vigente_hasta)
    values (old.id_precio, old.id_sede, old.id_sku, old.precio,
            old.fecha_actualizacion, now());
    new.fecha_actualizacion := now();
    new.fecha_confirmacion  := now();   -- cambiarlo es confirmarlo
  end if;
  return new;
end $$;


-- ==================== CONFIRMAR SIN CAMBIAR PRECIOS =========================
-- Es el botón «Mantienen precios».

create or replace function public.confirmar_precios_sede(p_id_sede bigint)
returns integer
language plpgsql
security invoker
as $$
declare
  v_filas integer;
begin
  update m_precios
     set fecha_confirmacion = now(),
         actualizado_por    = auth.uid()
   where id_sede = p_id_sede and activo;

  get diagnostics v_filas = row_count;
  return v_filas;
end $$;

comment on function public.confirmar_precios_sede is
  'Marca los precios de una sede como confirmados hoy, sin tocar los montos.';


create or replace function public.confirmar_precios_ferreteria(p_id_ferreteria bigint)
returns integer
language plpgsql
security invoker
as $$
declare
  v_filas integer;
begin
  update m_precios p
     set fecha_confirmacion = now(),
         actualizado_por    = auth.uid()
    from m_sedes s
   where s.id_sede = p.id_sede
     and s.id_ferreteria = p_id_ferreteria
     and s.activo and p.activo;

  get diagnostics v_filas = row_count;
  return v_filas;
end $$;


-- ===================== GUARDAR PRECIOS EN LOTE ==============================
-- Una sola llamada para todo lo que el usuario editó o cargó por Excel.
-- Modo 'actualizar': toca solo lo que viene en la lista.
-- Modo 'reemplazar': además desactiva lo que NO viene, por sede.
--
-- Nunca se borra un precio: se desactiva. Así una carga equivocada se revierte.

create or replace function public.guardar_precios(p jsonb)
returns jsonb
language plpgsql
security invoker
as $$
declare
  v_modo      text   := coalesce(p->>'modo', 'actualizar');
  v_sedes     bigint[];
  v_item      jsonb;
  v_actualizados integer := 0;
  v_nuevos       integer := 0;
  v_desactivados integer := 0;
  v_existe    boolean;
begin
  if v_modo not in ('actualizar', 'reemplazar') then
    raise exception 'Modo inválido: %. Usa actualizar o reemplazar.', v_modo;
  end if;

  select array_agg(distinct (x->>'id_sede')::bigint)
    into v_sedes
  from jsonb_array_elements(p->'precios') x;

  if v_sedes is null then
    raise exception 'No hay precios que guardar.';
  end if;

  for v_item in select * from jsonb_array_elements(p->'precios') loop
    select exists (
      select 1 from m_precios
      where id_sede = (v_item->>'id_sede')::bigint
        and id_sku  = (v_item->>'id_sku')::bigint
    ) into v_existe;

    insert into m_precios (id_sede, id_sku, precio, fuente, activo,
                           fecha_confirmacion, actualizado_por)
    values (
      (v_item->>'id_sede')::bigint,
      (v_item->>'id_sku')::bigint,
      (v_item->>'precio')::numeric,
      coalesce(v_item->>'fuente', 'asesor'),
      true, now(), auth.uid()
    )
    on conflict (id_sede, id_sku) do update
      set precio             = excluded.precio,
          activo             = true,
          fuente             = excluded.fuente,
          fecha_confirmacion = now(),
          actualizado_por    = auth.uid();

    if v_existe then
      v_actualizados := v_actualizados + 1;
    else
      v_nuevos := v_nuevos + 1;
    end if;
  end loop;

  -- Reemplazar: lo que no vino en la lista deja de venderse
  if v_modo = 'reemplazar' then
    update m_precios
       set activo = false, actualizado_por = auth.uid()
     where id_sede = any(v_sedes)
       and activo
       and (id_sede, id_sku) not in (
         select (x->>'id_sede')::bigint, (x->>'id_sku')::bigint
         from jsonb_array_elements(p->'precios') x
       );
    get diagnostics v_desactivados = row_count;
  end if;

  return jsonb_build_object(
    'actualizados', v_actualizados,
    'nuevos',       v_nuevos,
    'desactivados', v_desactivados
  );
end $$;

comment on function public.guardar_precios is
  'Guarda precios en lote. Modo reemplazar desactiva los que no vengan en la lista.';


-- ======================= ESTADO DIARIO DE PRECIOS ===========================
-- Lo que alimenta el semáforo y los contadores de la pantalla.

create or replace view v_estado_precios as
select
  f.id_ferreteria,
  f.nombre                                   as ferreteria,
  s.id_sede,
  s.codigo                                   as sede_codigo,
  s.nombre                                   as sede,
  d.nombre                                   as distrito,
  count(*) filter (where p.activo)           as productos,
  max(p.fecha_confirmacion)                  as ultima_confirmacion,
  max(p.fecha_actualizacion)                 as ultimo_cambio,
  -- Días desde la última confirmación. 0 = hoy.
  extract(day from now() - max(p.fecha_confirmacion))::int as dias_sin_confirmar,
  case
    when max(p.fecha_confirmacion) >= date_trunc('day', now()) then 'hoy'
    when max(p.fecha_confirmacion) >= date_trunc('day', now()) - interval '1 day' then 'ayer'
    when max(p.fecha_confirmacion) >= now() - interval '7 days' then 'esta semana'
    else 'desactualizado'
  end                                        as estado,
  u.nombre                                   as actualizado_por
from m_sedes s
join m_ferreterias f on f.id_ferreteria = s.id_ferreteria
join m_distritos   d on d.id_distrito   = s.id_distrito
left join m_precios p on p.id_sede = s.id_sede
left join m_usuarios u on u.id_usuario = (
  select actualizado_por from m_precios
  where id_sede = s.id_sede and actualizado_por is not null
  order by fecha_confirmacion desc limit 1
)
where s.activo and f.activo
group by f.id_ferreteria, f.nombre, s.id_sede, s.codigo, s.nombre, d.nombre, u.nombre;

comment on view v_estado_precios is
  'Una fila por sede: cuántos productos tiene y hace cuánto se confirmaron sus precios.';

alter view v_estado_precios set (security_invoker = true);


-- ===================== PERMISOS PARA ACTUALIZAR =============================
-- Los precios los actualiza un asesor o un supervisor, no solo el master.
-- Queda registrado quién lo hizo en actualizado_por.

drop policy if exists escribir_catalogo on m_precios;

drop policy if exists actualizar_precios on m_precios;
create policy actualizar_precios on m_precios
  for all to authenticated
  using (coalesce(rol_actual(), '') in ('asesor', 'supervisor', 'master'))
  with check (coalesce(rol_actual(), '') in ('asesor', 'supervisor', 'master'));

-- Lo mismo para el historial de promociones, por el mismo motivo
create or replace function public.archivar_promocion_anterior()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if (new.modalidad, new.tipo, new.valor, new.base_bloque,
      new.tope_beneficio, new.vigente_desde, new.vigente_hasta)
     is distinct from
     (old.modalidad, old.tipo, old.valor, old.base_bloque,
      old.tope_beneficio, old.vigente_desde, old.vigente_hasta) then
    insert into h_promociones (id_promocion, modalidad, tipo, valor, base_bloque,
                               tope_beneficio, vigente_desde, vigente_hasta)
    values (old.id_promocion, old.modalidad, old.tipo, old.valor, old.base_bloque,
            old.tope_beneficio, old.vigente_desde, old.vigente_hasta);
  end if;
  return new;
end $$;


grant select on v_estado_precios to authenticated;
grant execute on function confirmar_precios_sede(bigint) to authenticated;
grant execute on function confirmar_precios_ferreteria(bigint) to authenticated;
grant execute on function guardar_precios(jsonb) to authenticated;
