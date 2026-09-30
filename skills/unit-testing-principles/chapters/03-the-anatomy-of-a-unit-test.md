# Chapter 3. The anatomy of a unit test

Book pages 41 to 63.

## Core argument

A readable test has a fixed shape, a plain name, and its own setup. Uniform shape lowers the cost of reading every test in the suite. A test that reads like a story about the domain is cheaper to keep than one that reads like a list of method calls.

## The arrange, act, assert pattern

Every test has three parts. People call this AAA or the 3A pattern.

1. Arrange. Bring the SUT and its dependencies into the needed state.
2. Act. Call the SUT with the prepared dependencies. Capture the output, if there is one.
3. Assert. Verify the outcome. The outcome is a return value, the final state of the SUT or its collaborators, or the calls the SUT made to collaborators.

```python
def test_total_of_two_prices():
    first = Money(12)
    second = Money(30)
    sut = PriceCalculator()

    total = sut.add(first, second)

    assert total == Money(42)
```

The main gain is uniformity. Once a reader knows the shape, any test in the suite reads fast.

### Given, when, then

Given-when-then maps one to one onto arrange, act, assert. The only difference is audience. Given-when-then reads better for non-programmers, so it suits tests shared with business people.

### Which section to write first

Writing the arrange section first is natural and works in most cases.

In TDD, starting with the assert section is also an option. The developer does not yet know the behavior in full. Writing down the expected outcome first mirrors how people solve problems. They state the goal, then work out how to reach it.

When production code comes first, the developer already knows the expected behavior. Starting with arrange works better in that case.

## Avoid several act sections

A test with arrange, act, assert, act, assert verifies more than one unit of behavior. By chapter 2 it is an integration test, not a unit test.

Split it. One act per test keeps unit tests simple, fast, and easy to read.

### Bad example

```python
def test_cart_flow():
    cart = Cart()

    cart.add(Item("pen", Money(2)))
    assert cart.total() == Money(2)

    cart.apply_coupon(Coupon.percent_off(50))
    assert cart.total() == Money(1)

    cart.remove("pen")
    assert cart.total() == Money(0)
```

ADW flags this shape as `multiple_act_sections_in_unit_test`.

### Good example

```python
def test_cart_total_is_the_sum_of_item_prices():
    cart = Cart()

    cart.add(Item("pen", Money(2)))

    assert cart.total() == Money(2)


def test_half_off_coupon_halves_the_total():
    cart = cart_with(Item("pen", Money(2)))

    cart.apply_coupon(Coupon.percent_off(50))

    assert cart.total() == Money(1)
```

### The exception

Integration tests sometimes group several acts and asserts on purpose. Developers do this to save time. Integration tests are slow, and one act often leaves the system in the state the next act needs.

The author limits this exception to integration tests that already run slow. Unit tests and fast integration tests get split.

## Avoid if statements in tests

A test is a flat sequence of steps. It has no branches.

An `if` in a test shows that the test checks too many things. Split it. Unlike the rule on several act sections, this rule has no exception for integration tests. Branching adds reading cost and gives nothing back.

### Bad example

```python
def test_shipping_fee(order_kind):
    order = make_order(order_kind)

    fee = shipping.fee_for(order)

    if order_kind == "express":
        assert fee == Money(15)
    else:
        assert fee == Money(5)
```

ADW flags this shape as `if_statements_in_tests`.

### Good example

```python
def test_express_order_pays_the_express_fee():
    fee = shipping.fee_for(make_order(kind="express"))

    assert fee == shipping.EXPRESS_FEE


def test_standard_order_pays_the_standard_fee():
    fee = shipping.fee_for(make_order(kind="standard"))

    assert fee == shipping.STANDARD_FEE
```

The good version also avoids a pinned price. The rule under test is that express orders pay the express fee. The amount of the fee is a business setting. Asserting `Money(15)` would pin a tuned number and break on a price change. See `hardcoded_literal_in_source` in chapter 11.

This form works only because the test checks a selection between two distinct values. Chapter 9 adds a limit. An assertion that compares a production value with itself is a tautology. If the price itself is a contract, for example a price printed on an invoice that a customer sees, pin it as a literal instead.

## Section size

### Arrange is usually the largest

An arrange section as large as act plus assert is fine. When it grows much larger, move the setup into private factory functions in the test module or into a separate factory. Two patterns help here.

1. Object Mother. A class with named factory methods for common test objects.
2. Test Data Builder. A builder with defaults that each test overrides where it matters.

### Act is one line

A multi-line act section often reveals a problem in the SUT API.

