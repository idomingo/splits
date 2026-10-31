"""Fill in run kinds and places missing after an update before any page is built,
so the menu, the charts and the filters all see them on the very first page view."""


class FillMissing:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(("/static/", "/sync/")):
            try:
                from .derive import fill_missing
                from .models import SyncRun
                if not SyncRun.objects.filter(status=SyncRun.RUNNING).exists():
                    fill_missing()
            except Exception:  # never stop a page from loading over this
                pass
        return self.get_response(request)
