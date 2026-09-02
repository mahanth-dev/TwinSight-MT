from django.db import models


class Product(models.Model):
    wp_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=500)
    slug = models.CharField(max_length=220, blank=True)
    product_type = models.CharField(max_length=20, default="simple")
    status = models.CharField(max_length=20, default="publish")
    sku = models.CharField(max_length=120, blank=True)
    price = models.CharField(max_length=40, blank=True)
    price_max = models.CharField(max_length=40, blank=True)
    stock = models.CharField(max_length=20, blank=True)
    qty = models.CharField(max_length=20, blank=True)
    variation_count = models.PositiveIntegerField(default=0)
    categories = models.CharField(max_length=800, blank=True)
    family = models.CharField(max_length=40, default="other", db_index=True)
    family_label = models.CharField(max_length=80, blank=True)
    site_url = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.wp_id} · {self.name}"

    @property
    def featured(self):
        return self.images.filter(role="featured").first() or self.images.first()

    def fingerprint_payloads(self) -> list[dict]:
        out = []
        for img in self.images.exclude(dhash=""):
            out.append({"dhash": int(img.dhash, 16), "hist": img.hist or []})
        return out

    def as_match_dict(self) -> dict:
        return {
            "id": self.wp_id,
            "name": self.name,
            "sku": self.sku,
            "price": self.price,
            "price_max": self.price_max,
            "stock": self.stock,
            "family": self.family,
            "family_label": self.family_label,
            "url": self.site_url,
            "images": [True] if self.images.exists() else [],
            "fingerprints": self.fingerprint_payloads(),
        }


class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name="images", on_delete=models.CASCADE)
    rel_path = models.CharField(max_length=500)
    role = models.CharField(max_length=20, default="featured")
    dhash = models.CharField(max_length=64, blank=True)
    hist = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["id"]


class RivalProduct(models.Model):
    """A competitor listing that survived image-first matching against one of our products."""

    VERDICTS = [("match", "match"), ("uncertain", "uncertain")]

    product = models.ForeignKey(Product, related_name="rivals", on_delete=models.CASCADE)
    shop_host = models.CharField(max_length=120, db_index=True)
    shop_name = models.CharField(max_length=120, blank=True)
    rival_ref = models.CharField(max_length=60, blank=True)
    title = models.CharField(max_length=600)
    url = models.URLField(max_length=900)
    price = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=12, blank=True)
    stock = models.CharField(max_length=20, blank=True)
    image_url = models.URLField(max_length=900, blank=True)
    image_path = models.CharField(max_length=200, blank=True)
    verdict = models.CharField(max_length=20, choices=VERDICTS, default="uncertain")
    visual_score = models.FloatField(default=0)
    title_score = models.FloatField(default=0)
    reasons = models.TextField(blank=True)
    query_used = models.CharField(max_length=200, blank=True)
    found_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-visual_score"]
        constraints = [
            models.UniqueConstraint(fields=["product", "url"], name="uniq_rival_per_product")
        ]

    def __str__(self) -> str:
        return f"{self.shop_host} · {self.title[:40]}"

    @property
    def price_delta(self):
        """Rival minus ours, in the same unit. None when either side has no number."""
        try:
            ours = float(self.product.price)
            theirs = float(self.price)
        except (TypeError, ValueError):
            return None
        if not ours or not theirs:
            return None
        return theirs - ours

    @property
    def cheaper_than_us(self):
        delta = self.price_delta
        return delta is not None and delta < 0


class CompetitorOffer(models.Model):
    product = models.ForeignKey(
        Product, null=True, blank=True, related_name="offers", on_delete=models.SET_NULL
    )
    source_name = models.CharField(max_length=160, blank=True)
    source_url = models.URLField(blank=True, max_length=800)
    title = models.CharField(max_length=500, blank=True)
    price_text = models.CharField(max_length=80, blank=True)
    verdict = models.CharField(max_length=20, default="uncertain")
    visual_score = models.FloatField(default=0)
    title_score = models.FloatField(default=0)
    reasons = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
