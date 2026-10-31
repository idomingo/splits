"""Data model. Every Garmin record keeps its raw JSON so fields can be
re-extracted later (manage.py rebuild_from_raw) without fetching again."""
from django.db import models

from .sports import CATEGORY_CHOICES


class Place(models.Model):
    """A town or city from the bundled GeoNames list (see places.py)."""
    geonameid = models.IntegerField(unique=True)
    slug = models.SlugField(max_length=160, unique=True)
    name = models.CharField(max_length=200)
    country_code = models.CharField(max_length=2, db_index=True)
    country = models.CharField(max_length=100, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    population = models.IntegerField(default=0)
    custom_name = models.CharField(max_length=200, blank=True)   # your own name for it; wins when set

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.label}, {self.country}"

    @property
    def label(self):
        return self.custom_name or self.name


class Activity(models.Model):
    DETAIL_PENDING = "pending"
    DETAIL_OK = "ok"
    DETAIL_NONE = "none"      # Garmin has no usable file for this one
    DETAIL_ERROR = "error"
    DETAIL_CHOICES = [(s, s) for s in (DETAIL_PENDING, DETAIL_OK, DETAIL_NONE, DETAIL_ERROR)]

    activity_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255, blank=True)
    type_key = models.CharField(max_length=64, blank=True)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, db_index=True)
    event_type = models.CharField(max_length=32, blank=True)
    start_local = models.DateTimeField(db_index=True)
    start_gmt = models.DateTimeField(null=True, blank=True)

    distance_m = models.FloatField(null=True, blank=True)
    duration_s = models.FloatField(null=True, blank=True)
    moving_s = models.FloatField(null=True, blank=True)
    elapsed_s = models.FloatField(null=True, blank=True)
    elev_gain_m = models.FloatField(null=True, blank=True)
    elev_loss_m = models.FloatField(null=True, blank=True)
    avg_speed = models.FloatField(null=True, blank=True)   # m/s
    max_speed = models.FloatField(null=True, blank=True)
    avg_hr = models.FloatField(null=True, blank=True)
    max_hr = models.FloatField(null=True, blank=True)
    calories = models.FloatField(null=True, blank=True)
    avg_cadence = models.FloatField(null=True, blank=True)  # steps/min (run, walk) or rpm (bike)
    max_cadence = models.FloatField(null=True, blank=True)
    avg_stride_cm = models.FloatField(null=True, blank=True)
    steps = models.IntegerField(null=True, blank=True)
    avg_power = models.FloatField(null=True, blank=True)
    max_power = models.FloatField(null=True, blank=True)
    norm_power = models.FloatField(null=True, blank=True)
    aerobic_te = models.FloatField(null=True, blank=True)
    anaerobic_te = models.FloatField(null=True, blank=True)
    te_label = models.CharField(max_length=48, blank=True)
    training_load = models.FloatField(null=True, blank=True)
    vo2max = models.FloatField(null=True, blank=True)
    hr_z1 = models.FloatField(null=True, blank=True)
    hr_z2 = models.FloatField(null=True, blank=True)
    hr_z3 = models.FloatField(null=True, blank=True)
    hr_z4 = models.FloatField(null=True, blank=True)
    hr_z5 = models.FloatField(null=True, blank=True)
    min_temp = models.FloatField(null=True, blank=True)
    max_temp = models.FloatField(null=True, blank=True)
    start_lat = models.FloatField(null=True, blank=True)
    start_lon = models.FloatField(null=True, blank=True)
    location_name = models.CharField(max_length=128, blank=True)
    lap_count = models.IntegerField(null=True, blank=True)
    avg_gct_ms = models.FloatField(null=True, blank=True)
    avg_vert_osc_cm = models.FloatField(null=True, blank=True)
    avg_vert_ratio = models.FloatField(null=True, blank=True)

    raw = models.JSONField(default=dict)
    detail_status = models.CharField(max_length=10, choices=DETAIL_CHOICES, default=DETAIL_PENDING, db_index=True)
    detail_error = models.TextField(blank=True)
    detail_attempts = models.IntegerField(default=0)
    route_svg = models.TextField(blank=True)  # SVG path for a 100x100 box
    run_type = models.CharField(max_length=16, blank=True, db_index=True)         # set by the classifier
    run_type_manual = models.CharField(max_length=16, blank=True)                 # set by you; wins
    run_type_reason = models.CharField(max_length=255, blank=True)
    run_type_info = models.JSONField(default=dict, blank=True)                    # fast blocks etc.
    narrative = models.TextField(blank=True)  # filled by a later version; placeholder shown when empty
    place = models.ForeignKey(Place, null=True, blank=True, on_delete=models.SET_NULL, related_name="activities")
    route = models.JSONField(null=True, blank=True)          # simplified [[[lon, lat], ...], ...] for overview maps
    geo_version = models.SmallIntegerField(default=0)        # places.GEO_VERSION once place and route are set
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_local"]
        indexes = [models.Index(fields=["category", "-start_local"])]

    def __str__(self):
        return f"{self.start_local:%Y-%m-%d} {self.name}"

    # Convenience values used by templates
    @property
    def kind(self):
        """Run subcategory: your choice first, then the classifier's."""
        return self.run_type_manual or self.run_type

    @property
    def kind_label(self):
        from .runtypes import RUN_TYPE_LABEL
        return RUN_TYPE_LABEL.get(self.kind, "") if self.category == "run" else ""

    @property
    def wx(self):
        """Weather if we have it (None when missing or failed)."""
        try:
            w = self.weather
        except Exception:
            return None
        return w if w and not w.error else None

    @property
    def distance_km(self):
        return (self.distance_m or 0) / 1000.0

    @property
    def time_s(self):
        return self.moving_s or self.duration_s or self.elapsed_s or 0

    @property
    def pace_s_per_km(self):
        if self.distance_m and self.distance_m > 50 and self.time_s:
            return self.time_s / (self.distance_m / 1000.0)
        return None

    @property
    def speed_kmh(self):
        if self.distance_m and self.time_s:
            return (self.distance_m / 1000.0) / (self.time_s / 3600.0)
        return None

    @property
    def zone_seconds(self):
        zs = [self.hr_z1, self.hr_z2, self.hr_z3, self.hr_z4, self.hr_z5]
        if any(z for z in zs):
            return [z or 0 for z in zs]
        stream = getattr(self, "stream", None)
        if stream and stream.zone_s:
            return stream.zone_s
        return None


