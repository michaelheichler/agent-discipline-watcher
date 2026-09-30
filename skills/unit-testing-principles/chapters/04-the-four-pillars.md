# Chapter 4. The four pillars of a good unit test

Book pages 67 to 91.

## Core argument

Every automated test, whether unit, integration, or end-to-end, scores on four attributes.

1. Protection against regressions.
2. Resistance to refactoring.
3. Fast feedback.
4. Maintainability.

The value of a test is the product of the four scores. A zero on any one makes the whole test worthless.

No test maxes out the first three at once. Resistance to refactoring is not up for trade. Teams trade protection against speed.

This chapter is the frame of reference for every later chapter. Recognizing a valuable test comes before writing one.

## Pillar 1. Protection against regressions

This pillar measures how well a test finds bugs.

Bugs grow with features. More features mean more chances that a release breaks one of them. Code is a liability. A larger code base carries more exposure to bugs. Without protection, a team drowns in regressions and cannot sustain growth.

Three factors decide the score.

1. The amount of code the test executes.
2. The complexity of that code.
3. The domain significance of that code.

More executed code means a higher chance of catching a regression. This assumes real assertions. Running code without checking its outcome proves only that it throws no exception.

Complexity and domain significance matter as much as volume. A bug in business-critical logic costs more than a bug in boilerplate.

Trivial code rarely deserves a test. A one-line property leaves no room for a mistake.

```python
@dataclass
class Account:
    owner: str


def test_owner_round_trips():
    sut = Account(owner="Ada")

    assert sut.owner == "Ada"
```

This test verifies the dataclass machinery of Python, not a rule of the business.

Code the team did not write also counts. Libraries, frameworks, and external systems shape how the software works. The best protection includes them in the test scope, so the test checks the assumptions the code makes about them.

To maximize protection, a test exercises as much code as possible.

## Pillar 2. Resistance to refactoring

This pillar measures how well a test survives a refactoring without turning red.

Refactoring changes code without changing its observable behavior. Renaming a method or extracting a class are examples. The goal is better readability and lower complexity.

A false positive is a false alarm. The test fails, yet the feature works. False positives usually appear during refactoring, when the implementation changes and the behavior stays the same. The fewer false positives a test produces, the higher its score on this pillar.

### Why false positives do so much damage

Tests enable sustainable growth in two ways.

1. They warn early when a change breaks something. A fix before release costs far less than a fix in production.
2. They give confidence that a change does not break anything. Without confidence, developers avoid refactoring, and the code decays.

False positives attack both.

1. When tests fail for no reason, developers get used to red builds. They stop reacting, and real failures slip through with the noise.
2. When false positives are frequent, trust in the suite drops. Developers refactor less and change as little code as they can.

The author tells of a project a few years old whose direction had shifted. Nobody dared delete or refactor large chunks of old code, because some of it still served new features. Coverage was good. Every attempt to separate the old code broke many tests, old and new. Most failures were false alarms. The team started disabling failing tests. A real bug then reached production. One disabled test had caught it, and nobody looked. After that, the team stopped touching the old code at all.

This pattern is typical of projects with brittle tests. Developers first take failures seriously. They tire of tests that cry wolf. They ignore failures. Real bugs ship.

The fix is not to stop refactoring. The fix is to cut the brittleness of the suite. Chapter 7 shows how.

### Where false positives come from

A false positive comes from coupling between the test and the implementation details of the SUT. The more a test knows about how the SUT works, the more false alarms it raises.

The only defense is to decouple the test from those details. The test checks what the SUT hands back to its caller, which is its observable behavior, and ignores how the SUT got there. The test looks at the SUT from the point of view of its end user and checks only outcomes that matter to that user.

A good test tells a story about the problem domain. When it fails, the story and the behavior disagree. That is the only kind of failure worth having. It points straight at what went wrong. Every other failure is noise.

### Example. A test that inspects the algorithm

