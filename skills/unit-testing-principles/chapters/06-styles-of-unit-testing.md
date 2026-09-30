# Chapter 6. Styles of unit testing

Book pages 119 to 150.

## Core argument

Unit tests come in three styles.

1. Output-based. Feed input, check the return value.
2. State-based. Run an operation, check the state afterwards.
3. Communication-based. Replace collaborators with mocks, check the calls.

Output-based tests give the best quality. State-based tests come second. Use communication-based tests only now and then.

Output-based tests only work on code written in a functional way. The chapter shows how to move code toward a functional architecture so more tests take the output-based form. It also names the costs of that move.

## The three styles

One test can mix two or all three styles.

### Output-based

The test gives the SUT input and checks the output. It applies only to code that changes no global or internal state, so the return value is the only thing to check. People also call it the functional style, after functional programming, which prefers code without side effects.

```python
def shipping_discount(parcels):
    return min(len(parcels) * Decimal("0.02"), Decimal("0.10"))


def test_discount_for_three_parcels():
    parcels = [Parcel("a"), Parcel("b"), Parcel("c")]

    discount = shipping_discount(parcels)

    assert discount == Decimal("0.06")
```

The function adds 2 percent per parcel and caps the total at 10 percent. It stores nothing and writes nothing. Its only outcome is the value it returns.

A note on the literal. The test pins the rule "2 percent per parcel". If the business tunes the rate, the test changes with it, because the rate is the behavior. Chapter 11 draws the line between a rule and a tuned constant.

### State-based

The test checks the state of the system after the operation. The state belongs to the SUT, a collaborator, or an out of process dependency such as a database or the file system.

```python
class Playlist:
    def __init__(self):
        self._tracks = []

    @property
    def tracks(self):
        return tuple(self._tracks)

    def add(self, track):
        self._tracks.append(track)


def test_adding_a_track_to_a_playlist():
    track = Track("Blue in Green")
    sut = Playlist()

    sut.add(track)

    assert sut.tracks == (track,)
```

The outcome of `add` is a change in the playlist's state.

### Communication-based

The test uses mocks to check the calls between the SUT and its collaborators.

```python
def test_signup_sends_a_welcome_email():
    gateway = create_autospec(EmailGateway, instance=True)
    sut = SignupService(gateway)

    sut.sign_up("ada@example.com")

    gateway.send_welcome.assert_called_once_with("ada@example.com")
```

The classical school prefers state-based over communication-based. The London school prefers the reverse. Both use output-based tests.

## Comparing the styles on the four pillars

### Protection against regressions and fast feedback

Protection does not depend on the style. It depends on how much code runs, how complex it is, and how much it matters to the domain. Any style can exercise as much or as little code as needed.

One exception applies. Overusing communication-based tests produces shallow tests. They check a thin slice of code and mock everything else. Shallowness comes from abuse, not from the style itself.

Speed barely depends on style. As long as tests avoid out of process dependencies, all three run at roughly the same speed. Mocks add a little runtime cost. The difference shows only with tens of thousands of tests.

### Resistance to refactoring

Here the styles differ.

1. Output-based tests resist refactoring best. They couple only to the method under test. They couple to implementation details only if that method is itself an implementation detail.
2. State-based tests are more prone to false positives. They also touch the class's state. A larger surface of contact raises the chance of coupling to a leaked detail.
3. Communication-based tests are the most vulnerable. Chapter 5 showed that most tests that check interactions with doubles are brittle. Checking calls on stubs is always wrong. Mocks are fine only on calls that cross the application boundary with visible side effects.

Brittleness is not built into the communication style either. Good encapsulation and tests that target observable behavior keep false positives low. The amount of care needed differs by style.

### Maintainability

Here the styles differ a lot, and little helps the weaker ones. Maintainability has two parts.

1. How hard the test is to understand, which grows with size.
2. How hard the test is to run, which grows with the number of out of process dependencies it touches.

#### Output-based tests

They are the most maintainable. They are short. They boil down to "give input, check output", often two or three lines. The code under them changes no state, so they never touch out of process dependencies.

#### State-based tests

They are usually less maintainable, because state checks take more lines than output checks.

