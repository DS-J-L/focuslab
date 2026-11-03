"""Packaged, reference-preserving parrot rigs. Decode once; never perform I/O in paint.

Source atlases remain unmodified. Reviewed rectangles and facial patches register the
art at load time; a stable neutral head avoids silhouette changes during blinks.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

MAX_PART_PX = 256
CHARACTER_IDS = ("peach-lovebird", "sky-parrot", "lemon-cockatiel")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Patch:
    image: QImage
    area: QRectF  # normalized position in the unchanged neutral head


@dataclass(frozen=True)
class HeadView:
    frames: tuple[QImage, ...]  # open, half-closed, closed; one stable silhouette
    beak: QPointF  # normalized tip, measured on this viewpoint


@dataclass(frozen=True)
class CharacterArt:
    character_id: str
    parts: tuple[QImage | None, ...]
    faces: tuple[tuple[QImage, ...], ...]  # closed/open beak, nine eye expressions
    crest: QRectF | None
    fallback: QImage | None = None
    views: dict[str, tuple[HeadView, ...]] | None = None
    groom_columns: tuple[int, int] = (2, 3)  # left, right in the pitch atlas

    @property
    def head(self) -> QImage:
        return self.faces[0][0]

    @property
    def decoded_bytes(self) -> int:
        images = [im for im in self.parts if im is not None]
        if self.fallback is not None:
            images.append(self.fallback)
        images.extend(image for row in self.faces for image in row)
        if self.views:
            images.extend(image for bank in self.views.values()
                          for view in bank for image in view.frames)
        return sum(im.sizeInBytes() for im in images)


@cache
def catalog() -> dict:
    data = json.loads(files(__package__).joinpath("art/manifest.json").read_text("utf-8"))
    if data.get("version") != 1:
        raise ValueError("Unsupported parrot artwork manifest")
    return data["characters"]


def _sheet(spec: dict) -> QImage:
    data = files(__package__).joinpath("art", spec["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError(f"Parrot artwork checksum mismatch: {spec['file']}")
    image = QImage.fromData(data)
    if image.isNull() or not image.hasAlphaChannel():
        raise ValueError(f"Missing RGBA parrot artwork: {spec['file']}")
    if [image.width(), image.height()] != spec["size"]:
        raise ValueError(f"Incorrect parrot artwork size: {spec['file']}")
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def _cell(sheet: QImage, rect: list[int] | None, limit: int = MAX_PART_PX) -> QImage | None:
    if rect is None:
        return None
    source = QRect(*rect)
    if source.isEmpty() or not sheet.rect().contains(source):
        raise ValueError("Parrot source rectangle is outside its atlas")
    return sheet.copy(source).scaled(
        limit, limit,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


def _patch(head: QImage, area: list[float]) -> Patch:
    normalized = QRectF(*area)
    if not QRectF(0, 0, 1, 1).contains(normalized) or normalized.isEmpty():
        raise ValueError("Facial patch is outside the registered head")
    region = QRectF(
        normalized.x() * head.width(), normalized.y() * head.height(),
        normalized.width() * head.width(), normalized.height() * head.height(),
    ).toAlignedRect().intersected(head.rect())
    image = head.copy(region)
    # Feather only the patch's border, not the animated eye. This is a texture seam
    # mask, not a dissolve between incompatible expressions.
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    for end in ((image.width(), 0), (0, image.height())):
        gradient = QLinearGradient(0, 0, *end)
        for at, alpha in ((0, 0), (0.10, 255), (0.90, 255), (1, 0)):
            gradient.setColorAt(at, QColor(255, 255, 255, alpha))
        painter.fillRect(image.rect(), gradient)
    painter.end()
    return Patch(image, normalized)


@cache
def character_art(character_id: str) -> CharacterArt:
    if character_id not in CHARACTER_IDS:
        raise ValueError(f"Unknown parrot character: {character_id}")
    try:
        return _load_character(character_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Using static parrot art for %s: %s", character_id, exc)
        fallback = QImage.fromData(
            files(__package__).joinpath("art", f"{character_id}-fallback.png").read_bytes()
        )
        if fallback.isNull():
            raise ValueError(f"Missing fallback parrot artwork: {character_id}") from exc
        fallback = fallback.scaled(
            MAX_PART_PX, MAX_PART_PX,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        return CharacterArt(character_id, (), (), None, fallback)


def _load_character(character_id: str) -> CharacterArt:
    spec = catalog()[character_id]
    sheet = _sheet(spec["parts"])
    parts = tuple(_cell(sheet, rect) for rect in spec["parts"]["rects"])
    if any(part is None for part in parts[:8]):
        raise ValueError(f"Incomplete parrot rig: {character_id}")
    sheet = _sheet(spec["faces"])
    heads = tuple(_cell(sheet, rect) for rect in spec["faces"]["rects"])
    if len(heads) != 9 or any(head is None for head in heads):
        raise ValueError(f"Incomplete parrot expressions: {character_id}")
    if spec["crest"] is not None and parts[8] is None:
        raise ValueError(f"Missing parrot crest: {character_id}")
    eyes = tuple(tuple(_patch(head, area) for area in spec["eyes"]) for head in heads)
    mouth = _patch(heads[7], spec["mouth"])
    faces = []
    for beak_open in (False, True):
        expressions = []
        for index, patches in enumerate(eyes):
            image = heads[0].copy()
            painter = QPainter(image)
            # SourceAtop keeps the original head's alpha EXACTLY. Facial edits
            # cannot paint beyond the head or change its antialiased silhouette.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            if beak_open:
                draw_patch(painter, QRectF(image.rect()), mouth)
            if index:
                for patch in patches:
                    draw_patch(painter, QRectF(image.rect()), patch)
            painter.end()
            expressions.append(image)
        faces.append(tuple(expressions))
    return CharacterArt(
        character_id, parts, tuple(faces),
        QRectF(*spec["crest"]) if spec["crest"] is not None else None,
        views=_head_views(spec["directional"]),
        groom_columns=tuple(spec["directional"]["groom_columns"]),
    )


def _head_views(spec: dict) -> dict[str, tuple[HeadView, ...]]:
    banks = {}
    for name, columns in (("yaw", 5), ("pitch", 4)):
        definition = spec[name]
        if len(definition["rects"]) != columns * 3 or len(definition["beaks"]) != columns:
            raise ValueError("Incomplete directional head atlas")
        sheet = _sheet(definition)
        heads = tuple(_cell(sheet, rect, 192) for rect in definition["rects"])
        if any(head is None for head in heads):
            raise ValueError("Missing directional head")
        views = []
        for col in range(columns):
            base = heads[col]
            states = [base]
            for row in (1, 2):
                # Register facial edits on a constant head, keeping its outline
                # and beak tip stationary throughout a blink in every direction.
                patch = _patch(heads[row * columns + col], [.03, .12, .94, .64])
                image = base.copy()
                painter = QPainter(image)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
                draw_patch(painter, QRectF(image.rect()), patch)
                painter.end()
                states.append(image)
            point = QPointF(*definition["beaks"][col])
            if not QRectF(0, 0, 1, 1).contains(point):
                raise ValueError("Beak anchor is outside its head")
            views.append(HeadView(tuple(states), point))
        banks[name] = tuple(views)
    left, right = spec["groom_columns"]
    if left == right or any(index not in range(4) for index in (left, right)):
        raise ValueError("Invalid preening head selection")
    return banks


def preload_artwork() -> None:
    """Resolve and validate all art before the overlay starts its animation timer."""
    for character_id in CHARACTER_IDS:
        character_art(character_id)


def eye_frame(eye_open: float, expression: str = "normal") -> int:
    """Discrete registered art, sampled from elapsed-time-driven pose values."""
    if eye_open < 0.92:
        return max(0, min(4, round((1 - eye_open) * 4)))
    return {"happy": 5, "wide": 6, "angry": 8}.get(expression, 0)


def draw_patch(painter: QPainter, head_rect: QRectF, patch: Patch) -> None:
    area = patch.area
    target = QRectF(
        head_rect.x() + head_rect.width() * area.x(),
        head_rect.y() + head_rect.height() * area.y(),
        head_rect.width() * area.width(), head_rect.height() * area.height(),
    )
    painter.drawImage(target, patch.image)
