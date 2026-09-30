# Chapter 2. What is a unit test?

Book pages 20 to 40.

## Core argument

Most definitions of a unit test share three attributes. A unit test is an automatic check that does three things.

1. It verifies a small piece of code, called a unit.
2. It runs fast.
3. It runs in isolation.

Speed is subjective but rarely disputed. If the suite runs fast enough for the team, the tests are fast enough.

Isolation is the disputed part. Two schools of unit testing read it in different ways. Every other difference between the schools grows from this one disagreement.

The author prefers the classical school. The main reason is fragility. Tests built on mocks break more often on harmless changes.

## The two schools

People also call the classical school the Detroit school or the classicist school. Kent Beck wrote its canonical book on test-driven development (TDD).

People also call the London school the mockist school. Steve Freeman and Nat Pryce wrote its canonical book on growing object oriented software guided by tests.

| | Isolates | A unit is | Replaces with test doubles |
|---|---|---|---|
| London | units from each other | one class | every dependency except immutable ones |
| Classical | tests from each other | one class or a group of classes | shared dependencies only |

## Key terms

A test double is a stand-in object. It looks and acts like the real one but is simpler, so the test is easier to set up. Gerard Meszaros coined the term. The name comes from stunt doubles in films.

A mock is one kind of test double. It lets the test inspect the calls between the system under test and a collaborator. Chapter 5 separates mocks from stubs.

The system under test (SUT) is the class or group the test exercises. The method under test is the method the test calls on it.

## The London reading of isolation

The London school isolates the class under test from its collaborators. Each dependency that is not immutable gets a test double.

The school claims three benefits.

1. When a test fails, only the class under test is suspect.
2. A test double cuts the object graph. The test does not build the dependencies of dependencies.
3. The suite follows a simple rule of one test class per production class.

### Example in both styles

A small shop domain. A customer buys an item from a warehouse. If the warehouse has enough stock, the purchase succeeds and the stock drops. If not, the purchase fails and the stock stays the same.

Classical style. The test uses a real warehouse.

```python
def test_purchase_succeeds_when_stock_covers_quantity():
    warehouse = Warehouse()
    warehouse.add_stock(Item.LAMP, 8)
    buyer = Buyer()

    ok = buyer.purchase(warehouse, Item.LAMP, 3)

    assert ok is True
    assert warehouse.stock_of(Item.LAMP) == 5


def test_purchase_fails_when_stock_is_short():
    warehouse = Warehouse()
    warehouse.add_stock(Item.LAMP, 8)
    buyer = Buyer()

    ok = buyer.purchase(warehouse, Item.LAMP, 12)

    assert ok is False
    assert warehouse.stock_of(Item.LAMP) == 8
```

London style. The test replaces the warehouse with a mock.

```python
from unittest.mock import create_autospec


def test_purchase_succeeds_when_stock_covers_quantity():
    warehouse = create_autospec(WarehouseProtocol, instance=True)
    warehouse.has_enough.return_value = True
    buyer = Buyer()

    ok = buyer.purchase(warehouse, Item.LAMP, 3)

    assert ok is True
    warehouse.remove_stock.assert_called_once_with(Item.LAMP, 3)
```

The classical test checks the state of the warehouse after the purchase. The London test checks that the buyer called `remove_stock` once with the right arguments.

The London test needed an interface for the warehouse. Mocking a concrete class instead is an anti-pattern that chapter 11 covers. ADW flags that as `mocking_concrete_classes`.

The London test still uses the real `Item.LAMP` and the real number 3. Nobody replaces an immutable value. That rule is the same in both schools.

## The classical reading of isolation

The classical school isolates tests from each other. Each test runs alone, in parallel, or in any order, and the result does not change.

Tests can exercise several classes at once, as long as all of them live in memory and hold no state that other tests also touch.

A shared dependency breaks isolation. One test writes a customer row to a database. Another test deletes it in its own setup. Run in parallel, the first test fails with no bug in the code.

### Kinds of dependency

1. A shared dependency is visible to more than one test. Tests change it and so change each other's outcome. A static mutable field counts. A database counts.
2. A private dependency belongs to one test.
3. An out of process dependency runs outside the application process. It is a proxy to data not yet in memory.

Most out of process dependencies are also shared, but not all. A database in a fresh container per test run is out of process and private to that run. A read only database is also private in effect, because tests cannot change it.

A dependency with one instance in production stays private in tests as long as each test builds its own copy. A configuration object passed in through a constructor is a good example.

A test cannot build its own file system or its own database. Those stay shared, or the test replaces them with a double.

### Volatile dependencies

Mark Seemann and Steven van Deursen use the term volatile dependency. A dependency is volatile if either holds.

1. It needs a runtime environment beyond what a developer machine has by default. Databases and remote APIs are examples.
2. It behaves in a nondeterministic way. A random number source or the current time are examples.

The two ideas overlap but differ. All tests touch the same file system, yet it behaves the same on every machine, so it is not volatile. A random source is volatile, yet each test gets its own, so tests do not share it.

### Speed as a second reason

Shared dependencies usually live out of process. Calls to them are slow. A slow test fails the speed attribute and becomes an integration test.

