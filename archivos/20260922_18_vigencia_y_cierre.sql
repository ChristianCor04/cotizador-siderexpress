-- ============================================================================
-- 18 — Vigencia hasta medianoche y cierre de negociaciones
-- Requiere: 01 a 17
--
-- Tres cambios:
--   1. La cotización vence a la medianoche del MISMO día en que se emitió.
--   2. Un cliente no puede tener dos negociaciones abiertas a la vez.
--   3. Función para cerrar una negociación con su motivo.
-- ============================================================================

-- ================= 1. VIGENCIA HASTA LA MEDIANOCHE ==========================
-- Ojo con la zona horaria: el servidor de Supabase trabaja en UTC, así que
-- "medianoche" hay que calcularla en hora de Perú o se corre 5 horas.

update m_parametros
   set valor = '0',
       descripcion = 'Días adicionales de vigencia. 0 = vence a la medianoche del mismo día.'
 where clave = 'dias_vigencia_cotizacion';

create or replace function public.set_vencimiento_cotizacion()
returns trigger
language plpgsql
as $$
declare
  v_dias integer := coalesce(parametro_num('dias_vigencia_cotizacion'), 0)::int;
begin
  if new.fecha_vencimiento is null then
    -- Se pasa a hora de Lima, se trunca al día, se suma un día (la medianoche
    -- siguiente) y se vuelve a convertir a timestamptz.
    new.fecha_vencimiento :=
      (date_trunc('day', new.fecha at time zone 'America/Lima')
       + make_interval(days => v_dias + 1)) at time zone 'America/Lima';
  end if;
  return new;
end $$;

comment on function public.set_vencimiento_cotizacion is
  'Vence a la medianoche de Lima. Con el parámetro en 0, el mismo día de emisión.';

-- La tarea que vence cotizaciones debe correr DESPUÉS de esa medianoche.
-- Medianoche en Lima = 05:00 UTC, así que se programa a las 05:10 UTC:
--   select cron.schedule('vencer-cotizaciones', '10 5 * * *',
--                        $$select vencer_cotizaciones()$$);


-- ============ 2. UNA SOLA NEGOCIACIÓN ABIERTA POR CLIENTE ===================
-- security definer: la negociación abierta puede ser de OTRO asesor, y el RLS
-- se la ocultaría. Necesitamos verla para poder avisar.

create or replace function public.negociacion_abierta_de_cliente(p_id_cliente bigint)
returns table (
  id_negociacion bigint,
  estado         text,
  fecha_inicio   timestamptz,
  asesor         text,
  es_mia         boolean
)
language sql
stable
security definer
set search_path = public
as $$
  select n.id_negociacion,
         n.estado,
         n.fecha_inicio,
         coalesce(u.nombre, 'sin asignar'),
         n.id_usuario = auth.uid()
  from fact_negociaciones n
  left join m_usuarios u on u.id_usuario = n.id_usuario
  where n.id_cliente = p_id_cliente
    and n.estado in ('abierta', 'por_cerrar')
  order by n.fecha_inicio desc
  limit 1
$$;

comment on function public.negociacion_abierta_de_cliente is
  'Devuelve lo mínimo de la negociación abierta de un cliente, aunque sea de '
  'otro asesor, para poder avisar que no se puede crear otra.';


create or replace function public.validar_negociacion_unica()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_abierta bigint;
begin
  select id_negociacion into v_abierta
  from fact_negociaciones
  where id_cliente = new.id_cliente
    and estado in ('abierta', 'por_cerrar')
  limit 1;

  if v_abierta is not null then
    raise exception
      'Este cliente ya tiene una negociación activa (NEG-%). Para crear una '
      'nueva debe dar por finalizada la anterior.',
      lpad(v_abierta::text, 5, '0');
  end if;

  return new;
end $$;

drop trigger if exists trg_negociacion_unica on fact_negociaciones;
create trigger trg_negociacion_unica
  before insert on fact_negociaciones
  for each row execute function validar_negociacion_unica();

-- Nota: la regla se aplica solo al CREAR. Reabrir una negociación al anular
-- una venta sigue permitido, aunque el cliente ya tenga otra abierta: son
-- casos raros y bloquearlos dejaría la anulación sin poder ejecutarse.


-- ================== 3. CERRAR UNA NEGOCIACIÓN ===============================

create or replace function public.cerrar_negociacion(
  p_id_negociacion bigint,
  p_id_motivo      bigint
)
returns void
language plpgsql
security invoker
as $$
declare
  v_estado text;
begin
  select estado into v_estado
  from fact_negociaciones where id_negociacion = p_id_negociacion;

  if v_estado is null then
    raise exception 'La negociación no existe o no tienes acceso.';
  end if;
  if v_estado = 'ganada' then
    raise exception 'No se puede cerrar una negociación ganada.';
  end if;
  if p_id_motivo is null then
    raise exception 'Indica el motivo del cierre.';
  end if;

  -- Una negociación con una venta viva no se cierra como perdida
  if exists (
    select 1 from fact_ventas
    where id_negociacion = p_id_negociacion and estado <> 'anulada'
  ) then
    raise exception
      'Esta negociación tiene una venta registrada. Anúlala antes de cerrarla.';
  end if;

  -- Las cotizaciones que seguían vivas quedan rechazadas
  update fact_cotizaciones
     set estado = 'rechazada'
   where id_negociacion = p_id_negociacion
     and estado in ('enviada', 'aceptada');

  update fact_negociaciones
     set estado            = 'perdida',
         id_motivo_perdida = p_id_motivo,
         fecha_cierre      = now()
   where id_negociacion = p_id_negociacion;
end $$;


grant execute on function negociacion_abierta_de_cliente(bigint) to authenticated;
grant execute on function cerrar_negociacion(bigint, bigint) to authenticated;
