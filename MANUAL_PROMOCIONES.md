# Manual de promociones

Todo se hace desde la pantalla **Promociones**, sin escribir SQL. Solo el
administrador la ve.

La pantalla tiene tres pestañas:

| Pestaña | Para qué |
|---|---|
| **Vigentes** | Ver las que existen, simular cuánto darían y apagarlas |
| **Nueva promoción** | Crearlas |
| **Afiliación** | Registrar qué ferreterías aceptaron las que ellas pagan |

---

## Las cinco preguntas

Crear una promoción es responder cinco preguntas. El formulario está ordenado así.

### 1 · ¿Qué da?

Primero la **modalidad**, que define si el cliente paga menos hoy o recibe algo después:

| Modalidad | Qué pasa |
|---|---|
| **Descuento** | Baja el monto de la cotización. El cliente paga menos hoy y lo ve en el PDF |
| **Devolución** | El cliente paga completo y se le entrega el beneficio después de comprar |

Después el **tipo de cálculo**:

| Tipo | Cómo funciona | Ejemplo |
|---|---|---|
| **Porcentaje del total** | Un % de la canasta | 5% de descuento |
| **Monto fijo** | Siempre los mismos soles | S/ 150 de descuento |
| **Por cada X soles, da Y** | Solo cuenta los bloques completos | Por cada S/ 1,500, da S/ 50 |
| **Escalonada por tramos** | Distinto beneficio según cuánto compre | 1% desde S/ 3,000 y 2% desde S/ 6,000 |
| **Precio especial** | Fija el precio de un producto | El fierro a S/ 30 esta semana |

### 2 · ¿Cuándo aplica?

Las fechas, la compra mínima y el tope del beneficio (0 en ambos campos significa "sin límite").

Y el campo **«Se calcula»**, que es el más importante de entender:

- **Al cotizar:** se muestra en la cotización y baja el total.
- **Al vender, sobre lo pagado:** se calcula sobre lo que el cliente realmente compró.

Usa el segundo para los bonos. Si el cliente cotiza S/ 7,000 y termina comprando S/ 5,500, el bono se calcula sobre S/ 5,500. Calcularlo al cotizar le prometería un bono que no corresponde.

### 3 · ¿A qué clientes?

- **Segmento:** todos, solo B2B o solo B2C.
- **Historial de compras:** todos, solo primera compra, solo recompras, o clientes dormidos (ahí eliges cuántos días sin comprar).
- **Tipos de cliente:** para acotar a subtipos concretos, como solo ferreteros o solo constructoras.

Solo cuentan las **ventas validadas**. Un cliente que cotizó diez veces pero nunca compró sigue siendo primera compra.

### 4 · ¿Sobre qué y dónde?

Categorías y zonas. **Dejarlo vacío significa "todo"**, que es lo más común.

### 5 · ¿Cómo se aplica?

| Campo | Qué decide |
|---|---|
| **Quién la paga** | SIDEREXPRESS, la ferretería, el proveedor o compartido. Define el margen real |
| **Cómo llega al asesor** | Automática (no la puede quitar), sugerida (viene marcada) o manual (viene desmarcada) |
| **Requiere afiliación** | Si la paga la ferretería, solo aplica donde la aceptaron |
| **Acumulable** | Si se suma con otras o compite y gana la de mayor beneficio |
| **Prioridad** | Menor número, se evalúa primero. Desempata entre las no acumulables |

---

## Cuatro ejemplos completos

### A · Descuento directo del 5%

El caso más simple: baja lo que paga el cliente y lo asume SIDEREXPRESS.

| Campo | Valor |
|---|---|
| Nombre / Código | 5% de descuento · `DESC-5` |
| Modalidad | Descuento |
| Tipo | Porcentaje del total → **5** |
| Fechas | Hoy a fin de mes |
| Se calcula | Al cotizar |
| Quién la paga | siderexpress |
| Cómo llega | Sugerida |

### B · Bono de primera compra

S/ 30 por cada S/ 3,000, solo para clientes nuevos, entregado después de comprar.

| Campo | Valor |
|---|---|
| Nombre / Código | Bono de bienvenida · `BONO-NUEVO` |
| Modalidad | **Devolución** |
| Tipo | Por cada **3000** da **30** |
| Se calcula | **Al vender, sobre lo pagado** |
| Historial de compras | **Solo primera compra** |
| Cómo llega | Automática |

Con una compra de S/ 7,000 da S/ 60: son dos bloques completos, el resto no cuenta.

### C · Escalonada 1% y 2%, con tope de S/ 300

| Campo | Valor |
|---|---|
| Tipo | **Escalonada por tramos** |
| Tramo 1 | Desde 3000, hasta 6000, porcentaje, **1** |
| Tramo 2 | Desde 6000, hasta **0**, porcentaje, **2** |
| Compra mínima | 3000 |
| Tope | **300** |

El **0** en "hasta" significa *de ahí en adelante*. Solo un tramo puede quedar así.

Con S/ 20,000 daría S/ 400, pero el tope lo deja en S/ 300.

### D · Solo para ferreteros, que la paga la ferretería

| Campo | Valor |
|---|---|
| Tipo | Porcentaje → **8** |
| Tipos de cliente | **B2B · Ferretero** |
| Quién la paga | **ferreteria** |
| Requiere afiliación | **sí** (se marca solo al elegir «ferreteria») |

Al crearla aparece el aviso de que todavía no aplica en ninguna sede. Hay que ir a **Afiliación**, elegir la promoción, la ferretería y marcar "Acepta". Eso registra todas sus sedes de una vez.

---

## Cómo comprobar que quedó bien

En la pestaña **Vigentes** hay un campo para simular con una canasta. Escribe un monto y cada promoción muestra cuánto daría.

Es la forma más rápida de detectar un error antes de anunciarla: si pusiste 5 pensando en soles pero el tipo era porcentaje, el simulador te lo muestra al instante.

---

## Apagar una promoción

Nunca se borra, porque las cotizaciones antiguas la referencian y perderías el histórico. Dos formas:

- **Apagar promoción** en la pestaña Vigentes: deja de aplicarse de inmediato.
- **Cambiar fecha**: adelanta el vencimiento para que expire sola.

---

## Preguntas frecuentes

**¿Por qué mi promoción no aparece al cotizar?**

Revisa en este orden:

1. ¿Está vigente? Fecha de inicio pasada y de fin futura.
2. ¿La canasta llega al monto mínimo?
3. Si requiere afiliación, ¿esa ferretería la aceptó?
4. ¿El cliente cumple las condiciones de segmento e historial?
5. Si es de tipo «Al vender», no aparece al cotizar: es un bono posterior.

**¿Qué pasa si dos promociones aplican a la vez?**

Las acumulables se suman. Entre las no acumulables gana la de mayor beneficio, y si empatan decide la prioridad.

**¿El cliente ve la devolución en el PDF?**

Sí, como una línea aparte que dice cuánto recibirá después de comprar. El total a pagar no la descuenta.

**¿Puedo cambiar una promoción ya creada?**

Desde la pantalla solo la fecha de vencimiento y el encendido. El resto no se edita a propósito: cambiar el valor de una promoción en curso alteraría lo que ya se le prometió a clientes con cotizaciones vigentes. Si necesitas otra cosa, apaga la actual y crea una nueva.
