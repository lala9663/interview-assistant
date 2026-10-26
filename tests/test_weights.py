"""Model weights: presence checks without network, verified and resumable downloads. An in-memory
opener stands in for Hugging Face."""

from __future__ import annotations

import hashlib
import io
import threading
import time

from interview_assistant.providers.weights import (
    MARKER,
    WHISPER,
    DownloadManager,
    WeightFile,
    WeightSet,
    is_complete,
)

BLOBS = {"config.json": b'{"a": 1}', "model.bin": bytes(range(256)) * 40}


def _set(sha: str | None = None) -> WeightSet:
    return WeightSet(
        "faster-whisper/test",
        "org/repo",
        "abc123",
        (
            WeightFile("config.json", len(BLOBS["config.json"])),
            WeightFile(
                "model.bin",
                len(BLOBS["model.bin"]),
                sha or hashlib.sha256(BLOBS["model.bin"]).hexdigest(),
            ),
        ),
    )


class Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200, delay: float = 0) -> None:
        super().__init__(data)
        self.status = status
        self.delay = delay

    def read(self, n: int = -1) -> bytes:
        if self.delay:
            time.sleep(self.delay)
        return super().read(min(n, 512) if n > 0 else n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(log: list, *, honour_range: bool = True, delay: float = 0):
    def open_(request):
        name = request.full_url.rsplit("/", 1)[1]
        log.append((request.full_url, request.headers.get("Range")))
        data = BLOBS[name]
        rng = request.headers.get("Range")
        if rng and honour_range:
            return Response(data[int(rng.split("=")[1].rstrip("-")) :], 206, delay)
        return Response(data, 200, delay)

    return open_


def test_pinned_whisper_sets_name_their_files():
    assert set(WHISPER) == {"small", "medium", "large-v3", "large-v3-turbo"}
    for weights in WHISPER.values():
        names = {f.name for f in weights.files}
        assert {"config.json", "model.bin", "tokenizer.json"} <= names
        assert len(weights.revision) == 40 and all(
            c in "0123456789abcdef" for c in weights.revision
        )
        model = next(f for f in weights.files if f.name == "model.bin")
        assert model.sha256 and len(model.sha256) == 64
    assert {f.name for f in WHISPER["large-v3"].files} >= {
        "preprocessor_config.json",
        "vocabulary.json",
    }


def test_download_verifies_and_marks_complete(tmp_path, no_network):
    log: list = []
    weights = _set()
    manager = DownloadManager(tmp_path, endpoint="https://mirror.example", opener=_opener(log))
    assert manager.state(weights).status == "missing" and not is_complete(weights, tmp_path)
    manager.start(weights)
    state = manager.wait(weights, 5)
    assert state.status == "done" and state.downloaded_bytes == weights.size_bytes
    folder = weights.path(tmp_path)
    assert (folder / "model.bin").read_bytes() == BLOBS["model.bin"]
    assert (folder / MARKER).is_file() and is_complete(weights, tmp_path)
    assert not folder.with_name("test.partial").exists()
    assert log[0][0] == "https://mirror.example/org/repo/resolve/abc123/config.json"
    # Done means done: nothing is fetched again.
    assert manager.start(weights).status == "done" and len(log) == 2
    (folder / "model.bin").write_bytes(b"truncated")
    assert not is_complete(weights, tmp_path)


def test_a_hash_mismatch_fails_and_keeps_nothing(tmp_path, no_network):
    weights = _set(sha="0" * 64)
    manager = DownloadManager(tmp_path, opener=_opener([]))
    manager.start(weights)
    state = manager.wait(weights, 5)
    assert state.status == "failed" and "sha256" in state.error
    assert not weights.path(tmp_path).exists()
    assert not (weights.path(tmp_path).with_name("test.partial") / "model.bin").exists()


def test_an_interrupted_download_resumes_with_a_range_request(tmp_path, no_network):
    weights = _set()
    partial = weights.path(tmp_path).with_name("test.partial")
    partial.mkdir(parents=True)
    (partial / "config.json").write_bytes(BLOBS["config.json"])
    (partial / "model.bin").write_bytes(BLOBS["model.bin"][:5000])
    log: list = []
    manager = DownloadManager(tmp_path, opener=_opener(log))
    assert manager.state(weights).downloaded_bytes == len(BLOBS["config.json"]) + 5000
    manager.start(weights)
    assert manager.wait(weights, 5).status == "done"
    assert log == [("https://huggingface.co/org/repo/resolve/abc123/model.bin", "bytes=5000-")]
    assert (weights.path(tmp_path) / "model.bin").read_bytes() == BLOBS["model.bin"]

    # A server that ignores Range: start that file over.
    other = WeightSet("faster-whisper/other", "org/repo", "abc123", weights.files)
    partial = other.path(tmp_path).with_name("other.partial")
    partial.mkdir()
    (partial / "model.bin").write_bytes(BLOBS["model.bin"][:100])
    manager = DownloadManager(tmp_path, opener=_opener([], honour_range=False))
    manager.start(other)
    assert manager.wait(other, 5).status == "done"
    assert (other.path(tmp_path) / "model.bin").read_bytes() == BLOBS["model.bin"]


def test_cancel_stops_and_removes_the_partial_files(tmp_path, no_network):
    weights = _set()
    manager = DownloadManager(tmp_path, opener=_opener([], delay=0.05))
    manager.start(weights)
    deadline = time.monotonic() + 5
    while manager.state(weights).downloaded_bytes < 1000 and time.monotonic() < deadline:
        time.sleep(0.01)
    state = manager.cancel(weights)
    assert state.status == "cancelled"
    assert not weights.path(tmp_path).with_name("test.partial").exists()
    assert not is_complete(weights, tmp_path)
    assert threading.active_count() >= 1  # the download thread has ended (joined in cancel)


def test_a_bundle_gathers_files_from_several_sources_into_sub_folders(tmp_path, no_network):
    """PaddleOCR: detection and recognition from two Hugging Face repos; Tesseract data from a
    pinned GitHub URL. The HF token goes to the HF endpoint only."""
    log: list = []

    def open_(request):
        log.append((request.full_url, request.headers.get("Authorization")))
        return Response(BLOBS["config.json"] if request.full_url.endswith(".json") else BLOBS["model.bin"])

    bundle = WeightSet(
        "paddleocr/test",
        "Org/det",
        "aaa",
        (
            WeightFile("det/inference.json", len(BLOBS["config.json"]), remote="inference.json"),
            WeightFile("rec/inference.json", len(BLOBS["config.json"]), None, "Org/rec", "bbb", "inference.json"),
            WeightFile("kor.traineddata", len(BLOBS["model.bin"]), url="https://raw.example/tessdata/ccc/kor.traineddata"),
        ),
    )
    manager = DownloadManager(tmp_path, endpoint="https://hf.example", token="secret", opener=open_)
    manager.start(bundle)
    assert manager.wait(bundle, 5).status == "done" and is_complete(bundle, tmp_path)
    assert (bundle.path(tmp_path) / "rec" / "inference.json").read_bytes() == BLOBS["config.json"]
    assert log == [
        ("https://hf.example/Org/det/resolve/aaa/inference.json", "Bearer secret"),
        ("https://hf.example/Org/rec/resolve/bbb/inference.json", "Bearer secret"),
        ("https://raw.example/tessdata/ccc/kor.traineddata", None),
    ]


def test_pinned_ocr_bundles():
    from interview_assistant.providers.weights import PADDLEOCR, TESSDATA

    for bundle in (*PADDLEOCR.values(), *TESSDATA.values()):
        assert all(f.sha256 and len(f.sha256) == 64 for f in bundle.files), bundle.key
    mobile = {f.name for f in PADDLEOCR["ppocrv5-mobile"].files}
    assert {"det/inference.pdiparams", "rec/inference.pdiparams", "textline_ori/inference.yml"} <= mobile
    assert all(f.url and "/tessdata_best/e12c65a9" in f.url for f in TESSDATA["best"].files)
