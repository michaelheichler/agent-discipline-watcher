# Chapter 8. Why integration testing?

Book pages 185 to 215.

## Core argument

Unit tests alone do not prove the system works. Business logic has to work with the database, the message bus, and other parts. Integration tests check that.

The chapter answers five questions.

1. What integration tests cover and how many to write.
2. Which out of process dependencies to use for real and which to mock.
3. When an interface earns its place.
4. Which design habits make integration tests easier and the code healthier.
5. Whether and how to test logging.

## What an integration test is

### Its role

A unit test verifies one unit of behavior, runs fast, and runs isolated from other tests. Any test that fails one of these is an integration test.

In practice, integration tests check how the system works with out of process dependencies. They cover the controller quadrant from chapter 7. Unit tests cover the domain model and algorithms. Integration tests cover the glue between the domain model and out of process dependencies.

A controller test becomes a unit test if every out of process dependency gets a mock. Tests then share nothing, stay fast, and stay isolated. Most applications have one dependency that a mock does not fit, though. It is usually a database that no other application sees.

The other two quadrants get no tests. Trivial code is not worth it. Overcomplicated code gets split into algorithms and controllers first. All tests target the domain model quadrant and the controller quadrant.

### The pyramid revisited

Integration tests are slow, because they touch out of process dependencies. They cost more to maintain for two reasons.

1. The out of process dependencies have to stay up.
2. More collaborators make the test larger.

They also run through more code, both the team's own and library code, so they protect better than unit tests. They sit further from the code, so they resist refactoring better.

The ratio varies by project. The rule of thumb stays the same. Check as many edge cases of a business scenario as possible with unit tests. Use integration tests for one happy path, plus any edge case unit tests cannot reach.

A happy path is a successful run of a business scenario. An edge case is a run that ends in an error.

Moving most of the work into unit tests keeps maintenance cheap. One or two integration tests per scenario confirm the system works as a whole. This yields the pyramid ratio. End-to-end tests count as a subset of integration tests.

The shape depends on complexity. A simple application has little code in the domain model quadrant. Its tests form a rectangle, with equal numbers of unit and integration tests. The most trivial applications have no unit tests at all.

Integration tests keep their value even then. Simple code still has to work with other subsystems.

### Integration tests and failing fast

Pick the longest happy path for the integration test, the one that touches every out of process dependency. If no single path touches all of them, write more integration tests until the tests reach every external system.

Edge cases have an exception too. Skip an edge case whose wrong handling crashes the whole application at once.

In chapter 7, `Member.change_billing_country` requires `can_change_billing_country` as a precondition. The controller calls `can_change_billing_country` and stops on an error.

```python
error = member.can_change_billing_country()
if error:
    return error
```

An integration test could cover this branch. It adds too little value. If the controller skipped the check, the precondition inside `Member` raises and the application fails on the first run. The bug shows at once, is easy to fix, and corrupts no data.

The author repeats a tip. No test beats a bad test, and a test without significant value is a bad test.

The precondition in `Member` still deserves a test. A unit test covers it. An integration test is unnecessary.

Making bugs show up fast is the Fail Fast principle. It is a real alternative to integration testing.

### The Fail Fast principle

Stop the current operation as soon as an unexpected error occurs. This makes the application more stable in two ways.

1. It shortens the feedback loop. The earlier a bug shows, the easier the fix. A production bug costs orders of magnitude more than one found in development.
2. It protects persisted state. Bugs corrupt state. Once corrupt data reaches the database, repair gets much harder. Failing fast stops the corruption from spreading.

Exceptions suit this well. They interrupt the flow and rise to the top of the stack, where the application logs them and shuts down or restarts the operation.

Preconditions are one form of fail fast. A failed precondition means a wrong assumption about application state, which always means a bug. Reading configuration is another. Make the reader raise when the configuration is incomplete or wrong, and run it at startup. The application then refuses to start with a bad configuration.

## Which out of process dependencies to test directly

Integration tests use the real dependency or replace it with a mock. The choice follows the kind of dependency.

