# Créditos de automatización

## Dos bolsas separadas

Cada negocio dispone de:

- `included_credits_per_period`: créditos incluidos que concede cada periodo comercial
  de 30 días;
- `included_credits_used`: parte utilizada de esa concesión durante el periodo actual;
- `additional_credits_balance`: créditos comprados o ajustados que se acumulan y no
  caducan al renovar.

Los incluidos restantes son
`max(included_credits_per_period - included_credits_used, 0)` y el total disponible es
la suma de esos incluidos restantes y `additional_credits_balance`. Siempre se consume
primero la bolsa incluida. Solo un mensaje automático entregado correctamente genera
consumo.

Los campos `monthly_auto_limit` y `auto_used_current_period` se mantienen como espejos
deprecated para compatibilidad. No son la fuente de verdad del saldo.

## Ejemplo

Periodo inicial:

- incluidos: 100;
- adicionales: 200;
- total: 300.

Tras consumir 150, quedan 0 incluidos y 150 adicionales. Al renovar se descartan los
incluidos no utilizados del periodo anterior, se conceden 100 nuevos incluidos y se
conservan los 150 adicionales: total 250.

## Renovación, compra y ajuste

`Confirmar pago y renovar 30 días` pone `included_credits_used=0`, mantiene el saldo
adicional y registra `period_allowance_granted`. No crea una compra adicional.

Una compra adicional no cambia periodo, vencimiento, plan, canales ni consumo incluido.
Puede realizarse en `pending_renewal`; el saldo queda almacenado, pero no puede consumirse
hasta que exista un periodo activo.

El ajuste administrativo opera sobre saldos disponibles: `included_delta` modifica los
incluidos restantes sin permitir superar la concesión del periodo, y `additional_delta`
modifica el saldo acumulado. Ninguna operación puede dejar saldos negativos. Las
reducciones exigen confirmación visible en owner. No se implementa todavía un endpoint
de devolución separado; una corrección justificada utiliza el ajuste manual.

## Libro de movimientos

`automation_credit_transactions` conserva tipo, importe, deltas, ambos saldos y total
posteriores, metadatos de pago seguros, motivo, owner, periodo, mensaje relacionado,
idempotency key y fecha UTC. Tipos soportados:

- `period_allowance_granted`;
- `additional_credits_purchased`;
- `automatic_message_consumed`;
- `manual_adjustment`;
- `refund` y `correction`, reservados para flujos futuros;
- `migration_opening_balance`.

Existe unicidad por negocio/idempotency key y por `related_message_id`. Por ello una
compra repetida, un webhook duplicado, un echo o el mismo mensaje no pueden consumir o
añadir dos veces. La actualización de saldo y el movimiento se escriben en la misma
transacción. El libro es la fuente detallada de consumo; no se duplica cada mensaje en
el audit log general para evitar millones de entradas.

No se almacenan cuerpos de conversación, secretos, credenciales, datos bancarios
completos ni números de tarjeta.

## API y permisos

Owner:

- `GET /api/owner/businesses/{business_id}/automation-credits`;
- `POST /api/owner/businesses/{business_id}/automation-credits/purchase`;
- `POST /api/owner/businesses/{business_id}/automation-credits/adjustment`;
- `GET /api/owner/businesses/{business_id}/automation-credits/transactions`.

Business admin:

- `GET /api/admin/businesses/{slug}/automation-credits`, exclusivamente lectura.

Business staff y clientes no tienen acceso. Los contratos usan `extra="forbid"`; el
admin no puede inyectar campos de saldo en el PATCH operativo de automatización.

Compras, ajustes y concesiones generan las acciones de auditoría
`automation_additional_credits_purchased`, `automation_credit_adjusted` y
`automation_period_allowance_granted`. Incluyen valores anteriores/nuevos, motivo,
owner, request ID e idempotency key. Los consumos se auditan en el libro mediante
`automatic_message_consumed` y `related_message_id`.

## Migración

La migración idempotente aplica la política segura:

- incluidos por periodo = `monthly_auto_limit`;
- incluidos usados = `min(auto_used_current_period, monthly_auto_limit)`;
- adicionales = 0.

No se inventan créditos adicionales ni se pierde el consumo conocido. Se añade un
`migration_opening_balance` por negocio y se conservan los campos heredados como
espejos temporales.

## Prueba manual

1. Configurar 100 créditos incluidos.
2. Añadir 200 adicionales y comprobar total 300.
3. Simular 100 entregas y comprobar incluidos agotados, adicionales 200.
4. Simular 50 entregas más y comprobar adicionales 150.
5. Renovar y comprobar incluidos 100, adicionales 150 y total 250.
6. Repetir una compra con la misma idempotency key y comprobar que no duplica saldo.
7. Simular entrega fallida y comprobar que no consume.
8. Vencer el periodo y comprobar que no envía ni modifica ninguna bolsa.
9. Comprar durante `pending_renewal`, comprobar que acumula y que no se consume.
10. Revisar movimientos, auditoría, panel owner y panel admin de solo lectura.
