# Arquitectura v1.2.0

## Servidor

`ThreadingHTTPServer` expone un único host local. La ruta principal sirve la interfaz de acceso; los enlaces históricos `/captura/1` y `/captura/2` continúan abriendo la misma pantalla para no romper accesos guardados.

## Seguridad de acceso

- Usuario y contraseña por persona.
- Hash PBKDF2-HMAC-SHA256 con sal aleatoria y 240,000 iteraciones.
- Token de sesión aleatorio; en SQLite solo se almacena su SHA-256.
- Cookie HttpOnly, SameSite=Lax y expiración de 12 horas.
- Cambio obligatorio de contraseñas temporales.
- Las decisiones de departamento y capturista se toman en el servidor, no se confía en el JSON del navegador.

## Modelo de datos

- `departments`: áreas operativas.
- `positions`: puestos asociados a un departamento.
- `users`: administradores y capturistas.
- `sessions`: sesiones autenticadas.
- `evaluations`: evaluación, departamento y usuario que realizó la última captura.
- `area_results`: puntuaciones y observaciones.
- `employees`: nombres normalizados.
- `employee_department_positions`: último puesto conocido por persona dentro de cada departamento.

## Concurrencia

- Una conexión SQLite por solicitud.
- WAL, synchronous NORMAL y busy timeout de 30 segundos.
- Guardados completos con BEGIN IMMEDIATE.
- UUID idempotente y revisión optimista.
- `sqlite3.backup` para instantáneas consistentes.

## Exportación

El departamento se usa únicamente como filtro interno. `export_to_template` escribe los registros sobre la plantilla A:X sin agregar columnas. La exportación global crea un archivo Excel independiente por departamento dentro de un ZIP.
