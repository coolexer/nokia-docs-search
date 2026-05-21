from nokia_docs.products import (
    PRODUCT_ALIASES,
    PRODUCT_DISPLAY_NAMES,
    PRODUCT_PATTERNS,
    RN_PRODUCTS,
    resolve_product,
)


def test_product_registry_contains_runtime_aliases_and_names():
    assert resolve_product("sros") == "sros-26-3"
    assert resolve_product("rn srlinux") == "rn-srl"
    assert resolve_product("chassis") == "install-guides"
    assert PRODUCT_DISPLAY_NAMES["sros-26-3"].startswith("Nokia SR OS")
    assert PRODUCT_ALIASES["7750"] == "sros-26-3"


def test_product_registry_contains_indexing_patterns_and_rn_products():
    assert ("SR Linux", "srlinux-26-3") in PRODUCT_PATTERNS
    assert ("26-3", "sros-26-3") in PRODUCT_PATTERNS
    assert [p.key for p in RN_PRODUCTS] == ["sros", "srl", "sas", "mag-c", "eda"]
    assert [p.slug for p in RN_PRODUCTS] == ["rn-sros", "rn-srl", "rn-sas", "rn-mag-c", "rn-eda"]
