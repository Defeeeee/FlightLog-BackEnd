-- 025 — Los envíos de un plan de vuelo por mail (2026-10-19).
--
-- Vector manda el plan a la oficina ARO/AIS con el PDF firmado, como FPL.AR (AIC A
-- 19/2026: "firmado, digitalizado y enviado como adjunto (en PDF)"). Antes se manda una
-- prueba al mail del piloto, para ver cómo le llega a la oficina.
--
-- `envios` es la lista de lo que salió: [{ "modo": "prueba" | "aro", "a": "acfdo@…",
-- "resend_id": "…", "at": "…" }]. La escribe el backend con su hora, y `enviado_at` es la
-- del último envío **a la oficina** (las pruebas no cuentan): es lo que la lista muestra
-- como "Enviado".
--
-- Un tope de 20 envíos por plan, en la API: es un plan, no una lista de correo.

alter table public.planes_de_vuelo add column if not exists envios jsonb not null default '[]'::jsonb;
alter table public.planes_de_vuelo add column if not exists enviado_at timestamptz;

comment on column public.planes_de_vuelo.envios is
  'Envíos por mail del plan: [{modo: prueba|aro, a, resend_id, at}]. Los anota el backend.';
comment on column public.planes_de_vuelo.enviado_at is
  'Último envío a la oficina ARO/AIS (las pruebas no cuentan).';