```python
def test_posting_a_review():
    sut = Product()
    posted_at = datetime(2026, 3, 1, 12, 0)

    sut.post_review("Works well", "ada", posted_at)

    assert len(sut.reviews) == 1
    assert sut.reviews[0].text == "Works well"
    assert sut.reviews[0].author == "ada"
    assert sut.reviews[0].posted_at == posted_at
```

This is a small case with one review, and the assert section already has four lines. Real state checks often grow much bigger.

Two techniques shrink them.

1. Helper assertion functions. They take effort to write and to maintain. They pay off only when many tests reuse them, which is rare. Part 3 of the book returns to them.
2. Value equality. Make `Review` a value object that compares by content.

```python
@dataclass(frozen=True)
class Review:
    text: str
    author: str
    posted_at: datetime


def test_posting_a_review():
    sut = Product()
    review = Review("Works well", "ada", datetime(2026, 3, 1, 12, 0))

    sut.post_review(review.text, review.author, review.posted_at)

    assert sut.reviews == [review]
```

Value equality works only when the class is a value by nature. Forcing equality onto a class that is not a value, only to shorten tests, is code pollution. Chapter 11 covers code pollution.

Both techniques apply only now and then. Even with them, state-based tests stay larger than output-based ones.

#### Communication-based tests

They score worst. Setting up doubles and interaction checks takes space. Mock chains make it worse. A mock chain is a mock or stub that returns another mock, which returns another, several levels deep.

### The results

| | Output-based | State-based | Communication-based |
|---|---|---|---|
| Care needed to keep resistance to refactoring | low | medium | medium |
| Maintenance cost | low | medium | high |

Always prefer output-based tests. The catch is that they need functional code, which object oriented code rarely is. The rest of the chapter shows how to get there.

## Functional architecture

### Functional programming

Functional programming is programming with mathematical functions, also called pure functions. A pure function has no hidden inputs or outputs. Its signature, meaning name, arguments, and return type, states every input and output. The same input always gives the same output, however many times it runs.

`shipping_discount` above is pure. It takes a list of parcels and returns a decimal. Nothing else goes in or out.

A mathematical function links two sets. Each element of the first set maps to one element of the second. The function `f(x) = x + 1` maps 1 to 2 and 2 to 3. The function `shipping_discount` maps each list of parcels to one discount.

Explicit inputs and outputs make pure functions highly testable. Their tests are short and easy to maintain. Output-based testing applies only to pure functions, and it has the best maintainability and the lowest false-positive rate.

Hidden inputs and outputs make code less testable and less readable. Three kinds exist.

1. Side effects. An output the signature does not state. Changing an object's state or writing a file are examples.
2. Exceptions. A thrown exception opens a path that skips the contract in the signature. Any caller up the stack catches it. It is an extra output the signature does not show.
3. References to internal or external state. Reading the current time, querying a database, or reading a private mutable field are inputs the signature does not show.

A quick check is referential transparency. Swap a call for its return value. If the program still behaves the same, the function is pure.

```python
def increment(x):
    return x + 1
```

`increment(4)` and `5` are interchangeable.

```python
counter = 0


def increment():
    global counter
    counter += 1
    return counter
```

Swapping a call to this `increment` for its result drops the change to `counter`. The return value does not cover all outputs.

Side effects are the most common hidden output. A method that looks pure often is not.

```python
def add_review(self, text):
    review = Review(text)
    self._reviews.append(review)
    return review
```

The signature says text in, review out. The append to `self._reviews` is a hidden second output.

### What functional architecture is

An application with no side effects at all is useless. Updating user data or adding an item to a cart are side effects. They are the reason the application exists.

Functional programming does not remove side effects. It separates code that holds business logic from code that causes side effects. Each responsibility is complex enough alone. Mixed, they multiply complexity and hurt maintainability.

Functional architecture maximizes the code written in a purely functional, immutable way and minimizes the code that deals with side effects. Immutable means an object cannot change after creation. It pushes side effects to the edges of a business operation.

It splits code into two kinds.

1. Code that makes a decision. It needs no side effects and uses pure functions. People call it the functional core or immutable core.
2. Code that acts on the decision. It turns decisions into visible changes such as database writes or bus messages. People call it the mutable shell.

The two cooperate in three steps.

1. The mutable shell gathers all inputs.
2. The functional core produces decisions.
3. The mutable shell turns decisions into side effects.

