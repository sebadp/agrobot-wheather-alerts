# /add-alert

Crear una alerta interactivamente.

## Steps

1. Ask the user which field:
   - Campo La Esperanza: `f1e2d3c4-b5a6-7890-fedc-ba0987654321`
   - Campo Primavera: `f2e3d4c5-b6a7-8901-fedc-ba1098765432`
2. Ask the event type: frost, rain, hail, drought, heat_wave, strong_wind
3. Ask the threshold (0.0 to 1.0, default 0.7)
4. Create the alert:
   ```
   curl -s -X POST http://localhost:8000/api/v1/fields/{field_id}/alerts \
     -H "Content-Type: application/json" \
     -d '{"event_type": "{event}", "threshold": {threshold}}' | python3 -m json.tool
   ```
5. Show the result
