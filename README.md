# Splits

A personal training dashboard built on Garmin's official Personal API. It pulls
every activity and your daily health data into a local database, then shows:

- **Overview**: this week against your recent weeks, weekly volume by sport,
  training load, a year of activity, health at a glance, and a feed of every
  activity grouped by week.
- **One page per sport** (running, walking, cycling, ...): month by month and
  day by day volume, pace or speed over time, aerobic efficiency, best efforts
  over every distance per month and per quarter, weather against efficiency,
  when you train, distance spread, cadence.
- **Kinds of run**: every run is sorted into races and time trials, threshold,
  intervals, progression, long runs, steady, easy, recovery, strides, and
  warm-up and cool-down. Each kind has its own page under Running with the same
  charts. Open a run to see why it was sorted that way, or to change it.
- **Places**: every activity recorded with GPS gets the town or city where it
  started. Each place and each country has a page with a map of every route
  there, and every sport and kind of run page can be filtered to one place
  ("easy runs in Lisbon").
- **Activity detail**: route map coloured by heart rate zone, pace, heart rate,
  elevation, cadence, power and headwind through the session, the fast blocks of
  a workout, splits with wind, laps, time in zones, weather at the time, best
  efforts inside the session and how it compares with your last 90 days.
- **Personal**: lifetime totals, streaks, personal bests, records per sport,
  year by year, month by month and day by day, heart rate zones, fitness age, weight.
- **Health**: sleep and sleep need, heart rate (resting, asleep, daily range),
  HRV, VO2max, pulse ox, breathing rate, stress and its levels through the day,
  body battery, steps, floors, intensity minutes, calories, weight, each with a
  short note on how to read it, and 30 days to all-time views.

Text sections show placeholder text for now; they are stored in the database
(`Narrative` and `Activity.narrative`) and the pages show them when they are filled.

Everything runs on your own computer. The Garmin key, the database and the
downloaded activity files stay in this folder and are excluded from git.

## Setup (macOS)

1. Create a Personal API key at
   <https://connect.garmin.com/app/settings/personalApiToken> (Garmin shows it once).
2. In this folder:

   ```bash
   ./setup.sh
   ```

   It creates `.venv`, installs three packages (Django, requests, fitdecode),
   creates the database and an `.env` file.
3. Paste the key into `.env` after `GARMIN_PERSONAL_API_KEY=` (no quotes, no spaces).
4. Check the key and see which data Garmin returns:

   ```bash
   ./check.sh
   ```

   The output shows status codes and field names only, never the key or your values.

### Maps (optional)

The activity map uses CARTO basemaps when a key is set. Get a free key at
<https://carto.com/basemaps/apikey/> and add it to `.env`:

```
CARTO_API_KEY=...
CARTO_VECTOR_STYLE_URL=https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json?key=...
CARTO_RASTER_TILE_URL=https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=...
```

The vector style is drawn with MapLibre (sharp at every zoom, dark-matter style
in dark mode). The raster URL is the fallback when the vector style cannot load,
and without any key the map uses OpenStreetMap's own tiles. The key is sent to
the browser with each CARTO request, which is how CARTO keys work.

## Use

```bash
./run.sh          # opens http://127.0.0.1:8000
```

Click **Sync now** (or **Fetch my history** the first time). The first sync reads
your whole history: the activity list first, then one recording per activity,
then sleep, HRV and the daily summaries. Later syncs only fetch what is new.

From the terminal instead:

```bash
./sync.sh            # what is new
./sync.sh --full     # re-read everything
./sync.sh --recheck  # retry data sets that were marked as not available
```

Want to look around first? `./run.sh demo` uses a separate demo database
(`data/demo.sqlite3`) filled with three years of made-up data for a runner who
lives in Amsterdam and travels a few times a year. Delete that file to build it
again after an update.

## How runs are sorted

Nothing is tuned to one person. Every rule uses either the run itself (its heart
rate zones from your Garmin settings, its pace trace) or your own history (your
easy pace and usual run length over the weeks before, your best efforts):

1. Runs under 35 minutes within 40 minutes of a longer run the same day are
   warm-ups or cool-downs; short fast ones straight after a run are strides.
2. Races and time trials: marked as a race in Garmin Connect, mostly in zone 5,
   or a hard continuous effort at 3 km, 5 km, 10 km, 15 km, half or full
   marathon distance close to your best for it.
3. Workouts from the pace trace: blocks at least 18% faster than your easy pace.
   Two or more blocks averaging 3 minutes or more are threshold, shorter ones
   intervals; a steady build is a progression.
