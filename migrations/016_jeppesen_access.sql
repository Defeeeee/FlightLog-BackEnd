-- 016 — Quién puede ver las cartas Jeppesen.
--
-- El piloto tiene una carpeta de cartas Jeppesen en el servidor del backend
-- (`Charts/Argentina/<ICAO>/<categoría>/*.pdf`, cientos de PDF) y quiere que Vector
-- las muestre — hoy sólo para su propia cuenta, más adelante con niveles pagos.
--
-- ---------------------------------------------------------------------------
-- Por qué un booleano y no ya un esquema de niveles
-- ---------------------------------------------------------------------------
--
-- Porque hoy hay un solo piloto con acceso y se lo pone a mano. Un esquema de tiers
-- sin un solo piloto pagando todavía sería diseñar contra un requisito que no existe
-- — la sección "Lo que este plan no hace" del resto del repo es exactamente por
-- esto. Cuando haya un flujo de pago de verdad, migrar de un booleano a una tabla de
-- suscripciones es un cambio chico; lo caro sería lo inverso.
--
-- ---------------------------------------------------------------------------
-- Por qué NO va en `ProfileUpdate`
-- ---------------------------------------------------------------------------
--
-- **Este campo es a propósito invisible para el propio piloto.** `PATCH /profiles`
-- usa `ProfileUpdate`, que sólo declara los campos que un piloto puede tocar de sí
-- mismo — y `jeppesen_access` no está entre ellos. Agregarlo ahí sería dejar que
-- cualquiera se autoconceda acceso a contenido pago con un PATCH. Se lee en
-- `Profile` (así el propio front sabe si mostrar la sección) y se escribe sólo por
-- SQL directo o, el día de mañana, por el flujo de pago — nunca por el piloto.
--
-- `NOT NULL DEFAULT false`: no hay una interpretación de "no sé" que tenga sentido
-- acá — sin la columna, nadie tenía acceso, así que `false` es el hecho y no una
-- suposición.

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS jeppesen_access boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.profiles.jeppesen_access IS
  'true = puede ver y descargar las cartas Jeppesen del servidor. Se escribe a mano '
  'o por el flujo de pago, nunca por PATCH /profiles del propio piloto.';
