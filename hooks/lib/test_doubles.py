"""Assert from source text, because a dict lookup proves nothing."""
from __future__ import annotations

from lib.test_rules import doubles
from lib.test_rules.doubles import Unit
from lib.test_units import extract

MOCK_CLASS_VIOLATION = '''from unittest.mock import Mock


class PaymentGateway:
    def charge(self, amount: int) -> None:
        pass


def test_charge_uses_a_concrete_mock() -> None:
    gateway = Mock(spec=PaymentGateway)
    gateway.charge(10)
'''

MOCK_CLASS_CLEAN = '''from typing import Protocol
from unittest.mock import Mock


class PaymentGateway(Protocol):
    def charge(self, amount: int) -> None: ...


def test_charge_uses_an_interface_mock() -> None:
    gateway = Mock(spec=PaymentGateway)
    gateway.charge(10)
'''

MOCK_CLASS_VIOLATION_RS = '''struct PaymentGateway {}

#[test]
fn test_charge_uses_a_concrete_mock() {
    let gateway = MockPaymentGateway::new();
    gateway.charge(10);
}
'''

MOCK_CLASS_CLEAN_RS = '''trait PaymentGateway {}

#[test]
fn test_charge_uses_an_interface_mock() {
    let gateway = MockPaymentGateway::new();
    gateway.charge(10);
}
'''

VERIFICATION_VIOLATION = '''from unittest.mock import Mock


def test_send_confirms_call_happened() -> None:
    mailer = Mock()
    mailer.send("a@b.com")
    mailer.send.assert_called_once()
'''

VERIFICATION_CLEAN = '''from unittest.mock import Mock


def test_send_confirms_the_address() -> None:
    mailer = Mock()
    mailer.send("a@b.com")
    mailer.send.assert_called_once_with("a@b.com")
'''

VERIFICATION_VIOLATION_RS = '''#[test]
fn test_charge_runs_once() {
    let mut gateway = MockPaymentGateway::new();
    gateway.expect_charge().times(1).returning(|_| Ok(()));
    process(&gateway);
}
'''

VERIFICATION_CLEAN_RS = '''#[test]
fn test_charge_runs_once_with_amount() {
    let mut gateway = MockPaymentGateway::new();
    gateway.expect_charge().with(eq(10)).times(1).returning(|_| Ok(()));
    process(&gateway);
}
'''

def _unit(path: str, text: str, name: str) -> Unit:
    return next(unit for unit in extract(path, text) if unit.name == name)


def _hits(case: tuple[str, str, str], rule: str) -> list:
    path, text, name = case
    unit = _unit(path, text, name)
    return [hit for hit in doubles.RULE_SET.check(unit, text) if hit.rule == rule]


def test_mock_spec_on_a_concrete_class_is_flagged() -> None:
    case = ("test_gateway.py", MOCK_CLASS_VIOLATION, "test_charge_uses_a_concrete_mock")

    assert [hit.line for hit in _hits(case, "mocking_concrete_classes")] == [10]


def test_mock_spec_on_a_protocol_is_clean() -> None:
    case = ("test_gateway.py", MOCK_CLASS_CLEAN, "test_charge_uses_an_interface_mock")

    assert _hits(case, "mocking_concrete_classes") == []


def test_rust_mock_new_on_a_struct_is_flagged() -> None:
    case = ("gateway.rs", MOCK_CLASS_VIOLATION_RS, "test_charge_uses_a_concrete_mock")

    assert [hit.line for hit in _hits(case, "mocking_concrete_classes")] == [5]


def test_rust_mock_new_on_a_trait_is_clean() -> None:
    case = ("gateway.rs", MOCK_CLASS_CLEAN_RS, "test_charge_uses_an_interface_mock")

    assert _hits(case, "mocking_concrete_classes") == []


def test_bare_assert_called_once_is_flagged() -> None:
    case = ("test_mailer.py", VERIFICATION_VIOLATION, "test_send_confirms_call_happened")

    assert [hit.line for hit in _hits(case, "incomplete_mock_call_verification")] == [7]


def test_assert_called_once_with_is_clean() -> None:
    case = ("test_mailer.py", VERIFICATION_CLEAN, "test_send_confirms_the_address")

    assert _hits(case, "incomplete_mock_call_verification") == []


def test_rust_expect_without_with_is_flagged() -> None:
    case = ("mailer.rs", VERIFICATION_VIOLATION_RS, "test_charge_runs_once")
    hits = _hits(case, "incomplete_mock_call_verification")

    assert len(hits) == 1 and hits[0].line == 3


def test_rust_expect_with_a_matcher_is_clean() -> None:
    case = ("mailer.rs", VERIFICATION_CLEAN_RS, "test_charge_runs_once_with_amount")

    assert _hits(case, "incomplete_mock_call_verification") == []
