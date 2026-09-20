# Evaluación de Personal v1.2.0

Aplicación web local en Python para capturar evaluaciones desde teléfonos y computadoras, usando cuentas individuales, departamentos, puestos configurables, una sola base SQLite y exportaciones sobre el Excel institucional original.

## Primer inicio

1. Ejecute `INICIAR.bat` en la computadora que funcionará como servidor.
2. Mantenga abierta la ventana negra durante toda la captura.
3. La consola mostrará:
   - Administración local: `http://127.0.0.1:8765`
   - Host para capturistas: `http://IP-DE-LA-PC:8765`
4. Todos los teléfonos abren el mismo host e inician sesión con su propia cuenta.
5. Los teléfonos y la computadora deben estar conectados a la misma red Wi-Fi.

### Cuenta inicial

En el primer arranque se mantiene el usuario `admin`, pero **ya no existe una contraseña universal en el código**. Si no define `EVALUACION_ADMIN_PASSWORD`, la aplicación genera una contraseña aleatoria, la muestra en la consola y la conserva temporalmente sólo en `data/.initial_admin_password` (ignorado por Git) hasta que el administrador la cambie.

También puede fijar explícitamente la contraseña de aprovisionamiento antes del primer arranque:

```powershell
$env:EVALUACION_ADMIN_PASSWORD = "use-una-clave-temporal-propia"
python main.py
```

El primer acceso obliga a cambiar esa contraseña. Después, use `Administración` para crear los capturistas y entregarles:

- El host mostrado por la consola.
- Su nombre de usuario.
- Su contraseña temporal.

Cada capturista también debe cambiar su contraseña temporal al entrar por primera vez.

## Departamentos y puestos

La migración crea automáticamente:

- Departamento: `ADQUISICIÓN (REGISTRO)`.
- Los nueve puestos que ya existían en las versiones anteriores.
- Todas las evaluaciones previas quedan asignadas a ese departamento sin perder datos.

Desde la cuenta administradora puede:

- Crear nuevos departamentos.
- Activar o desactivar departamentos sin registros borrados.
- Crear puestos específicos dentro de cada departamento.
- Activar o desactivar puestos conservando el historial.
- Crear y desactivar cuentas de capturistas.
- Restablecer contraseñas temporales.

## Permisos

### Administrador

- Consulta todos los departamentos.
- Captura seleccionando el departamento.
- Administra usuarios, departamentos y puestos.
- Elimina evaluaciones.
- Descarga respaldos generales.
- Exporta un departamento o todos los departamentos.

### Capturista

- Solo ve el departamento asignado.
- Solo recibe los puestos y el autocompletado de ese departamento.
- Puede capturar y corregir evaluaciones de su departamento.
- Puede exportar el Excel de su departamento.
- No puede eliminar registros ni descargar la base general.

El servidor ignora cualquier intento del teléfono de cambiar manualmente el departamento enviado. La asignación se determina con la sesión iniciada.

## Excel institucional

El departamento se guarda en SQLite, pero **no se agrega ninguna columna al Excel**.

Al exportar:

- Se selecciona un departamento.
- Solo se incluyen las evaluaciones pertenecientes a ese departamento.
- Se conserva exactamente la plantilla A:X.
- Continúan disponibles la exportación por fechas y la descarga total sin fechas.

La opción administradora `Descargar Excel de todos los departamentos` genera un ZIP con un Excel institucional independiente para cada departamento.

## Captura simultánea segura

La aplicación conserva:

- `ThreadingHTTPServer` para atender varios equipos.
- SQLite en modo WAL.
- `busy_timeout=30000`.
- Transacciones `BEGIN IMMEDIATE`.
- UUID de captura contra doble envío.
- Revisión optimista contra sobrescrituras antiguas.
- Validación de duplicado por empleado, fecha y departamento.
- Sesiones individuales con cookies `HttpOnly` y `SameSite=Lax`.
- Contraseñas protegidas con PBKDF2-HMAC-SHA256 y sal aleatoria.

## Respaldo

El respaldo administrativo contiene:

- La base SQLite completa.
- Usuarios, departamentos, puestos y evaluaciones.
- Un Excel por departamento.
- Manifiesto con SHA-256 y tamaño de cada archivo.

## Requisitos

- Windows con Python 3.11, 3.12 o 3.13 de 64 bits.
- Sin dependencias externas para ejecutar.
- Chrome recomendado en Android para reconocimiento de voz.
- Red local privada. No publique el puerto 8765 directamente en Internet.

## Datos

- Base: `data/evaluaciones_personal.sqlite3`
- Plantilla: `assets/ESQUELETO FORMATO.xlsx`
- Exportaciones: `exports/`

La actualización desde v1.0.0, v1.1.0 o v1.1.1 es automática y no elimina evaluaciones.

## Pruebas

```bat
py -3 -m pip install -r requirements-dev.txt
py -3 -m pytest -q
```
