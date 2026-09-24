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
  precios_excel.py         Plantilla de precios y lectura del Excel cargado.
sesion.py                  Mantiene la sesión al recargar la página (F5).
assets/logo.png            Logo de la marca. Se usa en la app y en el PDF.
paginas/
  login.py                 Pantalla de login.
  negociaciones.py         Pantalla principal (lista + materiales + ferreterías).
  precios.py               Estado diario de precios, edición y carga por Excel.
  promociones.py           Crear promociones y registrar afiliaciones (solo master).
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

**La lista de materiales NO usa `st.data_editor`.** Se intentó y daba
problemas: la tabla editable guarda su propio estado y entraba en conflicto
con los datos que se le pasaban, así que las celdas se borraban al escribir.
Ahora es una barra para agregar arriba y campos sueltos por fila, cada uno
con su propia `key`. Es más predecible.

**`version_tabla` limpia la barra de agregar.** Va en la key de los campos de
producto, marca y cantidad. Al subir el número, Streamlit los trata como
nuevos y quedan vacíos para el siguiente producto. Se usa también al abrir
otra negociación.

**Hay dos formas de ubicar la obra**, y se usa la primera que esté disponible:

1. **Coordenadas** (link de Google Maps o lat/lon) → reglas 1.1, 1.2 y 1.3,
   que buscan ferreterías por distancia (2, 4 o 100 km según el monto).
2. **Departamento, provincia y distrito** → reglas 2.1 y 2.2, para el cliente
   que no quiere pasar su ubicación. Con canasta chica busca solo en su
   distrito; con canasta grande, en toda la provincia.

Los selectores de zona aparecen solos cuando no hay coordenadas válidas.
Si no hay ninguna de las dos, la app no deja cotizar.


## La pantalla de precios

Gira en torno a **dos fechas distintas** que guarda cada precio:

- `fecha_actualizacion`: cuándo cambió el monto.
- `fecha_confirmacion`: cuándo la ferretería confirmó que sigue vigente.

El botón «Mantienen precios» solo toca la segunda. Es lo que permite
distinguir un precio vigente de uno que nadie revisa hace dos semanas, y es
lo que alimenta el semáforo.

**La plantilla de Excel se descarga llena** con los precios actuales y una
columna por sede. La columna `id_sku` es la llave: si se borra, el archivo no
se puede procesar. Gracias a eso no hay que escribir nombres a mano y no se
repite el problema de «BC 6mm» contra «BC 6 mm».

**Nunca se borra un precio.** El modo «reemplazar» los marca como inactivos,
así una carga equivocada se revierte con un update.


## El ticket del CRM

Identifica la conversación del cliente y es **obligatorio para generar la
cotización**. Va arriba del panel central porque es lo primero que tiene el
asesor.

Una negociación puede tener varios tickets, porque el bot cierra la
conversación a las 2 horas y el cliente vuelve con uno nuevo. Se guardan en
`rel_negociacion_tickets` con un tipo:

| Tipo | Cuándo |
|---|---|
| `origen` | El primer ticket de la negociación |
| `seguimiento` | Un ticket nuevo al recotizar |
| `cierre` | Donde llegó el comprobante de pago |

Al abrir una negociación se propone el ticket más reciente. Si el cliente
volvió por otra conversación, el asesor lo cambia y aparece el aviso de que
se agregará como seguimiento.

El buscador acepta ticket, teléfono o número de cotización. Como un ticket
numérico puede parecerse a un número de cotización, se prueban los tres y se
muestran todas las coincidencias.


## Detalles de la última versión

**Vigencia hasta la medianoche.** La cotización vence a las 00:00 del día
siguiente, en hora de Perú. El cálculo vive en la base (trigger
`set_vencimiento_cotizacion`) porque el servidor trabaja en UTC y hacerlo en
Python daría 5 horas de diferencia. Para cambiarlo, edita el parámetro
`dias_vigencia_cotizacion` en `m_parametros`: 0 = mismo día, 1 = hasta la
medianoche siguiente.

**Un cliente, una negociación abierta.** Lo impide un trigger en la base, y
la app avisa antes: al buscar un cliente que ya tiene una activa, muestra
cuál es y quién la atiende. Si es de otro asesor, no la abre.

**El logo** está en `assets/logo.png`. Para cambiarlo, reemplaza el archivo
manteniendo el nombre; se actualiza en la app y en el PDF.

**El tema oscuro** se configura en `.streamlit/config.toml`. Los colores del
fondo y del rojo de marca están ahí.

**El botón de PDF desaparece al generarlo** y solo queda la descarga. Al
cambiar de negociación o recotizar, el PDF anterior se descarta: así nadie
envía un documento que no corresponde.


## Si la API dice que una relación es ambigua

Error típico: *"Could not embed because more than one relationship was found"*.

Pasa cuando dos tablas están unidas por más de un camino. Por ejemplo,
`fact_cotizaciones` llega a `m_sedes` por la sede elegida (`fk_cot_sede`) y
también a través de `fact_cotizaciones_ferreterias`, que es una tabla puente.

Se resuelve nombrando la llave en la consulta:

```python
.select("*, m_sedes!fk_cot_sede(codigo, nombre)")
```

Para saber qué llaves existen entre dos tablas:

```sql
select conname, conrelid::regclass, confrelid::regclass
from pg_constraint
where contype = 'f' and conrelid = 'fact_cotizaciones'::regclass;
```

