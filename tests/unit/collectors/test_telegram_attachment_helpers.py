# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure attachment helpers in the Telegram collector: the operator retrieval link and
the mime->kind map. The download/gate path rides the live Telethon client (coverage-
omitted); these are the bug-prone pure bits."""

from __future__ import annotations

import pytest

from eyenet.collectors.telegram.real import _mime_to_kind, _tme_link
from eyenet.contracts.enums import AttachmentKind

pytestmark = pytest.mark.unit


def test_tme_link_numeric_channel_is_private_c_form() -> None:
    # -100 supergroup prefix stripped; private c/ deep-link
    assert _tme_link("-1001234567890", 42) == "https://t.me/c/1234567890/42"
    assert _tme_link("1234567890", 7) == "https://t.me/c/1234567890/7"


def test_tme_link_username_is_public_form() -> None:
    assert _tme_link("@durov", 99) == "https://t.me/durov/99"
    assert _tme_link("somechannel", 1) == "https://t.me/somechannel/1"


@pytest.mark.parametrize(
    ("mime", "kind"),
    [
        ("image/png", AttachmentKind.IMAGE),
        ("video/mp4", AttachmentKind.VIDEO),
        ("audio/ogg", AttachmentKind.AUDIO),
        ("application/pdf", AttachmentKind.DOCUMENT),
        ("application/octet-stream", AttachmentKind.DOCUMENT),
    ],
)
def test_mime_to_kind(mime: str, kind: AttachmentKind) -> None:
    assert _mime_to_kind(mime) == kind
