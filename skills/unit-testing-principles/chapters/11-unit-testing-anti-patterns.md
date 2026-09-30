# Chapter 11. Unit testing anti-patterns

Book pages 259 to 274.

## Core argument

An anti-pattern is a common answer to a recurring problem. It looks right at first and causes trouble later.

This chapter collects anti-patterns that did not fit earlier chapters. Most follow from the principles of part 2. Spelling them out links each one to its root.

1. Unit testing private methods.
2. Exposing private state for tests.
3. Leaking domain knowledge into tests.
4. Code pollution.
5. Mocking concrete classes.
6. Working with time.

This file closes with the two ADW rules that go beyond the book, `hardcoded_name_presence` and `hardcoded_literal_in_source`, and derives them from the same principles.

## Unit testing private methods

The short answer is do not. The topic still has nuance.

### Private methods and fragility

Making a private method public only to test it breaks the chapter 5 principle of testing observable behavior only. The test couples to implementation details and loses resistance to refactoring, the most important of the four pillars. Test private methods indirectly, through the observable behavior that uses them.

```python
class Invoice:
    def total(self):
        return self._subtotal() + self.tax()

    def tax(self):
        return round(self._subtotal() * Decimal("0.19"), 2)
```

Here `tax` is public only because a test wants to call it. Callers use `total`. ADW flags this as `exposing_private_methods_for_testing`.

In Python the leak also happens without a rename. A test that calls `sut._subtotal()` reaches past the public API in the same way.

```python
def test_subtotal_sums_line_amounts():
    sut = Invoice(lines=[Line(Money(10)), Line(Money(5))])

    assert sut._subtotal() == Money(15)
```

Test `total` with inputs that exercise the subtotal instead.

### Private methods and weak coverage

Sometimes a private method is too complex to cover through the observable behavior. Assuming the observable behavior already has reasonable coverage, two causes are possible.

1. Dead code. If uncovered code serves no caller, it is probably a leftover from an old refactoring. Delete it.
2. A missing abstraction. A private method too complex to test through the public API signals a separate class waiting to come out.

```python
class Order:
    def __init__(self, customer, items):
        self._customer = customer
        self._items = items

    def summary(self):
        return (
            f"Customer: {self._customer.name}, "
            f"items: {len(self._items)}, "
            f"total: {self._price()}"
        )

    def _price(self):
        base = ...
        discount = ...
        tax = ...
        return base - discount + tax
```

`summary` is simple. It uses `_price`, which holds important business logic that deserves thorough tests. That logic is a missing abstraction. Do not expose `_price`. Extract it.

```python
class Order:
    def summary(self):
        price = PriceCalculator().calculate(self._customer, self._items)
        return f"Customer: {self._customer.name}, items: {len(self._items)}, total: {price}"


class PriceCalculator:
    def calculate(self, customer, items):
        base = ...
        discount = ...
        tax = ...
        return base - discount + tax
```

`PriceCalculator` now gets tests of its own, independent of `Order`. It has no hidden inputs or outputs, so the tests take the output-based style from chapter 6.

### When testing a private method is acceptable

Chapter 5 gave this table.

| | Observable behavior | Implementation detail |
|---|---|---|
| Public | good | bad |
| Private | not possible | good |

Public observable behavior and private implementation details make a well-designed API. Leaking details breaks encapsulation. The table marks private observable behavior as not possible, because a client cannot use a private method.

Testing a private method is not bad in itself. It is bad because private methods usually stand in for implementation details. In rare cases a method is private and still part of observable behavior, and the table has an exception.

A loan desk bulk-loads new applications into the database once a day. Staff then review them one by one and approve some.

```python
class LoanApplication:
    def __init__(self, approved, approved_at):
        if approved and approved_at is None:
            raise ValueError("an approved application needs an approval time")
        self._approved = approved
        self._approved_at = approved_at

    def approve(self, now):
        if self._approved:
            return
        self._approved = True
        self._approved_at = now
```

In the book's C# version, the constructor is private. The ORM restores the objects from the database and works with a private constructor. The application never creates applications itself, so it needs no public constructor.