### Managed and unmanaged dependencies

1. Managed dependencies. Out of process dependencies the team fully controls. Only the application reaches them, and nothing outside sees the interactions. The application database is the standard example. External systems reach the data through the application's API, not the database.
2. Unmanaged dependencies. Out of process dependencies the team does not fully control. Other applications observe the interactions. An SMTP server and a message bus are examples. Both produce side effects other systems see.

Chapter 5 showed that communication with managed dependencies is an implementation detail and communication with unmanaged dependencies is observable behavior. The rule for integration tests follows.

Use real instances of managed dependencies. Replace unmanaged dependencies with mocks.

Communication with unmanaged dependencies has to keep backward compatibility. Mocks fit that job. They make sure the communication pattern survives any refactoring.

Managed dependencies need no backward compatibility, since only the application talks to them. External clients do not care how the database looks. They care about the final state of the system. A real database in integration tests verifies that final state from the client's view. It also supports database refactoring, such as renaming a column or moving to another database engine.

### Dependencies that are both

Some dependencies are both managed and unmanaged. A database that other applications also read is the common case.

It usually starts with a system and its own database. Later another system needs some of the data, and the team opens a few tables to it for convenience. The database now has a private part and a shared part.

Integrating systems through a database couples them and slows further development. Use it only when nothing else works. An API, for synchronous calls, or a message bus, for asynchronous ones, is the better choice.

When a shared database already exists and cannot change soon, split it in tests. Treat the tables other applications see as an unmanaged dependency. Those tables act as a message bus, and their rows act as messages. Use mocks to keep the communication pattern with them stable. Treat the rest of the database as managed, and check its final state, not the interactions.

The split matters because the shared tables are visible. Change how the system writes to them only when unavoidable. Nobody knows how other applications react.

### When a real database is not available

Sometimes a real managed dependency cannot run in tests. A legacy database that does not deploy to a test environment, a security policy, or a high cost of running a test instance are examples.

Mocking the database anyway is not the answer. Mocking a managed dependency costs resistance to refactoring. The tests also protect less. If the database is the only out of process dependency, those integration tests add no protection beyond the unit tests from chapter 7. They only check which repository methods the controller calls. That buys confidence in three lines of controller code and a lot of plumbing.

If a real database is not possible, skip integration tests and focus on unit tests of the domain model. Scrutinize every test. A test without enough value has no place in the suite.

ADW names mocking a managed dependency as the catalog entry `mocking_managed_dependency`.

## Worked example

The billing system from chapter 7 changes a member's billing country. The controller reads member and company from the database, delegates decisions to the domain model, saves results, and sends a bus message when needed.

```python
class MemberController:
    def __init__(self, database, bus):
        self._database = database
        self._bus = bus

    def change_billing_country(self, member_id, new_country):
        member = MemberFactory.create(self._database.get_member(member_id))
        error = member.can_change_billing_country()
        if error:
            return error

        company = CompanyFactory.create(self._database.get_company())
        member.change_billing_country(new_country, company)

        self._database.save_company(company)
        self._database.save_member(member)
        for event in member.events:
            self._bus.send_billing_country_changed(event.member_id, event.new_country)
        return "OK"
```

### Which scenarios to test

Cover the longest happy path and any edge case unit tests miss. The longest happy path runs through every out of process dependency.

Here it is a change from the home country to a foreign one. That produces the most side effects.

1. The database updates both rows. The member's kind and country change, and the company's domestic count changes.
2. A message goes to the bus.

One edge case lacks a unit test, the locked-after-invoice case. It needs no test, because the application fails fast without the controller check. One integration test remains.

### Categorizing the database and the bus

Only this application reaches the database. That makes it a managed dependency, so the test uses a real one.

1. Insert a member and a company.
2. Run the change on that database.
3. Check the database state.

The bus exists only to talk to other systems. That makes it an unmanaged dependency, so the test mocks it and checks the calls.

### End-to-end tests

The sample gets no end-to-end tests. For an API, an end-to-end test runs against a deployed, running instance with no mocks at all. An integration test hosts the application in the test process and mocks only unmanaged dependencies.

