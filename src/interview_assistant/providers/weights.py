"""Local model weights: what each downloadable model needs, whether it is on disk, and the download.

Weights are pinned to a commit (Hugging Face; GitHub for the Tesseract language data) and large
files to their sha256, so what runs is what was reviewed. One set can gather files from several
repos into sub-folders (a PaddleOCR bundle: detection, recognition, orientation). Nothing is fetched until an admin presses "다운로드" (admin > 모델 설정); checking
whether a model is present only looks at file sizes on disk, never the network. Files land in
`IA_WEIGHTS_DIR` (default `weights/`, git-ignored): `<dir>.partial/` while downloading, renamed to
`<dir>/` once every file is complete and verified. An interrupted download resumes where it
stopped. `HF_ENDPOINT` (mirror) and `HF_TOKEN` are honoured; HTTP(S)_PROXY as usual.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Literal

log = logging.getLogger(__name__)

MARKER = ".complete.json"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class WeightFile:
    name: str  # path under the set's folder; may contain "/" ("det/inference.pdiparams")
    size: int
    sha256: str | None = None  # Git LFS files carry one; small JSON/text files do not
    # Where the file comes from when not `<set repo>/<name>`: another Hugging Face repo and commit
    # (`repo_id`, `revision`, `remote` = path in that repo), or a full pinned URL (GitHub raw).
    repo_id: str | None = None
    revision: str | None = None
    remote: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class WeightSet:
    key: str  # folder under the weights dir, e.g. "faster-whisper/medium"
    repo_id: str
    revision: str  # commit sha
    files: tuple[WeightFile, ...]
    license: str = "MIT"

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def path(self, root: Path) -> Path:
        return Path(root) / self.key

    def url(self, name: str, endpoint: str) -> str:
        return f"{endpoint.rstrip('/')}/{self.repo_id}/resolve/{self.revision}/{name}"

    def file_url(self, f: WeightFile, endpoint: str) -> str:
        if f.url:
            return f.url
        repo, revision = f.repo_id or self.repo_id, f.revision or self.revision
        return f"{endpoint.rstrip('/')}/{repo}/resolve/{revision}/{f.remote or f.name}"


def _whisper(size: str, repo_id: str, revision: str, *files: WeightFile) -> WeightSet:
    return WeightSet(f"faster-whisper/{size}", repo_id, revision, files)


# faster-whisper (CTranslate2) conversions of OpenAI Whisper, MIT. Checked 2026-10-25. v3 models
# carry 128 mel bins, hence the preprocessor config.
WHISPER: dict[str, WeightSet] = {
    "small": _whisper(
        "small",
        "Systran/faster-whisper-small",
        "536b0662742c02347bc0e980a01041f333bce120",
        WeightFile("config.json", 2370),
        WeightFile(
            "model.bin",
            483546902,
            "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        ),
        WeightFile("tokenizer.json", 2203239),
        WeightFile("vocabulary.txt", 459861),
    ),
    "medium": _whisper(
        "medium",
        "Systran/faster-whisper-medium",
        "08e178d48790749d25932bbc082711ddcfdfbc4f",
        WeightFile("config.json", 2257),
        WeightFile(
            "model.bin",
            1527906378,
            "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae",
        ),
        WeightFile("tokenizer.json", 2203239),
        WeightFile("vocabulary.txt", 459861),
    ),
    "large-v3": _whisper(
        "large-v3",
        "Systran/faster-whisper-large-v3",
        "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        WeightFile("config.json", 2394),
        WeightFile(
            "model.bin",
            3087284237,
            "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
        ),
        WeightFile("preprocessor_config.json", 340),
        WeightFile("tokenizer.json", 2480617),
        WeightFile("vocabulary.json", 1068114),
    ),
    # Formerly mobiuslabsgmbh/faster-whisper-large-v3-turbo (faster-whisper's "turbo" alias).
    "large-v3-turbo": _whisper(
        "large-v3-turbo",
        "dropbox-dash/faster-whisper-large-v3-turbo",
        "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        WeightFile("config.json", 2263),
        WeightFile(
            "model.bin",
            1617884929,
            "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da",
        ),
        WeightFile("preprocessor_config.json", 340),
        WeightFile("tokenizer.json", 2710337),
        WeightFile("vocabulary.json", 1068114),
    ),
}


def _paddle(folder: str, repo: str, revision: str, files: dict[str, tuple[int, str]]) -> list[WeightFile]:
    """One PaddleOCR model (inference.json/.pdiparams/.yml) from its own repo, into `folder`/."""
    return [
        WeightFile(f"{folder}/{name}", size, sha, f"PaddlePaddle/{repo}", revision, name)
        for name, (size, sha) in files.items()
    ]


# PP-OCRv5 (PaddlePaddle, Apache-2.0), checked 2026-10-26. A bundle is what one "model" choice
# needs: text detection (mobile or server), the Korean recognizer (Korean, English, digits) and
# the two small orientation classifiers the options can switch on. sha256 for every file.
_PADDLE_REC = _paddle(
    "rec",
    "korean_PP-OCRv5_mobile_rec",
    "c02ecaf1f22bfd1c618cce154fd19185b47e663a",
    {
        "inference.json": (217724, "562404e3c590c50c93778d5f0a94df21b47b5ab8f3ea6d47c7f8a7930c3bc844"),
        "inference.pdiparams": (13342671, "cac3e5f12cf04aaa77f6a5bc704e4e736ef2908476551891d84b41b4e9090462"),
        "inference.yml": (96039, "f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998"),
    },
)
_PADDLE_ORIENTATION = [
    *_paddle(
        "textline_ori",
        "PP-LCNet_x1_0_textline_ori",
        "cd237a44b0e359d4fe38310a416203cf7403faa5",
        {
            "inference.json": (104399, "b81929eeaff8e52db0fafb49c9fbfc5bc0572f81641fe0179cc52096323fb4d4"),
            "inference.pdiparams": (6743918, "0de2bcf996cf553e2b848dd7b1769dafffc6917b1ccdf55c1d8efe7909fbf743"),
            "inference.yml": (735, "8d5120d0e1a30a9df7ed46aa9119da3796ed066777089d1c1d705f132d5e90f9"),
        },
    ),
    *_paddle(
        "doc_ori",
        "PP-LCNet_x1_0_doc_ori",
        "d3b95a6dff5fe8a94f2748e12b61cb26818a0df8",
        {
            "inference.json": (104441, "3580978602f309c3554508dd85d4fe09b73a7e0d80d7f9e63258f5b72c390c69"),
            "inference.pdiparams": (6754166, "e8d6e7c5d264507e40e58a655779059d616b20d7441ea22047d829eb3931989c"),
            "inference.yml": (766, "9e195eb729a8173588cd0e8a852c8b373aa606e79e77b4ac7d8346f5426caf26"),
        },
    ),
]
PADDLEOCR: dict[str, WeightSet] = {
    "ppocrv5-mobile": WeightSet(
        "paddleocr/ppocrv5-mobile-ko",
        "PaddlePaddle/PP-OCRv5_mobile_det",
        "0d63e78e2b680928f6b1747d76a08db6e645efb7",
        (
            *_paddle(
                "det",
                "PP-OCRv5_mobile_det",
                "0d63e78e2b680928f6b1747d76a08db6e645efb7",
                {
                    "inference.json": (229777, "05feef1acb00aa4cd7362b15f7f501fc4f99d7b1fa73c1c871e0c7b1504b0f5c"),
                    "inference.pdiparams": (4692937, "afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b"),
                    "inference.yml": (903, "98069072e1b6b37d727fd9d9f11725faa46d6ea0de012f2ed26caea011c37699"),
                },
            ),
            *_PADDLE_REC,
            *_PADDLE_ORIENTATION,
        ),
        license="Apache-2.0",
    ),
    "ppocrv5-server": WeightSet(
        "paddleocr/ppocrv5-server-ko",
        "PaddlePaddle/PP-OCRv5_server_det",
        "ca867c897ecbca8873081573a802ad70d499cb94",
        (
            *_paddle(
                "det",
                "PP-OCRv5_server_det",
                "ca867c897ecbca8873081573a802ad70d499cb94",
                {
                    "inference.json": (402480, "af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28"),
                    "inference.pdiparams": (87932887, "183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d"),
                    "inference.yml": (903, "28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685"),
                },
            ),
            *_PADDLE_REC,
            *_PADDLE_ORIENTATION,
        ),
        license="Apache-2.0",
    ),
}


def _tessdata(flavour: str, commit: str, files: dict[str, tuple[int, str]]) -> WeightSet:
    base = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_{flavour}/{commit}"
    return WeightSet(
        f"tesseract/tessdata-{flavour}",
        f"tesseract-ocr/tessdata_{flavour}",
        commit,
        tuple(WeightFile(name, size, sha, url=f"{base}/{name}") for name, (size, sha) in files.items()),
        license="Apache-2.0",
    )


# Tesseract language data (Apache-2.0) from GitHub, pinned to a commit, checked 2026-10-26.
# Korean plus English (addresses, e-mail, English names on Korean resumes).
TESSDATA: dict[str, WeightSet] = {
    "best": _tessdata(
        "best",
        "e12c65a915945e4c28e237a9b52bc4a8f39a0cec",
        {
            "kor.traineddata": (12528128, "f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff"),
            "eng.traineddata": (15400601, "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba"),
        },
    ),
    "fast": _tessdata(
        "fast",
        "87416418657359cb625c412a48b6e1d6d41c29bd",
        {
            "kor.traineddata": (1677415, "6b85e11d9bbf07863b97b3523b1b112844c43e713df8b66418a081fd1060b3b2"),
            "eng.traineddata": (4113088, "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"),
        },
    ),
}


def is_complete(weights: WeightSet, root: Path) -> bool:
    """Every file present with its expected size, and the marker written after verification."""
    folder = weights.path(root)
    if not (folder / MARKER).is_file():
        return False
    for f in weights.files:
        p = folder / f.name
        if not p.is_file() or p.stat().st_size != f.size:
            return False
    return True


# --- download ---------------------------------------------------------------------------------

Status = Literal["missing", "downloading", "done", "failed", "cancelled"]
Opener = Callable[[urllib.request.Request], Any]  # urlopen-like; tests pass an in-memory one


@dataclass
class DownloadState:
    key: str
    status: Status
    total_bytes: int
    downloaded_bytes: int = 0
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)


class DownloadCancelled(Exception):
    pass


class DownloadManager:
    """Background downloads, one thread per model, progress readable at any time."""

    def __init__(
        self,
        root: Path,
        *,
        endpoint: str | None = None,
        token: str | None = None,
        opener: Opener | None = None,
    ) -> None:
        self.root = Path(root)
        self.endpoint = endpoint or os.environ.get("HF_ENDPOINT") or "https://huggingface.co"
        self.token = token if token is not None else os.environ.get("HF_TOKEN")
        self.opener: Opener = opener or (
            lambda request: urllib.request.urlopen(request, timeout=60)
        )
        self._states: dict[str, DownloadState] = {}
        self._lock = threading.Lock()

    def state(self, weights: WeightSet) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
        if current is not None and current.status in ("downloading", "failed", "cancelled"):
            return current
        if is_complete(weights, self.root):
            return DownloadState(weights.key, "done", weights.size_bytes, weights.size_bytes)
        return DownloadState(
            weights.key, "missing", weights.size_bytes, self._partial_bytes(weights)
        )

    def start(self, weights: WeightSet) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
            if current is not None and current.status == "downloading":
                return current
            if is_complete(weights, self.root):
                return DownloadState(weights.key, "done", weights.size_bytes, weights.size_bytes)
            state = DownloadState(
                weights.key,
                "downloading",
                weights.size_bytes,
                self._partial_bytes(weights),
                started_at=time.time(),
            )
            state.thread = threading.Thread(
                target=self._run, args=(weights, state), name=f"download {weights.key}", daemon=True
            )
            self._states[weights.key] = state
            state.thread.start()
            return state

    def cancel(self, weights: WeightSet) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
        if current is not None and current.status == "downloading":
            current.cancel.set()
            if current.thread is not None:
                current.thread.join(timeout=10)
        return self.state(weights)

    def wait(self, weights: WeightSet, timeout: float | None = None) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
        if current is not None and current.thread is not None:
            current.thread.join(timeout)
        return self.state(weights)

    def _partial_bytes(self, weights: WeightSet) -> int:
        partial = weights.path(self.root).with_name(weights.path(self.root).name + ".partial")
        if not partial.is_dir():
            return 0
        return sum(p.stat().st_size for p in partial.rglob("*") if p.is_file())

    # Runs in the download thread.
    def _run(self, weights: WeightSet, state: DownloadState) -> None:
        final = weights.path(self.root)
        partial = final.with_name(final.name + ".partial")
        try:
            partial.mkdir(parents=True, exist_ok=True)
            done_before = 0
            for f in weights.files:
                self._fetch(weights, f, partial / f.name, state, done_before)
                done_before += f.size
                state.downloaded_bytes = done_before
            (partial / MARKER).write_text(
                json.dumps(
                    {
                        "repo_id": weights.repo_id,
                        "revision": weights.revision,
                        "files": {f.name: f.size for f in weights.files},
                    }
                ),
                encoding="utf-8",
            )
            if final.exists():
                shutil.rmtree(final)
            os.replace(partial, final)
            state.status = "done"
        except DownloadCancelled:
            shutil.rmtree(partial, ignore_errors=True)
            state.status = "cancelled"
            state.downloaded_bytes = 0
        except Exception as exc:  # network, disk, hash: reported on the admin screen
            log.warning("weights download failed for %s: %s", weights.key, exc)
            state.status = "failed"
            state.error = _describe(exc)
        finally:
            state.finished_at = time.time()

    def _fetch(
        self,
        weights: WeightSet,
        f: WeightFile,
        target: Path,
        state: DownloadState,
        done_before: int,
    ) -> None:
        digest = hashlib.sha256() if f.sha256 else None
        target.parent.mkdir(parents=True, exist_ok=True)
        have = target.stat().st_size if target.exists() else 0
        if have > f.size:
            target.unlink()
            have = 0
        if have and digest is not None:
            with target.open("rb") as existing:
                for block in iter(lambda: existing.read(_CHUNK), b""):
                    digest.update(block)
        if have < f.size:
            url = weights.file_url(f, self.endpoint)
            headers = {"User-Agent": "interview-assistant"}
            if self.token and url.startswith(self.endpoint):  # never hand the HF token elsewhere
                headers["Authorization"] = f"Bearer {self.token}"
            if have:
                headers["Range"] = f"bytes={have}-"
            request = urllib.request.Request(url, headers=headers)
            with self.opener(request) as response:
                if have and getattr(response, "status", 200) != 206:  # no resume: start over
                    have = 0
                    digest = hashlib.sha256() if f.sha256 else None
                with target.open("ab" if have else "wb") as out:
                    self._copy(response, out, digest, state, done_before + have)
        size = target.stat().st_size
        if size != f.size:
            raise OSError(f"{f.name}: expected {f.size} bytes, got {size}")
        if digest is not None and digest.hexdigest() != f.sha256:
            target.unlink()
            raise OSError(f"{f.name}: sha256 mismatch (the file was discarded)")

    @staticmethod
    def _copy(
        response: BinaryIO, out: BinaryIO, digest: Any, state: DownloadState, offset: int
    ) -> None:
        written = 0
        while True:
            if state.cancel.is_set():
                raise DownloadCancelled
            block = response.read(_CHUNK)
            if not block:
                return
            out.write(block)
            if digest is not None:
                digest.update(block)
            written += len(block)
            state.downloaded_bytes = offset + written


def _describe(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return f"{type(exc).__name__}: {text}"[:300]
