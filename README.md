# Loom Store Monitoring

## Overview

This project is a FastAPI-based backend service for monitoring the uptime and downtime of stores. It ingests store status, business hours, and timezone data from CSV files, stores them in a SQLite database, and generates detailed uptime/downtime reports for each store over the last hour, day, and week.

## Features

- **CSV Data Ingestion:** Loads store status, business hours, and timezone data from CSVs into a database.
- **Uptime/Downtime Calculation:** Computes uptime and downtime for each store, considering business hours and timezones.
- **Report Generation:** Generates downloadable CSV reports summarizing store performance.
- **REST API:** Endpoints to trigger and retrieve reports.

## Setup Instructions

1. **Clone the repository**
2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the application**
   ```bash
   uvicorn main:app --reload
   ```
4. **CSV Files**
   - Place your `store_status.csv`, `menu_hours.csv`, and `timezones.csv` in the project root.

## API Usage

- **Trigger a report:**
  ```
  POST /trigger_report
  ```
  Returns a `report_id`.

- **Download a report:**
  ```
  GET /get_report?report_id=<your_report_id>
  ```
  Returns the CSV file if ready.

## Sample CSV Output

A sample report is generated in the repo as `report_dd0ca449-c435-48be-8ea3-7c7451f2a3b5.csv`:

```
store_id,uptime_last_hour,uptime_last_day,uptime_last_week,downtime_last_hour,downtime_last_day,downtime_last_week
00017c6a-7a77-4a95-bb2d-40647868aff6,60,8.42,73.42,0,2.08,2.08
000bba84-20af-4a8b-b68a-368922cc6ad1,0,0.0,0.0,60,24.0,168.0
...
```

## Ideas for Improvement

1. **Asynchronous Report Generation:** Use background task queues (e.g., Celery) for better scalability and reliability.
2. **Configurable Business Hours:** Allow business hours to be updated via API, not just CSV.
3. **Frontend Dashboard:** Build a simple dashboard to visualize store uptime/downtime trends.
4. **Alerting System:** Notify stakeholders when downtime exceeds a threshold.
5. **Unit & Integration Tests:** Add automated tests for reliability.