```python
def test_purchase_reduces_stock():
    warehouse = warehouse_with(Item.LAMP, 8)
    buyer = Buyer()

    ok = buyer.purchase(warehouse, Item.LAMP, 3)
    warehouse.remove_stock(ok, Item.LAMP, 3)

    assert warehouse.stock_of(Item.LAMP) == 5
```

The test still verifies one unit of behavior. The fault sits in the production API. A purchase has two outcomes that belong together. The buyer gets the item, and the stock drops. The API makes the client call a second method to finish the job.

If a client forgets the second call, the buyer has the lamp and the stock still says 8. That is an invariant violation. Protecting code from invariant violations is what encapsulation means.

Once bad data reaches a database, a restart does not fix it. Someone repairs records by hand and maybe contacts customers. Picture receipts for goods that nobody reserved.

The fix goes in production code. `purchase` removes the stock itself. Remove any path a caller takes to break an invariant.

The one-line rule holds for business logic. Utility and infrastructure code breaks it more often. The author does not forbid it there. He asks for a check for a leak of encapsulation each time.

### How many assertions

One assertion per test comes from the idea that a unit is the smallest piece of code. Chapter 2 rejected that idea. A unit is a unit of behavior. One behavior has several outcomes. Checking all of them in one test is fine.

A long assert section still hints at a missing abstraction. Instead of asserting each field of a result, give the result type proper equality and compare it to one expected value.

```python
assert receipt == Receipt(item=Item.LAMP, quantity=3, total=Money(36))
```

### Teardown

Some people add a fourth phase that cleans up files, connections, and the like. The author leaves it out of AAA, because a shared teardown method usually serves every test in a class.

Most unit tests need no teardown. They do not touch out of process dependencies, so they leave no side effects. Cleanup belongs to integration tests, covered in part 3.

## Name the SUT

A test has one entry point to the behavior, one class that triggers it. Name that object `sut` in every test. A reader then tells the SUT from its dependencies at a glance.

## Mark the three sections

Readers need to see where each section starts. Two methods exist.

1. Comments such as `# Arrange`, `# Act`, `# Assert`.
2. Blank lines between the sections.

Blank lines work for most unit tests. Large integration tests often need blank lines inside the arrange section to group setup stages. There, the blank lines no longer mark sections.

The author's rule has two parts.

1. Drop the section comments when the test follows AAA and needs no blank lines inside arrange or assert.
2. Keep the comments otherwise.

ADW discourages comments that narrate code. Section markers in a long integration test are an allowed exception, because they carry structure the blank lines lose.

## The test framework

The author works with xUnit in C#. Every object oriented language has similar frameworks, so the ideas carry over.

He likes that xUnit calls a test a Fact. A test is an atomic fact about the domain. A passing test proves the fact holds. A failing test means either the fact changed and the test needs a rewrite, or the system broke. A test describes behavior at a high level. It does not list what the code does line by line.

## Reusing test fixtures

A test fixture is an object the test runs against. It is a dependency passed to the SUT, a row in a database, or a file on disk. It sits in a known, fixed state before each run, so the test gives the same result each time.

Reuse of fixture setup shortens tests. One way of reuse is good, and one is bad.

### Bad. Setup in the constructor or a setUp method

```python
import unittest


class BuyerTests(unittest.TestCase):
    def setUp(self):
        self.warehouse = Warehouse()
        self.warehouse.add_stock(Item.LAMP, 8)
        self.sut = Buyer()

    def test_purchase_succeeds_when_stock_covers_quantity(self):
        ok = self.sut.purchase(self.warehouse, Item.LAMP, 3)

        self.assertTrue(ok)
        self.assertEqual(self.warehouse.stock_of(Item.LAMP), 5)

    def test_purchase_fails_when_stock_is_short(self):
        ok = self.sut.purchase(self.warehouse, Item.LAMP, 12)

        self.assertFalse(ok)
        self.assertEqual(self.warehouse.stock_of(Item.LAMP), 8)
```

ADW flags this shape as `test_fixture_reuse_via_constructor`. It has two drawbacks.

#### Drawback 1. High coupling between tests

Change the stock in `setUp` from 8 to 20. The first test still passes. The second test now fails, because 12 fits in 20. One edit to shared setup broke a test that the developer did not touch.

The guideline is that changing one test does not affect other tests. This differs from the chapter 2 rule on isolated execution. That rule is about running tests independently. This one is about editing tests independently. Good tests need both.

The shared fields `self.warehouse` and `self.sut` are the shared state that creates the coupling.

#### Drawback 2. Worse readability

The reader no longer sees the whole test in one place. Understanding a test now means reading `setUp` too.

