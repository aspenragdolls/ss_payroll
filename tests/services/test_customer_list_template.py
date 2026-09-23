from pathlib import Path


TEMPLATE = Path("app/templates/customers/list.html").read_text(encoding="utf-8")
STYLE = Path("app/static/style.css").read_text(encoding="utf-8")


def test_customers_list_has_sort_controls_and_column_headers():
    assert 'name="sort"' in TEMPLATE
    assert 'name="sort_dir"' in TEMPLATE
    assert "sort_header('name', 'Name')" in TEMPLATE
    assert "sort_header('lifetime_spend', 'Revenue')" in TEMPLATE
    assert "customers-more" in TEMPLATE
    assert "More filters" in TEMPLATE


def test_customers_list_hides_advanced_filters_by_default_markup():
    assert "customers-quick-filters" in TEMPLATE
    assert "customers-filter-group" in TEMPLATE
    assert "sort-link" in STYLE
    assert "customers-toolbar" in STYLE
