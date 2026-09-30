# Chapter 5. Mocks and test fragility

Book pages 92 to 118.

## Core argument

Mocks and fragile tests go together for a reason. A mock checks a call. Most calls inside an application are implementation details. A test that pins such a call breaks on refactoring.

Mocks do have a proper use. They verify calls that cross the application boundary and whose side effects the outside world sees. Those calls form a contract. The contract has to stay stable, so pinning it in a test is correct.

The chapter builds this answer in four steps.

1. Mocks versus stubs.
2. Observable behavior versus implementation details.
3. Hexagonal architecture and the two kinds of communication.
4. What this means for the two schools.

## Mocks versus stubs

### Five kinds of double, two roles

Gerard Meszaros names five test doubles. Dummy, stub, spy, mock, and fake. They collapse into two types.

1. Mocks, which include spies. They emulate and examine outgoing interactions. An outgoing interaction is a call the SUT makes to change the state of a dependency. Sending an email is one.
2. Stubs, which include dummies and fakes. They emulate incoming interactions. An incoming interaction is a call the SUT makes to get input data. Reading from a database is one.

The other differences are minor.

1. A spy works like a mock, but a developer writes it by hand. People also call it a handwritten mock.
2. A dummy is a plain value, such as `None` or a made-up string. It fills a parameter slot and plays no part in the outcome.
3. A stub is a full dependency configured to return set values for different scenarios.
4. A fake is a stub in most respects. Developers usually write a fake to replace a dependency that does not exist yet.

The key difference is that a mock both emulates and examines. A stub only emulates.

### The tool versus the double

The word mock has a second meaning. Mocking libraries ship a class named Mock, and that class also goes by "mock". It is a tool. The tool creates both mocks and stubs.

```python
from unittest.mock import create_autospec


def test_sending_a_welcome_email():
    gateway = create_autospec(EmailGateway, instance=True)
    sut = SignupService(gateway)

    sut.sign_up("ada@example.com")

    gateway.send_welcome.assert_called_once_with("ada@example.com")
```

Here the object from the tool is a mock. It examines an outgoing call whose only purpose is a side effect.

```python
def test_building_a_usage_report():
    database = create_autospec(UsageDatabase, instance=True)
    database.count_active_users.return_value = 10
    sut = ReportService(database)

    report = sut.build_report()

    assert report.active_users == 10
```

Here the same tool creates a stub. It feeds input to the SUT.

### Never assert interactions with stubs

A call to a stub is not part of the end result. It is a means to produce the result. The stub supplies input, and the SUT turns input into output.

Chapter 4 showed that the only defense against false positives is to verify the end result. Sending a welcome email is a result a domain expert cares about. Calling `count_active_users` is an internal step in how the report gets its data. How the SUT gathers data does not matter, as long as the report is correct.

```python
def test_building_a_usage_report():
    database = create_autospec(UsageDatabase, instance=True)
    database.count_active_users.return_value = 10
    sut = ReportService(database)

    report = sut.build_report()

    assert report.active_users == 10
    database.count_active_users.assert_called_once()
```

The last line is over-specification. It checks something that is not part of the result. The catalog lists it as `overspecification_asserting_interactions_with_stubs`. It is easy to spot, because no test ever asserts a call on a stub.

Mocks are harder. Not every use of a mock leads to fragility, but many do. The rest of the chapter explains which ones.

### One double as mock and stub

A double sometimes plays both roles.

```python
def test_purchase_fails_when_stock_is_short():
    warehouse = create_autospec(WarehouseProtocol, instance=True)
    warehouse.has_enough.return_value = False
    sut = Buyer()

    ok = sut.purchase(warehouse, Item.LAMP, 5)

    assert ok is False
    warehouse.remove_stock.assert_not_called()
```

The test stubs `has_enough` and examines `remove_stock`. These are two different methods, so the rule about stubs holds. People call such a double a mock, because being a mock carries more weight than being a stub.

The London flavor of this test is still fragile, for reasons later in the chapter.

### Commands, queries, mocks, and stubs

Bertrand Meyer's command query separation principle (CQS) says every method is either a command or a query, never both.

1. A command has side effects and returns nothing. Changing object state or writing a file are side effects.
2. A query has no side effects and returns a value.

Asking a question does not change the answer. Code that follows CQS reads well, because the signature tells what the method does.

Some methods break CQS for good reason. `list.pop()` removes an element and returns it. Follow CQS whenever it fits.

A double that replaces a command is a mock. A double that replaces a query is a stub. `send_welcome` is a command, so its double is a mock. `count_active_users` is a query, so its double is a stub.

## Observable behavior versus implementation details

