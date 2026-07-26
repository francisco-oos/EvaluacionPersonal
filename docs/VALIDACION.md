# Validación v1.2.0

Ejecutar desde la raíz:

```text
python -m pytest -q
```

Cobertura funcional:

- Inicio de sesión y cambio obligatorio de contraseña.
- Alta de departamento, puesto y capturista.
- Sesión limitada al departamento asignado.
- Captura asociada al usuario autenticado.
- Bloqueo de eliminación para capturistas.
- Duplicados por empleado, fecha y departamento.
- Concurrencia de dos usuarios con 60 evaluaciones.
- Exportación A:X sin columna de departamento.
- ZIP con un Excel por departamento.
- Controles móviles, navegación, teclado y exportación total.

Resultado esperado: `6 passed`.