A report renderer composes a page from three part renderers.

```python
class ReportRenderer:
    def __init__(self):
        self.parts = [TitleRenderer(), BodyRenderer(), SignatureRenderer()]

    def render(self, report):
        return "".join(part.render(report) for part in self.parts)


class BodyRenderer:
    def render(self, report):
        return f"<p>{report.body}</p>"
```

A test that checks the structure of the renderer.

```python
def test_renderer_uses_the_right_parts():
    sut = ReportRenderer()

    parts = sut.parts

    assert len(parts) == 3
    assert isinstance(parts[0], TitleRenderer)
    assert isinstance(parts[1], BodyRenderer)
    assert isinstance(parts[2], SignatureRenderer)
```

This test assumes that the right parts in the right order imply the right output. Many harmless changes break it.

1. Replace `BodyRenderer` with a `ParagraphRenderer` that produces the same HTML.
2. Drop the part renderers and build the HTML inside `render`.
3. Reorder the list and adjust the join.

Each change keeps the output identical and turns the test red. The test demands one implementation and ignores equally valid ones.

A test coupled to implementation details fails both goals above. Its warnings get ignored, and it makes developers afraid to refactor.

### The extreme case. A test that reads source text

```python
from pathlib import Path


def test_renderer_is_implemented_correctly():
    source = Path("app/report_renderer.py").read_text()

    assert "self.parts = [TitleRenderer(), BodyRenderer(), SignatureRenderer()]" in source
```

The author calls this the most egregious brittle test he has seen. Any edit to the file breaks it, including reformatting. It is the same kind of test as the structural one above, only more fragile. Both insist on one implementation and ignore observable behavior.

ADW flags a test that reads source text and asserts on a literal inside it as `hardcoded_literal_in_source`. It never protects behavior.

### The fix. Test outcomes, not steps

The only outcome of the renderer that matters is the HTML. As long as the HTML stays the same, how the renderer builds it is irrelevant.

```python
def test_rendering_a_report():
    sut = ReportRenderer()
    report = Report(title="t", body="b", signature="s")

    html = sut.render(report)

    assert html == "<h1>t</h1><p>b</p><em>s</em>"
```

This test treats the renderer as a black box. It checks the one result that end users see, how the report looks in a browser. Any failure signals a change a customer notices.

It produces few false positives, not zero. Adding a parameter to `render` breaks it at compile or import time. That kind of false positive is cheap. The error points at every call site. The costly false positives are the silent ones that look like a real bug and take time to investigate.

## How the first two pillars connect

Both pillars serve the accuracy of the suite, from opposite sides.

| | Feature works | Feature broken |
|---|---|---|
| Test passes | correct inference (true negative) | type II error (false negative) |
| Test fails | type I error (false positive) | correct inference (true positive) |

1. Protection against regressions guards against false negatives, bugs the test misses.
2. Resistance to refactoring guards against false positives, alarms with no bug.

The terms come from statistics. A flu test helps. "Positive" means the condition the test looks for is present. It says nothing good about having flu. A flu test is accurate when both false results are rare.

Test accuracy has two parts.

1. How well the test signals the presence of bugs.
2. How well the test signals their absence.

The author frames this as a signal-to-noise ratio. Signal is the number of bugs found. Noise is the number of false alarms. Raise the signal or lower the noise to improve accuracy. A test that finds no bugs is useless even with zero noise. A test with heavy noise is useless even if it finds every bug, because its findings drown.

### The dynamics over time

Early in a project, false positives hurt less than false negatives. A wrong warning costs little compared with a missed bug in production.

As the project grows, false positives weigh more and more, until they matter as much as false negatives.

The reason is refactoring. A young code base needs little cleanup. The code is fresh in memory, so a developer refactors it even under false alarms. As the code decays, regular refactoring becomes necessary. Each refactoring then runs into the brittle tests. Trust in the suite drops.