class ActivityStream(models.Model):
    """Down-sampled samples for charts and the map, plus derived splits."""
    activity = models.OneToOneField(Activity, on_delete=models.CASCADE, primary_key=True, related_name="stream")
    data = models.JSONField(default=dict)    # {"t": [...], "d": [...], "hr": [...], ...}
    splits = models.JSONField(default=list)  # per-km splits
    zone_s = models.JSONField(default=list)  # seconds in HR zones 1-5 (when Garmin did not provide them)
    source_file = models.CharField(max_length=255, blank=True)
    sample_count = models.IntegerField(default=0)


class ActivityLap(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="laps")
    index = models.IntegerField()
    start_offset_s = models.FloatField(null=True, blank=True)
    duration_s = models.FloatField(null=True, blank=True)
    distance_m = models.FloatField(null=True, blank=True)
    avg_speed = models.FloatField(null=True, blank=True)
    avg_hr = models.FloatField(null=True, blank=True)
    max_hr = models.FloatField(null=True, blank=True)
    avg_cadence = models.FloatField(null=True, blank=True)
    elev_gain_m = models.FloatField(null=True, blank=True)
    elev_loss_m = models.FloatField(null=True, blank=True)
    avg_power = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["activity", "index"]
        unique_together = [("activity", "index")]

    @property
    def pace_s_per_km(self):
        if self.distance_m and self.distance_m > 20 and self.duration_s:
            return self.duration_s / (self.distance_m / 1000.0)
        return None


class BestEffort(models.Model):
    """Fastest time over a set distance inside one activity (from the samples)."""
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="best_efforts")
    category = models.CharField(max_length=16, db_index=True)
    distance_m = models.IntegerField(db_index=True)
    seconds = models.FloatField()
    start_offset_s = models.FloatField(default=0)
    date = models.DateField(db_index=True)

    class Meta:
        unique_together = [("activity", "distance_m")]
        ordering = ["distance_m", "seconds"]


class DailySummary(models.Model):
    date = models.DateField(primary_key=True)
    steps = models.IntegerField(null=True, blank=True)
    distance_m = models.FloatField(null=True, blank=True)
    resting_hr = models.FloatField(null=True, blank=True)
    min_hr = models.FloatField(null=True, blank=True)
    max_hr = models.FloatField(null=True, blank=True)
    avg_stress = models.FloatField(null=True, blank=True)
    max_stress = models.FloatField(null=True, blank=True)
    bb_max = models.FloatField(null=True, blank=True)
    bb_min = models.FloatField(null=True, blank=True)
    bb_charged = models.FloatField(null=True, blank=True)
    bb_drained = models.FloatField(null=True, blank=True)
    im_moderate = models.FloatField(null=True, blank=True)
    im_vigorous = models.FloatField(null=True, blank=True)
    resp_avg = models.FloatField(null=True, blank=True)
    spo2_avg = models.FloatField(null=True, blank=True)
    kcal_total = models.FloatField(null=True, blank=True)
    kcal_active = models.FloatField(null=True, blank=True)
    floors_up = models.FloatField(null=True, blank=True)
    floors_down = models.FloatField(null=True, blank=True)
    steps_goal = models.IntegerField(null=True, blank=True)
    kcal_resting = models.FloatField(null=True, blank=True)
    spo2_min = models.FloatField(null=True, blank=True)
    resp_min = models.FloatField(null=True, blank=True)
    resp_max = models.FloatField(null=True, blank=True)
    stress_rest_s = models.FloatField(null=True, blank=True)
    stress_low_s = models.FloatField(null=True, blank=True)
    stress_med_s = models.FloatField(null=True, blank=True)
    stress_high_s = models.FloatField(null=True, blank=True)
    hydration_ml = models.FloatField(null=True, blank=True)
    raw = models.JSONField(default=dict)

    class Meta:
        ordering = ["date"]


