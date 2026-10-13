"""Testes do collect_images.py. Rodar com: python3 -m unittest discover -s FASE6/scripts"""

import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

import collect_images as ci


def result(pid, **overrides):
    # Resultado mínimo no formato da API do Openverse
    r = {
        "id": f"uuid-{pid}", "url": f"https://live.staticflickr.com/1234/{pid}_abc123_b.jpg",
        "title": "Cow", "creator": "Fulano", "creator_url": "https://www.flickr.com/photos/fulano",
        "license": "by", "license_version": "2.0", "license_url": "https://creativecommons.org/licenses/by/2.0/",
        "foreign_landing_url": f"https://www.flickr.com/photos/fulano/{pid}", "attribution": '"Cow" by Fulano',
    }
    r.update(overrides)
    return r


def parsed(pid):
    return ci.parse_results(json.dumps({"results": [result(pid)]}))[0]


class FlickrPhotoIdTest(unittest.TestCase):
    def test_openverse_url(self):
        self.assertEqual(ci.flickr_photo_id("https://live.staticflickr.com/8061/8183766228_c7b668f830_b.jpg"), 8183766228)

    def test_coco_url(self):
        self.assertEqual(ci.flickr_photo_id("http://farm4.staticflickr.com/3153/2970773875_164f0c0b83_z.jpg"), 2970773875)

    def test_url_without_size_suffix(self):
        self.assertEqual(ci.flickr_photo_id("https://farm1.staticflickr.com/1/123_abcdef.jpg"), 123)

    def test_invalid_urls(self):
        for url in ("", "https://upload.wikimedia.org/a/ab/Cow.jpg", "https://live.staticflickr.com/1/123_abc_b.png"):
            with self.assertRaises(ValueError):
                ci.flickr_photo_id(url)


class ParseResultsTest(unittest.TestCase):
    def test_valid_response(self):
        photos = ci.parse_results(json.dumps({"results": [result(1), result(2)]}))
        self.assertEqual([p["flickr_id"] for p in photos], [1, 2])
        self.assertEqual(photos[0]["landing_url"], "https://www.flickr.com/photos/fulano/1")

    def test_empty_list_is_valid_end_of_results(self):
        self.assertEqual(ci.parse_results('{"results": []}'), [])

    def test_optional_fields_null_become_empty_string(self):
        photo = ci.parse_results(json.dumps({"results": [result(1, creator=None, creator_url=None, title=None)]}))[0]
        self.assertEqual((photo["creator"], photo["creator_url"], photo["title"]), ("", "", ""))

    def test_not_json(self):
        with self.assertRaises(ValueError):
            ci.parse_results("<html>rate limited</html>")

    def test_missing_results_key(self):
        with self.assertRaises(ValueError):
            ci.parse_results('{"detail": "throttled"}')

    def test_results_not_a_list(self):
        with self.assertRaises(ValueError):
            ci.parse_results('{"results": null}')

    def test_result_without_license(self):
        r = result(1)
        del r["license"]
        with self.assertRaises(ValueError):
            ci.parse_results(json.dumps({"results": [r]}))

    def test_result_with_non_flickr_url(self):
        with self.assertRaises(ValueError):
            ci.parse_results(json.dumps({"results": [result(1, url="https://example.com/x.jpg")]}))


class IterPhotosTest(unittest.TestCase):
    def fake_fetch(self, pages):
        # pages: {(query, page): [ids]}; páginas ausentes são vazias
        return lambda query, page: [parsed(i) for i in pages.get((query, page), [])]

    def test_deduplicates_across_queries_and_tags_query(self):
        fetch = self.fake_fetch({("a", 1): [1, 2], ("b", 1): [2, 3]})
        photos = list(ci.iter_photos(["a", "b"], fetch))
        self.assertEqual([p["flickr_id"] for p in photos], [1, 2, 3])
        self.assertEqual(photos[2]["query"], "b")

    def test_follows_pages_until_empty(self):
        fetch = self.fake_fetch({("a", 1): [1], ("a", 2): [2]})
        self.assertEqual([p["flickr_id"] for p in ci.iter_photos(["a"], fetch)], [1, 2])

    def test_fetches_lazily(self):
        fetch = mock.Mock(side_effect=lambda q, p: [parsed(p)])
        next(ci.iter_photos(["a"], fetch))
        self.assertEqual(fetch.call_count, 1)  # não busca a página seguinte sem precisar


