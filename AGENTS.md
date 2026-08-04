# AGENTS.md — Bitácora de agentes de FlightLog-BackEnd

Este archivo es la **bitácora obligatoria** de todo agente de IA que modifique
este repositorio. Igual que un piloto no cierra un vuelo sin cargarlo en el
libro, ningún agente cierra una tanda de cambios sin dejar su entrada acá.

## Orientación rápida

- **Este repo es el backend** (Python + Litestar + Supabase).
  El frontend vive en `/Users/defeee/Vector/Vector-FrontEnd` (Next.js 16 App Router).
- **Los controladores** están en `src/controllers/` y los modelos en `src/models/`.
- **Las migraciones de SQL** viven en `migrations/`.
- **Tests**: Ejecutar `python test_audit_engine.py` para probar las reglas de auditoría.
- **Políticas de entorno**: Los archivos `.env` deben estar siempre en `.gitignore` y NUNCA commitearse.

---

## Proceso obligatorio

**Es obligatorio para cada agente.** Sin excepciones, sin "lo anoto después".

1. **Antes de empezar**, leé las entradas existentes al final de este archivo.
   Te dicen qué se tocó recién, por qué, y qué quedó pendiente o a medias.
2. **A medida que hacés cambios**, escribí la entrada. No al final de todo:
   si la sesión se corta, el trabajo sin registrar queda huérfano.
3. **Una entrada por tanda coherente de cambios** (una fase, una feature, un
   fix). No una por archivo, no una por sesión entera de ocho horas.
4. **Las entradas se agregan al final**, en orden cronológico. Nunca se
   reescribe ni se borra una entrada anterior — si algo salió mal o se
   revirtió, se escribe una entrada nueva que lo diga.
5. **El timestamp va en UTC**, obtenido de verdad (`date -u`), no estimado.
6. **La justificación no es opcional.** "Pedido del usuario" no alcanza:
   explicá *por qué esa solución* y qué alternativa descartaste. El próximo
   agente necesita el razonamiento, no el changelog — el changelog ya está en
   `git log`.
7. **Si algo quedó a medias, roto o bloqueado, se dice.** Una entrada que
   miente sobre el estado del repo es peor que no tener entrada.

---

## Template

Copiá este bloque tal cual y completalo:

```markdown
### YYYY-MM-DD HH:MM UTC — <Agente / modelo> — <Título corto de la tanda>

**Quién:** <nombre del agente, modelo y en nombre de quién trabaja>

**Qué cambié:**
- `ruta/al/archivo.py` — qué se hizo ahí, en una línea.
- `ruta/al/otro.sql` — ídem.

**Por qué:** El razonamiento. Qué problema resuelve, qué alternativas se
evaluaron y por qué se descartaron, qué restricción del proyecto lo condiciona.

**Estado:** Terminado / Parcial / Bloqueado — y si no está terminado, qué falta
exactamente y qué es lo próximo.

**Verificación:** Cómo se comprobó que funciona (tests, curl, etc.). Si no se verificó, decirlo explícitamente.
```

---

## Bitácora

### 2026-08-04 12:17 UTC — Antigravity (Gemini 3.6 Flash) — Creación de AGENTS.md y registro de feature múltiples libros

**Quién:** Antigravity (Gemini 3.6 Flash), para Federico Díaz Nemeth.

**Qué cambié:**
- `AGENTS.md` (nuevo) — creación del archivo de bitácora del backend con las mismas políticas y estructura que el repositorio frontend.
- Registrado de los cambios de `feat(logbooks)`:
  - `migrations/001_logbooks.sql` — migración para tabla `logbooks`, FK en `flights.logbook_id` y backfill de libro por defecto.
  - `src/models/logbook.py` y `src/controllers/logbooks.py` — modelo Pydantic y endpoints de gestión de libros.
  - `src/controllers/flights.py` y `src/models/flight.py` — soporte y fallback `_default_logbook_id` para asignación automática al crear vuelos.

**Por qué:** Se alinea el backend con la política obligatoria de documentación y trazabilidad de agentes definida en `AGENTS.md`. Se documenta la implementación de la feature de múltiples libros de vuelo aprobada en el plan post-flightdeck.

**Estado:** Terminado. PR creada en https://github.com/Defeeeee/FlightLog-BackEnd/pull/4

**Verificación:** `python test_audit_engine.py` pasa correctamente. `git status` limpio. Rama `feat/logbooks` pusheada a origin.
