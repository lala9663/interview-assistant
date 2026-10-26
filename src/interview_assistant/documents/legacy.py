"""Legacy Office files (.doc, .ppt): converted by LibreOffice headless into .docx / .pptx, then read
by the DOCX and PPTX extractors like any other file.

LibreOffice is a system program (providers/programs.py finds it); without it a legacy file is
refused with `ConverterMissing` ("변환기 없음"), which the admin screen and the intake failure
codes report as such. Each conversion runs in its own temporary folder with a throwaway user
profile (no clash with a LibreOffice the operator has open, nothing left behind), with macros
off (headless conversion never runs them) and a time limit. The converted file is read from
that folder and the folder is deleted; nothing is kept.

Properties, hidden text, comments, headers and footers survive the conversion, so the
de-identification sees what it sees in a .docx. Password-protected legacy files cannot be
converted and are refused as unreadable.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from interview_assistant.documents.base import ConverterMissing, ExtractionError
from interview_assistant.providers.programs import LIBREOFFICE

_TARGETS = {"doc": "docx", "ppt": "pptx"}


class LibreOfficeConverter:
    def __init__(self, timeout: int = 120, **_: Any) -> None:
        self.timeout = timeout
        self.model = "LibreOffice (headless)"
        self.version = "LibreOffice"

    async def warm_up(self) -> None:
        self._program()

    def _program(self) -> Path:
        exe = LIBREOFFICE.find()
        if exe is None:
            raise ConverterMissing(
                "구형 .doc/.ppt 변환기(LibreOffice)가 이 서버에 없습니다. 관리자에게 설치를 요청하거나 "
                ".docx/.pptx/.pdf로 다시 저장해 올려 주세요."
            )
        version = LIBREOFFICE.version()
        if version:
            self.version = version
        return exe

    def convert(self, data: bytes, fmt: str) -> bytes:
        target = _TARGETS.get(fmt)
        if target is None:
            raise ExtractionError(f"'{fmt}'는 변환할 수 있는 형식이 아닙니다.")
        exe = self._program()
        with tempfile.TemporaryDirectory(prefix="ia-convert-") as tmp:
            folder = Path(tmp)
            source = folder / f"input.{fmt}"
            source.write_bytes(data)
            out = folder / "out"
            profile = (folder / "profile").resolve().as_uri()
            try:
                done = subprocess.run(
                    [
                        str(exe), "--headless", "--norestore", "--nologo", "--nodefault",
                        "--nolockcheck", f"-env:UserInstallation={profile}",
                        "--convert-to", target, "--outdir", str(out), str(source),
                    ],
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )  # fmt: skip
            except subprocess.TimeoutExpired:
                raise ExtractionError(
                    f".{fmt} 변환이 {self.timeout}초 안에 끝나지 않았습니다 (손상되었거나 암호가 걸린 파일)."
                ) from None
            converted = out / f"input.{target}"
            if done.returncode != 0 or not converted.is_file():
                raise ExtractionError(
                    f".{fmt} 파일을 변환하지 못했습니다 (손상되었거나 암호가 걸린 파일)."
                )
            return converted.read_bytes()
