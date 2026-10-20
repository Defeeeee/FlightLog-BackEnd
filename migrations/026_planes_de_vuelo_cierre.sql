-- 026 — Cómo termina un plan de vuelo (2026-10-20).
--
-- Tres finales, y ninguno toca `flights` ni el saldo (un plan no es un vuelo):
--
-- - `vuelo_id`: el vuelo de la bitácora que se registró desde este plan. Lo pone el
--   frontend después de que `POST /flights` lo creó, y la API comprueba que el vuelo sea
--   del mismo piloto. Si se borra el vuelo, el plan queda sin él (`set null`).
-- - `cancelado_at`: se mandó la cancelación (CNL, AIP ENR 1.10 Apéndice 5) a la oficina.
-- - `descartado_at`: el piloto dijo "no lo volé" en el inicio, sin mandar nada.
--
-- Con cualquiera de los tres, el inicio deja de preguntar "¿ya volaste?".

alter table public.planes_de_vuelo
  add column if not exists vuelo_id uuid references public.flights (id) on delete set null;
alter table public.planes_de_vuelo add column if not exists cancelado_at timestamptz;
alter table public.planes_de_vuelo add column if not exists descartado_at timestamptz;

comment on column public.planes_de_vuelo.vuelo_id is
  'El vuelo registrado desde este plan. Un plan no es un vuelo: esto sólo los une.';
comment on column public.planes_de_vuelo.cancelado_at is 'Cuándo se mandó la cancelación (CNL) a la oficina.';
comment on column public.planes_de_vuelo.descartado_at is 'Cuándo el piloto dijo que no lo voló, sin mandar nada.';
