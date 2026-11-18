from __future__ import annotations

import ipaddress
import re
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class DisplayPage:
    page_id: str
    title: str
    description: str
    path: str | None = None
    page_type: str = "local"
    url: str | None = None


# Bootstrap pages are inserted once into SQLite. Runtime page management uses ControlStore.
DISPLAY_PAGES: tuple[DisplayPage, ...] = (
    DisplayPage("promo", "企业宣传片", "康晋电气企业宣传片展示", path="/static/pages/promo.html"),
    DisplayPage("factory", "智能制造", "工厂与制造流程展示模板", path="/static/pages/factory.html"),
    DisplayPage("product", "产品中心", "产品资料展示模板", path="/static/pages/product.html"),
    DisplayPage(
        "company_website", "康晋电气官方网站", "外部官网只读展示；不接管官网内部交互",
        page_type="external", url="https://www.zhcomking.com/",
    ),
)

DEFAULT_DISPLAY_PAGE_ID = "promo"
DISPLAY_PAGE_IDS = tuple(page.page_id for page in DISPLAY_PAGES)
_DISPLAY_PAGE_BY_ID = {page.page_id: page for page in DISPLAY_PAGES}
SAFE_PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_RESERVED_HOST_SUFFIXES = (
    ".localhost", ".local", ".internal", ".test", ".invalid", ".example", ".home", ".lan",
)


def list_display_pages() -> list[dict[str, str | None]]:
    return [asdict(page) for page in DISPLAY_PAGES]


def get_display_page(page_id: str) -> DisplayPage | None:
    return _DISPLAY_PAGE_BY_ID.get(page_id)


def validate_display_page_id(page_id: object) -> str:
    if not isinstance(page_id, str) or not SAFE_PAGE_ID.fullmatch(page_id):
        raise ValueError("页面 ID 必须为 1～64 位字母、数字、下划线、点或连字符，且以字母或数字开头")
    return page_id


def normalize_external_url(value: object) -> str:
    """Validate a public HTTPS destination without making a server-side request."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("网页地址必须是 1～2048 个字符的 HTTPS URL")
    raw = value.strip()
    if not raw or any(ord(char) < 32 or char == "\\" for char in raw):
        raise ValueError("网页地址包含无效字符")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        host = parsed.hostname
    except ValueError as error:
        raise ValueError("网页地址格式无效") from error
    if parsed.scheme.lower() != "https" or not host:
        raise ValueError("外部网页只允许 HTTPS 地址")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("网页地址不能包含用户名或密码")
    if port not in (None, 443):
        raise ValueError("外部网页只允许默认 HTTPS 端口 443")
    try:
        normalized_host = host.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as error:
        raise ValueError("网页域名格式无效") from error
    if not normalized_host or "." not in normalized_host:
        raise ValueError("网页必须使用公开域名，不能使用本机或局域网地址")
    if normalized_host == "localhost" or normalized_host.endswith(_RESERVED_HOST_SUFFIXES):
        raise ValueError("网页不能指向本机或局域网保留域名")
    try:
        ipaddress.ip_address(normalized_host)
    except ValueError:
        pass
    else:
        raise ValueError("网页不能使用 IP 地址，请填写公开域名")
    labels = normalized_host.split(".")
    if any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in labels
    ):
        raise ValueError("网页域名格式无效")
    return urlunsplit(("https", normalized_host, parsed.path or "/", parsed.query, parsed.fragment))
