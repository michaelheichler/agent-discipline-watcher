---
name: unit-testing-principles
description: Required reading for the adw-test-writer agent before it writes any test. Maps Khorikov's Unit Testing Principles, Practices, and Patterns to the ADW test rules, with a pre-write checklist and one chapter file per book chapter.
license: MIT
---

# Unit testing principles

This skill condenses Vladimir Khorikov's book "Unit Testing Principles, Practices, and Patterns" for an agent that writes tests. Every example and sentence in these files is original. The chapter files hold the full argument. This page holds the map, the checklist, and the rule index.

Read this page in full before you write a test. Open a chapter file when the checklist sends you there.

## The book in one page

### The goal

A test suite exists to keep a project growing at a steady pace. A test earns its place only when its value exceeds its upkeep. Coverage numbers measure nothing useful as a target. A suite with high coverage and weak assertions protects nobody. See chapter 1.

### The four pillars

Every test scores on four attributes.

1. Protection against regressions. The test fails when a real bug enters the code it exercises.
2. Resistance to refactoring. The test stays green when you restructure the code without changing its behavior.
3. Fast feedback. The test runs quickly.
4. Maintainability. A reader understands the test fast, and the test needs little setup to run.

### The value formula

The value of a test is the product of the four scores.

```text
value = protection * resistance * speed * maintainability
```

A zero on any pillar makes the whole test worthless. Resistance to refactoring is not negotiable, because a test that fails on every refactor trains the team to ignore failures. The real trade-off sits between protection and speed. Chapter 4 covers the pillars and the trade-off.

### Observable behavior versus implementation detail

A test must verify what the code does for its client, never how it does it. Observable behavior is an operation or a state that helps a client reach one of its goals. Everything else counts as an implementation detail. A test that pins an implementation detail breaks on refactors and produces false alarms. Chapter 5 explains the distinction and its link to mocks.

### The style ranking

Three styles exist, ranked by value.

1. Output based. Feed input, check the return value. This style gives the best resistance and the best maintainability. It needs pure functions.
2. State based. Act, then check the state of the system under test or its collaborators through the public API.
3. Communication based. Check the calls the code makes to its collaborators with mocks. Reserve this style for calls that cross the application boundary.

Prefer output based tests. Move code toward a functional core with a thin mutable shell to make that style possible. Chapter 6 covers the styles and functional architecture.

### The code quadrants

Two axes sort all production code. One axis is complexity or domain significance. The other is the number of collaborators.

| Quadrant | Complexity | Collaborators | What to do |
|---|---|---|---|
| Domain model and algorithms | High | Few | Unit test heavily. Highest return. |
| Trivial code | Low | Few | Do not test. |
| Controllers | Low | Many | Cover with a few integration tests. |
| Overcomplicated code | High | Many | Split it with the Humble Object pattern first. |

Chapter 7 shows how to move overcomplicated code into the domain and controller quadrants.

### When to write a test at all

Write a unit test for domain logic and algorithms. Write an integration test for each happy path through a controller, plus each edge case that no unit test reaches. Write no test for trivial code such as plain getters, data holders, and one line delegations. Write no test whose only content pins a name, a literal, or the presence of a symbol. Chapters 7 and 8 draw these lines.

### Dependencies and mocks

Managed dependencies belong to your application alone, for example its own database. Use the real one in integration tests. Unmanaged dependencies have observers outside your application, for example a message bus or an SMTP server. Mock those, and only at the outermost edge of your code. Chapters 8 and 9 cover mocks. Chapter 10 covers the database.

## Pre-write checklist

Run every step before you write a test. If a step fails, fix the plan before you write code.

### Decide whether the test earns its place

1. Name the behavior. Write one sentence that a domain expert understands. Put that sentence in the test name.
2. Name the bug. Describe one concrete regression that makes this test fail. If you cannot name one, do not write the test.
3. Place the code in a quadrant. Unit test domain code. Integration test controllers. Skip trivial code. Refactor overcomplicated code first.
4. Pick the style. Use output based if the code returns a value. Use state based if it changes state that a client can see. Use communication based only for calls to unmanaged dependencies.

