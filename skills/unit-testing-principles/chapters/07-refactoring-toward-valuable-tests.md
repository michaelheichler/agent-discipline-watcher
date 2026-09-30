# Chapter 7. Refactoring toward valuable unit tests

Book pages 151 to 182.

## Core argument

A suite rarely improves without changes to the code under it. Test code and production code depend on each other. Writing valuable tests takes design skill, not only test skill.

The chapter sorts all code into four quadrants by two measures. It shows how to move code out of the worst quadrant with the Humble Object pattern. It ends with what to unit test, what to skip, and how to keep controllers simple when business logic needs data in the middle of an operation.

## The four types of code

### Two dimensions

1. Complexity or domain significance.
2. Number of collaborators.

Complexity is the number of decision points, meaning branches, in the code. Cyclomatic complexity measures it as 1 plus the number of branching points. A method with no `if` and no conditional loop has complexity 1. The number also equals the count of independent paths from entry to exit, or the tests needed for full branch coverage. Each simple predicate counts. `if a and b` counts as two branches, like two nested `if` statements, for a complexity of 3.

Domain significance measures how much the code matters to the problem domain. Domain layer code usually links straight to end-user goals. Utility code does not.

The two parts are independent. A method that computes an order price has no branches and complexity 1, yet it is business-critical and deserves a test. Complex code does not always carry domain significance either.

The second dimension counts collaborators. A collaborator is a dependency that is mutable, out of process, or both. More collaborators make tests larger. Each one needs setup, and the test checks its state or interactions afterwards.

The kind of collaborator matters too. Out of process collaborators do not belong in the domain model. They need mock machinery in tests, and mocks are only safe on calls that cross the application boundary. Delegate all out of process communication to classes outside the domain layer. Domain classes then work only with in-process dependencies.

Implicit and explicit collaborators both count. A collaborator passed as an argument and one reached through a static call both need setup. Immutable dependencies, meaning values, do not count. They are easy to build and to assert against.

### The quadrants

| | Few collaborators | Many collaborators |
|---|---|---|
| High complexity or domain significance | domain model and algorithms | overcomplicated code |
| Low complexity and domain significance | trivial code | controllers |

1. Domain model and algorithms. Complex or significant code with few collaborators. Complex code often lives in the domain model, though a complex algorithm outside the domain also fits here.
2. Trivial code. A parameterless constructor or a one-line property. Few collaborators, little complexity or significance.
3. Controllers. Code that does no complex or business-critical work itself. It coordinates domain classes and external applications.
4. Overcomplicated code. High on both axes. A fat controller that does everything itself instead of delegating is the typical case.

### What to test

1. Unit test the domain model and algorithms. These tests give the best return. They protect well because the code is complex or important. They cost little because the code has few collaborators.
2. Do not test trivial code. Those tests have near-zero value.
3. Test controllers briefly, as part of a smaller set of integration tests. Part 3 covers this.
4. Split overcomplicated code. It is too hard to unit test and too risky to leave uncovered. Split it into algorithms and controllers.

The more important or complex the code, the fewer collaborators it has.

Removing overcomplicated code and unit testing only the domain model and algorithms gives a valuable, maintainable suite. Coverage will not reach 100 percent. That is fine. The goal is a suite where each test adds real value. Refactor or delete every other test. The author adds that writing no test at all beats writing a bad one.

## The Humble Object pattern

Gerard Meszaros introduced the Humble Object pattern as a way to fight coupling. It applies far more widely.

Code often resists testing because it couples to a framework dependency. Examples are asynchronous or multithreaded execution, user interfaces, and out of process dependencies.

Extract the logic into a separate, testable class. What remains is a thin, humble wrapper. It glues the hard dependency to the extracted logic, holds little or no logic itself, and needs no unit test.

Hexagonal and functional architectures both implement this pattern. Hexagonal architecture separates business logic from out of process communication. Functional architecture goes further. It separates business logic from communication with any collaborator. The functional core has no collaborators at all, which puts it right against the vertical axis of the quadrant diagram. The mutable shell and the application services sit in the controller quadrant.

The pattern is also a form of the Single Responsibility principle. One responsibility is always business logic, and the pattern separates it from almost anything.

