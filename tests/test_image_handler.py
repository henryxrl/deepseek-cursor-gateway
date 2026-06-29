from __future__ import annotations

import base64
import io
import json
import struct
import subprocess
import unittest
from unittest import mock
from urllib.error import HTTPError
import zlib

from deepseek_cursor_gateway import image_handler
from deepseek_cursor_gateway.image_handler import (
    ImageInputRejected,
    ImageSecurityViolation,
    OcrError,
    SecurityConfig,
    VisionConfig,
    _call_gemini_vision,
    _call_openai_vision,
    _decode_base64_data_url,
    _describe_image,
    _validate_url,
    count_image_blocks,
    sanitize_image_payload_for_trace,
)


class CountImageBlocksTest(unittest.TestCase):

    def test_pure_text_string_content(self):
        messages = [{"role": "user", "content": "Hello, world"}]
        self.assertEqual(count_image_blocks(messages), 0)

    def test_pure_text_array_content(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "text", "text": "Describe it."},
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 0)

    def test_single_image_url(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/a.png"},
                    },
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 1)

    def test_mixed_text_and_image(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/a.png"},
                    },
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 1)

    def test_multiple_images(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://a.com/1.png"}},
                    {"type": "image_url", "image_url": {"url": "https://a.com/2.png"}},
                    {"type": "image_url", "image_url": {"url": "https://a.com/3.png"}},
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 3)

    def test_images_across_multiple_messages(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://a.com/1.png"}},
                ],
            },
            {"role": "assistant", "content": "I see an image."},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://a.com/2.png"}},
                    {"type": "text", "text": "And this?"},
                ],
            },
        ]
        self.assertEqual(count_image_blocks(messages), 2)

    def test_unknown_content_part_not_counted_as_image(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "unknown_type", "data": "something"},
                    {"type": "image_url", "image_url": {"url": "https://a.com/x.png"}},
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 1)

    def test_base64_image_url(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                    },
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 1)

    def test_image_only_message(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://a.com/photo.jpg"},
                    },
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 1)

    def test_empty_content(self):
        self.assertEqual(count_image_blocks([]), 0)
        self.assertEqual(count_image_blocks([{"role": "user"}]), 0)
        self.assertEqual(count_image_blocks([{"role": "user", "content": None}]), 0)
        self.assertEqual(count_image_blocks(None), 0)
        self.assertEqual(count_image_blocks({"role": "user"}), 0)
        self.assertEqual(count_image_blocks(["not a message dict"]), 0)

    def test_image_url_with_detail_field(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://a.com/img.png", "detail": "high"},
                    },
                ],
            }
        ]
        self.assertEqual(count_image_blocks(messages), 1)


class ImageInputRejectedTest(unittest.TestCase):

    def test_exception_message(self):
        exc = ImageInputRejected(5)
        self.assertEqual(exc.image_count, 5)
        self.assertIn("5 image block", str(exc))
        self.assertIn("image_handling=strip", str(exc))
        self.assertIn("image_handling=ocr", str(exc))


class ImageSecurityTest(unittest.TestCase):

    def test_validate_url_blocks_dns_that_resolves_to_private_ip(self):
        fake_info = [
            (None, None, None, "", ("192.168.1.20", 443)),
        ]
        with mock.patch(
            "deepseek_cursor_gateway.image_handler.socket.getaddrinfo",
            return_value=fake_info,
        ):
            with self.assertRaises(ImageSecurityViolation):
                _validate_url("https://example.test/image.png", allow_local=False)

    def test_validate_url_allows_dns_that_resolves_to_public_ip(self):
        fake_info = [
            (None, None, None, "", ("93.184.216.34", 443)),
        ]
        with mock.patch(
            "deepseek_cursor_gateway.image_handler.socket.getaddrinfo",
            return_value=fake_info,
        ):
            _validate_url("https://example.test/image.png", allow_local=False)

    def test_data_url_mime_is_validated(self):
        payload = base64.b64encode(b"hello").decode("ascii")
        with self.assertRaises(ImageSecurityViolation):
            _decode_base64_data_url(
                f"data:text/html;base64,{payload}",
                SecurityConfig(),
            )


class TraceSanitizerTest(unittest.TestCase):

    def test_sanitizes_image_urls_and_ocr_summaries(self):
        payload = {
            "model": "deepseek-v4-pro",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,SECRET",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "[Image attachment converted by gateway]\n\n"
                                "OCR / visual summary:\nSECRET OCR TEXT"
                            ),
                        },
                    ],
                }
            ],
        }

        sanitized = sanitize_image_payload_for_trace(payload)
        content = sanitized["messages"][0]["content"]

        self.assertEqual(
            content[1]["image_url"],
            {"url": "[image_url omitted from trace]", "detail": "high"},
        )
        self.assertEqual(content[2]["text"], "[OCR summary omitted from trace]")
        self.assertIn(
            "SECRET", payload["messages"][0]["content"][1]["image_url"]["url"]
        )
        self.assertNotIn("SECRET", str(sanitized))


