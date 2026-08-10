-- R4 del plan 08 — el Repaso de Vuelo como documento.
--
-- RAAC 61.135(a): ninguna persona puede actuar como piloto al mando a menos que en
-- los 24 meses anteriores al mes en que actúe haya efectuado un repaso de vuelo con
-- instructor y porte el libro firmado por quien lo efectuó.
--
-- Es una de las cuatro condiciones de 61.060(a)(1) y la única que Vector no tenía.
-- No se puede derivar de los vuelos: la norma pide la firma de un instructor, y no
-- hay ni firmas ni un código de finalidad que lo identifique. Por eso se modela
-- como un documento más, al lado del CMA, y así hereda la lista de vencimientos y
-- los avisos por WhatsApp que ya funcionan.
--
-- Aplicada en producción el 2026-08-06. Va **antes** que el frontend: el CHECK
-- rechazaría el valor nuevo y el piloto vería un error al guardar.
alter table public.documents drop constraint documents_kind_check;

alter table public.documents add constraint documents_kind_check
  check (kind = any (array[
    'cma', 'licencia', 'habilitacion', 'seguro', 'aeronavegabilidad',
    'repaso_vuelo',
    'otro'
  ]));
