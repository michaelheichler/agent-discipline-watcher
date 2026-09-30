# Chapter 1. The goal of unit testing

Book pages 3 to 19.

## Core argument

Unit tests exist for one reason. They keep a project able to grow at a steady pace for years.

Better design is a side effect of testing. It is not the goal.

A suite full of weak tests does not reach the goal. It only delays the slowdown that a project without tests hits early.

## Why a project slows down

Every change to a code base adds a little disorder. The book calls this software entropy.

Without cleanup and refactoring, the disorder compounds. One fix breaks two other places. After a while, each new feature costs more hours than the last one.

Tests push back against this. They act as insurance against regressions.

A regression is a feature that stopped working after a change. In this skill, regression and bug mean the same thing.

Insurance lets the team refactor. Refactoring keeps disorder low. Low disorder keeps the pace steady.

## Tests are not free

Tests take effort up front. They pay back later, when the project grows and people change old code with confidence.

Tests are code. Code is a liability, not an asset. Every line adds surface for bugs and adds upkeep.

A test earns its place only when its value clearly beats its cost.

The cost of a test comes from four activities.

1. Changing the test when someone refactors the code under it.
2. Running the test on every change.
3. Chasing false alarms the test raises.
4. Reading the test to learn what the code does.

A test with a large cost and a small value has negative net worth. Deleting it improves the suite.

### Bad example. A test with near zero value and real cost

```python
def test_default_greeting_constant():
    assert greeter.DEFAULT_GREETING == "Hello"
```

This test catches no bug in any behavior. It breaks when a product owner changes the greeting to "Hi". Every such change now costs an extra edit. ADW flags this shape as `hardcoded_name_presence`.

### Good example. A test that pays for itself

```python
def test_greeting_uses_the_customer_first_name():
    customer = Customer(first_name="Ada", last_name="Lovelace")

    message = greeter.greet(customer)

    assert "Ada" in message
    assert "Lovelace" not in message
```

This test pins a rule the business cares about. It survives a change of wording. It fails when someone breaks the rule.

## Testability is a one-way signal

If a piece of code is hard to unit test, the design has a problem. The usual cause is tight coupling. The developer cannot pull two parts of the code apart.

The reverse does not hold. Code that is easy to test can still be a bad design.

Difficulty to test is a good negative indicator. Ease of test is a poor positive indicator.

## Coverage metrics

A coverage metric reports how much production code the suite executes, as a number between 0 and 100 percent.

### Code coverage

Code coverage, also called test coverage, divides the executed lines by all lines.

The number depends on layout, not on what the tests prove. Compressing a method into fewer lines raises the number without adding any check.

```python
def is_long(text):
    if len(text) > 5:
        return True
    return False


def test_short_text():
    assert is_long("abc") is False
```

The test skips one line, so line coverage is below 100 percent. Rewrite the body as `return len(text) > 5` and coverage jumps to 100 percent. The suite verifies exactly the same thing as before.

### Branch coverage

Branch coverage divides the executed branches by all branches. It counts control flow such as `if` and `match` arms.

It is more honest than line coverage, because code layout does not change it. The `is_long` function has two branches. The test above covers one, so branch coverage is 50 percent in both versions.

### Why neither metric measures quality

The author gives two reasons.

1. A metric cannot tell whether the test checked every outcome. It only sees that code ran.
2. A metric cannot see paths inside libraries that the code calls.

#### Outcomes the test never checks

Code often has more than one outcome. A return value is one. A changed field, a written file, or a sent message is another.

```python
class LengthChecker:
    def __init__(self):
        self.last_result = None

    def is_long(self, text):
        result = len(text) > 5
        self.last_result = result
        return result


def test_is_long_returns_false_for_short_text():
    checker = LengthChecker()
    assert checker.is_long("abc") is False
```

Coverage counts every line as covered. The test ignores `last_result`, the second outcome. A bug in that field goes unseen.

The extreme form is a test without any assertion. It runs code and checks nothing. It always passes and scores full coverage.

```python
def test_is_long_runs():
    checker = LengthChecker()
    checker.is_long("abc")
    checker.is_long("abcdef")
```

ADW flags a test with no real assertion as `hollow_test`.

The author tells a story from a real company. Management required 100 percent coverage and blocked any commit that lowered it. Developers answered by wrapping test bodies in try and except blocks with no asserts. The suite reached the target and protected nothing. The company later dropped the rule.

#### Paths hidden in libraries

```python
def parse_quantity(text):
    return int(text)


def test_parse_quantity():
    assert parse_quantity("5") == 5
```

Branch coverage reports 100 percent. The call to `int` still hides many paths. An empty string, the text "five", a value with spaces, and a huge number all behave in different ways. The metric sees none of them.

The author does not want metrics to count library paths. The point is that no number proves the suite is thorough.

### Coverage as a target

A coverage number works as an indicator. It fails as a goal.

The author compares it to a hospital patient with a fever. The temperature is a useful sign. A hospital that targets the number itself and cools the patient with an air conditioner misses the illness.

A mandatory coverage target creates the same perverse incentive. People write tests to move the number, not to protect behavior.

High coverage in the core of the system is good. Making it a hard requirement is bad.

Low coverage is a real warning. A number such as 60 percent means large parts of the code run under no test. High coverage alone tells you little.

ADW does not treat coverage as a goal. A test added only to cover lines, with no behavior check, is a `hollow_test`.

## Traits of a suite that pays off

The only reliable way to judge a suite is to judge each test on its own. No tool does this for you.

A successful suite has three properties.

1. It runs as part of the development cycle, ideally on every change.
2. It targets the most important parts of the code base.
3. It gives the most value for the least upkeep.

### Runs on every change

Tests that nobody runs have no value. The suite runs on every change, even small ones.

### Aims at the code that matters

The domain model holds the business logic. Tests of the domain model give the best return.

Three other kinds of code exist.

1. Infrastructure code.
2. External services and dependencies such as databases and third party systems.
3. Code that glues the parts together.

Some infrastructure code holds complex algorithms and deserves thorough tests. Most attention still goes to the domain model.

Integration tests cover the system as a whole, including the less critical parts. That is fine. The focus stays on the domain model.

To test the domain model on its own, the code has to keep it separate from other concerns. Chapter 7 shows how.

### Worth more than it costs

This property is the hardest one and the main subject of the book.

It has two skills inside it.

1. Recognizing a valuable test. This needs a frame of reference. Chapter 4 gives it.
2. Writing a valuable test. This also needs design skill, because a test and the code it covers are tightly linked.

Telling a good song from a bad one is easier than writing a good song. Judging a test is easier than writing one for the same reason.

## Trade-offs the author names

1. Tests cost effort now to save effort later. On a throwaway project, the trade does not pay.
2. Coverage helps as a warning and hurts as a target.
3. Unit testing all code evenly wastes effort. Focus on business logic.

## What the agent does with this chapter

1. Before writing a test, name the behavior it protects and the bug it catches.
2. Do not write a test to raise a coverage number.
3. Check every outcome of the code, not only the return value.
4. Do not pin a name, a greeting, a constant, or any literal that has no rule behind it.
5. Spend test effort on business logic first.