Whether to add end-to-end tests is a judgment call. With managed dependencies real and unmanaged ones mocked, integration tests protect nearly as well as end-to-end tests. One or two end-to-end tests after deployment still make a good sanity check. Run them through the longest happy path too. To emulate the external client, check the bus directly, but check the database only through the application.

### First version of the integration test

```python
def test_moving_away_from_the_home_country():
    db = Database(TEST_CONNECTION_STRING)
    member = create_member(db, country="DE", kind=MemberKind.DOMESTIC)
    create_company(db, home_country="DE", domestic_count=1)
    bus = create_autospec(MessageBus, instance=True)
    sut = MemberController(db, bus)

    result = sut.change_billing_country(member.member_id, "FR")

    assert result == "OK"

    member_from_db = MemberFactory.create(db.get_member(member.member_id))
    assert member_from_db.country == "FR"
    assert member_from_db.kind == MemberKind.INTERNATIONAL

    company_from_db = CompanyFactory.create(db.get_company())
    assert company_from_db.domestic_count == 0

    bus.send_billing_country_changed.assert_called_once_with(member.member_id, "FR")
```

The arrange section calls `create_member` and `create_company` helpers instead of inserting rows inline. Other integration tests reuse them.

The test checks the database state independently of the input data. It reads member and company back from the database into new objects before asserting. This way the test exercises both writes and reads, which gives the most protection. The reads use the same classes the controller uses, here `Database`, `MemberFactory`, and `CompanyFactory`.

The test works. It has room to improve. Helpers in the assert section would shorten it. The bus mock does not protect as well as it could. Chapters 9 and 10 cover both.

## Interfaces and dependencies

Interfaces are among the most misunderstood tools in unit testing. Developers add them for invalid reasons and overuse them.

### Interfaces and loose coupling

Many code bases pair every out of process dependency with an interface, even when only one implementation exists.

```python
class MessageBusProtocol(Protocol): ...
class MessageBus(MessageBusProtocol): ...

class MemberRepositoryProtocol(Protocol): ...
class MemberRepository(MemberRepositoryProtocol): ...
```

The usual reasons are two.

1. The interface abstracts the out of process dependency and gives loose coupling.
2. The interface lets new features arrive without changing existing code, following the open-closed principle.

Both are misconceptions.

An interface with one implementation is not an abstraction. It gives no looser coupling than the concrete class. Developers discover real abstractions. They do not invent them. Discovery happens after the fact, when the abstraction already exists in the code but has no name yet. An interface is a real abstraction only with at least two implementations.

The second reason breaks a more basic principle, YAGNI, short for "you aren't gonna need it". Do not build features nobody needs now, and do not bend existing code for them. Two reasons stand behind YAGNI.

1. Opportunity cost. Time spent on a feature the business does not need now is time taken from features it needs now. When the business finally asks for the feature, its view has usually changed, and the early code needs rework anyway. Building from scratch when the need appears works better.
2. Less code is better. Code written for a future nobody asked for raises the cost of ownership. Postpone new functionality as late as possible.

The author's tip. Every line of code costs money to write and to keep alive. Prefer the solution with the fewest and simplest lines.

Rare cases exist where YAGNI does not apply. The author covers them in a separate article on open-closed versus YAGNI.

### Why interfaces for out of process dependencies

Interfaces enable mocking. That is the practical reason for them. Without one, a test cannot create a double and cannot check calls to the dependency.

Do not add an interface for an out of process dependency unless tests mock it. Tests only mock unmanaged dependencies. The rule shrinks to this. Give an interface to an unmanaged dependency and to nothing else. Pass a managed dependency in as a concrete class, and keep passing it in explicitly.

A real abstraction, with two or more implementations, gets an interface whether or not tests mock it. A single-implementation interface for any other reason than mocking breaks YAGNI.

```python
class MemberController:
    def __init__(self, database: Database, bus: MessageBusProtocol):
        self._database = database
        self._bus = bus
```