Fragility means low resistance to refactoring. Chapter 4 showed that tests fail on refactoring when they couple to implementation details. The question is what counts as an implementation detail.

### Two separate dimensions

Every piece of production code sits on two axes.

1. Public API or private API.
2. Observable behavior or implementation detail.

Each axis has two values with no overlap. Access modifiers decide the first axis. In Python, a leading underscore marks private by convention. In Rust, the absence of `pub` does.

The second axis needs more care. Code is observable behavior if it does one of two things.

1. It exposes an operation that helps a client reach one of its goals. An operation calculates something, causes a side effect, or both.
2. It exposes state that helps a client reach one of its goals. State is the current condition of the system.

Code that does neither is an implementation detail.

Observable depends on the client and its goals. A client is code in the same code base, an external application, or a user interface. To count as observable, code has an immediate link to at least one client goal.

### Well-designed API

In a well-designed API, the public API matches the observable behavior exactly. Every implementation detail sits behind the private API.

When the public API extends past the observable behavior, the code leaks implementation details.

### Leak example with an operation

A customer record has a rule. A display name has no surrounding spaces and at most 40 characters.

```python
class Customer:
    def __init__(self):
        self.display_name = ""

    def normalize_name(self, raw):
        cleaned = (raw or "").strip()
        return cleaned[:40]


class CustomerController:
    def rename(self, customer_id, new_name):
        customer = self.repository.get(customer_id)
        customer.display_name = customer.normalize_name(new_name)
        self.repository.save(customer)
```

The controller wants to rename a customer. The assignment to `display_name` serves that goal. `normalize_name` is also an operation, but it has no direct link to the goal. The controller calls it only to satisfy the rule inside `Customer`. `normalize_name` is an implementation detail that leaks into the public API.

The fix hides the normalization inside the class.

```python
class Customer:
    def __init__(self):
        self._display_name = ""

    @property
    def display_name(self):
        return self._display_name

    @display_name.setter
    def display_name(self, raw):
        self._display_name = _normalize(raw)


def _normalize(raw):
    return (raw or "").strip()[:40]


class CustomerController:
    def rename(self, customer_id, new_name):
        customer = self.repository.get(customer_id)
        customer.display_name = new_name
        self.repository.save(customer)
```

The book adds a note. Strictly, the getter is also unused by the controller. In real projects, some other use case reads the name, so the getter stays.

A rule of thumb follows. If a client needs more than one operation to reach a single goal, the class likely leaks implementation details. Ideally, one operation reaches one goal. Before the fix, the controller made two calls. After it, one.

The rule holds for most business logic. Exceptions exist. Check each violation for a leak.

A test that calls `normalize_name` directly pins the leak. ADW flags making a helper public for tests as `exposing_private_methods_for_testing`. Chapter 11 covers it.

### Well-designed API and encapsulation

Encapsulation protects code against inconsistencies, also called invariant violations. An invariant is a condition that holds at all times. The 40-character name rule is one.

Leaking implementation details often leads to invariant violations. The old `Customer` both leaked `normalize_name` and let the client skip it and assign a raw name.

Encapsulation matters because of complexity. The more complex a code base gets, the slower the work and the more bugs appear. Without encapsulation, a developer has to remember which uses the code permits. That adds mental load on every change. The author's rule is to remove the chance of doing the wrong thing, rather than trusting anyone to always do the right thing. Good encapsulation removes wrong options from the API. It serves the same goal as unit testing, sustainable growth.

Martin Fowler's tell-don't-ask principle is close to this. It bundles data with the functions that act on it. Encapsulation is the goal. Two means reach it.

1. Hiding implementation details keeps internals out of reach, so clients cannot corrupt them.
2. Bundling data with operations keeps those operations consistent with the invariants.

### Leak example with state

The report renderer from chapter 4 exposed its list of part renderers as public state. The client wants rendered HTML. It needs only `render`. The list is an implementation detail that leaks.

That is why the chapter 4 test that inspected the list was brittle. Retargeting the test at `render` fixed it.

A pattern appears. Make every implementation detail private, and tests have no choice but to verify observable behavior. Resistance to refactoring improves on its own.

The author puts it as a tip. A well-designed API improves unit tests automatically.

A second guideline follows. Expose the minimum number of operations and the minimum state. Only code that directly helps a client reach its goals goes public.

The reverse leak does not exist. Hiding observable behavior makes it unreachable for the client, so by definition it stops being observable behavior.

| | Observable behavior | Implementation detail |
|---|---|---|
| Public | good | bad |
| Private | not possible | good |

## Mocks and fragility

### Hexagonal architecture

