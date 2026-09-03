from django.urls import path

from . import manage_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("products/", views.product_list, name="product_list"),
    path("products/<int:wp_id>/", views.product_detail, name="product_detail"),
    path("rivals/", views.rival_list, name="rival_list"),
    path("compare/", views.compare_hub, name="compare_hub"),
    path("media/img/<int:image_id>/", views.media_image, name="media_image"),
    path("media/rival/<int:rival_id>/", views.rival_image, name="rival_image"),
    path("manage/", manage_views.panel, name="manage_panel"),
    path("manage/crawl/start/", manage_views.crawl_start, name="crawl_start"),
    path("manage/crawl/stop/", manage_views.crawl_stop, name="crawl_stop"),
    path("manage/crawl/status/", manage_views.crawl_status, name="crawl_status"),
    path("manage/tests/run/", manage_views.run_test, name="manage_run_test"),
]
