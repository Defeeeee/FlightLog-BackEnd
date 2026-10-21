-- 030 — Vuelos traídos del CAD de ANAC a Vector (2026-10-21).
--
-- El camino inverso de la 029: el piloto que ya declaró sus vuelos en el CAD los trae a
-- Vector con el mismo marcador (ver la bitácora del frontend, 2026-10-21). Son vuelos ya
-- volados y, en general, ya pagados: **no generan cobro** en el modo saldo, ni al crearse
-- ni al editarse después. Por eso la marca queda en la fila y no sólo en el pedido.

alter table public.flights add column if not exists traido_del_cad boolean not null default false;

comment on column public.flights.traido_del_cad is
  'El vuelo se trajo del CAD de ANAC: no genera cobro en el modo saldo.';
