from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PostbackAction,
    RichMenuArea,
    RichMenuBounds,
    RichMenuRequest,
    RichMenuSize,
)

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)

WIDTH = 2500
TEACHER_HEIGHT = 1686  # 2 rows × 3 cols
STUDENT_HEIGHT = 843   # 1 row × 3 cols

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "rich_menu"
EMOJI_DIR = Path(__file__).resolve().parents[2] / "assets" / "emoji"


def _emoji_to_twemoji_hex(emoji_char: str) -> str:
    """Convert emoji char to lowercase twemoji hex filename (multi-codepoint joined by '-')."""
    parts = [f"{ord(c):x}" for c in emoji_char if c != "\ufe0f"]  # drop variation selectors
    return "-".join(parts)


@dataclass
class MenuButton:
    label: str
    emoji: str
    postback_data: str
    # gradient top → bottom (both RGB)
    color_top: tuple[int, int, int]
    color_bottom: tuple[int, int, int]


TEACHER_BUTTONS: list[MenuButton] = [
    MenuButton("派新作業", "📝", "action=assign_prompt", (76, 209, 149), (38, 160, 108)),
    MenuButton("今日作業", "📅", "action=today", (102, 167, 255), (56, 116, 208)),
    MenuButton("歷史紀錄", "📒", "action=history&days=7", (255, 184, 108), (214, 136, 54)),
    MenuButton("未完成", "⏳", "action=pending", (255, 121, 121), (210, 73, 73)),
    MenuButton("完成統計", "📊", "action=stats", (189, 147, 249), (141, 100, 214)),
    MenuButton("近7天排程", "📆", "action=schedule&days=7", (94, 210, 210), (48, 160, 160)),
]

STUDENT_BUTTONS: list[MenuButton] = [
    MenuButton("今日作業", "📚", "action=view_today", (102, 167, 255), (56, 116, 208)),
    MenuButton("我完成了", "✅", "action=complete_today", (76, 209, 149), (38, 160, 108)),
    MenuButton("不會標記", "🚩", "action=stuck_prompt", (255, 121, 121), (210, 73, 73)),
]


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates_bold = [
        "C:\\Windows\\Fonts\\msjhbd.ttc",
        "C:\\Windows\\Fonts\\msyhbd.ttc",
    ]
    candidates_regular = [
        "C:\\Windows\\Fonts\\msjh.ttc",
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\mingliu.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in (candidates_bold if bold else []) + candidates_regular:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


_EMOJI_FONT_PATHS = [
    "/usr/share/fonts/truetype/noto-color-emoji/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "C:\\Windows\\Fonts\\seguiemj.ttf",
]


def _render_emoji_to_image(emoji_char: str, target_height: int):
    """Render emoji as an RGBA PIL image at target_height.

    Priority:
      1. Bundled Twemoji PNG in assets/emoji/<hex>.png (always works, no font deps)
      2. NotoColorEmoji via Pillow (if installed)
      3. None (caller falls back to text draw)
    """
    from PIL import Image, ImageDraw, ImageFont

    # 1. Try bundled Twemoji PNG first — most reliable
    hex_code = _emoji_to_twemoji_hex(emoji_char)
    png_path = EMOJI_DIR / f"{hex_code}.png"
    if png_path.exists():
        try:
            img = Image.open(png_path).convert("RGBA")
            if img.height != target_height:
                ratio = target_height / img.height
                new_size = (max(1, int(img.width * ratio)), target_height)
                img = img.resize(new_size, Image.LANCZOS)
            return img
        except Exception as exc:
            log.warning("twemoji_load_failed", emoji=emoji_char, error=str(exc))

    # 2. Fallback: try NotoColorEmoji / Apple Color Emoji via font
    native_size = 109
    font = None
    for p in _EMOJI_FONT_PATHS:
        try:
            font = ImageFont.truetype(p, native_size)
            break
        except OSError:
            continue
    if font is None:
        return None
    canvas = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((30, 30), emoji_char, font=font, embedded_color=True)
    except Exception:
        return None
    bbox = canvas.getbbox()
    if bbox is None:
        return None
    canvas = canvas.crop(bbox)
    if canvas.height == 0:
        return None
    ratio = target_height / canvas.height
    new_size = (max(1, int(canvas.width * ratio)), target_height)
    return canvas.resize(new_size, Image.LANCZOS)


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]):
    from PIL import Image

    w, h = size
    grad = Image.new("RGB", (1, h), color=0)
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        grad.putpixel((0, y), (r, g, b))
    return grad.resize((w, h))


def _asset_path(role: str, index: int) -> Path:
    return ASSETS_DIR / f"{role}_{index + 1}.png"


