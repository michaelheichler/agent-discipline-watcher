# Chapter 9. Mocking best practices

Book pages 216 to 228.

## Core argument

Chapter 5 defined a mock as a double that emulates and examines calls between the SUT and its dependencies. Chapter 8 limited mocks to unmanaged dependencies, whose interactions other applications observe. Any other use produces brittle tests. That one rule gets most of the way.

This chapter adds the rest. It shows how to get the most protection and the most resistance to refactoring out of the mocks that remain.

1. Verify interactions at the outer edge of the system.
2. Prefer spies over mocks at that edge.
3. Do not rely on production code in assertions.
4. Use mocks in integration tests only.
5. Do not limit the number of mocks per test.
6. Verify the number of calls.
7. Mock only types you own.

## Where the example stands

The billing controller from chapter 8 now delegates event handling to a dispatcher. Diagnostic logging is gone. Support logging stays behind a domain logger.

```python
class MemberController:
    def __init__(self, database, bus, domain_logger):
        self._database = database
        self._dispatcher = EventDispatcher(bus, domain_logger)

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


class EventDispatcher:
    def __init__(self, bus, domain_logger):
        self._bus = bus
        self._domain_logger = domain_logger

    def dispatch(self, events):
        for event in events:
            self._dispatch_one(event)

    def _dispatch_one(self, event):
        match event:
            case BillingCountryChanged(member_id, new_country):
                self._bus.send_billing_country_changed(member_id, new_country)
            case MemberKindChanged(member_id, old_kind, new_kind):
                self._domain_logger.member_kind_changed(member_id, old_kind, new_kind)
```

The integration test runs through every out of process dependency, managed and unmanaged.

```python
def test_moving_away_from_the_home_country():
    db = Database(TEST_CONNECTION_STRING)
    member = create_member(db, country="DE", kind=MemberKind.DOMESTIC)
    create_company(db, home_country="DE", domestic_count=1)
    bus = create_autospec(MessageBusProtocol, instance=True)
    domain_logger = create_autospec(DomainLoggerProtocol, instance=True)
    sut = MemberController(db, bus, domain_logger)

    result = sut.change_billing_country(member.member_id, "FR")

    assert result == "OK"
    ...
    bus.send_billing_country_changed.assert_called_once_with(member.member_id, "FR")
    domain_logger.member_kind_changed.assert_called_once_with(
        member.member_id, MemberKind.DOMESTIC, MemberKind.INTERNATIONAL
    )
```

It mocks two unmanaged dependencies, the message bus and the domain logger. The chapter starts with the bus.

## Verify interactions at the system edge

The author states the guideline as a tip. When mocking, verify interactions with unmanaged dependencies at the outer edge of the system.

The bus mock above misses this. `MessageBusProtocol` does not sit at the edge. Its implementation shows why.

```python
class MessageBus:
    def __init__(self, bus: Bus):
        self._bus = bus

    def send_billing_country_changed(self, member_id, new_country):
        self._bus.send(
            f"Type: BILLING COUNTRY CHANGED; Id: {member_id}; Country: {new_country}"
        )


class Bus(Protocol):
    def send(self, message: str) -> None: ...
```

Both types belong to the project. `Bus` wraps the SDK of the message bus vendor. It hides technical details such as connection credentials and offers one clean method that sends any text message. `MessageBus` wraps `Bus` and defines the messages specific to the domain. It keeps every application message in one place for reuse.

Merging the two is possible and worse. Hiding the vendor library and holding all application messages are two separate jobs. The same split appeared in chapter 8, where `DomainLogger` states business logging needs on top of a generic logger.

`Bus` is the last link in the chain from the controller to the bus. `MessageBus` is an intermediate step.

Mocking `Bus` instead of `MessageBus` gives the most protection. Protection grows with the amount of code a test runs. Mocking the last type before the unmanaged dependency makes the test pass through more classes. For the same reason, do not mock `EventDispatcher`. It sits even further from the edge.

```python
def test_moving_away_from_the_home_country():
    bus = create_autospec(Bus, instance=True)
    message_bus = MessageBus(bus)
    domain_logger = create_autospec(DomainLoggerProtocol, instance=True)
    sut = MemberController(db, message_bus, domain_logger)

    ...

    bus.send.assert_called_once_with(
        f"Type: BILLING COUNTRY CHANGED; Id: {member.member_id}; Country: FR"
    )
```

The test uses the concrete `MessageBus`, not its protocol. The protocol had one implementation, and chapter 8 named mocking as the only legitimate reason for such an interface. No test mocks it anymore, so delete it and use `MessageBus` directly.

The test now checks the text sent to the bus. Compare it with the earlier check.

```python
bus.send_billing_country_changed.assert_called_once_with(member.member_id, "FR")
```

Checking a call on a project class differs a lot from checking the text that reaches an external system. External systems expect text messages from the application. They do not expect calls to `MessageBus`. The text is the only side effect visible outside. The classes that build it are implementation details.

The gain is twofold. Protection rises, and resistance to refactoring rises too. Whatever refactoring happens inside, the test stays green as long as the message keeps its structure.

