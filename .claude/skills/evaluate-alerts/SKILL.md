# /evaluate-alerts

Trigger manual de evaluacion y mostrar resultados.

## Steps

1. Run: `curl -s -X POST http://localhost:8000/api/v1/jobs/evaluate-alerts | python3 -m json.tool`
2. Show the result to the user
3. If notifications were created, fetch them:
   `curl -s http://localhost:8000/api/v1/users/a1b2c3d4-e5f6-7890-abcd-ef1234567890/notifications?limit=5 | python3 -m json.tool`