A typical application has two layers.

1. The domain layer sits in the middle. It holds the business logic, the functionality the application exists for. It gives the organization its edge.
2. The application services layer sits around it. It coordinates the domain layer with the outside world.

An application service does work such as this.

1. Query the database and build a domain object from the data.
2. Call an operation on that object.
3. Save the result back to the database.

The two layers together form a hexagon, the application. Other applications are hexagons too. An SMTP service, a third-party system, and a message bus are examples. The set of hexagons is a hexagonal architecture. Alistair Cockburn coined the term.

It stresses three guidelines.

1. Separation of concerns. The domain layer owns business logic and nothing else. Application services own talking to external applications and the database, and hold no business logic. The domain layer holds the domain knowledge, the how-to. Application services hold the use cases, the what-to.
2. One-way flow inside the application. Application services depend on the domain layer, never the reverse. Domain classes depend only on each other. The domain layer stays isolated from the outside world.
3. Communication between applications goes through the interface of the application services layer. Nothing outside reaches the domain layer directly. A hexagon has six sides, but the number of connections is arbitrary.

### Fractal behavior

Each layer has its own observable behavior and its own implementation details. The domain layer's observable behavior is the set of operations and state that helps the application services reach their goals. The rules of a well-designed API apply at every scale, a whole layer or a single class.

Tests then take a fractal shape too. A test of an application service checks the coarse goal of the external client. A test of a domain class checks a subgoal on the way.

Observable behavior flows inward. The external client's goal turns into subgoals for domain classes. Every piece of observable behavior in the domain layer traces back to a use case. The trace runs from domain class to application service to external client.

That is why every test traces back to a business requirement. A test that tells no story a domain expert understands couples to implementation details and is brittle.

In the renaming example, the controller is an application service. The external client does not care about normalization. The name rule exists because of the application's own restrictions. `normalize_name` traces to no client need, so it is private, and tests check it only through the `display_name` setter.

This tracing rule fits most domain classes and application services. It fits utility and infrastructure code less well. Their problems are low-level and rarely trace to one use case.

### Intra-system and inter-system communication

1. Intra-system communication runs between classes inside the application.
2. Inter-system communication runs between the application and other applications.

Intra-system communication is an implementation detail. The collaboration between domain classes is not part of their observable behavior. It has no direct link to a client goal. Coupling tests to it makes them fragile.

Inter-system communication is different. How the system talks to the outside world forms its observable behavior as a whole. It is part of the contract the application holds at all times.

The reason is how separate applications evolve. They need backward compatibility. Whatever refactoring happens inside, the pattern of external calls stays the same, so other applications keep understanding it. Bus messages keep their shape. SMTP calls keep the same number and type of parameters.

Mocks help when they verify the communication pattern between the system and external applications. Mocks that verify communication between classes inside the system produce brittle tests.

### Example

A use case. A customer buys a product. If the stock covers the quantity, three things happen.

1. The stock drops.
2. The customer gets a receipt email.
3. The system returns a confirmation.

The application is an API with no UI.

```python
class PurchaseController:
    def purchase(self, customer_id, product_id, quantity):
        customer = self.customers.get(customer_id)
        product = self.products.get(product_id)

        ok = customer.purchase(self.main_warehouse, product, quantity)

        if ok:
            self.email_gateway.send_receipt(customer.email, product.name, quantity)
        return ok
```

Two inter-system communications exist. One runs between the controller and the third-party caller, which starts the use case. One runs between the controller and the email gateway. The call from `Customer` to `Warehouse` is intra-system.

The email is a side effect visible outside. It links directly to the client's goal. The client wants a purchase and expects a receipt. Mocking the gateway is legitimate. The test has to confirm that this communication survives any refactoring.

```python
def test_successful_purchase_sends_a_receipt():
    gateway = create_autospec(EmailGateway, instance=True)
    sut = make_purchase_controller(email_gateway=gateway)

    ok = sut.purchase(customer_id=1, product_id=2, quantity=5)

    assert ok is True
    gateway.send_receipt.assert_called_once_with("customer@example.com", "Lamp", 5)
```

The client also sees `ok`. The test checks it by plain comparison. A return value needs no mock.

The fragile version mocks the warehouse.

```python
def test_purchase_succeeds_when_stock_covers_quantity():
    warehouse = create_autospec(WarehouseProtocol, instance=True)
    warehouse.has_enough.return_value = True
    sut = Customer()

    ok = sut.purchase(warehouse, Item.LAMP, 5)

    assert ok is True
    warehouse.remove_stock.assert_called_once_with(Item.LAMP, 5)
```