The author describes it as depth versus width. Code is deep, meaning complex or important, or wide, meaning it works with many collaborators. Never both. Controllers orchestrate many dependencies but hold no complexity. Domain classes do the opposite.

Many known patterns are Humble Object patterns.

1. Model View Presenter and Model View Controller separate business logic, UI, and coordination. The presenter and controller are humble objects that glue view and model.
2. The Aggregate pattern from Domain-Driven Design groups classes into clusters with strong links inside and loose links between them. Fewer connections across the code base mean better testability.

Testability is not the only gain. The same separation tames complexity and keeps the code maintainable.

## Worked example. From overcomplicated to split

### The domain

A coworking company bills members through an external invoicing system. The only use case is changing a member's billing country. Three rules apply.

1. A member whose billing country equals the company's home country is domestic. Everyone else is international.
2. The company tracks how many domestic members it has, for tax reporting. When a member flips between domestic and international, the count changes.
3. When the billing country changes, the invoicing system gets a message on the bus.

### The starting point

```python
class Member:
    def change_billing_country(self, member_id, new_country):
        row = Database.get_member(member_id)
        self.member_id = member_id
        self.country = row["country"]
        self.kind = MemberKind(row["kind"])

        if self.country == new_country:
            return

        company = Database.get_company()
        home = company["home_country"]
        domestic_count = company["domestic_count"]

        new_kind = MemberKind.DOMESTIC if new_country == home else MemberKind.INTERNATIONAL
        if self.kind != new_kind:
            delta = 1 if new_kind == MemberKind.DOMESTIC else -1
            Database.save_company(domestic_count + delta)

        self.country = new_country
        self.kind = new_kind

        Database.save_member(self)
        MessageBus.send_billing_country_changed(self.member_id, new_country)
```

The example skips validation for brevity.

The code has only two decision points. The member kind, and the domestic count update. Both are core business logic, so the class scores high on complexity and significance.

`Member` has four dependencies. Two are explicit, `member_id` and `new_country`. Those are values and do not count. Two are implicit, `Database` and `MessageBus`. Those are out of process collaborators, which do not belong in code with high domain significance. The class lands in the overcomplicated quadrant.

A domain class that loads and saves itself follows the Active Record pattern. It works in simple or short-lived projects. It fails to scale, because it mixes business logic with out of process communication.

### Take 1. Make the implicit dependencies explicit

The usual move adds interfaces for the database and the bus, injects them into `Member`, and mocks them in tests. Chapter 6 did this with the file system. It helps, but not enough.

On the quadrant diagram, a domain model that reaches out of process dependencies through an interface is still wide. Those dependencies are still proxies to data not yet in memory. Tests still need mock machinery. Mocking the database also makes tests fragile, as chapter 8 explains.

The domain model is cleaner with no out of process collaborators at all, direct or through an interface. Hexagonal architecture says the same.

### Take 2. Add an application services layer

Move all external communication into a humble controller, an application service in hexagonal terms. Domain classes depend only on in-process dependencies, such as other domain classes and plain values.

```python
class MemberController:
    def __init__(self):
        self._database = Database()
        self._bus = MessageBus()

    def change_billing_country(self, member_id, new_country):
        row = self._database.get_member(member_id)
        member = Member(member_id, row["country"], MemberKind(row["kind"]))

        company = self._database.get_company()
        new_count = member.change_billing_country(
            new_country, company["home_country"], company["domestic_count"]
        )

        self._database.save_company(new_count)
        self._database.save_member(member)
        self._bus.send_billing_country_changed(member_id, new_country)
```

A good first step with four problems.

1. The controller creates the database and bus itself instead of taking them as parameters. That blocks the integration tests of chapter 8.
2. The controller rebuilds a `Member` from raw data. That is complex logic, and a controller only orchestrates.
3. The same holds for company data. `Member` also returns the new domestic count, which looks wrong. The count belongs to the company, not to one member.
4. The controller saves data and sends the message every time, even when the country did not change.

`Member` has become easy to test. It has no collaborators at all.

```python
def change_billing_country(self, new_country, home_country, domestic_count):
    if self.country == new_country:
        return domestic_count

    new_kind = MemberKind.DOMESTIC if new_country == home_country else MemberKind.INTERNATIONAL
    if self.kind != new_kind:
        domestic_count += 1 if new_kind == MemberKind.DOMESTIC else -1

    self.country = new_country
    self.kind = new_kind
    return domestic_count
```

