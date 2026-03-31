# RoutePulse Full Version

This version adds a proper Flask backend, PostgreSQL schema, larger sample GPS data, and a browser dashboard with a live map.

## Features
- trip logging API
- GPS point storage
- stop detection
- geofence crossings
- points of interest
- trip summaries and analytics views
- Leaflet map replay using OpenStreetMap tiles

## Load the database
```bash
export PGPASSWORD=password
psql -U routeuser -h localhost -d routepulse -f schema.sql
psql -U routeuser -h localhost -d routepulse -f functions.sql
psql -U routeuser -h localhost -d routepulse -f views.sql
psql -U routeuser -h localhost -d routepulse -f sample_data.sql
```

## Run the app
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```
Open `http://127.0.0.1:5000`

## API examples
```bash
curl http://127.0.0.1:5000/api/trips
curl http://127.0.0.1:5000/api/trips/1
```