The controller takes both dependencies in its constructor. Only the bus has an interface, because only the bus gets a mock. The database is a managed dependency and needs none.

A mock also works without an interface if the dependency's methods are overridable and the mock subclasses the concrete class. That is worse than an interface. Chapter 11 explains why. ADW flags it as `mocking_concrete_classes`.

### Interfaces for in-process dependencies

Some code bases also put interfaces in front of domain classes.

```python
class MemberProtocol(Protocol):
    member_id: int
    country: str
    def can_change_billing_country(self) -> str | None: ...
    def change_billing_country(self, new_country: str, company: "Company") -> None: ...


class Member(MemberProtocol): ...
```

In practice such interfaces have one implementation, and that is a red flag. The only reason for a single-implementation interface on a domain class is to mock it. Unlike out of process dependencies, interactions between domain classes never get checked. Checking them couples tests to implementation details and fails on resistance to refactoring.

The catalog lists this as `unnecessary_interface_single_implementation`.

## Best practices for integration tests

Three habits help integration tests and the code base alike.

1. Make domain model boundaries explicit.
2. Reduce the number of layers.
3. Remove circular dependencies.

### Explicit domain model boundaries

Give the domain model a known, explicit place in the code base. The domain model is the collected domain knowledge about the problem the project solves. A clear boundary makes that part easier to see and reason about.

It helps testing too. Unit tests target the domain model and algorithms. Integration tests target controllers. A clear line between domain classes and controllers makes the line between unit and integration tests clear too.

The boundary can be a separate package or a namespace. The form matters less than keeping all domain logic under one distinct umbrella instead of scattering it.

### Fewer layers

Programmers tend to add layers of indirection to abstract and generalize. An enterprise application often has several, such as application services, business logic implementation, abstractions, and persistence. A feature cuts through all of them and takes a thin slice of each.

In extreme cases, so many layers exist that finding anything in the code base gets hard and even simple logic hides. Developers then want the specific answer to the problem in front of them, not a general version of it.

David J. Wheeler put it this way. Every problem in computer science yields to another layer of indirection, except the problem of too many layers of indirection.

Layers hurt reasoning. When every feature has a piece in every layer, assembling the full picture takes real effort. That mental load slows all development.

Too many abstractions also hurt tests. Code bases with many layers rarely have a clear boundary between controllers and domain model, which chapter 7 named as a precondition for effective tests. Developers also tend to test each layer on its own. That produces many low-value integration tests, each exercising one layer and mocking the layers below. The result is always weak protection and low resistance to refactoring.

Keep as few layers as possible. Most backend systems need three.

1. The domain layer, with the domain logic.
2. The application services layer, the controllers. It gives external clients an entry point and coordinates domain classes and out of process dependencies.
3. The infrastructure layer. It holds algorithms that do not belong in the domain, plus the code that reaches out of process dependencies, such as repositories, ORM mappings, and SMTP gateways.

The catalog lists over-layering as `excessive_layers_of_indirection`.

### No circular dependencies

A circular dependency, also called a cyclic dependency, means two or more classes depend on each other, directly or indirectly, to work.

A callback is the usual case.

```python
class CheckoutService:
    def check_out(self, order_id):
        service = ReceiptService()
        service.build_receipt(order_id, self)


class ReceiptService:
    def build_receipt(self, order_id, checkout):
        ...
        checkout.receipt_ready(order_id)
```

`CheckoutService` creates a `ReceiptService` and passes itself in. `ReceiptService` calls back to report the result.

Cycles add heavy mental load, like too many layers. They offer no clear starting point. To understand one class, a reader has to understand the whole cluster at once. Even a small set of interdependent classes gets hard to follow fast.

Cycles also hurt testing. Tests reach for interfaces and mocks to split the graph and isolate a unit of behavior. Chapter 5 ruled that out for the domain model.

An interface only masks a cycle. Put a protocol in front of `CheckoutService` and make `ReceiptService` depend on it. The cycle disappears at the type level but still runs at runtime. The reader's load stays the same, or grows, because of the extra interface.