The call to `remove_stock` does not cross the application boundary. Both caller and callee live inside. It is neither an operation nor state that helps the client. The client of these two domain classes is the controller, and its goal is a purchase. Only `customer.purchase` and `warehouse.stock_of` link to that goal. The first starts the purchase. The second shows the state after it. `remove_stock` is an intermediate step, an implementation detail.

## The schools revisited

The London school uses mocks for every dependency except immutable ones. It does not tell intra-system from inter-system calls. Its tests check calls between classes as often as calls to external systems. That habit couples tests to implementation details and removes resistance to refactoring. Resistance to refactoring is binary, so losing it makes the test nearly worthless.

The classical school does better. It replaces only dependencies that tests share, which almost always means out of process dependencies such as an SMTP service or a message bus. It still overuses mocks, less than the London school, because it replaces every shared dependency.

### Not every out of process dependency deserves a mock

Recap of the terms.

1. A shared dependency is one that tests share, not production code.
2. An out of process dependency runs in another process. A database, a message bus, and an SMTP service are examples.
3. A private dependency is any dependency that is not shared.

The classical school avoids shared dependencies because they let tests interfere with each other and block parallel runs. The book uses the term test isolation for the ability to run tests in parallel, in sequence, and in any order.

An in-process shared dependency is easy. Each test gets a new instance. An out of process one is harder. Creating a new database or message bus per test would slow the suite far too much. The usual answer replaces it with a double, a mock or a stub.

Some out of process dependencies do not deserve a mock. If only the application reaches a dependency, communication with it is not observable behavior. Nothing outside sees it. It acts as part of the application.

Backward compatibility is the reason to preserve external communication patterns. Other systems deploy on their own schedule, or the team does not control them. When the application acts as the only gateway to a system, that requirement vanishes. The team deploys the application and the system together, and clients notice nothing.

An application database is the standard case. No external system reads it. The team changes table layout, stored procedure parameters, or even the storage engine, and no client notices. Mocking that database makes tests fail on every such change. Treat the application and its database as one system.

The next question is how to test the application with its database without losing fast feedback. Chapters 6 and 7 answer it.

### Do mocks verify behavior

Mock advocates often claim that mocks verify behavior. In most cases they do not. How one class talks to its neighbors to reach a goal has nothing to do with observable behavior.

The author compares it to judging a person's behavior by measuring the signals between neurons. That level of detail is too fine. A client asking for help cares about the help, not about which neurons fire.

Mocks relate to behavior only when they verify calls that cross the application boundary, and only when the side effects of those calls are visible outside.

## Trade-offs the author names

1. Mocks give confidence that external contracts hold. Mocks on internal calls cost resistance to refactoring.
2. CQS makes code readable. Some methods, such as a stack pop, break it on purpose.
3. The one-operation-per-goal rule fits business logic. Utility code has exceptions.
4. Mocking a managed out of process dependency, such as the application database, costs resistance to refactoring. Chapter 8 shows the alternative.

## ADW rules that apply

1. `exposing_private_methods_for_testing`. Do not make a helper public to test it. Test it through the operation that uses it.
2. `exposing_private_state_for_testing`. Do not expose internal collections or fields to inspect them.
3. `mocking_concrete_classes`. Mock an interface at the boundary, not a concrete class.
4. The catalog entry `overspecification_asserting_interactions_with_stubs`. Never assert a call on a stub.

## Rust note

In Rust, `pub` on a helper function is the leak. The Rust idiom `#[cfg(test)] pub fn` still leaks the detail into the test API and invites the same brittle tests. Keep the helper private and test the public operation. Unit tests in a `#[cfg(test)] mod tests` block see private items, which makes the temptation stronger. The rule stays the same. Test through observable behavior.

Mocks in Rust need a trait. Put the trait on the boundary, such as `EmailGateway`, and keep domain structs concrete. Crates such as `mockall` generate mocks from a trait. A hand-written spy with a `RefCell<Vec<Sent>>` works as well and reads clearly.

```rust
#[derive(Default)]
struct SpyGateway {
    sent: RefCell<Vec<(String, String, u32)>>,
}

impl EmailGateway for SpyGateway {
    fn send_receipt(&self, email: &str, product: &str, quantity: u32) {
        self.sent.borrow_mut().push((email.into(), product.into(), quantity));
    }
}
```

## What the agent does with this chapter

1. Use a mock only for a call that leaves the application and that an outside system observes.
2. Use a stub for input. Never assert on a stub.
3. Keep domain collaborators real. Never mock a call between two domain classes.
4. Treat a database only the application touches as part of the application. Do not mock it.
5. When a test needs a private helper, test the public operation that calls it.
