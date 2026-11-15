# Changelog

All notable changes to Splits. Versions follow [semantic versioning](https://semver.org);
each version is a git tag.

## [Unreleased]

### Changed

- **Download for AI** now covers the whole session. When a warm-up, cool-down or
  strides were recorded as separate activities, the file for the main run lists
  every part in a session table near the top, then adds each part at the end with
  its own totals, zones, weather, splits and every recorded point. Downloading from
  a warm-up, cool-down or strides card gives the same file, named after the main
  run. A run recorded as a single activity gives exactly the same file as before.
- The **Training plan** page shows one week at a time, Monday to Sunday, and opens
  on this week. Arrows beside the heading step a week back or forward. Under the
  table, a pager has one numbered button per week with the date it starts, and
  arrows for the first, previous, next and last week. The open week is filled, and
  this week has a ring and the word "now". A long plan shows the first and last
  weeks, this week and the weeks around the open one.
- Each plan status carries a mark as well as its word and colour: ✔ done,
  ✖ missed, ↓ shorter, ↑ longer, + a run on a rest day. Planned
  sessions in the **training log** carry the same mark in a corner, so a status
  reads the same without colour.
- On the plan page, the last 4 weeks show a bar for sessions done and distance run
  against the plan.
- A link written in a race's notes can be opened.
- On a phone:
  - Rows that turn into cards are tighter, and a card leaves out values that are
    empty (a rest day has no distance or pace).
  - A past race shows its result against the predictions at the top right of its
    card.
  - A long activity name takes two lines in the feed instead of being cut short.
  - Buttons, menu rows, the theme button and the download button are at least 40px
    tall, and a tap shows on the thing you tapped.
  - Typing in a field no longer zooms the page.
  - The browser bar takes the colour of the page, in the light and the dark theme.
  - An odd tile at the end of a row of figures takes the whole row.
- Hover and press states change softly, race and course cards in a row are the same
  height, and the file button of the plan import matches the other buttons.

### Fixed

- A race stayed under "upcoming" and said **Today** for the whole race day, even after
  its run had synced. A race now counts as run as soon as its activity arrives: it
  moves to Past races with your result, and the countdown moves on to the next one.
- The Training plan page showed six weeks in one table, which was too long to read.
- On a phone, the page of a past race scrolled sideways when its result had two
  labels. The labels now wrap under the title.
- On a phone, the day names under **This week** on the overview slid out of their
  card when one activity was long enough to fill the column.
- On a narrow phone, the top bar wrapped onto two lines.

## [1.0.2] - 2026-11-03

### Fixed

- The Training plan table was far wider than a laptop screen, because long
  descriptions did not wrap. They now wrap and the table fits.
- The training log no longer scrolls sideways in a narrow window: it shows the full
  table when there is room and the week blocks from the phone layout when there is
  not. Long session names stay inside their day.
- Past races, the tables for each kind of run, course runs, places, and an
  activity's out and back and fast blocks turn into cards whenever their panel is
  too narrow for the table, in a narrow window as well as on a phone.

## [1.0.1] - 2026-11-03

### Added

- **Past races**: a race you have already run can be added like any other. Its
  prediction uses only the races and best efforts of the 90 days before it, and the
  race page shows your result against your goal and both predictions.
- The Races page has a **Past races** table: your time, what VDOT and Riegel
  predicted, and your goal.
- Each past race is marked **✔✔ Faster than both**, **✔ Faster than one** or
  **✖ Slower than both** predictions, and the goal shows **✔ under** or **✖ over**
  with the difference. Ticks, crosses and words carry the meaning, so it reads the
  same without colour; the colours are blue, grey and orange, which most colour-blind
  people can tell apart.
- A **No data before** label when there was no race or best effort over 3 km in the
  90 days before a race to predict from.

### Changed

- **Wide tables on a phone** are now shown as a card per row, with a label on each
  value, so nothing scrolls sideways: past races, the training plan, course runs,
  the tables for each kind of run, places, and an activity's out and back and fast
  blocks. On a wider screen they are still tables.

### Fixed

- The race date picker closed when moving to the previous or next month.
- The CSV example on the Training plan page ran off the side of a phone screen.

## [1.0.0] - 2026-11-01

A big round for runners: a training log, a training plan, races with predicted
times, race courses, pages built for each kind of run, and the dashboard on your
phone.

### Added

- **Training log**: week by week, day by day, every session in its own cell with
  its distance and kind; per week the running distance and its change, the longest
  run and its share of the week, and the easy / hard split. On a phone, each week
  is a block with the seven days side by side.
- **Training plan**: import a plan as a CSV file (or paste it), from a coach, a
  spreadsheet or an AI tool. The Plan page compares four weeks back and two ahead
  with what you ran (done, shorter, longer, missed, rested), and has a template and
  a ready-made prompt for AI tools. The plan also shows in the training log (with
  the planned weeks ahead) and in the download for AI.
- **Races**: add the races you have entered. Each gets a predicted time by Jack
  Daniels' VDOT and by Riegel's formula, the pace, km-by-km splits for your goal and
  both predictions, the VDOT your goal needs, paces to train at and your build-up.
  After race day, your result against each prediction. The next race shows on the
  Overview and the menu counts down the days.
- **Courses**: every race and time trial grouped by course from the GPS track (same
  start and finish, same distance, mostly the same roads), with every attempt, its
  clock time, heart rate and conditions. Courses run only once can be hidden.
- **Sessions**: a warm-up, cool-down or strides run is attached to the run it
  belongs to (same day, at most 40 minutes apart). It shows inside that run's card
  and counts once in session counts and averages.
- **Pages for each kind of run**: a table made for each kind. Races: clock time,
  VDOT and conditions, plus race fitness over time. Threshold and intervals: fast
  blocks, their pace and heart rate. Long runs: fast finish and aerobic decoupling.
  Easy, recovery and steady: pace in zone 2 and decoupling. Warm-ups and strides:
  the run each belongs to.
- **Pace at the same effort** on running pages: pace while heart rate sat in zone 2,
  zones 3 to 4 and zones 4 to 5 (from your own zones), each from the kinds of run
  done at that effort, with a 6-week median line.
- **Activity page**: ground contact, vertical oscillation, vertical ratio and stride
  length charts; stretches where heart rate did not follow pace, shaded on the heart
  rate chart; aerobic decoupling; the two halves of an out-and-back or each lap of a
  circuit; the session it belongs to; the course and its rank on it.
- **Open it on your phone**: `uv run manage.py start --lan` also listens on your
  Wi-Fi. Other devices need a private key once (the start command prints the link);
  the phone keeps it.
- **Download for AI**: for a race or time trial, the earlier ones on the same course
  or in the same place; the training plan for that day and the week around it; the
  races ahead.
- Demo data has warm-ups and cool-downs around races, repeated courses, an upcoming
  half marathon and a 7-week plan.
- Screenshots in the README, and this changelog.

### Changed

- **uv project**: `pyproject.toml` and `uv.lock`. One command sets everything up and
  starts the dashboard: `uv run manage.py start` (or `--demo`). `requirements.txt`
  stays for pip users.
- **Training load**: the load of the last 7 days against your usual week (the average
  of the last 28 days), with their ratio and bands (easing off, steady, building
  fast, a big jump), a one-line summary and running distance against your usual week.
- **Titles**: activities are named like their download, "Long run in Kildare 17.6 km",
  unless they have a name of their own in Garmin Connect.
- **Phone menu**: a Menu button opens the full list under the top bar, instead of a
  row that scrolled sideways.
- The activity calendar and weekly volume start at your first activity.
- Splits show every row.
- Races use a date picker with weeks starting on Monday.
- "Against your last 90 days" compares a run with runs of the same kind, leaving out
  warm-ups and strides.
- The README has a table of contents with links back to the top, and step-by-step
  instructions for the Garmin key and for CARTO maps.

### Removed

- `setup.sh`, `run.sh`, `check.sh` and `sync.sh`: replaced by
  `uv run manage.py start`, `garmin_check` and `sync_garmin`.
- The year-by-year charts on Personal.
- Best efforts per quarter (best per month stays).
- On the page of one kind of run: when you run, distance spread, cadence by month,
  and best efforts except on Races.

## [0.2.0] - 2026-10-31

### Added

- **Download for AI**: a button on every run (on its page and on each card) that saves
  one Markdown file with everything about it, named like
  `2026-10-28 06h44 Race or time trial in Rathangan 10.0 km.md`. It has a description,
  totals, heart rate zones, why the run was sorted as that kind, the weather hour by
  hour with headwind along the route, splits per km worked out from the recording,
  the watch's own laps, best efforts, the 90 days before, training context (four
  weeks of running, the 14 days before, personal bests, sleep, HRV, resting heart
  rate and body battery that day), every Garmin summary field and every recorded
  point as CSV. GPS coordinates are left out.
