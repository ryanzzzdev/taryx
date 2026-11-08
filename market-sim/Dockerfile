# Market coordinator simulator — deliberately independent of the core image.
FROM python:3.14-slim

WORKDIR /app
COPY market_sim.py .

EXPOSE 8091
CMD ["python", "market_sim.py", "--port", "8091", "--db", "/data/market_sim.db"]
