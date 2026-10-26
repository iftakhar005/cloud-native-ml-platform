"""JSON responses that DECLARE their encoding.

A bare `application/json` is correct per RFC 8259 (JSON is UTF-8 by definition),
but Windows PowerShell 5.1's Invoke-RestMethod decodes a response with no charset
as ISO-8859-1, turning every Bangla character into three Latin-1 ones. Declaring
the charset costs nothing for any other client and makes this API usable from a
stock Windows machine. Found by calling the live server from PowerShell.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"