En todo el modelo hay **solo dos pares de tablas** unidos a la vez por una
llave directa y por una tabla puente. Son los que obligan a precisar:

| Consulta | Hay que escribir |
|---|---|
| `fact_cotizaciones` → `m_sedes` | `m_sedes!fk_cot_sede(...)` |
| `m_usuarios` → `m_zonas` | `m_zonas!fk_usuario_zona(...)` |

Las demás tablas `rel_` no generan ambigüedad porque las tablas que unen no
están relacionadas directamente entre sí.

Ojo también con `fact_ventas`, que tiene dos caminos a `m_usuarios`
(`fk_ven_usuario` para quien registró y `fk_ven_validador` para quien validó).

Para detectarlo antes de que falle, esta consulta lista los casos:

```sql
with puentes as (
  select conrelid::regclass::text as puente,
         array_agg(confrelid::regclass::text order by confrelid::regclass::text) as une
  from pg_constraint
  where contype = 'f' and connamespace = 'public'::regnamespace
  group by conrelid having count(*) = 2
)
select p.puente, p.une[1], p.une[2]
from puentes p
where exists (select 1 from pg_constraint c
              where c.contype = 'f' and c.conrelid = p.une[1]::regclass
                and c.confrelid = p.une[2]::regclass);
```


## Documento del cliente

Tipo y número son **opcionales**: se puede cotizar y vender sin ellos. Pero si
se llena uno hay que llenar el otro, porque la base no acepta un tipo sin
número ni al revés.

Cuando sí se llenan, la app valida el formato antes de guardar (DNI de 8
dígitos, RUC de 11) para dar un mensaje claro en vez del error crudo de la
base. CE y pasaporte aceptan cualquier formato.

El documento aparece en el PDF de la cotización.


## Unidades de venta

Un mismo producto se puede cotizar en varias unidades, y **cada una tiene su
propio precio**: no hay conversión. Si la ferretería no manda precio por
tonelada, no compite en esa unidad y aparece como faltante.

Hoy están habilitadas:

| Categoría | Unidades |
|---|---|
| Fierro | Varilla de 9 m · Tonelada |
| Cemento | Bolsa de 42.5 kg · Kilogramo |
| Ladrillo | Unidad · Millar |
| Alambre y clavos | Kilogramo |
| Agregados | Metro cúbico |

Para habilitar otra combinación no hace falta tocar código, basta una línea
en el SQL Editor:

```sql
select generar_skus_por_unidad('ALAMBRE', 'TON');
```

Eso crea los SKU de esa categoría en la unidad nueva, con el peso calculado
(tonelada = 1000 kg, millar = mil veces la unidad suelta). Después hay que
cargarles precio desde la pantalla de Precios; mientras no lo tengan, la
unidad aparece como «sin precios».

**El desplegable ordena por cobertura:** primero la unidad que más
ferreterías cotizan, con el número al lado. Así el asesor sabe de entrada si
elegir tonelada le va a dejar una sola opción.


## Elegir los bonos del cliente

El panel dice cuántos bonos tiene activos el cliente y qué recibe con cada
uno, en las palabras que usaría el asesor:

- Descuento → «Se le descuentan S/ 60 si compra esta cotización»
- Devolución → «Recibirá S/ 60 después de realizar la compra»

Dos grupos con reglas distintas:

- **Excluyentes** (`acumulable = false`): compiten entre sí, se elige uno o
  «Ninguno de estos». Se muestran ordenados por beneficio.
- **Acumulables**: casillas que se suman. Vienen marcadas salvo las de
  aplicación `manual`.

Cualquiera se puede dejar sin dar, **incluidos los automáticos**. El botón
«No dar ninguno» los apaga todos.

**La venta respeta la elección.** Los bonos de momento `venta` también se
eligen aquí: `registrar_venta` solo aplica los marcados y recalcula su monto
sobre lo realmente pagado. Antes volvía a calcular todos los vigentes e
ignoraba lo que el asesor había decidido.

**Se guardan todos, dados y descartados.** Esa comparación alimenta
`v_promociones_omitidas`: un bono que se ofrece mucho y se da poco es uno que
no convence o que la ferretería no reconoce en el mostrador.

Detalle de Streamlit: el botón «No dar ninguno» escribe directamente el valor
de cada campo en `st.session_state` en vez de usar una bandera. Con una
bandera, la pantalla podía quedarse pegada mostrando todo desmarcado.


## Zonas de los usuarios

Un usuario puede cubrir **varias zonas**, en la tabla `rel_usuarios_zonas`.
`m_usuarios.id_zona` queda como zona principal, solo para mostrar, y se
registra sola en la tabla de relación al crear el usuario.

Para agregarle otra zona:

```sql
insert into rel_usuarios_zonas (id_usuario, id_zona)
select u.id_usuario, z.id_zona
from m_usuarios u, m_zonas z
where u.email = 'asesor@correo.com' and z.nombre = 'Chiclayo';
```

Para ver quién cubre qué: `select * from v_usuarios_zonas;`

**La zona de la negociación sale del distrito de la obra**, no del asesor. Lo
hace un trigger en la base. Así un asesor de Trujillo que atiende a un
cliente de Chiclayo no ensucia los reportes por zona.

Eso importa para el supervisor, que ve las negociaciones **de todas sus
zonas**. El asesor ve las suyas esté donde esté la obra.