The same mechanism gives integration and end-to-end tests their edge over unit tests on resistance to refactoring. They sit further from the code base, so low-level refactoring touches them less.

The author adds a tip. A call to an unmanaged dependency passes through several stages before it leaves the application. Pick the last stage. It is the best way to guarantee backward compatibility with external systems, which is the whole purpose of mocks.

The catalog lists the violation as `asserting_interactions_not_at_system_edge`.

## Replace mocks with spies

A spy serves the same purpose as a mock. Developers write a spy by hand, while a framework generates a mock. People also call spies handwritten mocks.

For classes at the system edge, spies beat mocks. A spy lets tests reuse assertion code, which shortens tests and helps readability.

```python
class BusSpy:
    def __init__(self):
        self._sent = []

    def send(self, message):
        self._sent.append(message)

    def should_send_number_of_messages(self, count):
        assert len(self._sent) == count
        return self

    def with_billing_country_changed(self, member_id, new_country):
        expected = f"Type: BILLING COUNTRY CHANGED; Id: {member_id}; Country: {new_country}"
        assert expected in self._sent
        return self
```

```python
def test_moving_away_from_the_home_country():
    bus = BusSpy()
    message_bus = MessageBus(bus)
    domain_logger = create_autospec(DomainLoggerProtocol, instance=True)
    sut = MemberController(db, message_bus, domain_logger)

    ...

    bus.should_send_number_of_messages(1).with_billing_country_changed(member.member_id, "FR")
```

The bus check is short and expressive. The fluent interface chains several checks into something close to a plain English sentence.

The author suggests naming the spy `BusMock`. The difference between a mock and a spy is an implementation detail, and many programmers do not know the word spy.

### Is this a full circle

The spy version looks a lot like the earlier check on `MessageBus`.

```python
bus.send_billing_country_changed.assert_called_once_with(member.member_id, "FR")
```

Both `BusSpy` and `MessageBus` wrap `Bus`, so the checks look alike. The difference is where they live. `BusSpy` is test code. `MessageBus` is production code. Assertions do not rely on production code.

The author compares tests to auditors. A good auditor does not take the auditee's word. The auditor checks everything twice. The spy acts as an independent checkpoint and raises an alarm when the message structure changes. A mock on `MessageBus` trusts the production code too much.

### Literals in assertions

The summary of the chapter states the rule directly. Do not rely on production code in assertions. Use a separate set of literals and constants in tests. Duplicate them from production code if needed. Tests provide a checkpoint independent of production code. Otherwise they risk tautology, tests that verify nothing and hold meaningless assertions.

```python
def test_receipt_message_format():
    spy = BusSpy()

    MessageBus(spy).send_billing_country_changed(7, "FR")

    assert spy.sent == [MessageBus.format_billing_country_changed(7, "FR")]
```

This test compares the production formatter to itself. It passes for any format, including a broken one. ADW treats this as a `hollow_test`.

The rule and ADW's rule `hardcoded_literal_in_source` seem to pull in opposite directions. They do not. The deciding question is whether the literal is part of observable behavior.

1. The text on the bus is a contract with external systems. Pin it as a literal in the test. A change to it is a real break for other systems, and the test catches it.
2. A tuned setting with no contract behind it, such as a retry count or a UI label, is not observable behavior. Do not pin it. Test the rule that uses it.
3. A literal read out of a source file never belongs in a test. That test checks text, not behavior. ADW flags it as `hardcoded_literal_in_source`.

## What about the domain logger

The bus mock now targets `Bus` at the system edge. The logger check still targets `DomainLoggerProtocol`.

```python
bus.should_send_number_of_messages(1).with_billing_country_changed(member.member_id, "FR")

domain_logger.member_kind_changed.assert_called_once_with(
    member.member_id, MemberKind.DOMESTIC, MemberKind.INTERNATIONAL
)
```

`DomainLogger` wraps a generic logger the way `MessageBus` wraps `Bus`. The generic logger also sits at the application boundary. Should the test target it too?

In most projects, no. The logger and the bus both count as unmanaged dependencies and need backward compatibility. The required precision differs. For the bus, no change to message structure is acceptable, since nobody knows how external systems react. For text logs, the exact structure matters little to the audience, support staff and system administrators. What matters is that the entries exist and carry the right information. Mocking `DomainLogger` alone gives enough protection.

## More mocking best practices

The sections above cover the first two practices.

1. Apply mocks to unmanaged dependencies only.
2. Verify interactions with them at the outer edge of the system.

Three more follow.

### Mocks are for integration tests only

This follows from the split between business logic and orchestration in chapter 7. Code either talks to out of process dependencies or is complex, never both. The split yields two layers, the domain model for complexity and controllers for communication.

Tests of the domain model are unit tests. Tests of controllers are integration tests. Mocks apply only to unmanaged dependencies, and only controllers work with those. Mocks belong in integration tests of controllers and nowhere else.

A mock in a unit test signals one of two problems. A domain class talks to an out of process dependency, which chapter 7 says to split. Or the test mocks another domain class, which chapter 5 says couples the test to implementation details.

### More than one mock per test is fine