The approval logic clearly deserves unit tests. Making the constructor public seems to break the rule on private methods. It does not. The constructor fulfills the contract with the ORM. Being private does not make that contract less real. Without it, the ORM cannot restore applications.

Making the constructor public here does not lead to brittle tests. It arguably moves the API closer to well-designed. Keep every precondition in the constructor that encapsulation needs, such as the approval time for approved applications.

To keep the public surface minimal instead, create the object in tests the way the ORM does, through reflection. It looks like a hack. It follows what the ORM already does. In Python the equivalent is a classmethod the ORM also uses, or `object.__new__` plus attribute setup in a test factory.

## Exposing private state

Another common anti-pattern exposes state that would otherwise stay private, only for tests. The rule matches the one for private methods. Do not expose state that would otherwise stay private. Test observable behavior only.

```python
class Customer:
    def __init__(self):
        self._status = CustomerStatus.REGULAR

    def promote(self):
        self._status = CustomerStatus.PREFERRED

    def discount(self):
        return Decimal("0.05") if self._status == CustomerStatus.PREFERRED else Decimal("0")
```

A customer starts regular. A promotion makes the customer preferred, which gives a 5 percent discount.

Testing `promote` raises a question. Its side effect changes `_status`, which is private. Making the field public is tempting. The status change seems to be the whole point of `promote`.

That is the anti-pattern. The author puts it this way. Tests interact with the SUT exactly as production code does, with no special privileges. Production code does not read `_status`, so it is not observable behavior. Exposing it couples tests to an implementation detail.

Look at how production code uses the class. It does not care about status, or the field would be public already. It cares about the discount after promotion. Check that.

1. A new customer has no discount.
2. A promoted customer has a 5 percent discount.

```python
def test_a_new_customer_has_no_discount():
    assert Customer().discount() == Decimal("0")


def test_a_promoted_customer_gets_the_preferred_discount():
    sut = Customer()

    sut.promote()

    assert sut.discount() == Decimal("0.05")
```

If production code starts to use the status later, tests may couple to it too, because it becomes observable behavior then.

The author's note. Widening the public API for testability is bad practice.

ADW flags this as `exposing_private_state_for_testing`. In Python the check covers both a new public property added for tests and a test that reads `sut._status` directly.

## Leaking domain knowledge to tests

This anti-pattern shows up most in tests of complex algorithms. A deliberately simple algorithm shows it.

```python
def add(a, b):
    return a + b
```

The wrong way to test it.

```python
def test_adding_two_numbers():
    a = 1
    b = 3
    expected = a + b

    assert add(a, b) == expected
```

A parameterized version adds cases for free.

```python
@pytest.mark.parametrize(("a", "b"), [(1, 3), (11, 33), (100, 500)])
def test_adding_two_numbers(a, b):
    expected = a + b

    assert add(a, b) == expected
```

Both look fine. Both repeat the production algorithm inside the test. With one line, it seems harmless. The author has seen tests of complex algorithms that did nothing but reimplement the algorithm in the arrange section, a copy of the production code.

Such tests couple to implementation details. They score almost zero on resistance to refactoring and are worthless. They cannot tell a real failure from a false positive. When a change to the algorithm breaks them, the team copies the new version into the test without looking for the cause. The test was a copy all along.

The fix. Do not imply any particular implementation in a test. Instead of repeating the algorithm, hard-code its results.

```python
@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(1, 3, 4), (11, 33, 44), (100, 500, 600)],
)
def test_adding_two_numbers(a, b, expected):
    assert add(a, b) == expected
```

Hard-coding the expected result feels odd at first. It is good practice in unit testing. Compute the values with something other than the SUT, ideally with a domain expert. That only matters for complex algorithms, since anyone can add two numbers. When refactoring legacy code, let the legacy code produce the expected values and use them in the tests.

The catalog lists this as `leaking_domain_knowledge_to_tests`.

### How this fits with the ADW literal rules

Hard-coding expected results and banning hard-coded literals seem to clash. They answer different questions.

1. An expected output for a given input is a fact about behavior. The test states "for this input, the answer is this". Hard-code it. That is what this section asks for.
2. A literal that is not an output of the behavior under test is not a fact about behavior. A class name, a config key, a tuned constant, or a line of source text is one. Pinning it catches no regression and breaks on harmless changes.