class CollectClassTest(unittest.TestCase):
    def setUp(self):
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory())) / "cow"
        self.out.mkdir()
        self.fetch = lambda q, page: [parsed(i) for i in range(1, 6)] if page == 1 else []

    def test_excludes_coco_and_stops_at_target(self):
        download = mock.Mock()
        kept, stats = ci.collect_class(["a"], self.out, {1, 3}, 2, fetch=self.fetch, download=download)
        self.assertEqual([p["flickr_id"] for p in kept], [2, 4])
        self.assertEqual(stats["coco"], 2)
        self.assertEqual(kept[0]["file"], "cow/flickr_2.jpg")
        downloaded = [c.args[0] for c in download.call_args_list]
        self.assertFalse(any("/1_" in u or "/3_" in u for u in downloaded))  # foto do COCO nunca é baixada

    def test_failed_download_is_counted_and_skipped(self):
        def download(url, _dest):
            if "/2_" in url:
                raise RuntimeError("404")
        kept, stats = ci.collect_class(["a"], self.out, set(), 3, fetch=self.fetch, download=download)
        self.assertEqual([p["flickr_id"] for p in kept], [1, 3, 4])
        self.assertEqual(stats["falha"], 1)

    def test_returns_fewer_when_results_run_out(self):
        kept, _ = ci.collect_class(["a"], self.out, set(), 10, fetch=self.fetch, download=mock.Mock())
        self.assertEqual(len(kept), 5)

    def test_unexpected_error_is_not_swallowed(self):
        download = mock.Mock(side_effect=PermissionError("disco"))
        with self.assertRaises(PermissionError):
            ci.collect_class(["a"], self.out, set(), 2, fetch=self.fetch, download=download)


class LoadCocoIdsTest(unittest.TestCase):
    def setUp(self):
        self.zip_path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "ann.zip"

    def write_zip(self, members):
        with zipfile.ZipFile(self.zip_path, "w") as zf:
            for name, urls in members.items():
                zf.writestr(name, json.dumps({"images": [{"flickr_url": u} for u in urls]}))

    def test_reads_train_and_val(self):
        self.write_zip({
            ci.COCO_MEMBERS[0]: ["http://farm1.staticflickr.com/1/111_aa_z.jpg"],
            ci.COCO_MEMBERS[1]: ["http://farm1.staticflickr.com/1/222_bb_z.jpg"],
        })
        self.assertEqual(ci.load_coco_ids(self.zip_path), {111, 222})

    def test_missing_member(self):
        self.write_zip({ci.COCO_MEMBERS[0]: []})
        with self.assertRaises(KeyError):
            ci.load_coco_ids(self.zip_path)

    def test_malformed_flickr_url(self):
        self.write_zip({ci.COCO_MEMBERS[0]: ["not-a-url"], ci.COCO_MEMBERS[1]: []})
        with self.assertRaises(ValueError):
            ci.load_coco_ids(self.zip_path)


class DownloadFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.dest = self.tmp / "img.jpg"

    def test_writes_jpeg(self):
        with mock.patch.object(ci, "http_get", return_value=b"\xff\xd8data"):
            self.assertTrue(ci.download_file("u", self.dest))
        self.assertEqual(self.dest.read_bytes(), b"\xff\xd8data")
        self.assertEqual(list(self.tmp.iterdir()), [self.dest])  # sem .part sobrando

    def test_skips_existing_file(self):
        self.dest.write_bytes(b"old")
        with mock.patch.object(ci, "http_get") as get:
            self.assertFalse(ci.download_file("u", self.dest))
        get.assert_not_called()

    def test_rejects_non_jpeg_and_leaves_nothing(self):
        with mock.patch.object(ci, "http_get", return_value=b"<html>"):
            with self.assertRaises(ValueError):
                ci.download_file("u", self.dest)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_empty_body_rejected(self):
        with mock.patch.object(ci, "http_get", return_value=b""):
            with self.assertRaises(ValueError):
                ci.download_file("u", self.dest)

    def test_network_failure_propagates_and_leaves_nothing(self):
        err = urllib.error.URLError("timeout")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError):
                ci.download_file("https://x/img.jpg", self.dest)
        self.assertEqual(list(self.tmp.iterdir()), [])


