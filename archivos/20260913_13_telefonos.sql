-- ============================================================================
-- 13 — Teléfonos: aceptar varios formatos, guardar uno solo
-- Requiere: 01 a 12
--
-- Antes solo se aceptaba +51987654321 y era incómodo de escribir.
-- Ahora se aceptan estas formas:
--     987654321          (9 dígitos, sin prefijo)
--     51987654321        (con código de país, sin +)
--     +51987654321       (formato internacional)
--     +51 987 654 321    (con espacios o guiones)
--
-- Y todas se GUARDAN igual: +51987654321
-- Eso evita que el mismo cliente entre dos veces con formatos distintos.
-- ============================================================================

-- ------------------------------------------------- regla del dominio -------
-- No se puede cambiar un check de dominio directamente: se quita y se pone.
alter domain telefono_pe drop constraint if exists telefono_pe_check;

-- La regla del dominio es amplia a propósito: solo exige que sean números
-- con separadores razonables. La validación fina la hace el trigger, que
-- además da un mensaje de error entendible.
alter domain telefono_pe add constraint telefono_pe_check
  check (
    value ~ '^\+?[0-9][0-9 ().-]*$'
    and length(regexp_replace(value, '[^0-9]', '', 'g')) between 8 and 11
  );

comment on domain telefono_pe is
  'Teléfono peruano. Acepta con o sin +51; se guarda siempre como +51XXXXXXXXX.';


-- ------------------------------------------------------ normalización ------
create or replace function public.normalizar_telefono(p_texto text)
returns text
language plpgsql
immutable
as $$
declare
  v_digitos text;
begin
  if p_texto is null or trim(p_texto) = '' then
    return null;
  end if;

  -- Deja solo los números: quita +, espacios, guiones y paréntesis
  v_digitos := regexp_replace(p_texto, '[^0-9]', '', 'g');

  -- Si ya trae el código de país, se lo quitamos para volver a armarlo igual
  if length(v_digitos) in (10, 11) and left(v_digitos, 2) = '51' then
    v_digitos := substr(v_digitos, 3);
  end if;

  -- Fijos escritos con el 0 de larga distancia: 044 123456 -> 44 123456
  if length(v_digitos) = 9 and left(v_digitos, 1) = '0' then
    v_digitos := substr(v_digitos, 2);
  end if;

  if length(v_digitos) not between 8 and 9 then
    raise exception
      'Teléfono inválido: "%". Debe tener 8 o 9 dígitos, con o sin el 51 adelante.',
      p_texto;
  end if;

  return '+51' || v_digitos;
end $$;

comment on function public.normalizar_telefono is
  'Convierte cualquier formato de teléfono peruano a +51XXXXXXXXX.';


-- --------------------------------------------------------- triggers --------
-- Se aplica antes de guardar, así da igual cómo lo escriba el asesor.

create or replace function public.trg_normalizar_telefono_cliente()
returns trigger
language plpgsql
as $$
begin
  new.telefono := normalizar_telefono(new.telefono);
  return new;
end $$;

drop trigger if exists trg_cliente_telefono on m_clientes;
create trigger trg_cliente_telefono
  before insert or update of telefono on m_clientes
  for each row execute function trg_normalizar_telefono_cliente();

create or replace function public.trg_normalizar_telefono_sede()
returns trigger
language plpgsql
as $$
begin
  if new.telefono is not null then
    new.telefono := normalizar_telefono(new.telefono);
  end if;
  return new;
end $$;

drop trigger if exists trg_sede_telefono on m_sedes;
create trigger trg_sede_telefono
  before insert or update of telefono on m_sedes
  for each row execute function trg_normalizar_telefono_sede();


-- ------------------------------------ normalizar lo que ya está guardado ---
update m_clientes
   set telefono = normalizar_telefono(telefono)
 where telefono is not null and telefono not like '+51%';

update m_sedes
   set telefono = normalizar_telefono(telefono)
 where telefono is not null and telefono not like '+51%';


-- ---------------------------------------------------- buscar sin formato ---
-- Para que el buscador de la app encuentre al cliente escriba como escriba.
create or replace function public.buscar_cliente(p_telefono text)
returns setof m_clientes
language sql
stable
as $$
  select * from m_clientes
  where telefono = normalizar_telefono(p_telefono)
$$;

comment on function public.buscar_cliente is
  'Busca un cliente por teléfono en cualquier formato.';