The two ADW rules below target the second group only.

## Code pollution

Code pollution means adding production code that only tests need.

It often takes the form of a switch.

```python
class Logger:
    def __init__(self, is_test_environment):
        self._is_test_environment = is_test_environment

    def log(self, text):
        if self._is_test_environment:
            return
        ...


class Controller:
    def some_method(self, logger):
        logger.log("some_method called")
```

The flag tells the logger whether it runs in production. In production it writes the message. In tests it does nothing.

```python
def test_some_method():
    logger = Logger(is_test_environment=True)
    sut = Controller()

    sut.some_method(logger)

    ...
```

The problem is that test code and production code mix, which raises maintenance cost of production code. Keep test code out of the production code base.

Introduce a logger protocol with two implementations. The real one lives in production code, next to the controller that uses it. The fake one lives in test code. The controller accepts the protocol and never learns which implementation it received.

```python
class LoggerProtocol(Protocol):
    def log(self, text: str) -> None: ...


class Logger:
    def log(self, text):
        ...


class Controller:
    def some_method(self, logger: LoggerProtocol):
        logger.log("some_method called")
```

```python
class FakeLogger:
    def log(self, text):
        pass
```

The production logger stays simple, because it no longer handles environments. The protocol itself is arguably a form of pollution. It lives in production code and only tests need it. It is still better. An interface adds far less risk than a flag. Production cannot hit a test-only path by accident. An interface has no code, so it holds no bugs. A flag adds surface area for bugs, and an interface does not.

Other common forms in Python are `if os.environ.get("TESTING")` branches, `if "pytest" in sys.modules` checks, and parameters named `_for_testing`. All of them are code pollution.

The catalog lists this as `code_pollution`.

## Mocking concrete classes

Mocks so far used interfaces. Mocking a concrete class is another option. It keeps part of the original functionality, which is sometimes handy. It has a big drawback. It points to a violation of the Single Responsibility principle.

```python
class ShipmentStatistics:
    def calculate(self, customer_id):
        records = self.fetch_shipments(customer_id)
        total_weight = sum(r.weight for r in records)
        total_cost = sum(r.cost for r in records)
        return total_weight, total_cost

    def fetch_shipments(self, customer_id):
        ...
```

The class computes the weight and cost of all shipments to a customer. It gets the shipment list from an external service in `fetch_shipments`. A controller uses it.

```python
class CustomerController:
    def __init__(self, statistics: ShipmentStatistics):
        self._statistics = statistics

    def statistics(self, customer_id):
        weight, cost = self._statistics.calculate(customer_id)
        return f"Total weight shipped: {weight}. Total cost: {cost}"
```

Testing the controller is awkward. The real `ShipmentStatistics` calls an unmanaged out of process dependency, so the test needs a stub for it. Replacing `ShipmentStatistics` entirely is also wrong, since it holds important calculation logic.

One way out mocks the concrete class and overrides only `fetch_shipments`.

```python
from unittest.mock import patch


def test_customer_with_no_shipments():
    with patch.object(ShipmentStatistics, "fetch_shipments", return_value=[]):
        sut = CustomerController(ShipmentStatistics())

        result = sut.statistics(1)

    assert result == "Total weight shipped: 0. Total cost: 0"
```

The patch keeps the real `calculate` and replaces only one method. This is the anti-pattern. ADW flags it as `mocking_concrete_classes`.

The need to mock a concrete class to keep part of its behavior comes from a Single Responsibility violation. The class `ShipmentStatistics` mixes two unrelated jobs, talking to the unmanaged dependency and computing statistics. The method `calculate` holds the domain logic. The method `fetch_shipments` only gathers its inputs. Split the class.

```python
class ShipmentGateway(Protocol):
    def fetch_shipments(self, customer_id: int) -> list[ShipmentRecord]: ...


class ShipmentStatistics:
    def calculate(self, records):
        total_weight = sum(r.weight for r in records)
        total_cost = sum(r.cost for r in records)
        return total_weight, total_cost


class CustomerController:
    def __init__(self, statistics: ShipmentStatistics, gateway: ShipmentGateway):
        self._statistics = statistics
        self._gateway = gateway

    def statistics(self, customer_id):
        records = self._gateway.fetch_shipments(customer_id)
        weight, cost = self._statistics.calculate(records)
        return f"Total weight shipped: {weight}. Total cost: {cost}"
```