- In that file: stretches where heart rate did not follow pace are marked, and zone
  times, splits and laps are given with and without them; the two halves of an
  out-and-back route or each lap of a circuit, when the GPS track clearly shows it;
  aerobic decoupling for easy, recovery, steady and long runs; and a note on which
  numbers the app worked out and which come from the watch.

### Changed

- The heat effect (temperature plus dew point) is in °C.
- For races, the download uses elapsed (clock) time.
- Hovering the charts through a session shows one tooltip, on the chart under the
  pointer, instead of one on every chart.
- The README has a table of contents, links back to the top and instructions for
  the Garmin key and CARTO maps.

### Removed

- The placeholder text sections on activities.

## [0.1.0] - 2026-10-31

The first public version.

### Added

- Sync with Garmin's official Personal API (read only): every activity, its
  recording (FIT file), and the daily health data, paged and retried to work within
  the API's limits. Raw data is kept, so field mappings can be fixed and rebuilt
  without calling Garmin again.
- **Overview**: this week against the last four, weekly volume by sport, training
  load, a year of activity, health at a glance and a feed of every activity by week.
- **A page per sport**: month by month and day by day, pace or speed over time,
  aerobic efficiency, best efforts over every distance per month and quarter,
  weather against efficiency, when you train, distance spread and cadence.