Most developers focus only on protection. The author explains why. Most projects are small and end before they reach the later stages. Teams there meet missed bugs more often than false alarms. On a medium or large project, both deserve equal attention.

## Pillar 3. Fast feedback

Fast tests allow more tests and more frequent runs. With a short feedback loop, tests flag a bug the moment it appears, and the fix costs almost nothing. Slow tests delay feedback. Bugs stay hidden longer and cost more to fix. Slow tests also discourage frequent runs, so developers waste time going the wrong way.

## Pillar 4. Maintainability

This pillar measures upkeep. It has two parts.

1. How hard the test is to understand. Size drives this. Fewer lines read faster and change more easily. Do not compress lines artificially to hit a count. Test code deserves the same care as production code.
2. How hard the test is to run. A test that talks to out of process dependencies needs them alive. Someone restarts the database server and fixes network issues.

## The value formula

The value of a test is the product of its four scores, each between 0 and 1.

```text
value = protection * resistance * speed * maintainability
```

A zero anywhere makes the product zero. A valuable test scores at least something on all four.

No tool measures these scores precisely. A reviewer still estimates them with good accuracy and decides whether to keep the test.

All code, test code included, is a liability. Set a high bar for the minimum value and admit only tests that clear it. A small number of highly valuable tests sustains growth better than a large number of mediocre ones.

## The ideal test does not exist

An ideal test scores 1 on all four. The first three attributes exclude each other. Maximizing two sacrifices the third. The multiplication rule makes it worse. Dropping one to zero kills the test. The goal is to trade in a way that none of the three falls too low.

### End-to-end tests at one end

End-to-end tests run through the UI, the database, and external systems. They execute the most code, both the team's own and third party. They give the best protection.

They also resist refactoring well. A correct refactoring does not change observable behavior, and end-to-end tests see only behavior. They sit as far from implementation details as a test gets.

They run slow. A system that relies only on end-to-end tests gets slow feedback. For most teams that rules out an all end-to-end suite.

### Trivial tests at the other end

Trivial tests run fast and rarely raise false alarms. They catch almost no regressions, because the code under them leaves little room for a mistake. The `Account.owner` example above is one.

Taken to the extreme, trivial tests become tautologies. They always pass or assert something that means nothing.

```python
def test_discount_rate():
    rate = pricing.discount_rate()

    assert rate == pricing.discount_rate()
```

ADW treats a tautology as a `hollow_test`.

### Brittle tests as a third corner

Brittle tests run fast and catch regressions. They fail on refactoring, whether or not the behavior broke.

```python
def test_find_by_id_runs_the_right_sql():
    sut = UserRepository(connection)

    sut.find_by_id(5)

    assert sut.last_sql == "SELECT * FROM users WHERE user_id = 5"
```

This test catches a bug such as the wrong column name. It also fails on each of these equivalent queries.

```sql
SELECT * FROM users WHERE user_id = 5
SELECT * FROM public.users WHERE user_id = 5
SELECT user_id, name, email FROM users WHERE user_id = 5
SELECT * FROM users WHERE user_id = %(user_id)s
```

The test checks how the repository works instead of what it returns. It locks the implementation in place and blocks refactoring. ADW flags a pinned SQL string of this kind as `hardcoded_literal_in_source`.

### The results

Any two of the first three pillars are easy to max out. The third then falls toward zero, and so does the value.

Maintainability does not correlate with the first three, with one exception. End-to-end tests are larger and need live dependencies, so they cost more to maintain.

### Where to compromise

Conceding a little of each pillar sounds balanced. It does not work, because resistance to refactoring is binary in practice. A test either has it or does not. There are almost no stages in between.

Max out resistance to refactoring and maintainability. Protection and speed then share one slider. Moving toward one moves away from the other.

The author's tip follows from this. Removing brittleness, meaning false positives, is the first priority on the path to a robust suite.