Removing the cycle is the better fix. `ReceiptService` depends on neither `CheckoutService` nor its interface. It returns its result as a plain value.

```python
class CheckoutService:
    def check_out(self, order_id):
        receipt = ReceiptService().build_receipt(order_id)
        ...


class ReceiptService:
    def build_receipt(self, order_id):
        ...
        return Receipt(order_id, ...)
```

Removing every cycle is rarely possible. Keep the remaining clusters of interdependent classes as small as possible.

The catalog lists this as `circular_dependencies`.

### Several act sections in a test

Chapter 3 called several arrange, act, or assert sections a code smell. They mean the test checks several units of behavior and loses maintainability.

Two related use cases tempt people to share one test, such as registering and deleting a member.

1. Arrange. Prepare registration data.
2. Act. Register the member.
3. Assert. Query the database for the new member.
4. Act. Delete the member.
5. Assert. Query the database to confirm the deletion.

The flow looks natural, because the first act prepares the second. Such tests lose focus and bloat fast. Split them, one act per test. Two tests where one seemed enough looks like extra work. It pays off, because each test stays focused on one behavior and stays easy to change.

The exception is an out of process dependency that is hard to bring into a needed state. Say registration also opens an account in an external banking system. The bank offers a sandbox for end-to-end tests. The sandbox is slow, or the bank limits calls. Combining several acts into one test then cuts the number of calls to the problematic dependency.

Such hard dependencies are the only legitimate reason for several act sections. Unit tests never have several acts, since they do not touch out of process dependencies. Integration tests rarely do. In practice, multistep tests almost always belong with end-to-end tests.

ADW flags several act sections in a unit test as `multiple_act_sections_in_unit_test`.

## Testing logging

Logging is a gray area. The chapter splits it into four questions.

### Should you test logging at all

Logging is a cross-cutting concern that appears anywhere in the code.

```python
def change_billing_country(self, new_country, company):
    self._logger.info(f"Changing billing country for member {self.member_id} to {new_country}")

    require(self.can_change_billing_country() is None)
    if self.country == new_country:
        return

    new_kind = MemberKind.DOMESTIC if company.is_domestic(new_country) else MemberKind.INTERNATIONAL
    if self.kind != new_kind:
        company.change_domestic_count(1 if new_kind == MemberKind.DOMESTIC else -1)
        self._logger.info(f"Member {self.member_id} changed kind from {self.kind} to {new_kind}")

    self.country = new_country
    self.kind = new_kind
    self.events.append(BillingCountryChanged(self.member_id, new_country))

    self._logger.info(f"Billing country changed for member {self.member_id}")
```

Logging records useful information. It also appears so often that testing it all costs a lot. The deciding question is whether logging is part of observable behavior or an implementation detail.

Logging is no different from other functionality. It writes to something outside the process, for example a log file or a table. If customers, clients, or anyone besides the developers read those side effects, logging is observable behavior and needs tests. If only developers read it, logging is an implementation detail. It changes freely, and it needs no tests.

A logging library is one case where logs are the only observable behavior. Business people who require logs of key workflows are another. Those logs become a business requirement and need tests. The same application often also keeps separate logs only for developers.

Steve Freeman and Nat Pryce name the two kinds.

1. Support logging produces messages that support staff or system administrators track.
2. Diagnostic logging helps developers see what happens inside the application.

### How to test logging

Logging touches out of process dependencies, so the usual rules apply. Use mocks to check the calls between the application and the log storage.

#### A wrapper over the logger

Do not mock the raw logger interface. Support logging is a business requirement, so make that requirement explicit in the code. Create a domain logger that lists every support log entry the business needs. Check calls on that class instead of the raw logger.

Say the business requires a log entry for every change of member kind. The entries at the start and end of the method exist only for debugging.

```python
def change_billing_country(self, new_country, company):
    self._logger.info(f"Changing billing country for member {self.member_id} to {new_country}")
    ...
    if self.kind != new_kind:
        company.change_domestic_count(1 if new_kind == MemberKind.DOMESTIC else -1)
        self._domain_logger.member_kind_changed(self.member_id, self.kind, new_kind)
    ...
    self._logger.info(f"Billing country changed for member {self.member_id}")
```

