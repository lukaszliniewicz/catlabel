from __future__ import annotations

import base64
import math
import tempfile
import unittest
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from PIL import Image as PILImage
from PIL import ImageFont, features
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from catlabel.core import resource_limits
from catlabel.core.models import Font
from catlabel.services import uploads


class TrackingUploadFile(UploadFile):
    def __init__(self, filename: str | None, data: bytes) -> None:
        self.read_sizes: list[int] = []
        self.close_calls = 0
        super().__init__(filename=filename, file=BytesIO(data))

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return await super().read(size)

    async def close(self) -> None:
        self.close_calls += 1
        await super().close()


class FakePdfBitmap:
    def __init__(self, size: tuple[int, int]) -> None:
        self.image = PILImage.new("RGB", size, (255, 255, 255))
        self.close_calls = 0

    def to_pil(self) -> PILImage.Image:
        return self.image

    def close(self) -> None:
        self.close_calls += 1


class FakePdfPage:
    def __init__(
        self,
        size: tuple[object, object],
        *,
        fail_render: bool = False,
    ) -> None:
        self.size = size
        self.fail_render = fail_render
        self.render_scales: list[float] = []
        self.close_calls = 0
        self.bitmap: FakePdfBitmap | None = None

    def get_size(self) -> tuple[object, object]:
        return self.size

    def render(self, scale: float = 1) -> FakePdfBitmap:
        self.render_scales.append(scale)
        if self.fail_render:
            raise RuntimeError("private PDF processing detail")
        width, height = self.size
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            raise AssertionError("fake page dimensions must be numeric to render")
        self.bitmap = FakePdfBitmap(
            (math.ceil(width * scale), math.ceil(height * scale))
        )
        return self.bitmap

    def close(self) -> None:
        self.close_calls += 1


class FakePdfDocument:
    def __init__(self, pages: list[FakePdfPage]) -> None:
        self.pages = pages
        self.close_calls = 0

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int) -> FakePdfPage:
        return self.pages[index]

    def close(self) -> None:
        self.close_calls += 1


class UploadLimitsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.font_directory = Path(self._temporary.name) / "fonts"
        font_directory_patch = patch.object(
            uploads, "_FONT_DIRECTORY", self.font_directory
        )
        font_directory_patch.start()
        self.addCleanup(font_directory_patch.stop)

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def _font_data(self) -> bytes:
        self.assertTrue(features.check("freetype2"), "Pillow FreeType is required")
        default_font = ImageFont.load_default()
        font_bytes = getattr(default_font, "font_bytes", None)
        self.assertIsInstance(font_bytes, bytes)
        assert isinstance(font_bytes, bytes)
        self.assertGreater(len(font_bytes), 0)
        self.assertLessEqual(len(font_bytes), uploads.MAX_UPLOAD_BYTES)
        return font_bytes

    def _database_fonts(self) -> list[Font]:
        with Session(self.engine) as session:
            return list(session.exec(select(Font)).all())

    async def _assert_upload_error(
        self, operation: Callable[..., Awaitable[object]], *args: object, status: int
    ) -> HTTPException:
        with self.assertRaises(HTTPException) as raised:
            await operation(*args)
        self.assertEqual(raised.exception.status_code, status)
        return raised.exception

    async def test_font_success_validates_freetype_and_stores_original_name(
        self,
    ) -> None:
        data = self._font_data()
        uploaded = TrackingUploadFile("NotoSans-Regular.TTF", data)

        font = await uploads.store_uploaded_font(uploaded, self.engine)

        self.assertEqual(uploaded.read_sizes, [uploads.MAX_UPLOAD_BYTES + 1])
        self.assertEqual(uploaded.close_calls, 1)
        self.assertTrue(uploaded.file.closed)
        self.assertEqual(font.name, "NotoSans-Regular.TTF")
        self.assertEqual(font.file_path, "fonts/NotoSans-Regular.TTF")
        self.assertEqual(
            (self.font_directory / font.name).read_bytes(),
            data,
        )
        rows = self._database_fonts()
        self.assertEqual(
            [(row.name, row.file_path) for row in rows], [(font.name, font.file_path)]
        )

    async def test_invalid_font_names_extensions_and_bytes_create_no_files(
        self,
    ) -> None:
        invalid_names: tuple[str | None, ...] = (
            None,
            "",
            ".",
            "..",
            "../font.ttf",
            "folder/font.ttf",
            "folder\\font.ttf",
            "C:font.ttf",
            "C:\\font.ttf",
            "/font.ttf",
            "a" * 197 + ".ttf",
            "nul\x00font.ttf",
            "bad:name.ttf",
            "font?.ttf",
            "NUL.ttf",
            "CON.otf",
            "COM1.ttf",
            "LPT9.ttf",
            "font.ttf ",
        )
        for filename in invalid_names:
            with self.subTest(filename=filename):
                uploaded = TrackingUploadFile(filename, b"not a font")
                error = await self._assert_upload_error(
                    uploads.store_uploaded_font,
                    uploaded,
                    self.engine,
                    status=400,
                )
                self.assertIn("font", str(error.detail).lower())
                self.assertEqual(uploaded.read_sizes, [uploads.MAX_UPLOAD_BYTES + 1])
                self.assertEqual(uploaded.close_calls, 1)
                self.assertFalse(self.font_directory.exists())

        for filename, data in (
            ("image.png", self._font_data()),
            ("broken.ttf", b"not a valid TrueType face"),
        ):
            with self.subTest(filename=filename):
                uploaded = TrackingUploadFile(filename, data)
                await self._assert_upload_error(
                    uploads.store_uploaded_font,
                    uploaded,
                    self.engine,
                    status=400,
                )
                self.assertEqual(uploaded.close_calls, 1)
                self.assertFalse(self.font_directory.exists())

    async def test_font_size_limit_reads_once_and_closes_upload(self) -> None:
        uploaded = TrackingUploadFile("large.ttf", b"12345")
        with patch.object(uploads, "MAX_UPLOAD_BYTES", 4):
            await self._assert_upload_error(
                uploads.store_uploaded_font,
                uploaded,
                self.engine,
                status=413,
            )
        self.assertEqual(uploaded.read_sizes, [5])
        self.assertEqual(uploaded.close_calls, 1)
        self.assertFalse(self.font_directory.exists())

    async def test_existing_target_and_database_rows_are_never_overwritten(
        self,
    ) -> None:
        font_data = self._font_data()
        self.font_directory.mkdir()
        existing_target = self.font_directory / "Existing.ttf"
        existing_target.write_bytes(b"preserve existing target")
        target_upload = TrackingUploadFile("Existing.ttf", font_data)
        await self._assert_upload_error(
            uploads.store_uploaded_font,
            target_upload,
            self.engine,
            status=409,
        )
        self.assertEqual(existing_target.read_bytes(), b"preserve existing target")
        self.assertEqual(self._database_fonts(), [])

        with Session(self.engine) as session:
            database_font = Font(name="Database.ttf", file_path="fonts/Database.ttf")
            session.add(database_font)
            session.commit()
        database_upload = TrackingUploadFile("Database.ttf", font_data)
        await self._assert_upload_error(
            uploads.store_uploaded_font,
            database_upload,
            self.engine,
            status=409,
        )
        self.assertFalse((self.font_directory / "Database.ttf").exists())
        rows = self._database_fonts()
        self.assertEqual(
            [(row.name, row.file_path) for row in rows],
            [("Database.ttf", "fonts/Database.ttf")],
        )

    async def test_failed_database_commit_removes_only_its_promoted_file(self) -> None:
        self.font_directory.mkdir()
        witness = self.font_directory / "existing-witness.bin"
        witness.write_bytes(b"preserve this unrelated file")
        uploaded = TrackingUploadFile("NewFont.ttf", self._font_data())

        def fail_commit(session: Session) -> None:
            raise RuntimeError(f"database failed at {self.font_directory}/private")

        with patch.object(uploads.Session, "commit", fail_commit):
            error = await self._assert_upload_error(
                uploads.store_uploaded_font,
                uploaded,
                self.engine,
                status=500,
            )

        self.assertEqual(error.detail, "Unable to store font.")
        self.assertNotIn(str(self.font_directory), str(error.detail))
        self.assertNotIn("NewFont.ttf", str(error.detail))
        self.assertFalse((self.font_directory / "NewFont.ttf").exists())
        self.assertEqual(witness.read_bytes(), b"preserve this unrelated file")
        self.assertEqual(
            sorted(path.name for path in self.font_directory.iterdir()), [witness.name]
        )
        self.assertEqual(self._database_fonts(), [])
        self.assertEqual(uploaded.close_calls, 1)

    async def test_pdf_size_limit_reads_once_and_closes_without_parsing(self) -> None:
        uploaded = TrackingUploadFile("large.pdf", b"12345")
        with (
            patch.object(uploads, "MAX_UPLOAD_BYTES", 4),
            patch("catlabel.services.uploads.pdfium.PdfDocument") as open_pdf,
        ):
            await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                uploaded,
                status=413,
            )
        open_pdf.assert_not_called()
        self.assertEqual(uploaded.read_sizes, [5])
        self.assertEqual(uploaded.close_calls, 1)

    async def test_real_single_page_pdf_uses_203_over_72_scale_and_closes(self) -> None:
        pdf_bytes = _single_page_pdf(72.0, 36.0)
        uploaded = TrackingUploadFile("sample.pdf", pdf_bytes)

        images = await uploads.convert_uploaded_pdf(uploaded)

        self.assertEqual(uploads._PDF_SCALE, 203 / 72)
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].startswith("data:image/png;base64,"))
        png_bytes = base64.b64decode(images[0].split(",", 1)[1])
        with PILImage.open(BytesIO(png_bytes)) as image:
            self.assertEqual(image.size, (203, 102))
        self.assertLessEqual(len(png_bytes), uploads.MAX_IMAGE_BYTES)
        self.assertEqual(uploaded.read_sizes, [uploads.MAX_UPLOAD_BYTES + 1])
        self.assertEqual(uploaded.close_calls, 1)

    async def test_pdf_invalid_geometry_and_processing_errors_close_resources(
        self,
    ) -> None:
        invalid_page = FakePdfPage((math.nan, 2.0))
        invalid_document = FakePdfDocument([invalid_page])
        invalid_upload = TrackingUploadFile("invalid.pdf", b"fake pdf")
        with patch(
            "catlabel.services.uploads.pdfium.PdfDocument",
            return_value=invalid_document,
        ):
            error = await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                invalid_upload,
                status=400,
            )
        self.assertEqual(error.detail, "Invalid PDF file.")
        self.assertEqual(invalid_document.close_calls, 1)
        self.assertEqual(invalid_page.close_calls, 1)
        self.assertEqual(invalid_page.render_scales, [])
        self.assertEqual(invalid_upload.close_calls, 1)

        failed_page = FakePdfPage((1.1, 2.1), fail_render=True)
        failed_document = FakePdfDocument([failed_page])
        failed_upload = TrackingUploadFile("render-failure.pdf", b"fake pdf")
        with (
            patch(
                "catlabel.services.uploads.pdfium.PdfDocument",
                return_value=failed_document,
            ),
            patch.object(
                PILImage.Image, "close", wraps=PILImage.Image.close
            ) as close_image,
        ):
            await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                failed_upload,
                status=400,
            )
        self.assertEqual(failed_document.close_calls, 1)
        self.assertEqual(failed_page.close_calls, 1)
        self.assertEqual(failed_page.render_scales, [203 / 72])
        self.assertEqual(close_image.call_count, 0)
        self.assertEqual(failed_upload.close_calls, 1)

    async def test_pdf_encoding_failure_closes_page_bitmap_and_both_pil_images(
        self,
    ) -> None:
        page = FakePdfPage((1.1, 2.1))
        document = FakePdfDocument([page])
        uploaded = TrackingUploadFile("encode-failure.pdf", b"fake pdf")
        closed_images: list[PILImage.Image] = []
        original_close = PILImage.Image.close

        def track_image_close(image: PILImage.Image) -> None:
            closed_images.append(image)
            original_close(image)

        with (
            patch(
                "catlabel.services.uploads.pdfium.PdfDocument",
                return_value=document,
            ),
            patch.object(PILImage.Image, "save", side_effect=OSError("private path")),
            patch.object(PILImage.Image, "close", track_image_close),
        ):
            error = await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                uploaded,
                status=400,
            )

        self.assertEqual(error.detail, "Invalid PDF file.")
        self.assertNotIn("private path", str(error.detail))
        self.assertEqual(page.render_scales, [203 / 72])
        self.assertIsNotNone(page.bitmap)
        assert page.bitmap is not None
        self.assertEqual(page.bitmap.close_calls, 1)
        self.assertEqual(page.close_calls, 1)
        self.assertEqual(document.close_calls, 1)
        self.assertEqual(len(closed_images), 2)
        self.assertEqual(uploaded.close_calls, 1)

    async def test_pdf_budget_precedes_render_and_closes_allocated_resources(
        self,
    ) -> None:
        oversized_page = FakePdfPage((7200.0, 36.0))
        oversized_document = FakePdfDocument([oversized_page])
        uploaded = TrackingUploadFile("large-geometry.pdf", b"fake pdf")
        with patch(
            "catlabel.services.uploads.pdfium.PdfDocument",
            return_value=oversized_document,
        ):
            error = await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                uploaded,
                status=413,
            )
        self.assertEqual(error.detail, "Uploaded PDF exceeds a processing limit.")
        self.assertEqual(oversized_page.render_scales, [])
        self.assertEqual(oversized_page.close_calls, 1)
        self.assertEqual(oversized_document.close_calls, 1)

        page = FakePdfPage((1.1, 2.1))
        document = FakePdfDocument([page])
        upload = TrackingUploadFile("image-limit.pdf", b"fake pdf")
        closed_images: list[PILImage.Image] = []
        original_close = PILImage.Image.close

        def track_image_close(image: PILImage.Image) -> None:
            closed_images.append(image)
            original_close(image)

        with (
            patch(
                "catlabel.services.uploads.pdfium.PdfDocument",
                return_value=document,
            ),
            patch.object(uploads, "MAX_IMAGE_BYTES", 1),
            patch.object(PILImage.Image, "close", track_image_close),
        ):
            error = await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                upload,
                status=413,
            )
        self.assertEqual(error.detail, "Uploaded PDF exceeds a processing limit.")
        self.assertEqual(page.render_scales, [203 / 72])
        self.assertIsNotNone(page.bitmap)
        assert page.bitmap is not None
        self.assertEqual(page.bitmap.close_calls, 1)
        self.assertEqual(page.close_calls, 1)
        self.assertEqual(document.close_calls, 1)
        self.assertEqual(len(closed_images), 2)
        self.assertEqual(upload.close_calls, 1)

    async def test_pdf_cumulative_pixel_budget_stops_before_next_bitmap(self) -> None:
        first_page = FakePdfPage((1.1, 2.1))
        second_page = FakePdfPage((1.1, 2.1))
        document = FakePdfDocument([first_page, second_page])
        uploaded = TrackingUploadFile("aggregate.pdf", b"fake pdf")
        with (
            patch(
                "catlabel.services.uploads.pdfium.PdfDocument",
                return_value=document,
            ),
            patch.object(resource_limits, "MAX_RENDER_PIXELS", 30),
        ):
            await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                uploaded,
                status=413,
            )

        self.assertEqual(first_page.render_scales, [203 / 72])
        self.assertIsNotNone(first_page.bitmap)
        assert first_page.bitmap is not None
        self.assertEqual(first_page.bitmap.close_calls, 1)
        self.assertEqual(second_page.render_scales, [])
        self.assertIsNone(second_page.bitmap)
        self.assertEqual([first_page.close_calls, second_page.close_calls], [1, 1])
        self.assertEqual(document.close_calls, 1)
        self.assertEqual(uploaded.close_calls, 1)

    async def test_pdf_page_count_limit_rejects_before_page_render(self) -> None:
        pages = [FakePdfPage((1.0, 1.0)), FakePdfPage((1.0, 1.0))]
        document = FakePdfDocument(pages)
        uploaded = TrackingUploadFile("many-pages.pdf", b"fake pdf")
        with (
            patch(
                "catlabel.services.uploads.pdfium.PdfDocument",
                return_value=document,
            ),
            patch.object(uploads, "MAX_PRINT_JOBS", 1),
        ):
            await self._assert_upload_error(
                uploads.convert_uploaded_pdf,
                uploaded,
                status=413,
            )
        self.assertEqual(document.close_calls, 1)
        self.assertEqual([page.render_scales for page in pages], [[], []])
        self.assertEqual([page.close_calls for page in pages], [0, 0])

    async def test_invalid_pdf_response_is_generic_and_upload_closes(self) -> None:
        uploaded = TrackingUploadFile("secret-name.pdf", b"not a valid pdf payload")
        error = await self._assert_upload_error(
            uploads.convert_uploaded_pdf,
            uploaded,
            status=400,
        )
        self.assertEqual(error.detail, "Invalid PDF file.")
        self.assertNotIn("secret-name", str(error.detail))
        self.assertNotIn("payload", str(error.detail))
        self.assertEqual(uploaded.read_sizes, [uploads.MAX_UPLOAD_BYTES + 1])
        self.assertEqual(uploaded.close_calls, 1)


def _single_page_pdf(width: float, height: float) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument.new()
    page = document.new_page(width, height)
    page.close()
    with BytesIO() as output:
        document.save(output)
        result = output.getvalue()
    document.close()
    return result


if __name__ == "__main__":
    unittest.main()