class SleepNight(models.Model):
    date = models.DateField(primary_key=True)
    total_s = models.FloatField(null=True, blank=True)
    deep_s = models.FloatField(null=True, blank=True)
    light_s = models.FloatField(null=True, blank=True)
    rem_s = models.FloatField(null=True, blank=True)
    awake_s = models.FloatField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    start_local = models.DateTimeField(null=True, blank=True)
    end_local = models.DateTimeField(null=True, blank=True)
    resp_avg = models.FloatField(null=True, blank=True)
    spo2_avg = models.FloatField(null=True, blank=True)
    avg_hr = models.FloatField(null=True, blank=True)
    resp_low = models.FloatField(null=True, blank=True)
    resp_high = models.FloatField(null=True, blank=True)
    spo2_low = models.FloatField(null=True, blank=True)
    sleep_stress = models.FloatField(null=True, blank=True)
    awake_count = models.IntegerField(null=True, blank=True)
    need_min = models.FloatField(null=True, blank=True)
    nap_s = models.FloatField(null=True, blank=True)
    raw = models.JSONField(default=dict)

    class Meta:
        ordering = ["date"]


class HrvDay(models.Model):
    date = models.DateField(primary_key=True)
    last_night = models.FloatField(null=True, blank=True)
    weekly_avg = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=24, blank=True)
    baseline_low = models.FloatField(null=True, blank=True)
    baseline_high = models.FloatField(null=True, blank=True)
    raw = models.JSONField(default=dict)

    class Meta:
        ordering = ["date"]


class WeightDay(models.Model):
    date = models.DateField(primary_key=True)
    weight_kg = models.FloatField(null=True, blank=True)
    bmi = models.FloatField(null=True, blank=True)
    body_fat = models.FloatField(null=True, blank=True)
    raw = models.JSONField(default=dict)

    class Meta:
        ordering = ["date"]


class Vo2Max(models.Model):
    SOURCE_DAILY = "daily"
    SOURCE_ACTIVITY = "activity"
    date = models.DateField(db_index=True)
    sport = models.CharField(max_length=16, default="running")
    value = models.FloatField()
    source = models.CharField(max_length=16, default=SOURCE_DAILY)

    class Meta:
        unique_together = [("date", "sport")]
        ordering = ["date"]


class FitnessAge(models.Model):
    date = models.DateField(primary_key=True)
    fitness_age = models.FloatField(null=True, blank=True)
    chrono_age = models.FloatField(null=True, blank=True)
    achievable = models.FloatField(null=True, blank=True)
    raw = models.JSONField(default=dict)


class Weather(models.Model):
    """Conditions during an activity, from Open-Meteo (model data, not a station)."""
    activity = models.OneToOneField(Activity, on_delete=models.CASCADE, primary_key=True, related_name="weather")
    source = models.CharField(max_length=32, blank=True)      # historical-forecast / archive
    fetched_at = models.DateTimeField(auto_now=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    grid_elevation = models.FloatField(null=True, blank=True)
    temp_c = models.FloatField(null=True, blank=True)
    feels_c = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)
    dew_point_c = models.FloatField(null=True, blank=True)
    precip_mm = models.FloatField(null=True, blank=True)       # total during the activity
    rain_mm = models.FloatField(null=True, blank=True)
    weather_code = models.IntegerField(null=True, blank=True)
    cloud_pct = models.FloatField(null=True, blank=True)
    pressure_msl = models.FloatField(null=True, blank=True)
    pressure_surface = models.FloatField(null=True, blank=True)
    wind_kmh = models.FloatField(null=True, blank=True)
    gust_kmh = models.FloatField(null=True, blank=True)
    wind_dir = models.FloatField(null=True, blank=True)        # where the wind comes from, degrees
    visibility_m = models.FloatField(null=True, blank=True)
    headwind_kmh = models.FloatField(null=True, blank=True)    # average along the route (+ = into the wind)
    headwind_share = models.FloatField(null=True, blank=True)  # share of time with > 5 km/h headwind
    hourly = models.JSONField(default=dict)                    # the hours around the activity
    error = models.CharField(max_length=255, blank=True)


class Narrative(models.Model):
    """Written summaries for a page section. Empty in v1 (placeholder text is shown)."""
    key = models.CharField(max_length=64, primary_key=True)  # e.g. "overview", "run", "health"
    title = models.CharField(max_length=128, blank=True)
    text = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class KeyValue(models.Model):
    """Small settings store: heart rate zones, endpoint availability, cursors."""
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls, key, default=None):
        row = cls.objects.filter(key=key).first()
        return row.value if row else default

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(key=key, defaults={"value": value})


class SyncRun(models.Model):
    RUNNING = "running"
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, default=RUNNING)
    mode = models.CharField(max_length=12, default="incremental")
    phase = models.CharField(max_length=64, blank=True)
    done = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    message = models.CharField(max_length=255, blank=True)
    new_activities = models.IntegerField(default=0)
    log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    pid = models.IntegerField(null=True, blank=True)  # process running the sync

    class Meta:
        ordering = ["-started_at"]