The author compares this to the CAP theorem for distributed data stores. A store provides at most two of consistency, availability, and partition tolerance. Partition tolerance is not optional for a large system, because the data does not fit on one machine. Architects then trade consistency against availability, feature by feature. A product catalog tolerates slightly stale reads. A product description edit needs consistency to avoid conflicting writes. Tests work the same way. Resistance to refactoring plays the role of partition tolerance.

## The test pyramid

The pyramid recommends a ratio of test types. Many unit tests form the base. Fewer integration tests sit in the middle. The fewest end-to-end tests sit on top.

Width means count. Height means closeness to how a user acts. Each layer picks a different point on the slider between protection and speed. End-to-end tests favor protection. Unit tests favor speed. Integration tests sit between.

No layer gives up resistance to refactoring. Higher layers score higher on it only because they sit further from the code. Unit tests still aim for as few false positives as possible. Chapter 5 shows how.

End-to-end tests stay few because of the multiplication rule. They score low on speed and maintainability. Keep them for the most critical features, where no bug is acceptable, and only when unit and integration tests cannot give the same protection.

### When the pyramid does not fit

1. A plain CRUD application with few business rules. Unit tests turn trivial. Integration tests keep their value, because even simple code has to work with the database. The pyramid becomes a rectangle, or has more integration tests than unit tests.
2. An API with one out of process dependency, such as a database, and no UI. End-to-end tests run fast and cost little, since only one dependency needs care. They differ from integration tests only in the entry point. An end-to-end test hosts the application like a real user reaches it. An integration test hosts it in the same process.

Chapter 8 returns to the pyramid.

## Black-box and white-box testing

1. Black-box testing checks a system without knowledge of its internals. It builds on requirements, meaning what the system does, not how.
2. White-box testing checks the internals. Tests derive from the source code.

| | Protection against regressions | Resistance to refactoring |
|---|---|---|
| White-box | good | bad |
| Black-box | bad | good |

White-box tests are thorough and find errors a spec misses. They couple to the implementation and produce false positives. They also rarely trace back to a behavior a business person cares about, which signals low value.

Resistance to refactoring is not up for trade. The default is black-box testing, for unit, integration, and end-to-end tests alike. A test that does not trace back to a business requirement is brittle. Restructure it or delete it. Do not let it into the suite as is.

The one exception is utility code with high algorithmic complexity. Chapter 7 covers it.

White-box methods still help when analyzing tests. Use a coverage tool to find branches no test exercises. Then write the missing tests as if nothing were known about the internals.

## Trade-offs the author names

1. Protection, resistance, and speed exclude each other. Pick two.
2. Resistance to refactoring is not negotiable, because it is binary.
3. The remaining slider runs between protection and speed. The pyramid spreads tests across it.
4. False positives matter little early and as much as missed bugs later.

## ADW rules that apply

1. `hardcoded_literal_in_source`. A test that reads source text, or pins an SQL string, verifies steps, not results.
2. `hollow_test`. A tautology or a trivial round trip scores near zero on protection.
3. `exposing_private_state_for_testing`. Reading an internal list such as `sut.parts` couples the test to the algorithm. Chapter 11 covers it.

## Rust note

In Rust, the structural test often needs a `pub` field or a `#[cfg(test)]` accessor to reach the parts list. Either one leaks an implementation detail into the API. Test the rendered string instead. `include_str!` on a source file inside a test is the Rust form of the source-reading test. Never write it.

```rust
#[test]
fn rendering_a_report() {
    let report = Report::new("t", "b", "s");

    let html = ReportRenderer::default().render(&report);

    assert_eq!(html, "<h1>t</h1><p>b</p><em>s</em>");
}
```

## What the agent does with this chapter

1. Score the planned test on all four pillars before writing it. Drop it if any score is near zero.
2. Assert on the end result a user or caller sees. Never assert on the steps.
3. Never read source files, SQL text, or internal lists to check structure.
4. Prefer black-box tests. Use coverage only to find missing cases.
5. Keep the test short without compressing it.
