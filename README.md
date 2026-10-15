# Descubre+ MVP 0.3

Aplicación web responsiva integrada con API FastAPI y SQLite. Incluye registro/inicio de sesión de clientes y restaurantes, búsqueda por código postal, alta de restaurantes, publicación de promociones, emisión de códigos únicos y canje de un solo uso, además de historial de visitas.

## Iniciar en una computadora

Requiere Python 3.10 o superior. Dentro de esta carpeta:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Abre http://127.0.0.1:8000 en el navegador. La base de datos `descubre.db` se crea automáticamente.

## Flujo de prueba

1. Crear cuenta tipo restaurante e iniciar sesión.
2. En Mi negocio, registrar un restaurante y publicar una promoción.
3. Cerrar sesión, crear cuenta tipo cliente e iniciar sesión.
4. En Explorar, obtener una promoción y copiar el código.
5. Cerrar sesión, entrar con la cuenta restaurante y validar el código en Mi negocio.
6. Revisar el historial de visitas y comprobar que un segundo canje del mismo código se rechaza.

## Límites antes de producción

Este paquete es un MVP local, **no** un servicio alojado ni preparado para operar públicamente con usuarios reales. Requiere HTTPS, base de datos administrada, gestión de sesiones segura, recuperación de contraseñas, límites de solicitudes, correo de verificación, protección antiabuso, avisos de privacidad y términos, observabilidad y copias de seguridad. El QR se genera usando un servicio externo: **no debe usarse con datos reales sensibles**; en producción conviene generar QR localmente. El formulario de canje valida el código de texto; la lectura por cámara está pendiente. Las promociones aún no tienen fecha de caducidad ni límites de canje por persona.