```python
class DomainLogger:
    def __init__(self, logger):
        self._logger = logger

    def member_kind_changed(self, member_id, old_kind, new_kind):
        self._logger.info(f"Member {member_id} changed kind from {old_kind} to {new_kind}")
```

Diagnostic logging still uses the raw logger. Support logging now goes through `DomainLogger`, which speaks the domain language and states each entry the business needs. Support logging becomes easier to read and maintain.

#### Structured logging

This design resembles structured logging. Structured logging separates capturing log data from rendering it.

Plain logging formats a string and writes it.

```python
logger.info("Member id is " + str(12))
```

The result is hard to analyze. Counting messages of one kind, or messages about one member, needs special tooling.

Structured logging adds structure to the storage. The call looks similar.

```python
logger.info("Member id is {member_id}", member_id=12)
```

Underneath, the library stores a message template and the parameters together as captured data. A renderer then turns the data into a flat log, JSON, or CSV. JSON and CSV make analysis easy.

`DomainLogger` is not a structured logger, but it follows the same idea. `member_kind_changed` works like the template. Together with the member id and the two kinds, it forms the log data. The method renders that data into a flat file, and adding JSON or CSV output takes little work.

#### Tests for support and diagnostic logging

The class `DomainLogger` fronts an out of process dependency, the log storage. The class `Member` now talks to that dependency. That breaks the split between business logic and out of process communication, and `Member` slides into the overcomplicated quadrant.

The fix is the same as for bus notifications in chapter 7. Add a domain event for kind changes. The controller turns it into a `DomainLogger` call.

```python
def change_billing_country(self, new_country, company):
    self._logger.info(f"Changing billing country for member {self.member_id} to {new_country}")
    require(self.can_change_billing_country() is None)
    if self.country == new_country:
        return

    new_kind = MemberKind.DOMESTIC if company.is_domestic(new_country) else MemberKind.INTERNATIONAL
    if self.kind != new_kind:
        company.change_domestic_count(1 if new_kind == MemberKind.DOMESTIC else -1)
        self.events.append(MemberKindChanged(self.member_id, self.kind, new_kind))

    self.country = new_country
    self.kind = new_kind
    self.events.append(BillingCountryChanged(self.member_id, new_country))
    self._logger.info(f"Billing country changed for member {self.member_id}")
```

Both events share one base type and live in one list.

```python
def change_billing_country(self, member_id, new_country):
    member = MemberFactory.create(self._database.get_member(member_id))
    error = member.can_change_billing_country()
    if error:
        return error

    company = CompanyFactory.create(self._database.get_company())
    member.change_billing_country(new_country, company)

    self._database.save_company(company)
    self._database.save_member(member)
    self._dispatcher.dispatch(member.events)
    return "OK"
```

A new `EventDispatcher` turns domain events into out of process calls.

1. `BillingCountryChanged` becomes a bus message.
2. `MemberKindChanged` becomes a `DomainLogger.member_kind_changed` call.

The split between domain logic and out of process communication is back. Support logging now tests like the other unmanaged dependency, the bus.

1. Unit tests check for a `MemberKindChanged` event on the `Member` under test.
2. The single integration test uses a mock to confirm the call to `DomainLogger`.

Support logging done inside a controller needs no domain events. Controllers already orchestrate the domain model and out of process dependencies, and `DomainLogger` is one of those. The controller calls it directly.

`Member` still writes diagnostic logs with the raw logger at the start and end of the method. That is on purpose. Diagnostic logging is for developers only. It needs no unit test, so it does not have to leave the domain model.

Still, keep diagnostic logging out of `Member` and other domain classes where possible. The next section explains why.

### How much logging is enough

Support logging is a business requirement, so the business decides. Diagnostic logging is up to the team. Do not overuse it, for two reasons.