4. Long runs: 90 minutes or more, or an hour and one and a half times your usual
   run. Then steady (zones 3 to 5), recovery (short and easy) and easy.

A kind you pick on the activity page always wins.

## Places

Places are worked out on your computer from the start point of each activity,
using the GeoNames list of towns with 1,000 people or more (bundled in
`dashboard/geodata`). A city counts for its whole area, so a run in a suburb
counts for the city; anywhere outside a city's area gets the nearest town.
Indoor sessions and anything without GPS have no place. Rename a place on its
page if you prefer another name. To refresh the bundled lists from GeoNames, run
`python devtools/build_geodata.py` (needs `pip install geonamescache`).

## Weather

Outdoor runs, walks and rides get the weather at their start point and time from
[Open-Meteo](https://open-meteo.com): no key, free for personal use. The sync
asks once per activity (temperature, feels like, humidity, dew point, rain, wind
and gusts, cloud, pressure, visibility) and stores it, so each activity is only
fetched once. From that the app works out the headwind or tailwind at every point
of the route and per split. These are model values for the area, not a weather
station on your street. To fetch it again for everything:

```bash
python manage.py fetch_weather --all
```

## How the Garmin side works

- The key is exchanged for an access token (24 hours, no refresh). The token is
  cached in `data/token.json` and renewed after 20 hours.
- Responses over about 256 KB fail on Garmin's side, so the app pages activities
  20 at a time and asks for health data in 28-day windows. When Garmin still
  says a window is too large, the app splits it in half and tries again.
- 429 and 5xx answers are retried with a pause. A 404 means the endpoint is not
  part of the Personal API; the app notes that and skips it on later syncs.
- Activity recordings come as FIT files (inside a ZIP). They are kept in
  `data/fit/` and turned into down-sampled series, per-km splits and best efforts.
- Every Garmin record keeps its raw JSON. If Garmin renames a field, fix the
  mapping in `dashboard/garmin/extract.py` and run
  `python manage.py rebuild_from_raw`: no new calls to Garmin needed.
- Keys expire (30 days to 1 year). When the sync says the key was rejected,
  create a new one and replace it in `.env`.

## Project layout

```
config/                  Django settings and URLs
dashboard/
  garmin/client.py       token, retries, range splitting
  garmin/sync.py         the sync phases (activities, files, health data)
  garmin/extract.py      Garmin JSON -> model fields
  fitparse.py            FIT/ZIP reader
  streams.py             splits, best efforts, route outline, zones
  analytics.py           numbers behind each page
  views.py, templates/   pages
  static/dashboard/      CSS, JS, ECharts, Leaflet, Archivo font
  runtypes.py            how each run is sorted into a kind
  places.py              offline town and city lookup, place filters
  geodata/               GeoNames towns and countries (CC BY 4.0)
  weather.py             Open-Meteo client, headwind along the route
  derive.py              fills in kinds and places missing after an update
  management/commands/   sync_garmin, garmin_check, seed_demo, rebuild_from_raw,
                         fetch_weather, assign_places
devtools/mock_garmin.py  a fake Garmin API for testing without a key
devtools/build_geodata.py  rebuilds dashboard/geodata from GeoNames
```

### Testing without Garmin

```bash
pip install -r devtools/requirements-dev.txt
python devtools/mock_garmin.py --port 8765 &
GARMIN_API_BASE=http://127.0.0.1:8765 GARMIN_PERSONAL_API_KEY=test-key \
  DB_PATH=data/mock.sqlite3 python manage.py sync_garmin
```

The mock also answers Open-Meteo requests: add
`WEATHER_FORECAST_URL=http://127.0.0.1:8765/v1/forecast WEATHER_ARCHIVE_URL=http://127.0.0.1:8765/v1/archive`.

## License

MIT, see [LICENSE](LICENSE). Bundled third-party parts keep their own licenses (listed below).

## Credits

Weather data by [Open-Meteo](https://open-meteo.com) (CC BY 4.0).

Place names from [GeoNames](https://www.geonames.org) (CC BY 4.0), via the
[geonamescache](https://github.com/yaph/geonamescache) package (MIT).

Charts: [Apache ECharts](https://echarts.apache.org) (Apache 2.0). Maps:
[MapLibre GL JS](https://maplibre.org) (BSD 3) and [Leaflet](https://leafletjs.com) (BSD 2),
map data by OpenStreetMap contributors, basemaps by CARTO.

Font: [Archivo](https://github.com/Omnibus-Type/Archivo) (SIL Open Font License).

Not affiliated with Garmin.