The gateway now owns the communication with the unmanaged dependency. A protocol backs it, so tests mock the protocol instead of a concrete class. The controller is the Humble Object from chapter 7.

## Working with time

Many features need the current date and time. Tests of time-dependent code risk false positives. The time during the act phase differs from the time during the assert phase. Three options exist to stabilize this dependency. One is an anti-pattern. Of the other two, one is better.

### Time as an ambient context

The first option is the ambient context from chapter 8, applied to time. Code calls a custom static clock instead of the built-in `datetime.now`.

```python
class Clock:
    _now = staticmethod(datetime.now)

    @classmethod
    def now(cls):
        return cls._now()

    @classmethod
    def init(cls, func):
        cls._now = staticmethod(func)


Clock.init(datetime.now)
Clock.init(lambda: datetime(2026, 1, 1))
```

The first `init` runs in production. The second runs in unit tests.

Like the logger case, this is an anti-pattern. The ambient context pollutes production code and makes testing harder. The static field is a dependency shared between tests, which turns those tests into integration tests. Monkeypatching `datetime.now` in a test has the same problem.

The catalog lists this as `time_as_ambient_context`. ADW no longer enforces a clock rule. The book's reasoning still applies.

### Time as an explicit dependency

The better way injects time explicitly, as a service or as a plain value.

```python
class ClockProtocol(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self):
        return datetime.now(tz=UTC)


class LoanController:
    def __init__(self, clock: ClockProtocol):
        self._clock = clock

    def approve(self, application_id):
        application = self._repository.get(application_id)
        application.approve(self._clock.now())
        self._repository.save(application)
```

Prefer the value over the service. Plain values are easier to work with in production code and easier to supply in tests.

Injecting time as a value everywhere is rarely possible, because dependency injection frameworks handle value objects poorly. The compromise hands the clock service to the entry point of each operation, reads the current time once there, and passes that value down. The controller above takes the clock service and hands a `datetime` value to `LoanApplication.approve`.

```python
def test_approving_a_pending_application_records_the_time():
    sut = LoanApplication(approved=False, approved_at=None)
    now = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)

    sut.approve(now)

    assert sut.approved_at == now
```

## ADW rules beyond the book

The book does not name the next two rules. The user added them to ADW. Both follow from the four pillars and from chapter 4's rule to aim at the end result.

### `hardcoded_name_presence`

The test asserts that a name exists. A class, a function, a module, a config key, a CLI flag, a skill, or a hook name. It checks presence, not behavior.

```python
def test_registry_has_the_export_command():
    assert "export" in commands.REGISTRY


def test_settings_define_the_retry_key():
    assert hasattr(settings, "RETRY_LIMIT")
```

Score it on the pillars.

1. Protection. Near zero. The test passes when `export` exists but does nothing useful. It catches only a deletion, which any real test of the export command catches too.
2. Resistance to refactoring. Near zero. A rename breaks it with no change in behavior.
3. The product is near zero.

Test what the name does instead.

```python
def test_export_command_writes_a_csv_file(tmp_path):
    target = tmp_path / "out.csv"

    run_cli(["export", "--to", str(target)])

    assert target.read_text().startswith("id,name\n")
```

If the name itself is a contract that outside users type, such as a public CLI flag, test it by invoking it, as above. The call fails if the name disappears, and it also proves the name does something.

### `hardcoded_literal_in_source`

The test pins a literal that has no rule behind it. Two shapes are common.

1. The test reads a source file, a config file, or a template and asserts that some text appears in it. Chapter 4 called the source-reading test the most brittle test the author had seen.
2. The test asserts a tuned constant, such as a timeout, a threshold, a model name, or a retry count, whose value no domain expert would state as a rule.