Keep the decision objects complete, so the shell acts on them without making further decisions. Keep the shell as dumb as possible. Cover the core with many output-based tests. Cover the shell with a few integration tests.

### Encapsulation and immutability

Functional architecture and immutability serve the same goal as unit testing, sustainable growth. Encapsulation and immutability connect closely.

Encapsulation protects internals from corruption in two ways. It shrinks the API that changes data, and it puts the remaining API under scrutiny.

Immutability attacks the same problem from another side. Nothing corrupts what cannot change. Validation happens once, when the object comes into existence. After that the object passes around freely. With all data immutable, the whole class of encapsulation issues disappears.

Michael Feathers put it like this. Object oriented programming makes code understandable by encapsulating moving parts. Functional programming makes code understandable by minimizing moving parts.

### Functional versus hexagonal

Both separate concerns. In hexagonal architecture, the domain layer owns business logic and the application services own communication with external systems such as a database or an SMTP service. That mirrors the split between decisions and actions.

Both have a one-way flow of dependencies. Domain classes depend only on each other. The immutable core does not depend on the mutable shell. The core stands alone. That is why functional architecture is so testable. A test strips away the shell and feeds the core plain values.

They differ in how they treat side effects. Functional architecture pushes all side effects out of the core. Hexagonal architecture allows side effects inside the domain layer, as long as they stay inside it. A domain object changes its own state but does not write to the database. An application service picks up the change and saves it.

Functional architecture is hexagonal architecture taken to the extreme.

## Moving toward functional architecture

### The starting point

A small system records sensor readings in plain text files. Each line holds a sensor id and a timestamp. When the newest file reaches a line limit, the system starts a new file with the next index.

```text
readings_1.txt
  probe-7;2026-03-01T08:00:00
  probe-2;2026-03-01T08:05:00
  probe-7;2026-03-01T08:10:00

readings_2.txt
  probe-4;2026-03-01T08:15:00
```

```python
class ReadingLog:
    def __init__(self, max_lines, directory):
        self._max_lines = max_lines
        self._directory = Path(directory)

    def record(self, sensor_id, taken_at):
        files = _sorted_by_index(self._directory.glob("readings_*.txt"))
        line = f"{sensor_id};{taken_at.isoformat()}"

        if not files:
            (self._directory / "readings_1.txt").write_text(line)
            return

        index, path = files[-1]
        lines = path.read_text().splitlines()
        if len(lines) < self._max_lines:
            path.write_text("\n".join([*lines, line]))
        else:
            (self._directory / f"readings_{index + 1}.txt").write_text(line)
```

`record` does all the work. It lists files, sorts them by index, creates the first file, or appends to the newest one, or opens the next one.

The class is hard to test. A test puts files in place, runs `record`, reads the files back, checks them, and cleans up.

The file system is a shared dependency, so tests interfere and cannot run in parallel without extra effort. It also makes them slow. Maintainability suffers, because the working directory has to exist on every developer machine and on the build server.

| | Initial version |
|---|---|
| Protection against regressions | good |
| Resistance to refactoring | good |
| Fast feedback | bad |
| Maintainability | bad |

These tests are integration tests by the chapter 2 definition. They fail the speed and isolation criteria.

### Step 1. Mock the file system

The usual fix extracts file operations behind an interface and injects it.

```python
class FileSystem(Protocol):
    def list_files(self, directory: str) -> list[str]: ...
    def read_lines(self, path: str) -> list[str]: ...
    def write_text(self, path: str, content: str) -> None: ...
```

```python
def test_a_new_file_starts_when_the_newest_file_is_full():
    fs = create_autospec(FileSystem, instance=True)
    fs.list_files.return_value = ["logs/readings_1.txt", "logs/readings_2.txt"]
    fs.read_lines.return_value = [
        "probe-7;2026-03-01T08:00:00",
        "probe-2;2026-03-01T08:05:00",
        "probe-7;2026-03-01T08:10:00",
    ]
    sut = ReadingLog(max_lines=3, directory="logs", file_system=fs)

    sut.record("probe-4", datetime(2026, 3, 1, 9, 0))

    fs.write_text.assert_called_once_with(
        "logs/readings_3.txt", "probe-4;2026-03-01T09:00:00"
    )
```

This is a legitimate use of a mock. The files are visible to end users, who read them with another tool. The writes and their effects are part of the observable behavior. Chapter 5 named that as the only legitimate use of mocks.

