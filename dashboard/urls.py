from django.urls import path

from . import views

urlpatterns = [
    path("", views.overview, name="overview"),
    path("sport/<slug:slug>/", views.sport, name="sport"),
    path("sport/<slug:slug>/<slug:kind>/", views.sport, name="sport_kind"),
    path("activity/<int:activity_id>/runtype/", views.set_run_type, name="set_run_type"),
    path("activity/<int:activity_id>/", views.activity, name="activity"),
    path("activity/<int:activity_id>/download/", views.export_activity, name="export_activity"),
    path("log/", views.training_log, name="log"),
    path("races/", views.races, name="races"),
    path("races/<int:race_id>/", views.race, name="race"),
    path("plan/", views.plan, name="plan"),
    path("plan/template.csv", views.plan_template, name="plan_template"),
    path("courses/", views.courses, name="courses"),
    path("courses/<int:course_id>/", views.course, name="course"),
    path("places/", views.places, name="places"),
    path("places/<slug:slug>/", views.place, name="place"),
    path("places/<slug:slug>/rename/", views.rename_place, name="rename_place"),
    path("personal/", views.personal, name="personal"),
    path("health/", views.health, name="health"),
    path("feed/", views.feed_more, name="feed_more"),
    path("sync/start/", views.sync_start, name="sync_start"),
    path("sync/status/", views.sync_status, name="sync_status"),
]