```python
def test_timeout_is_thirty_seconds():
    assert client.DEFAULT_TIMEOUT == 30


def test_prompt_mentions_json():
    source = Path("app/prompts.py").read_text()

    assert "Respond in JSON" in source
```

Score them on the pillars.

1. Protection. Near zero. A timeout of 30 says nothing about whether requests time out. The prompt text says nothing about whether the model returns JSON.
2. Resistance to refactoring. Zero. Tuning the number or rewording the prompt breaks the test with no bug.

Test the behavior the literal produces.

```python
def test_a_request_slower_than_the_timeout_fails():
    server = SlowServer(delay=client.DEFAULT_TIMEOUT + 1)

    with pytest.raises(RequestTimeout):
        client.fetch(server.url)


def test_the_parser_accepts_the_model_reply_format():
    reply = '{"answer": 42}'

    assert parse_reply(reply) == Answer(42)
```

Pin a literal only when it is observable behavior, as chapter 9 showed for contract text on a bus. An expected output for a given input is also fine, as the section on domain knowledge showed.

### `assert_in_loop`

Chapter 3 covered it. A loop with an assert inside hides which case failed and stops at the first failure. Use parameterization. The rule matters most for tests that loop over a registry and assert each entry, which often combine with `hardcoded_name_presence`.

### `hollow_test`

Chapters 1, 4, and 9 covered it. A test with no assertion, an assertion that always holds, or an assertion that compares production output with itself. The value formula gives it zero protection.

## Conclusion of the book

The chapter walked through common real-world cases and judged each with the four pillars. The author admits that applying every guideline at once is a lot, and that real situations are rarely clear-cut. He points readers to his blog and course for more examples. The four pillars remain the tool for judging any new case.

## Trade-offs the author names

1. Testing through the public API sometimes leaves a complex private method thinly covered. The answer is extracting a class, not exposing the method.
2. A private constructor that serves an ORM is observable behavior. Making it public, or using reflection in tests, is fine.
3. Hard-coded expected values need a source other than the SUT. For complex algorithms that source is a domain expert or legacy code.
4. An interface added for a fake is mild code pollution. It is still far safer than a test flag.
5. Injecting time as a value is cleaner. Injecting it as a service tends to be necessary at the entry point.

## ADW rules that apply

1. `exposing_private_methods_for_testing`. Test through the public operation. Extract a class when the private logic is complex.
2. `exposing_private_state_for_testing`. Check what production code reads, not internal fields.
3. `mocking_concrete_classes`. Split the class and mock the gateway protocol.
4. `hardcoded_name_presence`. Test what the name does, not that it exists.
5. `hardcoded_literal_in_source`. Test the behavior a literal produces. Never read source text in a test.
6. `hollow_test` and `assert_in_loop`, covered above.
7. The catalog entries `leaking_domain_knowledge_to_tests`, `code_pollution`, and `time_as_ambient_context` come from this chapter.

## Rust note

Rust unit tests in a `#[cfg(test)] mod tests` block inside the same file can call private functions and read private fields. The compiler allows it. The book's reasoning forbids it for the same reasons as in Python. Test the `pub` API. Extract a struct with its own `pub` API when a private function holds complex logic.

A `#[cfg(test)]` branch inside production code is code pollution in its most direct form. `#[cfg(test)] pub fn` accessors are the Rust form of exposing private state. Both belong on the list to avoid.

For time, pass a `DateTime<Utc>` or `SystemTime` value into domain functions. Keep a `Clock` trait only at the entry point that needs the current time.

```rust
#[test]
fn a_promoted_customer_gets_the_preferred_discount() {
    let mut customer = Customer::default();

    customer.promote();

    assert_eq!(customer.discount(), dec!(0.05));
}
```

## What the agent does with this chapter

1. Never make a private method or field public for a test. Never call an underscore method or read an underscore field from a test.
2. When private logic is too complex to test through the public API, report the missing abstraction and extract it.
3. Hard-code expected outputs computed outside the SUT. Never recompute them with the production algorithm.
4. Never add test-only flags or branches to production code.
5. Never patch methods on a concrete class. Split it and use a protocol at the boundary.
6. Pass time as a value into domain code.
7. Never assert that a name exists or that a source file contains a literal. Test the behavior behind it.