`Member` now sits in the domain quadrant, near the vertical axis. The controller is in the controller quadrant but close to the overcomplicated one, because it holds complex logic.

### Take 3. Remove complexity from the application service

Move the reconstruction logic out of the controller. An ORM is the natural home, since every ORM has a place to map tables to classes. Without an ORM, write a factory in the domain model. It is a separate class or, for simple cases, a class method on the domain class.

```python
class MemberFactory:
    @staticmethod
    def create(row):
        require(len(row) >= 3)
        return Member(row["id"], row["country"], MemberKind(row["kind"]))
```

The factory has no collaborators and is easy to test. `require` is a small helper that raises when its argument is false. It reads better than a negated `if` followed by a raise, because positive statements read more easily.

The reconstruction logic is complex, yet it has no domain significance. It does not serve the goal of changing a billing country. It is utility code.

The logic counts as complex even with one visible branch. Chapter 1 showed that libraries hide branches. Indexing into a row and converting types each hide decisions inside the framework, such as which element to return and whether a conversion fails. Those hidden branches make the factory worth a test.

### Take 4. Introduce a Company class

Returning a new domestic count from `Member` signals a misplaced responsibility, which signals a missing abstraction. A `Company` domain class bundles company data with its logic.

```python
class Company:
    def __init__(self, home_country, domestic_count):
        self.home_country = home_country
        self.domestic_count = domestic_count

    def change_domestic_count(self, delta):
        require(self.domestic_count + delta >= 0)
        self.domestic_count += delta

    def is_domestic(self, country):
        return country == self.home_country
```

These two methods follow tell-don't-ask. `Member` tells the company to change the count, or asks it to classify a country. It does not pull raw data and do the work itself.

A `CompanyFactory` rebuilds companies the way `MemberFactory` rebuilds members.

```python
class MemberController:
    def change_billing_country(self, member_id, new_country):
        member = MemberFactory.create(self._database.get_member(member_id))
        company = CompanyFactory.create(self._database.get_company())

        member.change_billing_country(new_country, company)

        self._database.save_company(company)
        self._database.save_member(member)
        self._bus.send_billing_country_changed(member_id, new_country)
```

```python
class Member:
    def change_billing_country(self, new_country, company):
        if self.country == new_country:
            return

        new_kind = MemberKind.DOMESTIC if company.is_domestic(new_country) else MemberKind.INTERNATIONAL
        if self.kind != new_kind:
            company.change_domestic_count(1 if new_kind == MemberKind.DOMESTIC else -1)

        self.country = new_country
        self.kind = new_kind
```

`Member` is cleaner. It takes a `Company` and delegates two decisions to it. It now has one collaborator, `Company`, which moves it slightly to the right. It is a little less testable, not much.

The factories and both domain classes sit in the domain quadrant. The controller sits firmly in the controller quadrant. Its only job is gluing the parts together.

### Comparison with chapter 6

The shape matches the functional architecture of chapter 6. In both, the domain layer never talks to out of process dependencies. The application services fetch raw data, pass it to the domain model, and persist results.

The difference is side effects. The functional core has none. This domain model has some, a changed country and a changed count. They stay inside the domain model until the controller saves `Member` and `Company`.

Keeping all side effects in memory until the end helps testing a lot. Tests need no out of process dependencies and no communication-based checks. Output-based and state-based tests on in-memory objects cover everything.

## Optimal unit test coverage

| | Few collaborators | Many collaborators |
|---|---|---|
| High complexity or domain significance | `Member.change_billing_country`, `Company.change_domestic_count`, `Company.is_domestic`, `MemberFactory.create`, `CompanyFactory.create` | none |
| Low complexity and domain significance | constructors of `Member` and `Company` | `MemberController.change_billing_country` |

### The domain layer and utility code

Tests of the top-left quadrant give the best cost-benefit ratio.

```python
def test_moving_to_the_home_country_makes_a_member_domestic():
    company = Company(home_country="DE", domestic_count=1)
    sut = Member(1, "FR", MemberKind.INTERNATIONAL)

    sut.change_billing_country("DE", company)

    assert company.domestic_count == 2
    assert sut.country == "DE"
    assert sut.kind == MemberKind.DOMESTIC
```

