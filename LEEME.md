# Cotizador SIDEREXPRESS

## Qué hay en cada archivo

```
app.py                     Se ejecuta esto. Login y menú.
config.py                  Conexión a Supabase y valores que puedes cambiar.
db.py                      TODAS las consultas a la base. Nada más habla con Supabase.
logica/
  geo.py                   Distancias y coordenadas desde un link de Maps.
  cotizacion.py            Reglas de negocio: a qué ferreterías se pide precio.
  pdf.py                   Cómo se ve el PDF de la cotización.
sesion.py                  Mantiene la sesión al recargar la página (F5).
paginas/
  login.py                 Pantalla de login.
  negociaciones.py         Pantalla principal (lista + materiales + ferreterías).
```

## Dónde tocar según lo que quieras cambiar

| Quiero cambiar… | Archivo |
|---|---|
| Los montos o radios de las reglas | En Supabase, tabla `m_reglas_cotizacion` |
| Días que vale una cotización | En Supabase, tabla `m_parametros` |
| Cuántas sedes se evalúan | `config.py` → `TOP_N_SEDES` |
| Cómo se calcula la canasta | `logica/cotizacion.py` |
| Cómo se ve el PDF | `logica/pdf.py` |
| Cómo se ve una pantalla | El archivo dentro de `paginas/` |
| Qué datos se traen de la base | `db.py` |

## Reglas para no romper nada

1. **Solo `db.py` habla con Supabase.** Si necesitas un dato nuevo, agrega
   una función ahí y llámala desde la pantalla.
2. **`logica/` no importa `streamlit` ni `db`.** Recibe listas y diccionarios,
   y devuelve listas y diccionarios. Así se puede probar sola.
3. **Lo que debe sobrevivir a un clic va en `st.session_state`.** Streamlit
   vuelve a ejecutar todo el archivo cada vez que tocas algo.
4. **Nunca guardes la sesión del usuario en `st.cache_data`.** Las cachés se
   comparten entre todos los usuarios de la app.


## Detalles que conviene conocer

**La marca es opcional.** Si el asesor la deja vacía, la lógica busca todas las
marcas de ese producto y se queda con la más barata de cada ferretería. En el
PDF sale la marca que realmente se eligió, para que el cliente sepa qué compra.

**Las celdas vacías vienen como `nan`, no como vacío.** Por eso existe la
función `_celda()` en `paginas/negociaciones.py`: sin ella, `if valor:` daría
verdadero en una celda vacía.

**La sesión se guarda en una cookie del navegador** que dura 7 días, para que
recargar la página no devuelva al login. Se borra al cerrar sesión.

**Guardar la cotización usa una sola llamada** (`registrar_cotizacion` en
Supabase) que graba cabecera, detalle, ferreterías evaluadas y promociones de
una vez. Si algo falla, no se guarda nada a medias.

**La venta nace de una cotización.** En el panel central aparece el bloque
«Venta» cuando la negociación ya tiene una cotización enviada. Al registrarla:

1. La cotización elegida pasa a `aceptada` y las demás a `reemplazada`.
2. Se crea la venta en estado `pendiente_validacion`, copiando los productos.
3. Un supervisor o el master la valida, y la negociación queda `ganada`.
4. Si el pago se cae, se anula con motivo y la negociación se reabre sola.

Los bonos post venta se calculan sobre lo que el cliente **realmente pagó**,
no sobre lo cotizado.

**La tabla editable se refresca con `version_tabla`.** Streamlit recuerda el
contenido de `st.data_editor` por su `key`. Si la key no cambia, al abrir otra
negociación seguiría mostrando la anterior. Por eso la key lleva un número que
sube cada vez que se cargan materiales distintos. Si agregas otra tabla
editable que también cargue datos, usa el mismo patrón.

**Hay dos formas de ubicar la obra**, y se usa la primera que esté disponible:

1. **Coordenadas** (link de Google Maps o lat/lon) → reglas 1.1, 1.2 y 1.3,
   que buscan ferreterías por distancia (2, 4 o 100 km según el monto).
2. **Departamento, provincia y distrito** → reglas 2.1 y 2.2, para el cliente
   que no quiere pasar su ubicación. Con canasta chica busca solo en su
   distrito; con canasta grande, en toda la provincia.

Los selectores de zona aparecen solos cuando no hay coordenadas válidas.
Si no hay ninguna de las dos, la app no deja cotizar.
