# Notas de mantenimiento v1.2.0

- No borre `data/evaluaciones_personal.sqlite3` durante una actualización.
- Al iniciar v1.2.0, la migración agrega usuarios, sesiones, departamentos y puestos sin eliminar tablas anteriores.
- La cuenta inicial `admin` solo se crea cuando la base no contiene usuarios.
- No exponga el puerto 8765 directamente a Internet; está diseñado para red local privada.
- Para agregar un nuevo criterio del Excel, actualice `AREAS` y `AREA_COLUMNS` de forma coordinada.
- Los puestos desactivados permanecen en evaluaciones históricas, pero ya no aparecen para nuevas capturas.
- Un departamento no puede desactivarse mientras tenga capturistas activos.
- Solo el administrador puede eliminar evaluaciones y descargar el respaldo general.
- Pruebas: `python -m pytest -q`.
