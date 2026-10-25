# Legacy billing simulator — deliberately independent of the core image.
FROM python:3.14-slim

WORKDIR /app
COPY legacy_sim.py .

EXPOSE 8090
CMD ["python", "legacy_sim.py", "--port", "8090", "--db", "/data/legacy_calc.db"]
