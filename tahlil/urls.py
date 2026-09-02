from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("products/", views.product_list, name="product_list"),
    path("products/<int:wp_id>/", views.product_detail, name="product_detail"),
    path("rivals/", views.rival_list, name="rival_list"),
    path("rivals/crawl/start/", views.crawl_start, name="crawl_start"),
    path("rivals/crawl/stop/", views.crawl_stop, name="crawl_stop"),
    path("rivals/crawl/status/", views.crawl_status, name="crawl_status"),
    path("compare/", views.compare_hub, name="compare_hub"),
    path("media/img/<int:image_id>/", views.media_image, name="media_image"),
    path("media/rival/<int:rival_id>/", views.rival_image, name="rival_image"),
]
