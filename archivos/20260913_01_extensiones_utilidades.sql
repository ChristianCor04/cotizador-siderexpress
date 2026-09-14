-- ============================================================================
-- 01 — Extensiones, dominios y funciones de utilidad
-- Cotizador SIDEREXPRESS
-- Ejecutar PRIMERO. Todo lo demás depende de este archivo.
-- ============================================================================

-- ---------------------------------------------------------------- extensiones
-- btree_gist: lo necesita la restricción que impide vigencias de precio
-- traslapadas en h_precios (archivo 03).
create extension if not exists btree_gist with schema extensions;

-- pg_cron: tarea nocturna que vence cotizaciones.
-- En Supabase se activa desde Database > Extensions. Esta línea es solo respaldo.
-- create extension if not exists pg_cron;


-- ------------------------------------------------------------------- dominios
-- Un dominio es un tipo de dato propio con su regla incluida.
-- Se define una vez y se reutiliza en todas las tablas que lo necesiten.

-- Teléfono peruano en formato internacional: +51 + 8 dígitos (fijo) o 9 (celular).
do $$
begin
  if not exists (select 1 from pg_type where typname = 'telefono_pe') then
    create domain telefono_pe as text
      check (value ~ '^\+51[0-9]{8,9}$');
  end if;
end $$;

comment on domain telefono_pe is
  'Teléfono peruano normalizado: +51 seguido de 8 o 9 dígitos. Ej. +51987654321';


-- ------------------------------------------------------------------ funciones
-- Mantiene updated_at al día sin que la aplicación tenga que acordarse.
-- Se engancha como trigger BEFORE UPDATE en cada tabla que tenga esa columna.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end $$;

comment on function public.set_updated_at is
  'Trigger BEFORE UPDATE: actualiza updated_at con la hora del servidor.';

-- Nota: la función rol_actual(), que usan las políticas RLS, se crea en el
-- archivo 04 porque necesita que la tabla m_usuarios ya exista.
