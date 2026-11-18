from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DisplayPage:
    page_id: str
    title: str
    description: str
    path: str | None = None
    page_type: str = "local"
    url: str | None = None


# Only explicitly registered destinations may be loaded by the public display shell.
# Local pages must stay under /static/pages/. External pages must use a fixed HTTPS URL.
DISPLAY_PAGES: tuple[DisplayPage, ...] = (
    DisplayPage(
        page_id="promo",
        title="企业宣传片",
        description="康晋电气企业宣传片展示",
        path="/static/pages/promo.html",
    ),
    DisplayPage(
        page_id="factory",
        title="智能制造",
        description="工厂与制造流程展示模板",
        path="/static/pages/factory.html",
    ),
    DisplayPage(
        page_id="product",
        title="产品中心",
        description="产品资料展示模板",
        path="/static/pages/product.html",
    ),
    DisplayPage(
        page_id="company_website",
        title="康晋电气官方网站",
        description="外部官网只读展示；不接管官网内部交互",
        page_type="external",
        url="https://www.zhcomking.com/",
    ),
)

DEFAULT_DISPLAY_PAGE_ID = "promo"
DISPLAY_PAGE_IDS = tuple(page.page_id for page in DISPLAY_PAGES)
_DISPLAY_PAGE_BY_ID = {page.page_id: page for page in DISPLAY_PAGES}


def list_display_pages() -> list[dict[str, str | None]]:
    return [asdict(page) for page in DISPLAY_PAGES]


def get_display_page(page_id: str) -> DisplayPage | None:
    return _DISPLAY_PAGE_BY_ID.get(page_id)