Full coverage of `change_billing_country` takes three more tests.

1. Moving away from the home country.
2. Changing country without changing kind.
3. Changing to the same country.

Tests for the other three classes are shorter. Parameterization groups their cases.

```python
@pytest.mark.parametrize(
    ("country", "expected"),
    [("DE", True), ("FR", False)],
)
def test_classifies_a_country_as_domestic_or_not(country, expected):
    sut = Company(home_country="DE", domestic_count=0)

    assert sut.is_domestic(country) is expected
```

### The other three quadrants

The constructors of `Member` and `Company` are trivial. Tests of them protect too little to be worth the effort.

The refactoring removed all overcomplicated code, so that quadrant holds nothing to test.

Chapter 8 covers the controller quadrant.

### Preconditions

A precondition is a special kind of branch. `change_domestic_count` requires that the count never drops below zero. The check only fires in exceptional cases, which usually mean a bug. It lets the software fail fast and stops bad data from reaching the database, where it is much harder to fix.

The author's guideline is not a hard rule. Test preconditions that have domain significance. The non-negative count is one. It is part of the invariants of `Company`.

Skip preconditions without domain meaning. The row length check in `MemberFactory.create` is one. A test for it has little value.

## Conditional logic in controllers

The split between business logic and orchestration works best when an operation has three clean stages.

1. Read data from storage.
2. Run business logic.
3. Write data back.

Often the stages blur. The operation needs more data from an out of process dependency based on an intermediate decision. The write also often depends on that decision.

Chapter 6 listed the options. The chapter frames them as three choices.

1. Push all external reads and writes to the edges anyway. The read, decide, act structure holds. The controller calls out of process dependencies even when not needed.
2. Inject out of process dependencies into the domain model. The business logic decides when to call them.
3. Split the decision into more granular steps. The controller acts on each step.

The challenge is to balance three attributes.

1. Domain model testability, which depends on the number and kind of collaborators in domain classes.
2. Controller simplicity, which depends on decision points in the controller.
3. Performance, measured by the number of out of process calls.

Each option gives two of the three.

| Option | Keeps | Gives up |
|---|---|---|
| Push reads and writes to the edges | controller simplicity, domain testability | performance |
| Inject dependencies into the domain | performance, controller simplicity | domain testability |
| Split the decision into steps | performance, domain testability | controller simplicity |

In most projects performance matters, so option 1 is out. Option 2 puts most code back in the overcomplicated quadrant, the exact state the refactoring escaped. The author advises against it.

Option 3 remains. It makes controllers more complex and pushes them toward the overcomplicated quadrant. Two patterns keep that complexity in check. Rarely does all complexity leave the controller, but it stays manageable.

### The CanExecute/Execute pattern

A new rule. A member changes the billing country only until the first invoice goes out. After that, the member sees an error.

`Member` gets an `invoiced` flag. The check has two possible homes.

In `Member`, with the controller acting on the result.

```python
def change_billing_country(self, new_country, company):
    if self.invoiced:
        return "Billing country is locked after the first invoice"
    ...
```

```python
def change_billing_country(self, member_id, new_country):
    member = MemberFactory.create(self._database.get_member(member_id))
    company = CompanyFactory.create(self._database.get_company())

    error = member.change_billing_country(new_country, company)
    if error:
        return error

    self._database.save_company(company)
    self._database.save_member(member)
    self._bus.send_billing_country_changed(member_id, new_country)
    return "OK"
```

The controller makes no decisions. It loads `Company` on every call, even when the change will fail. That is option 1, with a performance cost.

The new `if` in the controller does not count as added complexity. It belongs to the acting phase. `Member` makes the decision, and the controller acts on it.

In the controller.

```python
def change_billing_country(self, member_id, new_country):
    member = MemberFactory.create(self._database.get_member(member_id))
    if member.invoiced:
        return "Billing country is locked after the first invoice"

    company = CompanyFactory.create(self._database.get_company())
    member.change_billing_country(new_country, company)
    ...
```

