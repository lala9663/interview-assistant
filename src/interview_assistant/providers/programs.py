"""System programs some providers call (Tesseract, LibreOffice): where they are and their version.

Looked up without the network and without running anything but the program's own `--version`:
an environment variable naming the executable wins, then PATH, then the usual install folders.
Installing them is the server operator's job (docs/setup.md); the admin screen only reports
whether they were found.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Program:
    key: str  # requirement key on the admin screen
    label: str
    names: tuple[str, ...]  # executable names to look for on PATH
    env: str  # environment variable that may name the executable
    candidates: tuple[str, ...]  # usual install locations
    install: str  # how to install it, shown when missing

    def find(self) -> Path | None:
        named = os.environ.get(self.env)
        if named:
            return Path(named) if Path(named).is_file() else None
        for name in self.names:
            found = shutil.which(name)
            if found:
                return Path(found)
        for candidate in self.candidates:
            path = Path(os.path.expandvars(candidate))
            if path.is_file():
                return path
        return None

    def version(self) -> str | None:
        path = self.find()
        return _version(str(path)) if path else None


@lru_cache(maxsize=8)
def _version(path: str) -> str | None:
    # Windows soffice.exe is a GUI program and prints nothing; its console twin soffice.com does.
    console = Path(path).with_suffix(".com")
    if os.name == "nt" and path.lower().endswith(".exe") and console.is_file():
        path = str(console)
    try:
        done = subprocess.run(
            [path, "--version"], capture_output=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (done.stdout or done.stderr).decode("utf-8", "replace").strip()
    if not out:
        return None
    # "LibreOffice 26.8.1.1 bf6ef26…" (build hash dropped), "tesseract v5.4.0.20240606"
    return " ".join(out.splitlines()[0].split()[:2])


TESSERACT = Program(
    "program:tesseract",
    "프로그램 Tesseract",
    ("tesseract",),
    "TESSERACT_CMD",
    (
        r"%ProgramFiles%\Tesseract-OCR\tesseract.exe",
        r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ),
    "Windows: `winget install UB-Mannheim.TesseractOCR`, Ubuntu: `apt install tesseract-ocr`. "
    "다른 곳에 설치했으면 TESSERACT_CMD에 실행 파일 경로를 적습니다.",
)

LIBREOFFICE = Program(
    "program:soffice",
    "프로그램 LibreOffice",
    ("soffice", "libreoffice"),
    "SOFFICE_CMD",
    (
        r"%ProgramFiles%\LibreOffice\program\soffice.exe",
        r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ),
    "Windows: `winget install TheDocumentFoundation.LibreOffice`, Ubuntu: "
    "`apt install libreoffice-core libreoffice-writer libreoffice-impress`. 다른 곳에 설치했으면 "
    "SOFFICE_CMD에 실행 파일 경로를 적습니다.",
)

JAVA = Program(
    "program:java",
    "프로그램 Java",
    ("java",),
    "JAVA_CMD",
    (),
    "JRE 8 이상을 설치합니다 (hwplib 경로를 구현할 때만 필요).",
)
