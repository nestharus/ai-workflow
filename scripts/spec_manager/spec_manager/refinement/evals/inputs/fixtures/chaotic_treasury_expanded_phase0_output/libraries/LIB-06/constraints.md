# Audit and Notification: CONSTRAINTS


([=CON-LIB-06-001])
<!-- source: notification_and_audit.md:7-7 -->
The service must guarantee that every audit entry is written before the corresponding notification is dispatched, ensuring that if an operator investigates an alert the audit record is already available for inspection. In the event of a write failure the service must retry with the same idempotency key and must not dispatch the notification until the write succeeds.