Tests run fast now, and nobody tends the file system. Protection and resistance stay the same.

| | Initial | With mocks |
|---|---|---|
| Protection against regressions | good | good |
| Resistance to refactoring | good | good |
| Fast feedback | bad | good |
| Maintainability | bad | moderate |

The setup is still convoluted. Mock libraries help, but the result reads worse than plain input and output.

### Step 2. Split into core and shell

Move the side effects out of `ReadingLog` entirely. `ReadingLog` only decides what to do with the files. A new `Persister` acts on the decision.

```python
@dataclass(frozen=True)
class FileContent:
    name: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class FileUpdate:
    name: str
    content: str


class ReadingLog:
    def __init__(self, max_lines):
        self._max_lines = max_lines

    def record(self, files, sensor_id, taken_at):
        ordered = _sorted_by_index(files)
        line = f"{sensor_id};{taken_at.isoformat()}"

        if not ordered:
            return FileUpdate("readings_1.txt", line)

        index, newest = ordered[-1]
        if len(newest.lines) < self._max_lines:
            return FileUpdate(newest.name, "\n".join([*newest.lines, line]))
        return FileUpdate(f"readings_{index + 1}.txt", line)
```

`ReadingLog` takes file contents instead of a directory path. It returns an instruction instead of writing files.

```python
class Persister:
    def read_directory(self, directory):
        return [
            FileContent(p.name, tuple(p.read_text().splitlines()))
            for p in Path(directory).glob("readings_*.txt")
        ]

    def apply(self, directory, update):
        (Path(directory) / update.name).write_text(update.content)
```

The persister reads the directory and applies updates. It has no branches. All complexity lives in `ReadingLog`. This is the split between business logic and side effects.

Keep `FileContent` and `FileUpdate` as close as possible to the built-in file operations. Do all parsing and preparation in the core, so the shell stays trivial. If the platform only offered "read the whole file as one string", `FileContent` would hold one string and the core would split it into lines.

An application service glues core and shell and gives external clients an entry point.

```python
class ReadingService:
    def __init__(self, directory, max_lines):
        self._directory = directory
        self._log = ReadingLog(max_lines)
        self._persister = Persister()

    def record(self, sensor_id, taken_at):
        files = self._persister.read_directory(self._directory)
        update = self._log.record(files, sensor_id, taken_at)
        self._persister.apply(self._directory, update)
```

In hexagonal terms, `ReadingService` and `Persister` belong to the application services layer. `ReadingLog` belongs to the domain.

Every test now supplies a hypothetical directory state and checks the decision.

```python
def test_a_new_file_starts_when_the_newest_file_is_full():
    sut = ReadingLog(max_lines=3)
    files = [
        FileContent("readings_1.txt", ()),
        FileContent("readings_2.txt", (
            "probe-7;2026-03-01T08:00:00",
            "probe-2;2026-03-01T08:05:00",
            "probe-7;2026-03-01T08:10:00",
        )),
    ]

    update = sut.record(files, "probe-4", datetime(2026, 3, 1, 9, 0))

    assert update == FileUpdate("readings_3.txt", "probe-4;2026-03-01T09:00:00")
```

The test keeps the speed gain and improves maintainability. It has no mock setup, only plain input and output.

| | Initial | With mocks | Output-based |
|---|---|---|---|
| Protection against regressions | good | good | good |
| Resistance to refactoring | good | good | good |
| Fast feedback | bad | good | good |
| Maintainability | bad | moderate | good |

The core always returns a value or a set of values. Two values with equal content are interchangeable. A frozen dataclass gives value equality in Python, so the test compares the whole update in one assertion. The book achieves the same in C# with a struct or custom equality members.

### Further growth

The sample has three branches and one use case. Two extensions show that the design scales.

1. Delete every line for one sensor. That touches several files, so the core returns a list of updates.
2. The business wants no empty files left behind. The update type grows into an action type with a kind, such as update or delete.

Error handling also gets simpler and more explicit. The core returns an error next to the update, or inside it. The application service checks the error. If one exists, it skips the persister and reports the error to the caller.

```python
def record(self, files, sensor_id, taken_at) -> tuple[FileUpdate | None, str | None]:
    ...
```

## Drawbacks of functional architecture

Functional architecture is not always possible. Even when it is, its maintainability gains often come with a performance cost and a larger code base.

