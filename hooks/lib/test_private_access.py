"""Assert on source input, because the module under test stays untouched."""
from __future__ import annotations

from lib.test_rules import private_access
from lib.test_units import extract

VIOLATES_METHOD = '''
def test_discount_uses_the_internal_calculation() -> None:
    order = Order(100)
    assert calculator._calculate_discount_internal(order) == 90
'''

CLEAN_METHOD = '''
def test_discount_applies_through_the_public_api() -> None:
    order = Order(100)
    assert calculator.get_price(order) == 90
'''

VIOLATES_STATE = '''
def test_checkout_records_the_applied_discounts() -> None:
    order = Order(100)
    checkout.process(order)
    assert checkout._applied_discounts == ["SUMMER10"]
'''

CLEAN_STATE = '''
def test_checkout_returns_the_applied_discounts() -> None:
    order = Order(100)
    receipt = checkout.process(order)
    assert receipt.applied_discounts == ["SUMMER10"]
'''

MONKEYPATCH_PRIVATE = '''
def test_worker_skips_the_real_send(monkeypatch) -> None:
    monkeypatch.setattr(gateway, "_smtp_client", FakeSmtp())
    gateway.send("a@example.com")
'''

SELF_HELPER_IS_CLEAN = '''
class TestGroup:
    def test_uses_its_own_helper(self) -> None:
        self._seed()
        assert self._count == 1
'''

NAMEDTUPLE_REPLACE_IS_CLEAN = '''
def test_layer_swaps_one_field() -> None:
    layer = WARM._replace(probe=lambda: None)
    assert layer.probe() is None
'''

DOTTED_CONFIG_STRING_IS_CLEAN = '''
def test_launch_disables_the_default_app() -> None:
    assert sdk.launches[0].config_overrides == ("apps._default.enabled=false",)
'''


def _hits(source: str) -> list[tuple[str, int]]:
    unit = extract("tests/test_sample.py", source)[0]
    return [(hit.rule, hit.line) for hit in private_access.check(unit, source)]


def test_a_call_on_a_private_method_is_flagged() -> None:
    assert _hits(VIOLATES_METHOD) == [("exposing_private_methods_for_testing", 4)]


def test_a_call_on_the_public_method_is_clean() -> None:
    assert _hits(CLEAN_METHOD) == []


def test_reading_a_private_attribute_is_flagged() -> None:
    assert _hits(VIOLATES_STATE) == [("exposing_private_state_for_testing", 5)]


def test_reading_the_public_result_is_clean() -> None:
    assert _hits(CLEAN_STATE) == []


def test_monkeypatching_a_private_name_counts_as_a_method_hit() -> None:
    assert _hits(MONKEYPATCH_PRIVATE) == [("exposing_private_methods_for_testing", 3)]


def test_a_tests_own_self_helper_is_not_flagged() -> None:
    assert _hits(SELF_HELPER_IS_CLEAN) == []


def test_namedtuple_replace_is_not_flagged() -> None:
    assert _hits(NAMEDTUPLE_REPLACE_IS_CLEAN) == []


def test_a_dotted_config_key_inside_a_string_is_not_flagged() -> None:
    assert _hits(DOTTED_CONFIG_STRING_IS_CLEAN) == []


def test_rust_units_are_skipped() -> None:
    unit = extract("src/lib.rs", "#[test]\nfn later() { obj._name(); }\n")[0]

    assert list(private_access.check(unit, "")) == []