Performance holds, since `Company` loads only after the check. The decision now lives in two places. The controller decides whether to proceed. `Member` decides what the change does. A caller can now change the country without checking `invoiced`, which weakens encapsulation. This fragmentation moves the controller toward the overcomplicated zone.

The fix adds `can_change_billing_country` to `Member` and makes it a precondition of the change.

```python
def can_change_billing_country(self):
    if self.invoiced:
        return "Billing country is locked after the first invoice"
    return None


def change_billing_country(self, new_country, company):
    require(self.can_change_billing_country() is None)
    ...
```

Two gains follow.

1. The controller needs no knowledge of the rules. It calls `can_change_billing_country` and acts on the answer. That method can hold many checks, all hidden from the controller.
2. The precondition in `change_billing_country` guarantees that nobody changes the country without the check.

All decisions now live in the domain layer. The controller has no way to skip the check, so its decision point disappears in effect. It still holds an `if` around `can_change_billing_country`, but that `if` needs no test. The unit test of the precondition in `Member` is enough.

A real project uses a result type instead of a string for errors.

### Domain events

Sometimes the steps that led to the current state are hard to reconstruct. External systems still need to know exactly what happened. Tracking that in the controller adds complexity. Domain events track important changes in the domain model. The controller turns them into out of process calls after the operation.

A domain event describes something meaningful to domain experts. That meaning sets it apart from technical events such as button clicks. Applications often use domain events to tell other systems about important changes.

The billing example has a bug here. The controller sends a bus message even when the country did not change.

```python
def change_billing_country(self, new_country, company):
    require(self.can_change_billing_country() is None)
    if self.country == new_country:
        return
    ...
```

```python
    member.change_billing_country(new_country, company)
    self._database.save_company(company)
    self._database.save_member(member)
    self._bus.send_billing_country_changed(member_id, new_country)
```

Moving the sameness check into the controller fragments the logic. Moving it into `can_change_billing_country` is wrong, because a same-country request is not an error. This one check adds little fragmentation, and the author would not call the controller overcomplicated for it. In harder cases, avoiding needless out of process calls without passing those dependencies into the domain model is only possible with domain events.

A domain event is a class with the data other systems need.

```python
@dataclass(frozen=True)
class BillingCountryChanged:
    member_id: int
    new_country: str
```

Name events in the past tense, because they describe things that already happened. Events are values, immutable and interchangeable.

`Member` collects events as it changes.

```python
def change_billing_country(self, new_country, company):
    require(self.can_change_billing_country() is None)
    if self.country == new_country:
        return

    new_kind = MemberKind.DOMESTIC if company.is_domestic(new_country) else MemberKind.INTERNATIONAL
    if self.kind != new_kind:
        company.change_domestic_count(1 if new_kind == MemberKind.DOMESTIC else -1)

    self.country = new_country
    self.kind = new_kind
    self.events.append(BillingCountryChanged(self.member_id, new_country))
```

The controller turns events into bus messages.

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
    for event in member.events:
        self._bus.send_billing_country_changed(event.member_id, event.new_country)
    return "OK"
```

The controller still saves `Member` and `Company` every time. Persistence does not depend on events. The reason is the difference between database writes and bus messages.

Only this application touches its database. Communication with that database is not observable behavior. It is an implementation detail. As long as the final database state is right, the number of calls does not matter. The bus is different. Bus messages are observable behavior. To keep the contract with external systems, the application puts a message on the bus only when the country changes.

Saving unconditionally costs little. After all validations, a same-country request is rare. An ORM also skips the round trip when nothing changed.

The solution generalizes. A base `DomainEvent` class, a base class for domain objects that holds an event list, and a dispatcher that sends events instead of the controller doing it by hand. Large projects also need to merge events before dispatch. The book leaves that out of scope.

Domain events move the tracking decision from the controller into the domain model. A unit test checks event creation directly, with no mocks.

```python
def test_moving_away_from_the_home_country():
    company = Company(home_country="DE", domestic_count=1)
    sut = Member(1, "DE", MemberKind.DOMESTIC, invoiced=False)

    sut.change_billing_country("FR", company)

    assert company.domestic_count == 0
    assert sut.country == "FR"
    assert sut.kind == MemberKind.INTERNATIONAL
    assert sut.events == [BillingCountryChanged(1, "FR")]