### Applicability

The sample worked because the system gathered every input before deciding. Often the flow needs more data from an out of process dependency, based on an intermediate result.

Say the log also checks a sensor's calibration status when it reports more than a threshold of readings in the last hour. The calibration status lives in a database. Passing a database object into `ReadingLog.record` adds a hidden input. The method stops being a pure function, and output-based tests no longer apply.

Two options exist.

1. The application service reads the calibration status up front, along with the directory. This costs performance, because it queries the database even when the check is unnecessary. It keeps the separation intact. All decisions stay in `ReadingLog`.
2. `ReadingLog` gets a method such as `needs_calibration_check`. The service calls it first and fetches the status only when it returns true. This keeps performance and gives up some separation. The decision to call the database now lives in the service.

Making the domain model depend on the database directly is the one bad option. Chapters 7 and 8 explain how to balance performance against separation.

### Collaborators versus values

`ReadingLog.record` also depends on `self._max_lines`, which is not in the method signature. That is not a hidden input. The constructor signature shows it, and it never changes between construction and the call. It is a value.

A database object is different. It is a collaborator, a dependency that is mutable or a proxy to data not yet in memory. The database object is a proxy. It needs an out of process call and rules out output-based testing.

A class in the functional core works with the product of a collaborator's work, a value. It does not work with the collaborator.

### Performance

Critics of functional architecture point to performance. The tests do not get slower. The output-based tests run as fast as the mocked ones. The system itself makes more out of process calls. The first two versions of the reading log did not read every file. The final version reads all of them to follow the read, decide, act pattern.

Choosing functional architecture trades performance for maintainability of both production and test code. Where the performance impact is small, functional architecture wins. Elsewhere the opposite choice wins. No choice fits every system.

### Code base size

Functional architecture needs a clear split between core and shell. That means more code up front. In return it lowers complexity and raises maintainability over time.

Not every project has enough complexity to pay back the investment. Some code bases matter little to the business or are too simple. Apply functional architecture strategically, based on the complexity and importance of the system.

Do not chase purity at too high a cost. Most projects cannot make the domain model fully immutable, least of all in an object oriented language. Most suites end up with output-based and state-based tests plus a small number of communication-based ones. That is fine. The goal is to move as many tests as is reasonable to the output-based style, not all of them.

## Trade-offs the author names

1. Output-based tests need pure code. Pure code sometimes needs extra out of process calls, which costs performance.
2. Gathering inputs up front keeps the separation. Deciding when to fetch keeps performance. Each option gives up one.
3. Functional architecture adds code at the start. It pays off only in complex and important systems.
4. Helper assertions and value equality shorten state tests. Helpers cost effort. Value equality on a non-value class is code pollution.

## ADW rules that apply

1. `mocking_concrete_classes`. The file system double implements a protocol, not a concrete class.
2. `hollow_test`. A state-based test that only checks a count, and not the content, verifies too little.
3. `exposing_private_state_for_testing`. Do not make `_reviews` public to check it. Expose a read-only view that a real client needs, or test through output.

## Rust note

Rust pushes toward this design naturally. Ownership makes shared mutable state awkward. A core function that takes `&[FileContent]` and returns `FileUpdate` is easy to write and to test. `#[derive(PartialEq, Debug)]` gives value equality for one-line assertions.

```rust
#[derive(Debug, PartialEq)]
struct FileUpdate {
    name: String,
    content: String,
}

#[test]
fn a_new_file_starts_when_the_newest_file_is_full() {
    let log = ReadingLog::new(3);
    let files = vec![
        FileContent::new("readings_1.txt", &[]),
        FileContent::new("readings_2.txt", &["a;t1", "b;t2", "c;t3"]),
    ];

    let update = log.record(&files, "probe-4", at(9, 0));

    assert_eq!(update, FileUpdate::new("readings_3.txt", "probe-4;2026-03-01T09:00:00"));
}
```

## What the agent does with this chapter

1. Prefer an output-based test. If the code under test has side effects, report the split into core and shell as the better design.
2. Use state-based tests when the outcome is a state change. Compare whole values, not field by field.
3. Use communication-based tests only for calls that leave the application.
4. Do not add equality to a class only to shorten a test.
5. Do not chase purity where the performance cost is high. A few state-based tests are fine.
