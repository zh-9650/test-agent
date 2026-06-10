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


def test_decode_declared_utf8_takes_nul_check_path():
    """declared UTF-8 still goes through NUL-check (doesn't decode UTF-16 as UTF-8)."""
    utf16_raw = "hello".encode("utf-16-le")
    result = _decode_content(utf16_raw, declared_charset="utf-8")
    # Should NOT return text with NUL characters; falls back to another encoding
    assert "\x00" not in result


def test_decode_declared_charset_fallback():
    """When declared_charset fails (raises UnicodeDecodeError), fallback runs."""
    raw = "配置".encode("gbk")
    result = _decode_content(raw, declared_charset="ascii")
    assert result == "配置"


# ---------------------------------------------------------------------------
# NUL-filter: reject UTF-8 decoding when result contains NUL chars
# ---------------------------------------------------------------------------

def test_decode_rejects_utf16_without_bom():
    """UTF-16 without BOM is rejected by UTF-8 check and caught by fallback."""
    utf16_raw = "hello".encode("utf-16-le")
    result = _decode_content(utf16_raw)
    assert result == "hello"
    assert "\x00" not in result


# ---------------------------------------------------------------------------
# Real mojibake scenarios
# ---------------------------------------------------------------------------

def test_decode_utf8_bytes_as_latin1_then_reencode():
    """Simulate: original UTF-8 bytes -> decoded as Latin-1 -> re-encoded as UTF-8.

    This is a common double-encoding bug.  _decode_content should not crash
    and should return usable (though not recoverable) text.
    """
    original = "配置"
    utf8_bytes = original.encode("utf-8")
    latin1_garbled = utf8_bytes.decode("latin-1")
    double_encoded = latin1_garbled.encode("utf-8")
    result = _decode_content(double_encoded)
    assert result is not None
    assert len(result) > 0


def test_decode_gbk_as_utf8():
    """Simulate: GBK bytes decoded as UTF-8 (= the original bug that caused 閰嶇疆).

    _decode_content should try GBK fallback and recover correctly.
    """
    raw = "配置管理".encode("gbk")
    wrongly_decoded = raw.decode("utf-8", errors="replace")
    # Now re-encode (as if the garbled text was saved and re-uploaded)
    re_encoded = wrongly_decoded.encode("utf-8", errors="replace")
    result = _decode_content(re_encoded)
    assert result is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_decode_mixed_encoding_utf8_wins():
    """UTF-8 is preferred over coincidental GBK match."""
    raw = "配置管理".encode("utf-8")
    result = _decode_content(raw)
    assert result == "配置管理"
    assert result != raw.decode("gbk", errors="replace")