```

The last assertion checks the size of the list and its content at once. The controller still needs a test that it orchestrates correctly. That takes far fewer tests, and chapter 8 covers them.

## Conclusion of the chapter

The common thread is abstracting how side effects reach external systems. Keep side effects in memory until the end of the operation, and plain unit tests cover them without out of process dependencies. Domain events abstract upcoming bus messages. Changes to domain objects abstract upcoming database writes.

Abstractions are easier to test than the things they abstract.

Some business logic fragmentation is unavoidable. Checking that a billing email is unique needs the database, so it cannot live in the domain model without an out of process dependency. Failures in out of process dependencies that change the course of the operation are another case. The domain layer does not call those dependencies, so it cannot decide how to react. That logic goes into controllers and gets integration tests. Separating business logic from orchestration still pays off, because it makes unit testing far easier.

Domain classes rarely lose all collaborators either. One, two, or three collaborators do not make a domain class overcomplicated, as long as none of them touches an out of process dependency.

Do not mock those in-domain collaborators. No client of the domain model sees the calls between them. Only the first call, from the controller to a domain class, links directly to the controller's goal. Later calls between domain classes in the same operation are implementation details.

Code is observable behavior if it meets one of two criteria.

1. It links directly to one of the client's goals.
2. It causes a side effect in an out of process dependency that external applications see.

The controller's `change_billing_country` meets the first criterion as the entry point. The bus call meets the second. Chapter 8 verifies both. The call from the controller to `Member` links to no goal of the external client. The client does not care how the controller implements the change, as long as the final state is right and the bus message goes out. Tests of the controller do not check its calls on `Member`.

One level down, the controller is the client. `Member.change_billing_country` links directly to the controller's goal and gets tests. The calls from `Member` to `Company` are implementation details from the controller's view. Tests of `Member` do not check them. The same reasoning applies one more level down, when testing `Company` from the view of `Member`.

The author describes it as peeling an onion. Test each layer from the view of the layer above it. Ignore how it talks to the layers below. Each peeled layer turns an implementation detail into observable behavior, covered by its own set of tests.

## Trade-offs the author names

1. Controller simplicity, domain testability, and performance form a triangle. Pick two.
2. Pushing reads to the edges keeps the design pure and costs performance.
3. Injecting dependencies into the domain keeps performance and ruins testability. The author rejects it.
4. Splitting decisions keeps performance and testability and adds controller logic. CanExecute/Execute and domain events keep that logic small.
5. Unconditional saves cost a little performance and keep persistence simple.

## ADW rules that apply

1. `hollow_test`. A test of a trivial constructor or property has near-zero value. Do not write it.
2. `hardcoded_name_presence`. Checking that a controller or factory class exists by name, instead of checking behavior, catches no regression.
3. `mocking_concrete_classes`. Do not mock `Company` to test `Member`. Use the real domain object.
4. The catalog entries `humble_object_pattern`, `can_execute_execute_pattern`, `domain_events_pattern`, and `code_quadrants_framework` come from this chapter.

## Rust note

Rust makes the humble split explicit through traits and ownership. A domain struct that takes `&mut Company` and returns nothing, or returns a `Result`, stays free of I/O. A `Vec<DomainEvent>` field collects events. The controller owns the database and bus handles and drains `member.events` after saving. `CanExecute` maps to a method returning `Result<(), ChangeError>`, and the precondition in the execute method becomes `debug_assert!` or an early `Err`.

```rust
#[test]
fn moving_away_from_the_home_country() {
    let mut company = Company::new("DE", 1);
    let mut member = Member::new(1, "DE", MemberKind::Domestic, false);

    member.change_billing_country("FR", &mut company).unwrap();

    assert_eq!(company.domestic_count(), 0);
    assert_eq!(member.events(), &[BillingCountryChanged::new(1, "FR")]);
}
```

## What the agent does with this chapter

1. Place the code under test in a quadrant before writing a test.
2. Unit test the domain model and algorithms thoroughly.
3. Skip trivial code. Leave controllers to integration tests.
4. When the code under test sits in the overcomplicated quadrant, report the Humble Object split instead of writing a mock-heavy test.
5. Test domain-significant preconditions. Skip technical ones.
6. Check domain events as values in unit tests, not through mocks.
