-- ============================================================================
-- 26 — Varias zonas por usuario y la zona de la negociación sale de la obra
-- Requiere: 01 a 22, 24 y 25
--
-- Dos cambios que van juntos:
--
--   1. Un usuario puede cubrir varias zonas. El supervisor ve las
--      negociaciones de todas las suyas.
--
--   2. La zona de la negociación se deduce del DISTRITO DE LA OBRA, no del
--      asesor. Antes, un asesor de Trujillo que atendía a un cliente de
--      Chiclayo dejaba la negociación marcada como Trujillo y los reportes
--      por zona salían mal.
-- ============================================================================

-- ==================== 1. VARIAS ZONAS POR USUARIO ===========================

create table if not exists rel_usuarios_zonas (
  id_usuario uuid   not null,
  id_zona    bigint not null,
  asignado_en timestamptz not null default now(),

  constraint pk_usuarios_zonas primary key (id_usuario, id_zona),
  constraint fk_uz_usuario foreign key (id_usuario)
    references m_usuarios (id_usuario) on delete cascade,
  constraint fk_uz_zona foreign key (id_zona)
    references m_zonas (id_zona) on delete restrict
);

create index if not exists idx_uz_zona on rel_usuarios_zonas (id_zona);

comment on table rel_usuarios_zonas is
  'Zonas que cubre cada usuario. m_usuarios.id_zona queda como zona '
  'principal, solo para mostrar.';

-- Los usuarios que ya existen conservan su zona
insert into rel_usuarios_zonas (id_usuario, id_zona)
select id_usuario, id_zona from m_usuarios where id_zona is not null
on conflict do nothing;

-- Al crear un usuario con zona, se registra sola
create or replace function public.sincronizar_zona_principal()
returns trigger
language plpgsql
as $$
begin
  if new.id_zona is not null then
    insert into rel_usuarios_zonas (id_usuario, id_zona)
    values (new.id_usuario, new.id_zona)
    on conflict do nothing;
  end if;
  return null;
end $$;

drop trigger if exists trg_usuario_zona on m_usuarios;
create trigger trg_usuario_zona
  after insert or update of id_zona on m_usuarios
  for each row execute function sincronizar_zona_principal();


create or replace function public.zonas_del_usuario(p_id_usuario uuid)
returns setof bigint
language sql
stable
security definer
set search_path = public
as $$
  select id_zona from rel_usuarios_zonas where id_usuario = p_id_usuario
$$;


-- ============ 2. QUÉ VE CADA QUIEN, CON VARIAS ZONAS ========================

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
    when 'master' then true
    when 'supervisor' then exists (
      select 1 from rel_usuarios_zonas
      where id_usuario = auth.uid() and id_zona = p_id_zona
    )
    else p_id_usuario = auth.uid()
  end
$$;

comment on function public.puede_ver_negociacion is
  'El supervisor ve las negociaciones de TODAS sus zonas; el asesor, las suyas '
  'esté donde esté la obra.';


-- ============ 3. LA ZONA SALE DE LA OBRA, NO DEL ASESOR =====================

create or replace function public.zona_de_la_obra()
returns trigger
language plpgsql
as $$
declare
  v_zona bigint;
begin
  if new.id_distrito is not null then
    select id_zona into v_zona from m_distritos where id_distrito = new.id_distrito;
    if v_zona is not null then
      new.id_zona := v_zona;
    end if;
  end if;

  -- Sin distrito conocido se conserva lo que haya llegado (la zona del asesor)
  return new;
end $$;

drop trigger if exists trg_negociacion_zona on fact_negociaciones;
create trigger trg_negociacion_zona
  before insert or update of id_distrito on fact_negociaciones
  for each row execute function zona_de_la_obra();

comment on function public.zona_de_la_obra is
  'La zona de la negociación es la del distrito de la obra. Así un asesor '
  'puede atender cualquier ciudad sin ensuciar los reportes por zona.';


-- ==================== PERMISOS Y SEGURIDAD ==================================

alter table rel_usuarios_zonas enable row level security;

drop policy if exists leer_zonas_usuario on rel_usuarios_zonas;
create policy leer_zonas_usuario on rel_usuarios_zonas
  for select to authenticated
  using (id_usuario = auth.uid() or coalesce(rol_actual(), '') in ('supervisor', 'master'));

drop policy if exists escribir_zonas_usuario on rel_usuarios_zonas;
create policy escribir_zonas_usuario on rel_usuarios_zonas
  for all to authenticated
  using (coalesce(rol_actual(), '') = 'master')
  with check (coalesce(rol_actual(), '') = 'master');

grant select, insert, update, delete on rel_usuarios_zonas to authenticated;
grant execute on function zonas_del_usuario(uuid) to authenticated;


-- ==================== QUIÉN CUBRE QUÉ =======================================

create or replace view v_usuarios_zonas as
select
  u.id_usuario,
  u.nombre,
  u.email,
  u.rol,
  u.activo,
  zp.nombre                                as zona_principal,
  count(z.id_zona)                         as n_zonas,
  string_agg(z.nombre, ', ' order by z.nombre) as zonas
from m_usuarios u
left join m_zonas zp on zp.id_zona = u.id_zona
left join rel_usuarios_zonas uz on uz.id_usuario = u.id_usuario
left join m_zonas z on z.id_zona = uz.id_zona
group by u.id_usuario, u.nombre, u.email, u.rol, u.activo, zp.nombre;

alter view v_usuarios_zonas set (security_invoker = true);
grant select on v_usuarios_zonas to authenticated;