Even when setup only creates objects, keep it in the test. Otherwise a reader wonders whether `setUp` also configures something. A self-contained test leaves no such doubt.

### Good. Private factory functions

```python
def test_purchase_succeeds_when_stock_covers_quantity():
    warehouse = warehouse_with(Item.LAMP, 8)
    sut = Buyer()

    ok = sut.purchase(warehouse, Item.LAMP, 3)

    assert ok is True
    assert warehouse.stock_of(Item.LAMP) == 5


def test_purchase_fails_when_stock_is_short():
    warehouse = warehouse_with(Item.LAMP, 8)
    sut = Buyer()

    ok = sut.purchase(warehouse, Item.LAMP, 12)

    assert ok is False
    assert warehouse.stock_of(Item.LAMP) == 8


def warehouse_with(item, quantity):
    warehouse = Warehouse()
    warehouse.add_stock(item, quantity)
    return warehouse
```

The factory keeps tests short and keeps the full context visible. The test states "a warehouse with 8 lamps" in its own body. The factory takes parameters, so each test says what it needs. It does not couple tests to each other.

In this small case, a factory adds little. It shows the technique for larger setups.

### The exception

A fixture that all or nearly all tests use goes into shared setup. A database connection in integration tests is the usual case. The author puts it in a base class for integration tests, not in each test class. The test classes then have no constructor of their own.

```python
class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.database = Database.connect(test_connection_string())

    def tearDown(self):
        self.database.close()
```

### A note on pytest fixtures

A function-scoped pytest fixture builds a fresh object per test, so it avoids shared mutable state. It still hides the arrangement from the test body. Prefer a fixture that returns a factory, or a plain factory function, when the test needs to state its own inputs. A module-scoped or session-scoped fixture that returns mutable state repeats the coupling problem above.

## Naming tests

Good names show what the test verifies and how the system behaves.

A common convention is `[MethodUnderTest]_[Scenario]_[ExpectedResult]`. The author calls it one of the least helpful. It pulls attention toward implementation details instead of behavior.

Plain English names work better. They are more expressive and do not force a rigid structure.

| Rigid name | Plain name |
|---|---|
| `test_add_two_prices_returns_sum` | `test_total_of_two_prices` |

The rigid name repeats "add" and "sum". A non-programmer cannot tell what "returns" means or where the sum goes.

Some say only programmers read test names, and programmers decode cryptic names for a living. The author answers that cryptic names tax everyone. The tax is small per read but adds up across the suite and over time. It hurts most when someone returns to an old feature or reads a colleague's test.

### Guidelines

1. Do not follow a rigid naming policy. A complex behavior does not fit a narrow template.
2. Name the test as if describing the scenario to a non-programmer who knows the domain. A domain expert or business analyst is the target reader.
3. Separate words with underscores. Long names read better that way.

Test class names in the book skip underscores because they are short. A test class named after a production class is an entry point. It does not limit the tests to that class. The unit is still a unit of behavior.

### Worked renaming

Start from a rigid name.

```python
def test_is_valid_booking_past_date_returns_false():
    sut = BookingService()
    booking = Booking(date=today() - timedelta(days=1))

    assert sut.is_valid(booking) is False
```

1. Plain English. `test_booking_with_invalid_date_should_be_considered_invalid`. A non-programmer understands it. The method name `is_valid` left the test name.
2. Specific. An invalid date here means a past date. `test_booking_with_past_date_should_be_considered_invalid`.
3. Shorter. The word "considered" adds nothing. `test_booking_with_past_date_should_be_invalid`.
4. A fact, not a wish. A test states a fact. Replace the wish wording with "is". `test_booking_with_past_date_is_invalid`.
5. Grammar. Articles help. `test_booking_with_a_past_date_is_invalid`.

The final name states one fact about the behavior under test.

### Keep the method name out of the test name

A test verifies behavior, not code. The SUT method is only an entry point. Renaming `is_valid` to `is_correct` changes no behavior. With the method name inside the test name, the test needs a rename too. That coupling to implementation details raises upkeep. Chapter 5 returns to this.

The exception is utility code. Its behavior means nothing to business people, so method names in test names are fine there.

## Parameterized tests

One test rarely describes a whole behavior. A behavior has several facts, and each fact deserves a test. For complex behavior, the test count grows fast. Parameterized tests group similar facts into one test.

Say the earliest allowed booking date is two days from today. Four facts follow. Yesterday is invalid. Today is invalid. Tomorrow is invalid. Two days from now is valid. Four near-identical tests differ only in the date.

### Grouped version