### Shape the test

1. Check for pins. The test must not assert that a name exists, that a source file contains a string, or that a literal equals itself. Assert on behavior the name or literal produces.
2. Keep one act. Arrange, act, and assert once. A second act means a second test.
3. Keep the test straight. No `if` in the test body. No loop around an assertion. Use a parameterized test for several inputs.
4. Build fixtures with factory functions. Do not share mutable state through a test class constructor or a module level object.

### Respect the boundaries

1. Mock only at the edge. Mock an interface you own that wraps an unmanaged dependency. Never mock a concrete class. Never mock a managed dependency.
2. Verify mocks fully. Check the call count and the arguments of each mocked call. Confirm that no other calls happened.
3. Stay on the public API. Do not make a private method public to test it. Do not expose private state to assert on it. Test through the public caller instead.

### Prove the test works

1. Compute expected values independently. Do not copy the production algorithm into the test. Use precomputed results from the domain.
2. Make the test fail first. Break the production code on purpose and watch the test go red. A test that stays green with broken code is hollow.

## ADW rules and the book

ADW enforces several of these ideas as rules. The table names the chapter that explains each rule.

| ADW rule | Book idea | Chapter |
|---|---|---|
| `hollow_test` | A test with no protection against regressions | 4, 11 |
| `hardcoded_name_presence` | Pinning a name couples the test to an implementation detail | 1, 7, 11 |
| `hardcoded_literal_in_source` | Pinning a literal gives zero protection and zero resistance | 3, 11 |
| `assert_in_loop` | Hidden branching in a test, and one assertion hides the failing case | 3, 11 |
| `if_statements_in_tests` | A test with branches verifies more than one thing | 3 |
| `multiple_act_sections_in_unit_test` | Several behaviors in one unit test | 3 |
| `test_fixture_reuse_via_constructor` | Shared fixtures couple tests and hide the arrange section | 3 |
| `exposing_private_methods_for_testing` | Testing an implementation detail | 5, 11 |
| `exposing_private_state_for_testing` | State the client never sees counts as an implementation detail | 5, 11 |
| `mocking_concrete_classes` | A concrete mock signals a class with two jobs | 5, 9, 11 |
| `incomplete_mock_call_verification` | A partial check on an unmanaged call misses regressions | 8, 9 |

The names match the entries in `docs/research/2026-09-30-khorikov-test-catalog.md`. Two rules, `hollow_test` and `assert_in_loop`, go beyond the catalog. Chapter 11 scores both on the four pillars.

## Chapter files

### Part 1, the bigger picture

1. `chapters/01-the-goal-of-unit-testing.md` covers sustainable growth and coverage metrics.
2. `chapters/02-what-is-a-unit-test.md` covers the classical and London schools and the definition of a unit.
3. `chapters/03-the-anatomy-of-a-unit-test.md` covers AAA, fixtures, naming, and parameterized tests.

### Part 2, making tests work for you

1. `chapters/04-the-four-pillars.md` covers the pillars, the value formula, and the test pyramid.
2. `chapters/05-mocks-and-test-fragility.md` covers mocks, stubs, observable behavior, and hexagonal architecture.
3. `chapters/06-styles-of-unit-testing.md` covers the three styles and functional architecture.
4. `chapters/07-refactoring-toward-valuable-tests.md` covers the quadrants, Humble Object, and domain events.

### Part 3, integration testing

1. `chapters/08-why-integration-testing.md` covers integration tests, managed dependencies, and logging.
2. `chapters/09-mocking-best-practices.md` covers mocks at the edge, spies, and types you own.
3. `chapters/10-testing-the-database.md` covers migrations, transactions, cleanup, and repositories.

### Part 4, anti-patterns

1. `chapters/11-unit-testing-anti-patterns.md` covers private methods, private state, leaking knowledge, code pollution, concrete mocks, time, and the ADW rules beyond the book.