class SplitDatasetTest(unittest.TestCase):
    files = [f"cow/flickr_{i}.jpg" for i in range(40)]

    def test_sizes_and_no_overlap(self):
        split = ci.split_dataset(self.files)
        self.assertEqual({k: len(v) for k, v in split.items()}, {"train": 32, "val": 4, "test": 4})
        all_files = split["train"] + split["val"] + split["test"]
        self.assertEqual(sorted(all_files), sorted(self.files))

    def test_deterministic_regardless_of_input_order(self):
        self.assertEqual(ci.split_dataset(self.files), ci.split_dataset(list(reversed(self.files))))

    def test_wrong_count(self):
        for files in ([], self.files[:39], self.files + ["cow/extra.jpg"]):
            with self.assertRaises(ValueError):
                ci.split_dataset(files)

    def test_duplicates(self):
        with self.assertRaises(ValueError):
            ci.split_dataset(self.files[:39] + [self.files[0]])

    def test_forced_files_land_in_test(self):
        forced = [self.files[5], self.files[30]]
        split = ci.split_dataset(self.files, forced)
        self.assertEqual({k: len(v) for k, v in split.items()}, {"train": 32, "val": 4, "test": 4})
        self.assertTrue(set(forced) <= set(split["test"]))
        self.assertEqual(sorted(split["train"] + split["val"] + split["test"]), sorted(self.files))

    def test_forced_is_deterministic(self):
        forced = [self.files[5]]
        self.assertEqual(ci.split_dataset(self.files, forced), ci.split_dataset(list(reversed(self.files)), forced))

    def test_all_test_slots_forced(self):
        forced = self.files[:4]
        self.assertEqual(sorted(ci.split_dataset(self.files, forced)["test"]), sorted(forced))

    def test_too_many_forced(self):
        with self.assertRaises(ValueError):
            ci.split_dataset(self.files, self.files[:5])

    def test_forced_outside_files(self):
        with self.assertRaises(ValueError):
            ci.split_dataset(self.files, ["cow/outra.jpg"])


class ReadApprovedTest(unittest.TestCase):
    def setUp(self):
        self.cand = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for rel in ("cow/a.jpg", "dog/b.jpg"):
            (self.cand / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.cand / rel).write_bytes(b"\xff\xd8")
        self.approved = self.cand / "approved.txt"

    def test_groups_by_class_and_ignores_comments(self):
        self.approved.write_text("# cabeçalho\ncow/a.jpg  # boa\n\ndog/b.jpg\n", encoding="utf-8")
        approved, forced = ci.read_approved(self.approved, self.cand)
        self.assertEqual(approved, {"cow": ["cow/a.jpg"], "dog": ["dog/b.jpg"]})
        self.assertEqual(forced, {"cow": [], "dog": []})

    def test_test_marker(self):
        self.approved.write_text("cow/a.jpg test  # difícil\ndog/b.jpg\n", encoding="utf-8")
        approved, forced = ci.read_approved(self.approved, self.cand)
        self.assertEqual(approved, {"cow": ["cow/a.jpg"], "dog": ["dog/b.jpg"]})
        self.assertEqual(forced, {"cow": ["cow/a.jpg"], "dog": []})

    def test_invalid_marker(self):
        for line in ("cow/a.jpg teste\n", "cow/a.jpg test extra\n"):
            self.approved.write_text(line, encoding="utf-8")
            with self.assertRaises(ValueError):
                ci.read_approved(self.approved, self.cand)

    def test_empty_file(self):
        self.approved.write_text("", encoding="utf-8")
        self.assertEqual(ci.read_approved(self.approved, self.cand), ({"cow": [], "dog": []}, {"cow": [], "dog": []}))

    def test_unknown_class(self):
        self.approved.write_text("cat/a.jpg\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            ci.read_approved(self.approved, self.cand)

    def test_missing_file(self):
        self.approved.write_text("cow/nope.jpg\n", encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            ci.read_approved(self.approved, self.cand)


if __name__ == "__main__":
    unittest.main()
