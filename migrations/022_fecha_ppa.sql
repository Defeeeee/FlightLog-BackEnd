-- 022 — La fecha en que el piloto rindió la PPA (2026-09-24).
--
-- Decisión de Federico: los alumnos pilotos no tienen libro de vuelo, y **sus horas de
-- alumno no cuentan una vez que rinden la PPA**. Cuando un alumno cambia su licencia a
-- PPA, el frontend le pide esta fecha, y el camino a la PCA y el libro en PDF cuentan
-- los vuelos desde ahí.
--
-- **Nullable y sin valor por defecto a propósito:** quien nunca fue alumno en Vector no
-- la tiene, y para él todo sigue igual (se cuentan todos sus vuelos). No se completa
-- para nadie: no hay forma de saberla, y una fecha inventada le borraría horas a alguien.
alter table public.profiles add column if not exists fecha_ppa date;

comment on column public.profiles.fecha_ppa is
  'Cuándo rindió la PPA. Los vuelos anteriores son de alumno y no cuentan para la PCA ni el libro. NULL = nunca fue alumno en Vector: cuentan todos.';
