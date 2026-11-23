# Contributing

Use synthetic records only. Keep dollar amounts in the fixture adjudications and the plan-guide facts. Do not add a path that lets a model choose a member amount.

Run the local checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m membercare.evals
```

Leave the blueprint acceptance targets unmarked unless a run recorded the measurement. PostgreSQL, Keycloak, a vector index, speech recognition, and a container build are not required for the current local subset.
