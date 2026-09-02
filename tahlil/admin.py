from django.contrib import admin

from .models import CompetitorOffer, Product, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("wp_id", "name", "family_label", "status", "stock", "sku")
    list_filter = ("status", "family", "product_type", "stock")
    search_fields = ("name", "sku", "wp_id", "categories")
    inlines = [ProductImageInline]


@admin.register(CompetitorOffer)
class CompetitorOfferAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "source_name", "verdict", "visual_score")
    list_filter = ("verdict",)