Some people advise one mock per test, on the theory that two mocks mean the test checks two things.

That idea comes from the misunderstanding covered in chapter 2, that a unit is a unit of code and each unit gets tested alone. A unit is a unit of behavior. The code behind one behavior spans several classes, one class, or a small method. The size does not matter.

The same holds for mocks. The number of mocks needed to verify one behavior does not matter. The billing test needs two, one for the bus and one for the logger. It could need more. The count depends only on how many unmanaged dependencies take part in the operation. The test author does not control it.

### Verify the number of calls

For unmanaged dependencies, check two things.

1. Expected calls happen.
2. Unexpected calls do not happen.

This also comes from backward compatibility. It runs both ways. The application does not drop messages external systems expect, and it does not send messages they do not expect.

Checking that a message went out is not enough.

```python
bus.send.assert_any_call(expected_message)
```

Also check that it went out exactly once.

```python
bus.send.assert_called_once_with(expected_message)
```

Most mocking libraries also check that no other calls happened on the mock. In Python, compare the full call list.

```python
assert bus.method_calls == [call.send(expected_message)]
```

`BusSpy` does the same. `should_send_number_of_messages(1)` covers both "exactly once" and "no other calls".

ADW flags a mock check that confirms a call happened but not how often, or not that nothing else happened, as `incomplete_mock_call_verification`.

### Mock only types you own

Steve Freeman and Nat Pryce introduced this rule. Wrap each third-party library in a thin adapter that you own, and point your mocks at the adapter instead of the library. Their arguments include these.

1. Developers often lack deep knowledge of how third-party code works.
2. Even when the library ships interfaces, mocking them is risky. The mock has to match what the library does, and nobody can be sure it does.
3. Adapters hide non-essential technical details of the library and define the relationship in the application's own terms.

The author agrees. Adapters act as an anti-corruption layer between the code and the outside world. They do three things.

1. Hide the complexity of the library.
2. Expose only the features the application needs.
3. Use the project's domain language.

`Bus` in the example is such an adapter. Even if the vendor SDK had a clean interface, a wrapper still pays off. Library upgrades change behavior in unknown ways. Without an adapter, an upgrade ripples through the whole code base. With one, the ripple stops at the adapter.

The rule does not apply to in-process dependencies. Mocks are for unmanaged dependencies only, so in-memory and managed dependencies need no abstraction for testing. A date and time library that reaches nothing outside the process is fine to use as is. An ORM that reaches a database no other application sees needs no wrapper either. A wrapper around any library is possible, but it rarely pays off outside unmanaged dependencies.

The catalog lists the rule as `mock_types_you_own` and its violation as `mocking_types_you_dont_own_violation`.

## Trade-offs the author names

1. Mocking the last type before the edge gives more protection and more resistance. It needs an adapter the team owns.
2. Checking exact message text catches every contract break. For logs, that precision is overkill, so a domain logger mock suffices.
3. Spies add a little test code. They make assertions reusable and independent of production code.
4. Duplicating literals in tests costs an edit when a contract changes on purpose. That edit is the point, because a contract change needs a deliberate decision.

## ADW rules that apply

1. `incomplete_mock_call_verification`. Check the exact count and the absence of other calls.
2. `mocking_concrete_classes`. Mock the protocol at the edge, or use a hand-written spy. Do not patch a concrete class.
3. `hollow_test`. An assertion that compares production output with the same production formatter proves nothing.
4. `hardcoded_literal_in_source`. Pin contract text as a literal. Never pin text read out of a source file.
5. The catalog entries `asserting_interactions_not_at_system_edge`, `mock_types_you_own`, and `mocking_types_you_dont_own_violation` come from this chapter.

## Rust note

A spy in Rust needs interior mutability, because the trait method usually takes `&self`. `RefCell<Vec<String>>` fits single-threaded tests. `Mutex<Vec<String>>` fits code that sends across threads. Put the edge trait in the project crate, not in the vendor crate, so the project owns what it mocks.

```rust
#[derive(Default)]
struct BusSpy {
    sent: RefCell<Vec<String>>,
}

impl Bus for BusSpy {
    fn send(&self, message: &str) {
        self.sent.borrow_mut().push(message.to_owned());
    }
}

#[test]
fn moving_away_from_the_home_country_sends_one_message() {
    let spy = BusSpy::default();

    MessageBus::new(&spy).send_billing_country_changed(7, "FR");

    assert_eq!(
        *spy.sent.borrow(),
        vec!["Type: BILLING COUNTRY CHANGED; Id: 7; Country: FR".to_owned()]
    );
}
```

The single `assert_eq!` on the whole vector checks the count, the content, and the absence of other messages at once.

## What the agent does with this chapter

1. Mock the last type before an unmanaged dependency. Never mock an intermediate wrapper or a dispatcher.
2. Prefer a small hand-written spy at the edge when several tests check the same messages.
3. Write expected contract text as literals in the test. Never compute the expected value with production code.
4. Use mocks only in integration tests of controllers. Never in unit tests of domain code.
5. Check the exact number of calls and that no other calls happened.
6. Mock only adapters the project owns. Never mock a vendor SDK type directly.