```python
import pytest


@pytest.mark.parametrize(
    ("days_from_now", "expected"),
    [(-1, False), (0, False), (1, False), (2, True)],
)
def test_detects_an_invalid_booking_date(days_from_now, expected):
    sut = BookingService()
    booking = Booking(date=today() + timedelta(days=days_from_now))

    assert sut.is_valid(booking) is expected
```

Each parameter row is a separate fact and a separate test case.

### The cost

The code shrinks, but the facts get harder to read from the name. More parameters make it worse.

A compromise splits the positive case into its own test with a descriptive name. The negative cases stay grouped without the `expected` flag.

```python
@pytest.mark.parametrize("days_from_now", [-1, 0, 1])
def test_detects_an_invalid_booking_date(days_from_now):
    booking = Booking(date=today() + timedelta(days=days_from_now))

    assert BookingService().is_valid(booking) is False


def test_the_soonest_booking_date_is_two_days_from_now():
    booking = Booking(date=today() + timedelta(days=2))

    assert BookingService().is_valid(booking) is True
```

The author's rule of thumb has three steps.

1. Keep positive and negative cases in one parameterized test only when the inputs make each case obvious.
2. Otherwise, pull the positive case into its own test.
3. If the behavior is complex, skip parameterization. Give each case its own test.

### Loops are not parameterization

A loop over cases with an assert inside hides which case failed and stops at the first failure. The runner reports one test, not four facts.

```python
def test_booking_dates():
    for days_from_now, expected in [(-1, False), (0, False), (2, True)]:
        booking = Booking(date=today() + timedelta(days=days_from_now))
        assert BookingService().is_valid(booking) is expected
```

ADW flags this shape as `assert_in_loop`. Use the framework's parameterization, or `subTest` in unittest, so each case reports on its own.

### Data that the framework cannot inline

In C#, attribute arguments must be compile-time constants, so the book passes day offsets instead of dates and uses a data method for complex values. In Python, pytest evaluates the parameter list once, when it imports the module. A call to `date.today()` in that list captures the import moment, not the moment the test runs. Pass offsets, as above, and compute the date inside the test. For complex objects, use `pytest.param` with an `id`, or build them in the test from simple inputs.

Rust has no built-in parameterization. Two options follow.

1. A crate such as `rstest` with `#[case]` rows.
2. A declarative macro that generates one `#[test]` function per case.

Both keep one reported test per fact. A `for` loop with `assert!` inside one `#[test]` is the same `assert_in_loop` problem.

```rust
#[rstest]
#[case(-1)]
#[case(0)]
#[case(1)]
fn detects_an_invalid_booking_date(#[case] days_from_now: i64) {
    let booking = Booking::new(today() + Duration::days(days_from_now));

    assert!(!BookingService::default().is_valid(&booking));
}
```

## Assertion libraries

An assertion library makes assertions read like sentences. In C# the author uses Fluent Assertions, where a check reads "result should be 30".

People absorb information as stories with the shape subject, action, object. "Bob opened the door." A fluent assertion follows that shape. The author links the success of object oriented programming partly to the same readability benefit.

Fluent libraries also provide helpers for numbers, strings, collections, and dates. The cost is one more development-only dependency.

In Python, a plain `assert` with pytest already reads close to a sentence and gives detailed failure output. Libraries such as `assertpy` or `hamcrest` add fluent forms. In Rust, `assert_eq!` and crates such as `pretty_assertions` fill the same role.

## Trade-offs the author names

1. Several act sections speed up slow integration tests. They make unit tests harder to read. Split them in unit tests.
2. Constructor setup shortens tests. It couples tests and hides context. Use factories, except for fixtures nearly every test needs.
3. Parameterized tests shrink code. They blur the facts. Split out the positive case, or skip parameterization for complex behavior.
4. Fluent assertions read better. They add a dependency.

## ADW rules that apply

1. `multiple_act_sections_in_unit_test`. One act per unit test.
2. `if_statements_in_tests`. No branches in any test.
3. `test_fixture_reuse_via_constructor`. No shared mutable setup through a constructor or `setUp`.
4. `assert_in_loop`. Use parameterization, not a loop with an assert.
5. `hardcoded_literal_in_source`. Assert rules, not tuned prices or other business settings.

## What the agent does with this chapter

1. Write every test as arrange, act, assert, separated by blank lines.
2. Keep the act to one line. If it takes two, report the leaked invariant in production code.
3. Put all of a test's setup inside the test, through factory functions with parameters.
4. Name the test as a plain fact about the domain. Leave the method name out.
5. Use parametrization for similar facts. Never loop over cases with an assert inside.
