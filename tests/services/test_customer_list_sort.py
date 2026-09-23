from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.customer_service import CustomerListFilters, _sort_customers


def _item(
    *,
    name: str,
    status: str = "active",
    neighborhood: str | None = None,
    zip_code: str | None = None,
    lead_source: str | None = None,
    last_visit: date | None = None,
    next_service_due: date | None = None,
    lifetime_spend: str = "0",
):
    customer = SimpleNamespace(
        name=name,
        status=status,
        neighborhood=neighborhood,
        zip_code=zip_code,
        lead_source=lead_source,
        next_service_due=next_service_due,
    )
    return SimpleNamespace(
        customer=customer,
        last_visit=last_visit,
        lifetime_spend=Decimal(lifetime_spend),
        year_spend=Decimal("0"),
        visit_count=0,
    )


def test_sort_by_name_asc_and_desc():
    items = [_item(name="Zoe"), _item(name="Ada"), _item(name="Mia")]
    asc = _sort_customers(items, sort="name", sort_dir="asc")
    desc = _sort_customers(items, sort="name", sort_dir="desc")
    assert [i.customer.name for i in asc] == ["Ada", "Mia", "Zoe"]
    assert [i.customer.name for i in desc] == ["Zoe", "Mia", "Ada"]


def test_sort_by_revenue_desc():
    items = [
        _item(name="Low", lifetime_spend="100"),
        _item(name="High", lifetime_spend="900"),
        _item(name="Mid", lifetime_spend="400"),
    ]
    ordered = _sort_customers(items, sort="lifetime_spend", sort_dir="desc")
    assert [i.customer.name for i in ordered] == ["High", "Mid", "Low"]


def test_sort_last_service_puts_nulls_last():
    items = [
        _item(name="Never"),
        _item(name="Recent", last_visit=date(2026, 9, 1)),
        _item(name="Older", last_visit=date(2025, 1, 1)),
    ]
    newest_first = _sort_customers(items, sort="last_service", sort_dir="desc")
    assert [i.customer.name for i in newest_first] == ["Recent", "Older", "Never"]


def test_filters_query_omits_defaults():
    filters = CustomerListFilters(q="park", status="active", sort="lifetime_spend", sort_dir="desc")
    params = filters.query_params()
    assert params == {
        "q": "park",
        "status": "active",
        "sort": "lifetime_spend",
        "sort_dir": "desc",
    }


def test_sort_toggle_and_as_query():
    filters = CustomerListFilters(status="lead", sort="name", sort_dir="asc")
    assert filters.sort_toggle_dir("name") == "desc"
    assert filters.sort_toggle_dir("lifetime_spend") == "asc"
    qs = filters.as_query(sort="name", sort_dir="desc")
    assert "status=lead" in qs
    assert "sort_dir=desc" in qs


def test_advanced_filter_count():
    filters = CustomerListFilters(
        q="x",
        status="active",
        zip_code="84106",
        last_service="never",
        lead_source="google",
    )
    assert filters.advanced_filter_count() == 3
    assert filters.has_advanced() is True
    assert filters.active_filter_count() == 5