class GeminiVisionTest(unittest.TestCase):

    def test_uses_custom_base_url(self):
        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value.read.return_value = (
            b'{"candidates":[{"content":{"parts":[{"text":"summary"}]}}]}'
        )

        vision = VisionConfig(
            backend="gemini",
            base_url="https://vision-proxy.example.test/v1beta/",
            model="gemini-2.0-flash",
            api_key="secret-key",
            timeout=12,
        )
        with mock.patch(
            "deepseek_cursor_gateway.image_handler.urlopen",
            return_value=fake_response,
        ) as mock_urlopen:
            result = _call_gemini_vision(b"fake-png-bytes", vision)

        self.assertEqual(result, "summary")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            (
                "https://vision-proxy.example.test/v1beta/models/"
                "gemini-2.0-flash:generateContent?key=secret-key"
            ),
        )
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 12)


class OpenAICompatibleVisionTest(unittest.TestCase):

    def test_uses_detected_image_mime(self):
        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"summary"}}]}'
        )

        vision = VisionConfig(
            backend="openai_compatible",
            base_url="https://vision-proxy.example.test/v1",
            model="gpt-4o-mini",
            api_key="secret-key",
            timeout=12,
        )
        with mock.patch(
            "deepseek_cursor_gateway.image_handler.urlopen",
            return_value=fake_response,
        ) as mock_urlopen:
            result = _call_openai_vision(b"\xff\xd8\xffjpeg-bytes", vision)

        self.assertEqual(result, "summary")
        request = mock_urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        image_url = body["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/jpeg;base64,"))
        self.assertEqual(body["max_tokens"], 1024)
        self.assertNotIn("max_completion_tokens", body)

    def test_uses_max_completion_tokens_for_gpt5(self):
        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"summary"}}]}'
        )

        vision = VisionConfig(
            backend="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="gpt-5.4-mini",
            api_key="secret-key",
            timeout=12,
        )
        with mock.patch(
            "deepseek_cursor_gateway.image_handler.urlopen",
            return_value=fake_response,
        ) as mock_urlopen:
            result = _call_openai_vision(b"\x89PNG\r\n\x1a\npng-bytes", vision)

        self.assertEqual(result, "summary")
        request = mock_urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["max_completion_tokens"], 1024)
        self.assertNotIn("max_tokens", body)

    def test_http_error_includes_provider_body(self):
        error_body = b'{"error":{"message":"model does not support image input"}}'
        http_error = HTTPError(
            "https://vision-proxy.example.test/v1/chat/completions",
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(error_body),
        )
        vision = VisionConfig(
            backend="openai_compatible",
            base_url="https://vision-proxy.example.test/v1",
            model="text-only-model",
            api_key="secret-key",
        )
        with mock.patch(
            "deepseek_cursor_gateway.image_handler.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaises(OcrError) as ctx:
                _call_openai_vision(b"\x89PNG\r\n\x1a\npng-bytes", vision)

        self.assertIn("Vision API returned 400", str(ctx.exception))
        self.assertIn("model does not support image input", str(ctx.exception))


class VisionConcurrencyTest(unittest.TestCase):

    def tearDown(self):
        image_handler.init_vision_concurrency(0)

    def test_init_vision_concurrency_zero_disables_limit(self):
        image_handler.init_vision_concurrency(1)
        self.assertIsNotNone(image_handler._vision_semaphore)

        image_handler.init_vision_concurrency(0)
        self.assertIsNone(image_handler._vision_semaphore)

    def test_describe_image_uses_semaphore_around_backend_call(self):
        events = []

        class RecordingSemaphore:
            def acquire(self):
                events.append("acquire")

            def release(self):
                events.append("release")

        def fake_backend(image_bytes, vision):
            events.append("backend")
            return "summary"

        vision = VisionConfig(backend="openai_compatible")
        with mock.patch(
            "deepseek_cursor_gateway.image_handler._vision_semaphore",
            RecordingSemaphore(),
        ):
            with mock.patch(
                "deepseek_cursor_gateway.image_handler._call_openai_vision",
                side_effect=fake_backend,
            ):
                summary = _describe_image(b"fake-image", vision, ocr_cache=None)

        self.assertEqual(summary, "summary")
        self.assertEqual(events, ["acquire", "backend", "release"])

    def test_describe_image_releases_semaphore_when_backend_fails(self):
        events = []

        class RecordingSemaphore:
            def acquire(self):
                events.append("acquire")

            def release(self):
                events.append("release")

        def fake_backend(image_bytes, vision):
            events.append("backend")
            raise OcrError("boom")

        vision = VisionConfig(backend="openai_compatible")
        with mock.patch(
            "deepseek_cursor_gateway.image_handler._vision_semaphore",
            RecordingSemaphore(),
        ):
            with mock.patch(
                "deepseek_cursor_gateway.image_handler._call_openai_vision",
                side_effect=fake_backend,
            ):
                with self.assertRaises(OcrError):
                    _describe_image(b"fake-image", vision, ocr_cache=None)

        self.assertEqual(events, ["acquire", "backend", "release"])

    def test_describe_image_cache_hit_does_not_acquire_semaphore(self):
        cache = mock.Mock()
        cache.get.return_value = "cached summary"
        semaphore = mock.Mock()
        semaphore.acquire.side_effect = AssertionError(
            "cache hits should not acquire vision semaphore"
        )

        vision = VisionConfig(backend="openai_compatible")
        with mock.patch(
            "deepseek_cursor_gateway.image_handler._vision_semaphore", semaphore
        ):
            with mock.patch(
                "deepseek_cursor_gateway.image_handler._call_openai_vision",
                side_effect=AssertionError("cache hits should not call vision backend"),
            ):
                summary = _describe_image(b"fake-image", vision, cache)

        self.assertEqual(summary, "cached summary")
        semaphore.acquire.assert_not_called()
        cache.put.assert_not_called()


class VisionFallbackTest(unittest.TestCase):

    def test_describe_image_uses_fallback_backend_after_primary_failure(self):
        vision = VisionConfig(
            backend="openai_compatible",
            fallback_backend="tesseract",
            tesseract_lang="eng",
        )

        with mock.patch(
            "deepseek_cursor_gateway.image_handler._call_openai_vision",
            side_effect=OcrError("primary down"),
        ) as primary:
            with mock.patch(
                "deepseek_cursor_gateway.image_handler._call_tesseract_ocr",
                return_value="fallback text",
            ) as fallback:
                summary = _describe_image(b"fake-image", vision, ocr_cache=None)

        self.assertEqual(summary, "fallback text")
        primary.assert_called_once()
        fallback.assert_called_once()

    def test_describe_image_raises_primary_error_without_fallback(self):
        vision = VisionConfig(backend="openai_compatible")

        with mock.patch(
            "deepseek_cursor_gateway.image_handler._call_openai_vision",
            side_effect=OcrError("primary down"),
        ):
            with self.assertRaises(OcrError) as ctx:
                _describe_image(b"fake-image", vision, ocr_cache=None)

        self.assertIn("primary down", str(ctx.exception))


class VisionWarmupImageTest(unittest.TestCase):

    def test_embedded_warmup_png_has_valid_chunks(self):
        data = image_handler._VISION_WARMUP_IMAGE_BYTES
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")

        pos = 8
        seen_iend = False
        while pos < len(data):
            length = struct.unpack(">I", data[pos : pos + 4])[0]
            chunk_type = data[pos + 4 : pos + 8]
            chunk_data = data[pos + 8 : pos + 8 + length]
            expected_crc = struct.unpack(
                ">I", data[pos + 8 + length : pos + 12 + length]
            )[0]
            actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
            self.assertEqual(actual_crc, expected_crc, chunk_type)
            if chunk_type == b"IEND":
                seen_iend = True
            pos += 12 + length

        self.assertTrue(seen_iend)
        self.assertEqual(pos, len(data))


class TesseractOcrTest(unittest.TestCase):

    def test_tesseract_returns_extracted_text(self):
        from deepseek_cursor_gateway.image_handler import _call_tesseract_ocr

        fake_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Hello world\nfrom an image\n",
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=fake_result) as mock_run:
            vision = VisionConfig(backend="tesseract", tesseract_lang="eng", timeout=30)
            result = _call_tesseract_ocr(b"fake-png-bytes", vision)

        self.assertEqual(result, "Hello world\nfrom an image")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "tesseract")
        self.assertEqual(args[2], "stdout")
        self.assertIn("-l", args)
        self.assertIn("eng", args)

    def test_tesseract_not_installed_raises_clear_error(self):
        from deepseek_cursor_gateway.image_handler import _call_tesseract_ocr

        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            vision = VisionConfig(backend="tesseract", tesseract_lang="eng", timeout=30)
            with self.assertRaises(OcrError) as ctx:
                _call_tesseract_ocr(b"fake", vision)
            self.assertIn("not installed", str(ctx.exception))

    def test_tesseract_nonzero_exit_raises_ocr_error(self):
        from deepseek_cursor_gateway.image_handler import _call_tesseract_ocr

        exc = subprocess.CalledProcessError(1, "tesseract", stderr="bad image")
        with mock.patch("subprocess.run", side_effect=exc):
            vision = VisionConfig(backend="tesseract", tesseract_lang="eng", timeout=30)
            with self.assertRaises(OcrError) as ctx:
                _call_tesseract_ocr(b"fake", vision)
            self.assertIn("exited with code 1", str(ctx.exception))

    def test_tesseract_empty_output_returns_placeholder(self):
        from deepseek_cursor_gateway.image_handler import _call_tesseract_ocr

        fake_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="  \n  ",
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=fake_result):
            vision = VisionConfig(backend="tesseract", tesseract_lang="eng", timeout=30)
            result = _call_tesseract_ocr(b"fake", vision)

        self.assertEqual(result, "(no text detected in image)")

    def test_describe_image_dispatches_to_tesseract(self):
        vision = VisionConfig(
            backend="tesseract", tesseract_lang="eng+chi_sim", timeout=10
        )
        fake_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="extracted text",
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=fake_result):
            summary = _describe_image(b"fake-image-bytes", vision, ocr_cache=None)

        self.assertEqual(summary, "extracted text")


if __name__ == "__main__":
    unittest.main()