- **Kinds of run**: every run sorted into races and time trials, threshold,
  intervals, progression, long runs, steady, easy, recovery, strides and warm-up
  and cool-down, from the run itself and your own history (nothing tuned to one
  person). Each kind has its own page, and you can change the kind of any run.
- **Places**: the town or city of every activity with GPS, found offline from
  GeoNames, with a page and a map of routes for each place and country, and a place
  filter on every sport and kind page.
- **Activity detail**: route map coloured by heart rate zone, pace, heart rate,
  elevation, cadence, power and headwind through the session, fast blocks, splits
  with wind, laps, zones, weather, best efforts and a comparison with the last 90
  days.
- **Weather** from Open-Meteo for every outdoor activity, with the headwind or
  tailwind along the route.
- **Personal**: lifetime totals, streaks, personal bests, records per sport, year by
  year, month by month and day by day, heart rate zones, fitness age and weight.
- **Health**: sleep and sleep need, heart rate, HRV, VO2max, pulse ox, breathing,
  stress, body battery, steps, floors, intensity minutes, calories and weight, each
  with a short note on how to read it.
- Maps with CARTO basemaps (optional key) or OpenStreetMap tiles, light and dark
  themes.
- Demo data (`run.sh demo`) and a mock Garmin API for testing without a key.
- Setup and run scripts for macOS, MIT license.

[1.0.2]: https://github.com/idomingo/splits/compare/1.0.1...1.0.2
[1.0.1]: https://github.com/idomingo/splits/compare/1.0.0...1.0.1
[1.0.0]: https://github.com/idomingo/splits/compare/0.2.0...1.0.0
[0.2.0]: https://github.com/idomingo/splits/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/idomingo/splits/releases/tag/0.1.0