1. Too much logging clutters the code. This hurts the domain model most. The author advises against diagnostic logging in `Member`, even though it is fine for unit tests, because it hides the logic.
2. The signal-to-noise ratio of logs matters. The more a system logs, the harder the relevant entries are to find. Maximize the signal and minimize the noise.

Avoid diagnostic logging in the domain model. It usually moves to controllers without trouble. Even there, add it only while debugging, and remove it after. Ideally, diagnostic logging covers unhandled exceptions only.

### How to pass logger instances around

One way is a static lookup stored in a static field.

```python
class Member:
    _logger = logging.getLogger(__name__)

    def change_billing_country(self, new_country, company):
        self._logger.info(...)
        ...
```

Steven van Deursen and Mark Seemann call this ambient context and list it as an anti-pattern. Two of their arguments follow.

1. The dependency hides, and changing it is hard.
2. Testing gets harder.

The author agrees and adds a third. Ambient context masks design problems. If injecting a logger into a domain class feels so awkward that ambient context looks attractive, something is wrong. The code logs too much or has too many layers of indirection. Ambient context hides the symptom. Fix the cause.

Inject the logger explicitly, through the constructor or as a method argument.

```python
def change_billing_country(self, new_country, company, logger):
    logger.info(f"Changing billing country for member {self.member_id} to {new_country}")
    ...
    logger.info(f"Billing country changed for member {self.member_id}")
```

In Python, module-level `logging.getLogger(__name__)` is the standard idiom and rarely hurts diagnostic logging. The rule matters for support logging. Business-required log entries go through an injected domain logger, never through a module-level global.

## Conclusion

Look at every communication with an out of process dependency through one question. Is it part of observable behavior or an implementation detail? Log storage is no different. Mock logging when non-programmers read the logs. Do not test it otherwise.

## Trade-offs the author names

1. Integration tests protect better and resist refactoring better. Unit tests run faster and cost less. The pyramid balances them.
2. One happy path per scenario in integration tests, edge cases in unit tests.
3. Skip integration tests for edge cases that fail fast.
4. Mocking a managed dependency costs resistance to refactoring and adds little protection. Without a real database, skip integration tests.
5. Combining acts in one test is acceptable only when an out of process dependency is hard to bring into a needed state.

## ADW rules that apply

1. `multiple_act_sections_in_unit_test`. Only end-to-end tests with a hard external dependency justify several acts.
2. `mocking_concrete_classes`. Mock an interface on an unmanaged dependency. Do not subclass a concrete class to mock it.
3. `incomplete_mock_call_verification`. The bus mock in the first test version checks one call. Chapter 9 tightens it.
4. `hollow_test`. An integration test that mocks the only out of process dependency and checks repository calls adds no value.
5. The catalog entries `mocking_managed_dependency`, `unnecessary_interface_single_implementation`, `excessive_layers_of_indirection`, `circular_dependencies`, `fail_fast_principle`, and `logging_test_guideline` come from this chapter.

## Rust note

Rust traits play the role of interfaces. Add a trait only for unmanaged dependencies that tests mock, such as `trait MessageBus`. Keep the database handle concrete, for example a `PgPool` or a repository struct, and run integration tests against a real test database. A generic parameter `C: MessageBus` or a `Box<dyn MessageBus>` both work for injection.

The `log` and `tracing` crates are global facades, a form of ambient context. They suit diagnostic logging. For support logging, pass a `DomainLogger` struct explicitly, or emit domain events and let the controller dispatch them.

## What the agent does with this chapter

1. Write unit tests for every edge case of the domain logic. Write one integration test for the longest happy path.
2. Skip integration tests for edge cases that fail fast through a precondition.
3. Use the real application database in integration tests. Mock only buses, email gateways, and other systems that outside parties observe.
4. Never mock the application database. If no real database is available, write no integration test.
5. Do not add an interface for testing a domain class. Do not add one for a managed dependency.
6. Test support logging through a domain logger or domain events. Do not test diagnostic logging.
7. Keep one act per test. Report a multistep test unless an external dependency forces it.