def _full_override(role: str) -> Path:
    return ASSETS_DIR / f"{role}_full.png"


def build_menu_image(rows: int, cols: int, buttons: list[MenuButton], role: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFilter

    # 1. Full override
    full_path = _full_override(role)
    if full_path.exists():
        img = Image.open(full_path).convert("RGB")
        expected_h = TEACHER_HEIGHT if rows == 2 else STUDENT_HEIGHT
        if img.size != (WIDTH, expected_h):
            img = img.resize((WIDTH, expected_h))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    height = TEACHER_HEIGHT if rows == 2 else STUDENT_HEIGHT
    canvas = Image.new("RGB", (WIDTH, height), color=(240, 242, 247))

    cell_w = WIDTH // cols
    cell_h = height // rows
    gap = 24
    radius = 56
    font_label = _load_font(88, bold=True)
    font_emoji = _load_font(200)  # fallback only, used if no emoji font available

    for idx, btn in enumerate(buttons):
        r, c = divmod(idx, cols)
        x0 = c * cell_w + gap
        y0 = r * cell_h + gap
        x1 = (c + 1) * cell_w - gap
        y1 = (r + 1) * cell_h - gap
        cw, ch = x1 - x0, y1 - y0

        # Drop shadow
        shadow = Image.new("RGBA", (cw + 60, ch + 60), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle((30, 30, 30 + cw, 30 + ch), radius=radius, fill=(0, 0, 0, 80))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
        canvas.paste(shadow, (x0 - 30, y0 - 16), shadow)

        # Gradient tile
        grad = _vertical_gradient((cw, ch), btn.color_top, btn.color_bottom)
        mask = Image.new("L", (cw, ch), 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.rounded_rectangle((0, 0, cw, ch), radius=radius, fill=255)
        canvas.paste(grad, (x0, y0), mask)

        # Subtle highlight sheen at top
        sheen = Image.new("RGBA", (cw, ch // 2), (255, 255, 255, 0))
        sdraw = ImageDraw.Draw(sheen)
        sdraw.rounded_rectangle(
            (0, 0, cw, ch // 2), radius=radius, fill=(255, 255, 255, 40)
        )
        canvas.paste(sheen, (x0, y0), sheen)

        # Icon: asset override > rendered emoji > text fallback
        asset = _asset_path(role, idx)
        icon_cy = y0 + int(ch * 0.42)
        target_h = int(min(cw, ch) * 0.48)
        icon_img = None
        if asset.exists():
            icon_img = Image.open(asset).convert("RGBA")
            icon_img.thumbnail((target_h, target_h), Image.LANCZOS)
        else:
            icon_img = _render_emoji_to_image(btn.emoji, target_height=target_h)

        if icon_img is not None:
            ix = x0 + (cw - icon_img.width) // 2
            iy = icon_cy - icon_img.height // 2
            canvas.paste(icon_img, (ix, iy), icon_img)
        else:
            # Last-resort text fallback
            draw = ImageDraw.Draw(canvas)
            try:
                bbox = draw.textbbox((0, 0), btn.emoji, font=font_emoji)
                ew = bbox[2] - bbox[0]
                eh = bbox[3] - bbox[1]
                ex = x0 + (cw - ew) // 2 - bbox[0]
                ey = icon_cy - eh // 2 - bbox[1]
                draw.text((ex, ey), btn.emoji, font=font_emoji, fill=(255, 255, 255))
            except Exception:
                log.warning("emoji_render_failed_all_fallbacks", emoji=btn.emoji)

        # Label
        draw = ImageDraw.Draw(canvas)
        lb = draw.textbbox((0, 0), btn.label, font=font_label)
        lw = lb[2] - lb[0]
        lh = lb[3] - lb[1]
        lx = x0 + (cw - lw) // 2 - lb[0]
        ly = y0 + int(ch * 0.78) - lh // 2 - lb[1]
        draw.text((lx + 3, ly + 3), btn.label, font=font_label, fill=(0, 0, 0, 90))
        draw.text((lx, ly), btn.label, font=font_label, fill=(255, 255, 255))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _build_areas(rows: int, cols: int, height: int, buttons: list[MenuButton]) -> list[RichMenuArea]:
    cell_w = WIDTH // cols
    cell_h = height // rows
    areas = []
    for idx, btn in enumerate(buttons):
        r, c = divmod(idx, cols)
        areas.append(
            RichMenuArea(
                bounds=RichMenuBounds(x=c * cell_w, y=r * cell_h, width=cell_w, height=cell_h),
                action=PostbackAction(data=btn.postback_data, displayText=btn.label),
            )
        )
    return areas


def _messaging_clients() -> tuple[ApiClient, MessagingApi, MessagingApiBlob]:
    cfg = Configuration(access_token=get_settings().LINE_CHANNEL_ACCESS_TOKEN)
    client = ApiClient(cfg)
    return client, MessagingApi(client), MessagingApiBlob(client)


def _delete_existing_menus() -> None:
    client, api, _ = _messaging_clients()
    try:
        menus = api.get_rich_menu_list().richmenus or []
        for m in menus:
            try:
                api.delete_rich_menu(rich_menu_id=m.rich_menu_id)
                log.info("rich_menu_deleted", rich_menu_id=m.rich_menu_id)
            except Exception as exc:
                log.warning("rich_menu_delete_failed", error=str(exc))
    finally:
        client.close()


def _create_and_upload(rows: int, cols: int, name: str, chat_bar: str, buttons: list[MenuButton], role: str) -> str:
    height = TEACHER_HEIGHT if rows == 2 else STUDENT_HEIGHT
    client, api, blob = _messaging_clients()
    try:
        req = RichMenuRequest(
            size=RichMenuSize(width=WIDTH, height=height),
            selected=False,
            name=name,
            chatBarText=chat_bar,
            areas=_build_areas(rows, cols, height, buttons),
        )
        created = api.create_rich_menu(rich_menu_request=req)
        rich_menu_id = created.rich_menu_id
        image = build_menu_image(rows, cols, buttons, role)
        blob.set_rich_menu_image(
            rich_menu_id=rich_menu_id,
            body=image,
            _headers={"Content-Type": "image/png"},
        )
        log.info("rich_menu_created", name=name, rich_menu_id=rich_menu_id)
        return rich_menu_id
    finally:
        client.close()


def _link_menu(user_id: str, rich_menu_id: str) -> None:
    if not user_id:
        return
    client, api, _ = _messaging_clients()
    try:
        api.link_rich_menu_id_to_user(user_id=user_id, rich_menu_id=rich_menu_id)
        log.info("rich_menu_linked", user_id=user_id, rich_menu_id=rich_menu_id)
    finally:
        client.close()


_STUDENT_MENU_ID_CACHE: str | None = None


def _load_student_menu_id() -> str | None:
    """Find existing student menu on LINE (if any) and cache ID."""
    global _STUDENT_MENU_ID_CACHE
    if _STUDENT_MENU_ID_CACHE:
        return _STUDENT_MENU_ID_CACHE
    client, api, _ = _messaging_clients()
    try:
        menus = api.get_rich_menu_list().richmenus or []
        for m in menus:
            if getattr(m, "name", "") == "student-menu":
                _STUDENT_MENU_ID_CACHE = m.rich_menu_id
                return _STUDENT_MENU_ID_CACHE
        return None
    finally:
        client.close()


def link_student_menu_for_user(user_id: str) -> None:
    """Called when a new student auto-registers — link student menu to that user."""
    menu_id = _load_student_menu_id()
    if menu_id is None:
        log.warning("student_menu_not_found_cannot_link", user_id=user_id)
        return
    _link_menu(user_id, menu_id)


def setup_rich_menus() -> dict:
    global _STUDENT_MENU_ID_CACHE
    settings = get_settings()
    _delete_existing_menus()
    _STUDENT_MENU_ID_CACHE = None

    teacher_id = _create_and_upload(2, 3, "teacher-menu", "老師選單", TEACHER_BUTTONS, "teacher")
    student_id = _create_and_upload(1, 3, "student-menu", "學生選單", STUDENT_BUTTONS, "student")
    _STUDENT_MENU_ID_CACHE = student_id

    if settings.TEACHER_USER_ID:
        _link_menu(settings.TEACHER_USER_ID, teacher_id)

    # Link student menu to every active student in DB
    linked_students: list[str] = []
    try:
        from app import db as _db
        from app.services import student as student_svc

        session = _db.SessionLocal()
        try:
            # seed legacy if configured
            student_svc.ensure_seed(session, settings.STUDENT_USER_ID)
            for s in student_svc.list_active(session):
                _link_menu(s.line_user_id, student_id)
                linked_students.append(s.line_user_id[:8])
        finally:
            session.close()
    except Exception as exc:
        log.warning("setup_rich_menu_link_students_failed", error=str(exc))

    return {
        "ok": True,
        "teacher_rich_menu_id": teacher_id,
        "student_rich_menu_id": student_id,
        "teacher_linked": bool(settings.TEACHER_USER_ID),
        "students_linked": linked_students,
    }
