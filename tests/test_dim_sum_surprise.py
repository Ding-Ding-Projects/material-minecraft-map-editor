import io
import json
from pathlib import Path
from threading import Event
import time
import unittest
from urllib.error import URLError

from amulet_map_editor.api import dim_sum_surprise as surprise

ROOT = Path(__file__).resolve().parents[1]


def dish_document():
    return {
        "id": "hk-dish-0001",
        "name": {"en": "Classic Har Gow", "zhHant": "蝦餃"},
        "image": {
            "path": "images/hk-dish-0001-classic-har-gow.png",
            "alt": {
                "en": "Warm tea-house photograph of Classic Har Gow",
                "yue": "港式茶樓木枱上嘅蝦餃",
            },
        },
    }


class FakeResponse(io.BytesIO):
    def __init__(self, payload, *, content_length=None):
        super().__init__(payload)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def geturl(self):
        return surprise.CATALOG_URL

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class DimSumSurpriseTestCase(unittest.TestCase):
    def metadata(self):
        return surprise.DishMetadata(
            dish_id="hk-dish-0001",
            name_english="Classic Har Gow",
            name_cantonese="蝦餃",
            alt_english="Warm tea-house photograph of Classic Har Gow",
            alt_cantonese="港式茶樓木枱上嘅蝦餃",
            image_asset_path="images/hk-dish-0001-classic-har-gow.png",
        )

    def test_draw_probability_boundaries_are_exactly_ten_percent(self):
        self.assertTrue(surprise.should_show(0.0))
        self.assertTrue(surprise.should_show(0.099999999))
        self.assertFalse(surprise.should_show(0.1))
        self.assertFalse(surprise.should_show(0.999999999))
        with self.assertRaises(ValueError):
            surprise.should_show(1.0)

    def test_single_startup_instance_never_draws_or_fires_twice(self):
        draws = []
        payloads = []
        ready = Event()

        def draw():
            draws.append(0.0)
            return 0.0

        def receive(payload):
            payloads.append(payload)
            ready.set()

        controller = surprise.StartupDimSumSurprise(
            random_value=draw,
            chooser=lambda dishes: dishes[0],
            catalog_fetcher=lambda: (self.metadata(),),
        )
        self.assertTrue(controller.begin("english", receive))
        self.assertFalse(controller.begin("english", receive))
        self.assertTrue(ready.wait(1.0))
        self.assertEqual(draws, [0.0])
        self.assertEqual(len(payloads), 1)
        self.assertTrue(payloads[0].non_blocking)
        self.assertFalse(payloads[0].steal_focus)

    def test_all_language_modes_use_authoritative_names_and_alt_text(self):
        dish = self.metadata()
        english = surprise.build_payload(dish, "english")
        cantonese = surprise.build_payload(dish, "cantonese")
        bilingual = surprise.build_payload(dish, "bilingual")
        self.assertEqual(english.title, "Classic Har Gow")
        self.assertEqual(english.alt_text, dish.alt_english)
        self.assertEqual(cantonese.title, "蝦餃")
        self.assertEqual(cantonese.alt_text, dish.alt_cantonese)
        self.assertEqual(bilingual.title, "Classic Har Gow · 蝦餃")
        self.assertIn(dish.alt_english, bilingual.alt_text)
        self.assertIn(dish.alt_cantonese, bilingual.alt_text)

    def test_native_projection_copy_is_factual_and_non_networked(self):
        payload = surprise.build_payload(self.metadata(), "bilingual")
        title, body = surprise.notification_copy(payload)
        self.assertIn("Classic Har Gow · 蝦餃", title)
        self.assertIn(self.metadata().alt_english, body)
        self.assertIn(self.metadata().alt_cantonese, body)
        self.assertIn(self.metadata().image_asset_path, body)
        self.assertNotIn("http", body)

    def test_projection_rejects_non_ready_payloads(self):
        payload = surprise.DimSumSurprisePayload(
            status="offline",
            dish_id="hk-dish-0001",
            title="Classic Har Gow",
            alt_text="alt",
            image_asset_path="images/dish.png",
        )
        with self.assertRaises(ValueError):
            surprise.notification_copy(payload)

    def test_catalog_fetch_is_bounded_and_extracts_only_display_metadata(self):
        raw = json.dumps(
            {"schemaVersion": "1.0.0", "dishes": [dish_document()]}
        ).encode("utf-8")
        seen = {}

        def opener(request, *, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            return FakeResponse(raw, content_length=len(raw))

        dishes = surprise.fetch_public_catalog(opener=opener)
        self.assertEqual(seen["url"], surprise.CATALOG_URL)
        self.assertLessEqual(seen["timeout"], surprise.CATALOG_TIMEOUT_SECONDS)
        self.assertEqual(dishes, (self.metadata(),))

        too_large = surprise.fetch_public_catalog(
            opener=lambda *_args, **_kwargs: FakeResponse(
                b"{}", content_length=surprise.MAX_CATALOG_BYTES + 1
            )
        )
        self.assertEqual(too_large, ())

    def test_offline_failure_is_a_quiet_no_op(self):
        self.assertEqual(
            surprise.fetch_public_catalog(
                opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    URLError("offline")
                )
            ),
            (),
        )
        called = Event()
        controller = surprise.StartupDimSumSurprise(
            random_value=lambda: 0.0,
            catalog_fetcher=lambda: (),
        )
        self.assertTrue(controller.begin("english", lambda _payload: called.set()))
        time.sleep(0.05)
        self.assertFalse(called.is_set())

    def test_consumer_repository_contains_no_dim_sum_image_copies(self):
        image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
        copied = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and path.suffix.lower() in image_suffixes
            and (
                "dim_sum" in path.as_posix().lower()
                or "dim-sum" in path.as_posix().lower()
            )
        ]
        self.assertEqual(copied, [])


if __name__ == "__main__":
    unittest.main()
