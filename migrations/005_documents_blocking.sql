-- Un documento puede condicionar el vuelo.
--
-- El semáforo de RAAC 61.060(a)(1) tiene cuatro condiciones fijas, pero un piloto
-- de escuela vive con exigencias que la norma no enumera —cuota del aeroclub,
-- adaptación a la aeronave, autorización del instructor, curso interno—. Hoy esas
-- se cargan como `otro` y no condicionan nada: quedan de adorno en una lista.
--
-- De menos a más restrictivo:
--
--   'nada'       informativo (default: nada ya cargado cambia de significado)
--   'pasajeros'  vencido => volás solo, sin pasajeros
--   'solo'       vencido => sólo con instructor, y ese vuelo es el que lo renueva
--   'vuelo'      vencido => no volás
--
-- 'solo' es la semántica del repaso de vuelo de 61.135.
--
-- Aplicada en producción el 2026-08-06 (en dos pasos; consolidada acá).
alter table public.documents
  add column blocking text not null default 'nada'
  check (blocking in ('nada', 'pasajeros', 'solo', 'vuelo'));

comment on column public.documents.blocking is
  'Qué pasa cuando este documento vence: nada (informativo), pasajeros (no llevar pasajeros), solo (sólo con instructor) o vuelo (no volar).';