### Value objects and collaborators

A dependency is either shared or private. A private one is either mutable or immutable. An immutable private dependency is a value object.

Value objects have no identity. Two with the same content are interchangeable. The number 5 is a value. `Item.LAMP` is a value.

A collaborator is any dependency that tests share or that holds mutable state. A warehouse with changing stock is a collaborator. A database gateway is a collaborator.

In `buyer.purchase(warehouse, Item.LAMP, 3)` there are three dependencies. Only `warehouse` is a collaborator.

The classical school replaces shared dependencies. The London school replaces every collaborator, shared or private.

## Weighing the London benefits

### Benefit 1. Finer granularity

The London school treats a class as the unit. The author calls this misleading.

A test verifies a unit of behavior, not a unit of code. The behavior is something meaningful in the problem domain. A business person recognizes it as useful. It spans one method, one class, or several classes. The count of classes is irrelevant.

A good test tells a story about the problem the code solves. A non-programmer understands the story.

Cohesive story: "When I press the doorbell, the door opens."

Fragmented story: "When I press the doorbell, the relay closes, the latch coil gets current, the bolt retracts, the hinge turns."

The second story lists mechanics. It does not say whether the door opened. Tests that target single classes read like the second story.

### Benefit 2. Easy tests for large object graphs

Test doubles let a test skip building deep graphs. The author argues this solves the wrong problem.

A large graph of classes points to a design problem. When the arrange section of a test grows beyond reason, the code needs work. Mocks hide the problem instead of fixing it. Part 2 of the book shows the fix.

### Benefit 3. Precise failure location

With London tests, a bug usually fails only the tests of the broken class. With classical tests, a bug also fails the tests of every class that uses it. Failures ripple.

The author does not see this as a big problem. If the team runs tests after each change, the last edit is the likely cause. Fixing one bug fixes all the failing tests.

A wide ripple also carries information. The broken code matters to much of the system.

## Other differences

### Design with TDD

A TDD cycle has three steps. Write a failing test. Write the least code that makes it pass. Refactor under the protection of the passing test.

The London school leads to outside-in development. Start from the top, specify with mocks which collaborators the class talks to, then build each collaborator in turn.

The classical school has less guidance here. It usually goes inside-out. Start with the domain model and add layers until users can reach it.

### Over-specification

This is the biggest difference and the main objection to the London school. London tests couple more often to implementation details of the SUT. Chapter 5 explains why.

## Integration and end-to-end tests

The schools also disagree on what an integration test is.

A London follower calls any test with a real collaborator an integration test. Most classical tests are integration tests in that view.

The book uses the classical definitions. A unit test verifies a single unit of behavior, runs fast, and runs in isolation from other tests.

An integration test fails at least one of those criteria. Three typical cases follow.

1. The test touches a shared dependency such as a database, so tests cannot run in isolation.
2. The test calls an out of process dependency and is slow.
3. The test verifies two or more units of behavior at once. Teams sometimes merge two slow tests into one to save time. Those tests were integration tests already, so this case rarely decides anything.

An integration test also covers modules from separate teams working together.

An end-to-end test is an integration test with most or all out of process dependencies in scope. It checks the system from the user's point of view. People also call these UI tests, GUI tests, or functional tests.

Picture a system with a database, a file system, and a payment gateway. An integration test keeps the database and the file system real and doubles the gateway. The team controls the first two and cannot reset the third. An end-to-end test keeps all three real, or nearly all.

End-to-end tests cost the most to maintain. Run them late in the build, after unit and integration tests pass. Some teams run them only on the build server. Some dependencies have no test version at all, so even end-to-end tests sometimes use a double.

## Trade-offs the author names

1. London tests are fine-grained and easy to set up. They couple to implementation and break on refactoring.
2. Classical tests cost more setup when the graph is deep. That cost signals a design problem worth fixing.
3. Classical tests fail in a ripple. The ripple is a small cost and carries information.

## ADW rules that apply

1. `mocking_concrete_classes`. Double an interface or a protocol you own, not a concrete class.
2. `test_fixture_reuse_via_constructor`. Shared mutable setup breaks isolation between tests. Chapter 3 covers the fix.

## Rust note

Rust has no runtime mocking of concrete types. London style in Rust needs a trait for each collaborator plus a generic parameter or a trait object. That extra machinery exists only for tests. In Rust, the classical style costs less. Keep the real struct and double only the trait that stands for an out of process system.

```rust
#[test]
fn purchase_fails_when_stock_is_short() {
    let mut warehouse = Warehouse::default();
    warehouse.add_stock(Item::Lamp, 8);

    let ok = Buyer::default().purchase(&mut warehouse, Item::Lamp, 12);

    assert!(!ok);
    assert_eq!(warehouse.stock_of(Item::Lamp), 8);
}
```

## What the agent does with this chapter

1. Test a unit of behavior. Do not create one test class per production class by reflex.
2. Keep in-memory collaborators real. Replace only shared or out of process dependencies.
3. Never replace a value object with a double.
4. Give every test its own private copy of any mutable state.
5. When the arrange section grows large, report the design problem instead of adding mocks.
