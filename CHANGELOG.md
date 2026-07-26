# Changelog

## 1.2.0 — 2026-07-25

- Cuenta administradora inicial con cambio obligatorio de contraseña.
- Inicio de sesión individual para cada capturista usando un solo host.
- Contraseñas PBKDF2-HMAC-SHA256, sesiones HttpOnly y expiración de 12 horas.
- Alta, desactivación y restablecimiento de contraseña de capturistas.
- Catálogo administrable de departamentos y puestos por departamento.
- Migración automática de registros previos a ADQUISICIÓN (REGISTRO).
- Trazabilidad por usuario y departamento en la base general.
- Aislamiento de consultas y capturas para usuarios no administradores.
- Duplicados evaluados por empleado, fecha y departamento.
- Exportación del Excel institucional por departamento sin agregar columnas.
- ZIP administrador con un Excel por cada departamento.
- Respaldo general con BD, Excel por departamento y manifiesto SHA-256.
- Conservación de navegación, voz, teclado móvil, borradores y limpieza automática.

## 1.1.1 — 2026-07-25

- Barra inferior consciente del teclado móvil mediante `VisualViewport`.
- Botones principales elevados sobre el teclado y reorganizados en una fila compacta.
- Centrado automático del campo activo para evitar que quede oculto.
- Limpieza automática del formulario después de guardar una evaluación final.
- La pestaña `Nueva evaluación` abre inmediatamente una captura vacía, sin recargar.
- Nuevo botón para exportar toda la base sin fechas e incluyendo finales y borradores.
- Versionado en las URLs de CSS y JavaScript para evitar cargar archivos antiguos desde caché.

## 1.1.0 — 2026-07-25

- Botón «Anterior» visible y estable en teléfono, sin quedar oculto por desplazamiento horizontal.
- Botón adicional para volver al área previa dentro de cada sección.
- Revisión final con botón «Editar» para datos generales y para cada una de las cinco áreas.
- Dos enlaces independientes: Capturista 1 y Capturista 2.
- Una sola base SQLite central para ambos teléfonos.
- SQLite WAL, `busy_timeout`, transacciones `BEGIN IMMEDIATE` y servidor multihilo.
- UUID de captura para impedir filas duplicadas por doble toque o repetición de red.
- Control de revisión optimista para impedir que una versión antigua sobrescriba una edición reciente.
- Bloqueo de evaluaciones finales duplicadas del mismo empleado en la misma fecha.
- Registro del capturista que realizó la última modificación.
- Un único Excel consolidado con todas las capturas.
- Respaldo consistente mediante la API `sqlite3.backup` aun con capturas activas.

## 1.0.0 — 2026-07-25

- Primera versión funcional.
- Captura móvil secuencial por cinco áreas.
- Voz para nombre y comentarios con corrección manual.
- Calificaciones 3/2/1 o blanco.
- Borradores y evaluaciones finales.
- SQLite como fuente de verdad.
- Autocompletado de personal y recuperación de su última categoría.
- Exportación exacta sobre la plantilla institucional A:X.
- Respaldo ZIP con BD, Excel y manifiesto SHA-256.
- Interfaz adaptable a teléfono y computadora.
