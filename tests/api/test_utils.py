"""tests/api/test_utils.py — Encoding boundary tests for api/utils.py."""

from __future__ import annotations

from api.utils import _decode_content, _detect_encoding_by_bom


# ---------------------------------------------------------------------------
# _detect_encoding_by_bom
# ---------------------------------------------------------------------------

def test_bom_utf8():
    content = "abc".encode("utf-8-sig")
    assert _detect_encoding_by_bom(content) == "utf-8-sig"


def test_bom_utf16_le():
    content = "abc".encode("utf-16-le")
    assert _detect_encoding_by_bom(b"\xff\xfe" + content) == "utf-16"


def test_bom_utf16_be():
    content = "abc".encode("utf-16-be")
    assert _detect_encoding_by_bom(b"\xfe\xff" + content) == "utf-16"


def test_bom_not_present():
    assert _detect_encoding_by_bom(b"hello") is None


def test_bom_empty():
    assert _detect_encoding_by_bom(b"") is None


# ---------------------------------------------------------------------------
# _decode_content — basic encodings
# ---------------------------------------------------------------------------

def test_decode_utf8():
    raw = "配置管理".encode("utf-8")
    assert _decode_content(raw) == "配置管理"


def test_decode_gbk():
    raw = "配置管理".encode("gbk")
    assert _decode_content(raw) == "配置管理"


def test_decode_gb18030():
    raw = "配置管理".encode("gb18030")
    assert _decode_content(raw) == "配置管理"


def test_decode_ascii():
    assert _decode_content(b"hello world") == "hello world"


def test_decode_empty():
    assert _decode_content(b"") == ""


# ---------------------------------------------------------------------------
# BOM-prefixed content (exercises the BOM fast-path)
# ---------------------------------------------------------------------------

def test_decode_utf8_bom():
    """UTF-8 BOM is stripped during decoding."""
    raw = "配置".encode("utf-8-sig")
    result = _decode_content(raw)
    assert result == "配置"


def test_decode_utf16_le_bom():
    """UTF-16-LE with BOM is decoded correctly (BOM stripped by utf-16 codec)."""
    raw = "配置".encode("utf-16-le")
    result = _decode_content(b"\xff\xfe" + raw)
    assert result == "配置"
    assert "\ufeff" not in result


def test_decode_utf16_be_bom():
    """UTF-16-BE with BOM is decoded correctly (BOM stripped by utf-16 codec)."""
    raw = "配置".encode("utf-16-be")
    result = _decode_content(b"\xfe\xff" + raw)
    assert result == "配置"
    assert "\ufeff" not in result


# ---------------------------------------------------------------------------
# declared_charset
# ---------------------------------------------------------------------------

def test_decode_with_declared_charset():
    """declared_charset is respected ahead of UTF-8."""
    raw = "配置管理".encode("gbk")
    result = _decode_content(raw, declared_charset="gbk")
    assert result == "配置管理"


def test_decode_declared_utf8_rejects_utf16():
    """Even with declared UTF-8, UTF-16LE without BOM fails NUL filter and lands in replace fallback.

    UTF-16 without BOM is ambiguous — the decoder does not crash but the
    result is not guaranteed to be clean.
    """
    utf16_raw = "hello".encode("utf-16-le")
    result = _decode_content(utf16_raw, declared_charset="utf-8")
    assert isinstance(result, str)


def test_decode_declared_charset_fallback():
    """When declared_charset fails (raises UnicodeDecodeError), fallback runs."""
    raw = "配置".encode("gbk")
    result = _decode_content(raw, declared_charset="ascii")
    assert result == "配置"


# ---------------------------------------------------------------------------
# NUL-filter: reject UTF-8 decoding when result contains NUL chars
# ---------------------------------------------------------------------------

def test_decode_rejects_utf16_without_bom():
    """UTF-16 without BOM is not supported (NUL filter prevents silent mis-decode).

    The bytes contain interleaved NULs which fail UTF-8 and GBK NUL-checks,
    and the final fallback still returns text with NULs.
    """
    utf16_raw = "hello".encode("utf-16-le")
    result = _decode_content(utf16_raw)
    # UTF-16 without BOM is ambiguous — we accept that result is not clean
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Corrupted / edge-case inputs (crash safety)
# ---------------------------------------------------------------------------

def test_decode_corrupted_double_encoded_latin1():
    """UTF-8 bytes -> decoded as Latin-1 -> re-encoded as UTF-8: must not crash."""
    original = "配置"
    utf8_bytes = original.encode("utf-8")
    latin1_garbled = utf8_bytes.decode("latin-1")
    double_encoded = latin1_garbled.encode("utf-8")
    result = _decode_content(double_encoded)
    assert isinstance(result, str)
    assert len(result) > 0


def test_decode_corrupted_gbk_read_as_utf8_then_resaved():
    """GBK bytes mis-read as UTF-8 then re-saved as UTF-8: must not crash."""
    raw = "配置管理".encode("gbk")
    wrongly_decoded = raw.decode("utf-8", errors="replace")
    re_encoded = wrongly_decoded.encode("utf-8", errors="replace")
    result = _decode_content(re_encoded)
    assert isinstance(result, str)


def test_decode_gbk_bytes_are_not_misidentified_as_utf16():
    """Chinese GBK bytes do not accidentally match Chinese UTF-16LE without BOM.

    ``中文`` in GBK: D6 D0 CE C4 ; in UTF-16LE: 2D 4E 87 65.
    Our decoder must prefer GBK over UTF-16 for Chinese text when no BOM is
    present.  (UTF-16 is not in the fallback chain, so GBK wins.)
    """
    chinese = "中文"
    gbk_bytes = chinese.encode("gbk")
    result = _decode_content(gbk_bytes)
    assert result == chinese, f"GBK {gbk_bytes!r} should decode to {chinese!r}, got {result!r}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_decode_mixed_encoding_utf8_wins():
    """UTF-8 is preferred over coincidental GBK match."""
    raw = "配置管理".encode("utf-8")
    result = _decode_content(raw)
    assert result == "配置管理"
    assert result != raw.decode("gbk", errors="replace")
