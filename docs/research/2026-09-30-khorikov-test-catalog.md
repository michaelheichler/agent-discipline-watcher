# Unit testing principles and anti-patterns catalog

Source. *Unit Testing Principles, Practices, and Patterns* by Vladimir Khorikov (Manning, 2020).

Page numbers below are PDF page numbers from the extracted copy of the book, not printed page numbers.

## Entry table

| # | id | detection class | pillar |
|---|----|----|----|
| 1 | four_pillars_and_tradeoff | STATIC | all four pillars |
| 2 | observable_behavior_vs_implementation_detail | SEMANTIC | resistance to refactoring |
| 3 | output_based_testing_style | SEMANTIC | resistance to refactoring, maintainability |
| 4 | state_based_testing_style | SEMANTIC | protection against regressions |
| 5 | communication_based_testing_style | SEMANTIC | resistance to refactoring (at risk) |
| 6 | code_quadrants_framework | CONTEXT | protection against regressions, maintainability |
| 7 | humble_object_pattern | CONTEXT | maintainability, fast feedback |
| 8 | test_pyramid | CONTEXT | all four pillars |
| 9 | fail_fast_principle | CONTEXT | protection against regressions |
| 10 | can_execute_execute_pattern | CONTEXT | maintainability, resistance to refactoring |
| 11 | domain_events_pattern | CONTEXT | maintainability, fast feedback |
| 12 | mocks_vs_stubs_definition | STATIC | resistance to refactoring |
| 13 | managed_vs_unmanaged_dependencies | CONTEXT | resistance to refactoring |
| 14 | mock_types_you_own | SEMANTIC | resistance to refactoring, maintainability |
| 15 | aaa_pattern | STATIC | maintainability |
| 16 | test_naming_guideline | SEMANTIC | maintainability |
| 17 | parameterized_tests | STATIC | maintainability |
| 18 | logging_test_guideline | CONTEXT | resistance to refactoring |
| 19 | assertion_free_test | STATIC | protection against regressions |
| 20 | coverage_metric_as_goal | CONTEXT | protection against regressions |
| 21 | tautology_test | SEMANTIC | protection against regressions |
| 22 | testing_trivial_code | CONTEXT | maintainability |
| 23 | overcomplicated_code_untested | CONTEXT | protection against regressions, maintainability |
| 24 | brittle_test_source_string_comparison | SEMANTIC | resistance to refactoring |
| 25 | overspecification_asserting_interactions_with_stubs | SEMANTIC | resistance to refactoring |
| 26 | mocking_managed_dependency | SEMANTIC | resistance to refactoring |
| 27 | mock_chains | SEMANTIC | maintainability |
| 28 | unnecessary_interface_single_implementation | CONTEXT | maintainability |
| 29 | multiple_act_sections_in_unit_test | STATIC | maintainability |
| 30 | if_statements_in_tests | STATIC | maintainability |
| 31 | test_fixture_reuse_via_constructor | STATIC | maintainability |
| 32 | large_arrange_section | SEMANTIC | maintainability |
| 33 | asserting_interactions_not_at_system_edge | CONTEXT | resistance to refactoring, protection against regressions |
| 34 | incomplete_mock_call_verification | STATIC | protection against regressions |
| 35 | mocking_types_you_dont_own_violation | SEMANTIC | resistance to refactoring |
| 36 | testing_repositories_directly | CONTEXT | maintainability |
| 37 | in_memory_database_substitute | CONTEXT | protection against regressions |
| 38 | reusing_database_context_across_sections | STATIC | protection against regressions |
| 39 | model_database_anti_pattern | CONTEXT | maintainability |
| 40 | wrapping_test_in_uncommitted_transaction | SEMANTIC | protection against regressions |
| 41 | circular_dependencies | CONTEXT | maintainability |
| 42 | excessive_layers_of_indirection | CONTEXT | maintainability |
| 43 | exposing_private_methods_for_testing | STATIC | resistance to refactoring |
| 44 | exposing_private_state_for_testing | STATIC | resistance to refactoring |
| 45 | leaking_domain_knowledge_to_tests | SEMANTIC | resistance to refactoring |
| 46 | code_pollution | CONTEXT | maintainability |
| 47 | mocking_concrete_classes | STATIC | maintainability |
| 48 | time_as_ambient_context | STATIC | maintainability, fast feedback |
| 49 | hardcoded_name_presence (user rule) | SEMANTIC | protection against regressions |
| 50 | hardcoded_literal_in_source (user rule) | STATIC | protection against regressions |

## Entries

### 1. four_pillars_and_tradeoff

**Definition**.
A good unit test scores well on four metrics at once. Protection against regressions means the test catches bugs. If you change implementation without changing behavior, resistance to refactoring means the test still passes. Fast feedback means the test runs in a short time. Maintainability means the test costs little to read and to keep working. No test scores at the top on all four. Every test design choice trades one metric against another.

**Book reference**.
Chapter 4, "The four pillars of a good unit test," pages 90 to 96.

**Pillar**.
Serves all four pillars as a framework. It also states the trade-off between them.

**Detection class**.
STATIC. A tool can score a test's mock count, assertion count, and dependency count. Then the tool flags a test that scores zero on any one metric.

**Detection signal**.
The test has zero assertions. The test checks internal call order or private state. The test calls a real network service. The test's arrange section is bigger than its act and assert sections combined.

**Violating example**.
```csharp
[Fact]
public void Test1()
{
    var sut = new Calculator();
    sut.Add(1, 2);
    // no assertion at all
}
```

**Clean example**.
```csharp
[Fact]
public void Adding_two_numbers()
{
    var sut = new Calculator();
    int result = sut.Add(1, 2);
    Assert.Equal(3, result);
}
```

### 2. observable_behavior_vs_implementation_detail

**Definition**.
Observable behavior is what a class exposes to reach a client's goal, or to produce a side effect visible outside the application. An implementation detail is everything else. A well-designed API exposes observable behavior only and hides implementation details. A test must check observable behavior only.

**Book reference**.
Chapter 5, "Observable behavior versus implementation detail," pages 122 to 129.

**Pillar**.
If violated, this hurts resistance to refactoring. A test that checks an implementation detail breaks on any internal rewrite. It breaks even though the behavior is still correct.

**Detection class**.
SEMANTIC. A judgment on whether a checked member is a client goal or a side detail needs the calling context, not only a pattern match.

**Detection signal**.
A test checks a private field made public only for the test. A second sign is a test that checks a call between two in-process collaborators instead of the final result.

**Violating example**.
```csharp
// User.NormalizeName is a private helper.
// Made public only so the test can call it directly.
Assert.Equal("john", user.NormalizeName("John"));
```

**Clean example**.
```csharp
user.Rename("John");
Assert.Equal("john", user.NormalizedName);
```

### 3. output_based_testing_style

**Definition**.
Output-based testing feeds an input to a piece of code and checks the returned output. It works only on code with no hidden state and no side effects, a functional core. Of the three testing styles in the book, this one gives the best resistance to refactoring and the best maintainability.

**Book reference**.
Chapter 6, "Styles of unit testing," pages 145 to 149.

**Pillar**.
Serves resistance to refactoring and maintainability.

**Detection class**.
SEMANTIC. Telling an output-based test apart from a state-based test needs to see whether the assertion checks a return value or a mutated object.

**Detection signal**.
The test calls a pure function and checks only its return value, with no setup of mutable collaborators.

**Violating example (state-based, for contrast).**
```csharp
var holder = new PriceHolder();
holder.SetTaxRate(0.1);
holder.Apply(100);
Assert.Equal(110, holder.Price);
```

**Clean example**.
```csharp
decimal result = PriceCalculator.ApplyTax(100, 0.1);
Assert.Equal(110, result);
```

### 4. state_based_testing_style

**Definition**.
State-based testing checks the final state of the system under test, or of one of its collaborators, after the act step. If the code has state but no out-of-process side effects, this style works well. It gives good protection against regressions, but it costs more to maintain than output-based tests.

**Book reference**.
Chapter 6, "Styles of unit testing," pages 149 to 151.

**Pillar**.
Serves protection against regressions. Costs more maintainability than output-based testing.

**Detection class**.
SEMANTIC. This needs to know whether the checked value came from a mutated object or from a pure return value.

**Detection signal**.
The test creates an object, calls a mutating method on it, then reads a property of that same object in the assert step.

**Violating example (a legitimate style, contrast with entry 3).**
```csharp
var order = new Order();
order.AddProduct(product, quantity: 2);
Assert.Equal(3, order.GetProduct(product).Quantity);
```

**Clean example**.
```csharp
var order = new Order();
order.AddProduct(product, quantity: 2);
Assert.Equal(2, order.GetProduct(product).Quantity);
```

### 5. communication_based_testing_style

**Definition**.
Communication-based testing uses mocks to check calls that the system under test makes to its collaborators. Of the three styles, this one gives the worst resistance to refactoring and the worst maintainability. It couples a test to how the code talks to its neighbors, not to what the code produces.

**Book reference**.
Chapter 6, "Styles of unit testing," pages 151 to 153.

**Pillar**.
Puts resistance to refactoring at risk. Use this style only for calls that cross into an unmanaged, out-of-process dependency.

**Detection class**.
SEMANTIC. This needs to know whether the mocked dependency is in-process, managed, or unmanaged. That fact decides whether the test is sound or brittle.

**Detection signal**.
A test builds a mock and calls `Verify` on a method of an in-process collaborator.

**Violating example**.
```csharp
var storeMock = new Mock<IStore>();
var sut = new Customer();
sut.Purchase(storeMock.Object, product, 1);
storeMock.Verify(x => x.RemoveInventory(product, 1), Times.Once);
```

**Clean example**.
```csharp
var emailGatewayMock = new Mock<IEmailGateway>();
var sut = new CustomerController(emailGatewayMock.Object);
sut.SendGreetingsEmail(customer);
emailGatewayMock.Verify(x => x.SendGreetingsEmail(customer.Email), Times.Once);
```

### 6. code_quadrants_framework

**Definition**.
Production code sorts into four types along two axes. One axis is complexity or domain significance. The other axis is the number of collaborators. The domain model and algorithms type has high significance and few collaborators. Trivial code has low significance and few collaborators. Controllers have low significance and many collaborators. Overcomplicated code has high significance and many collaborators. Only the domain model and algorithms type gives a strong return on unit testing.

**Book reference**.
Chapter 7, "Identifying the code to refactor," pages 152 to 157.

**Pillar**.
Serves protection against regressions in the domain quadrant, where testing pays off. Serves maintainability by naming the quadrants where testing does not pay off.

**Detection class**.
CONTEXT. Placing a class in a quadrant needs the whole class graph, the collaborator count, and a judgment of domain significance. A single file is not enough.

**Detection signal**.
A unit test with a long arrange section builds several out-of-process collaborators around a class that has a one-line constructor.

**Violating example**.
```csharp
// A trivial constructor does not deserve a test.
[Fact]
public void User_constructor_sets_fields()
{
    var user = new User(1, "a@b.com", UserType.Customer);
    Assert.Equal(1, user.UserId);
}
```

**Clean example**.
```csharp
[Fact]
public void Changing_email_from_non_corporate_to_corporate()
{
    var company = new Company("mycorp.com", 1);
    var sut = new User(1, "user@gmail.com", UserType.Customer);
    sut.ChangeEmail("new@mycorp.com", company);
    Assert.Equal(UserType.Employee, sut.Type);
}
```

### 7. humble_object_pattern

**Definition**.
The Humble Object pattern splits a class that mixes business logic with a dependency that is hard to test. It pulls the logic out into a plain class with no dependencies. What remains is a thin wrapper that only coordinates calls, so it needs no test.

**Book reference**.
Chapter 7, "Using the Humble Object pattern to split overcomplicated code," pages 178 to 186.

**Pillar**.
Serves maintainability and fast feedback. It turns overcomplicated code into a testable domain class and an untested thin wrapper.

**Detection class**.
CONTEXT. A tool must see both the wrapper class and the class it calls. If the logic did not move out of the wrapper, the split does not count.

**Detection signal**.
A constructor or a controller method with many branches calls a plain class with no external dependencies, right next to it.

**Violating example**.
```csharp
public class OrderController
{
    public void Ship(Order order)
    {
        if (order.Items.Count == 0) throw new Exception("Empty order");
        var cost = order.Items.Sum(i => i.Price) * 1.1m; // tax logic buried here
        _smtp.Send(order.CustomerEmail, "Shipped", cost.ToString());
    }
}
```

**Clean example**.
```csharp
public class ShippingCalculator // plain, testable, no dependencies
{
    public decimal CalculateCost(Order order) => order.Items.Sum(i => i.Price) * 1.1m;
}

public class OrderController // humble, not tested directly
{
    public void Ship(Order order)
    {
        var cost = _calculator.CalculateCost(order);
        _smtp.Send(order.CustomerEmail, "Shipped", cost.ToString());
    }
}
```

### 8. test_pyramid

**Definition**.
The Test Pyramid states that a good test suite needs many fast unit tests, fewer integration tests, and few end-to-end tests. Each layer trades speed for confidence. Business complexity, not a fixed ratio, decides the right shape for one project.

**Book reference**.
Chapter 4, "Exploring well-known test automation concepts," pages 110 to 113.

**Pillar**.
Serves all four pillars, because it balances speed against protection across a whole suite, not inside one test.

**Detection class**.
CONTEXT. Counting a project's real ratio of unit, integration, and end-to-end tests needs the whole test suite, not a single file.

**Detection signal**.
A suite with almost no unit tests and a large share of slow end-to-end tests, or the same imbalance in the other direction.

**Violating example**.
```csharp
// 2 unit tests, 40 end-to-end tests driving a browser, for a system
// with rich business rules and a simple UI.
```

**Clean example**.
```csharp
// 200 unit tests around the domain model, 30 integration tests around
// the database, 5 end-to-end tests for the critical user paths.
```

### 9. fail_fast_principle

**Definition**.
The Fail Fast principle states that code must stop the current operation as soon as it finds an unexpected state. A precondition check that throws right away is one form of this rule. It turns a silent bug into a loud, quick failure.

**Book reference**.
Chapter 8, "Integration testing vs. failing fast," pages 211 to 213.

**Pillar**.
Serves protection against regressions, because a loud failure surfaces close to its cause, not far downstream.

**Detection class**.
CONTEXT. Deciding whether a check belongs at this boundary needs the call chain around it, not the single line.

**Detection signal**.
A method keeps running after it reads an invalid argument or a null reference, instead of throwing right away.

**Violating example**.
```csharp
public void SetName(string name)
{
    _name = name; // null or empty name silently accepted
}
```

**Clean example**.
```csharp
public void SetName(string name)
{
    if (string.IsNullOrWhiteSpace(name))
        throw new ArgumentException("Name cannot be empty");
    _name = name;
}
```

### 10. can_execute_execute_pattern

**Definition**.
The CanExecute/Execute pattern splits a controller action into two methods. CanExecute checks whether the current state allows the action, and returns a result with no side effect. If CanExecute said yes, Execute runs the action.

**Book reference**.
Chapter 7, "Using the CanExecute/Execute pattern," pages 194 to 199.

**Pillar**.
Serves maintainability and resistance to refactoring, because CanExecute becomes a pure, easy output-based test.

**Detection class**.
CONTEXT. Spotting the pattern needs both methods and the call between them, not one method read alone.

**Detection signal**.
A controller method mixes validation branches and a side-effecting action in one block, with no separate check method.

**Violating example**.
```csharp
public void ChangeEmail(User user, string newEmail, Company company)
{
    if (user.IsEmailConfirmed) throw new Exception("Cannot change");
    user.Email = newEmail; // validation and action mixed together
}
```

**Clean example**.
```csharp
public bool CanChangeEmail(User user) => !user.IsEmailConfirmed;

public void ChangeEmail(User user, string newEmail)
{
    user.Email = newEmail;
}
```

### 11. domain_events_pattern

**Definition**.
The Domain Events pattern records what happened inside an object as a list of event objects, instead of hiding the change in mutable state alone. A test can then check the event list with a plain output-based assertion.

**Book reference**.
Chapter 7, "Using domain events to track changes in the domain model," pages 197 to 206.

**Pillar**.
Serves resistance to refactoring, because it turns a state change that is hard to observe into an output a test can check.

**Detection class**.
CONTEXT. Judging whether an event list fits needs the domain class design, not a single test file.

**Detection signal**.
A test reads several private fields to check a change happened, instead of reading one event object that gives the same answer.

**Violating example**.
```csharp
sut.ChangeEmail("new@mycorp.com", company);
Assert.Equal(UserType.Employee, sut.Type); // one field, easy to miss others
```

**Clean example**.
```csharp
sut.ChangeEmail("new@mycorp.com", company);
var event1 = (EmailChangedEvent)sut.DomainEvents.Single();
Assert.Equal(user.Id, event1.UserId);
```

### 12. mocks_vs_stubs_definition

**Definition**.
A stub feeds a canned answer to the system under test. A mock records a call the system under test makes outward, so a test can check that the call happened. Only a mock, not a stub, deserves a check in the assert section.

**Book reference**.
Chapter 5, "Differentiating mocks from stubs," pages 114 to 121.

**Pillar**.
Serves resistance to refactoring, because treating a stub like a mock adds a check that breaks on harmless refactors.

**Detection class**.
STATIC. A tool can pattern-match a call like `Verify` on a test double that only ever fed input.

**Detection signal**.
A test builds a test double, uses it only to feed input, then still calls `Verify` on it.

**Violating example**.
```csharp
var loggerStub = new Mock<ILogger>();
sut.Process(loggerStub.Object);
loggerStub.Verify(x => x.Log(It.IsAny<string>())); // stub, checked like a mock
```

**Clean example**.
```csharp
var loggerStub = new Mock<ILogger>();
var result = sut.Process(loggerStub.Object);
Assert.Equal(ExpectedResult, result);
```

### 13. managed_vs_unmanaged_dependencies

**Definition**.
A managed dependency is an out-of-process system only your own application reaches, such as your own database. An unmanaged dependency is one other applications can reach too, such as an SMTP server or a message bus. A test must check final state for a managed dependency, but must check the outgoing call for an unmanaged one.

**Book reference**.
Chapter 8, "Working with both managed and unmanaged dependencies," pages 213 to 218.

**Pillar**.
Serves resistance to refactoring, because the wrong check for a dependency type ties a test to a call it must not care about.

**Detection class**.
CONTEXT. Telling a managed dependency from an unmanaged one needs to know who else can reach it, beyond its type name.

**Detection signal**.
A test mocks a call into the application's own database instead of reading the row back after the call runs.

**Violating example**.
```csharp
var dbMock = new Mock<IDatabase>();
sut.Save(order, dbMock.Object);
dbMock.Verify(x => x.Insert(order)); // own database, checked as a mock
```

**Clean example**.
```csharp
sut.Save(order, realDatabase);
var saved = realDatabase.GetOrder(order.Id);
Assert.Equal(order.Total, saved.Total);
```

### 14. mock_types_you_own

**Definition**.
A test must mock only a type the project itself defines and owns. A third-party type, such as a library class, must sit behind a thin adapter that the project owns instead.

**Book reference**.
Chapter 9, "Only mock types that you own," pages 249 to 251.

**Pillar**.
Serves resistance to refactoring and maintainability, because a change in a third-party API cannot break a test built on the project's own adapter.

**Detection class**.
SEMANTIC. Deciding whether a mocked type belongs to the project or to a dependency needs to see which codebase declares that type.

**Detection signal**.
A test builds a mock straight from a third-party namespace, with no project-owned adapter interface in between.

**Violating example**.
```csharp
var s3Mock = new Mock<AmazonS3Client>(); // third-party type, mocked directly
```

**Clean example**.
```csharp
public interface IFileStorage { void Save(string key, byte[] data); }
var storageMock = new Mock<IFileStorage>(); // project-owned adapter
```

### 15. aaa_pattern

**Definition**.
The AAA pattern splits a test into three parts. Arrange builds the objects a test needs. Act calls the method under test. Assert checks the result.

**Book reference**.
Chapter 3, "How to structure a unit test," pages 65 to 69.

**Pillar**.
Serves maintainability, because the same shape in every test makes each one fast to read.

**Detection class**.
STATIC. A tool can check for these three groups, in order, marked by blank lines or comments, inside a test method body.

**Detection signal**.
A test method mixes arrange, act, and assert code together, with no clear break between the three parts.

**Task 8a note**.
Dropped. The only concrete example is a C# one-liner joined by semicolons. Python and Rust statements do not carry that marker. The other candidate signal, "code after the last assert," fires on ordinary cleanup and on a second raises check. It also overlaps with rule #29, `multiple_act_sections_in_unit_test`, which already covers a second act-assert pair with acceptable precision.

**Violating example**.
```csharp
var sut = new Calculator(); Assert.Equal(3, sut.Add(1, 2)); var y = sut.Add(1,1);
```

**Clean example**.
```csharp
var sut = new Calculator();

int result = sut.Add(1, 2);

Assert.Equal(3, result);
```

### 16. test_naming_guideline

**Definition**.
A good test name states the unit of behavior under test, the scenario, and the expected result, in plain words. It skips method names and internal details, so a reader who never opens the source code still understands the test.

**Book reference**.
Chapter 3, "Naming a unit test," pages 78 to 79.

**Pillar**.
Serves maintainability, because a clear name tells a reader what broke without opening the test body.

**Detection class**.
SEMANTIC. Judging whether a name states behavior, not implementation, needs to compare the name against what the test body does.

**Detection signal**.
A test name built from a method name and its parameter types, so it echoes a function signature instead of a scenario.

**Violating example**.
```csharp
[Fact]
public void IsDeliveryValid_InvalidDate_ReturnsFalse() { }
```

**Clean example**.
```csharp
[Fact]
public void Delivery_with_a_past_date_is_invalid() { }
```

### 17. parameterized_tests

**Definition**.
A parameterized test runs the same arrange, act, and assert code against many input and output pairs. It cuts copy-paste across near-identical tests, but each row still needs a name a reader can understand on its own.

**Book reference**.
Chapter 3, "Refactoring to parameterized tests," pages 80 to 83.

**Pillar**.
Serves maintainability, because one test body covers many scenarios instead of many near-duplicate methods.

**Detection class**.
STATIC. A tool can match a data-driven attribute, such as `[Theory]` with `[InlineData]`, on a test method.

**Detection signal**.
Several test methods with the same body and only the input values changed between them.

**Violating example**.
```csharp
[Fact]
public void Delivery_on_Monday_is_valid() => Assert.True(Check(DayOfWeek.Monday));

[Fact]
public void Delivery_on_Tuesday_is_valid() => Assert.True(Check(DayOfWeek.Tuesday));
```

**Clean example**.
```csharp
[Theory]
[InlineData(DayOfWeek.Monday)]
[InlineData(DayOfWeek.Tuesday)]
public void Delivery_on_a_weekday_is_valid(DayOfWeek day) => Assert.True(Check(day));
```

### 18. logging_test_guideline

**Definition**.
If another part of the system reads a log, such as an alert or a support tool, that log call is worth a test. A log line a developer only glances at in a text file does not earn a unit test.

**Book reference**.
Chapter 8, "How much logging is enough?" and "How do you pass around logger instances?" pages 227 to 234.

**Pillar**.
Serves resistance to refactoring, because a test that checks every log call breaks on harmless wording changes.

**Detection class**.
CONTEXT. Judging whether a log line is observable behavior needs to know whether another system reads that log. The call site alone does not say.

**Detection signal**.
A test checks the exact text of a log message that no other system parses or reads.

**Violating example**.
```csharp
sut.Process(order);
loggerMock.Verify(x => x.Log("Processing order " + order.Id));
```

**Clean example**.
```csharp
sut.Process(order);
alertServiceMock.Verify(x => x.RaiseAlert(AlertType.OrderFailed)); // a system reads this
```

### 19. assertion_free_test

**Definition**.
An assertion-free test runs the system under test but checks nothing about the result. It can pass forever, even after a real bug appears, because it never states what the correct outcome must be.

**Book reference**.
Chapter 3, the section on how many assertions an assert section needs, pages 67 to 68.

**Pillar**.
Hurts protection against regressions, because a test that checks nothing catches nothing.

**Detection class**.
STATIC. A tool can count assertion calls in a test method and flag a count of zero.

**Detection signal**.
A test method with an act step and no `Assert` call anywhere in its body.

**Violating example**.
```csharp
[Fact]
public void Order_ships()
{
    var sut = new Order();
    sut.Ship(); // no assertion follows
}
```

**Clean example**.
```csharp
[Fact]
public void Order_ships()
{
    var sut = new Order();
    sut.Ship();
    Assert.Equal(OrderStatus.Shipped, sut.Status);
}
```

### 20. coverage_metric_as_goal

**Definition**.
Code coverage counts which lines or branches a test suite runs, but it says nothing about whether the test checks the result. A team that chases a coverage number can write tests that touch code without checking behavior.

**Book reference**.
Chapter 1, "Using coverage metrics to measure test suite quality," pages 30 to 37.

**Pillar**.
Hurts protection against regressions, because a high coverage number can hide tests with no real assertions.

**Detection class**.
CONTEXT. Reading a coverage percentage alone cannot show whether the covered lines have a matching check. It needs the test bodies too.

**Detection signal**.
A team sets a coverage target as a release gate, and tests near that boundary have thin or missing assertions.

**Violating example**.
```csharp
// Coverage tool marks this line "covered." No assertion checks the price.
sut.CalculatePrice(order);
```

**Clean example**.
```csharp
decimal price = sut.CalculatePrice(order);
Assert.Equal(109.99m, price);
```

### 21. tautology_test

**Definition**.
A tautology test cannot fail no matter what the code does, because its assertion restates the same fact the act step already sets up. It runs and passes, but it checks nothing real.

**Book reference**.
Chapter 4, "Extreme case #2: Trivial tests," page 104.

**Pillar**.
Hurts protection against regressions. A test that cannot fail gives no signal, even after a bug appears.

**Detection class**.
SEMANTIC. Spotting a tautology needs to compare the assert value against the exact value the arrange or act step already fixed.

**Detection signal**.
The value in the assert call is the same literal or variable the test itself passed in during arrange.

**Violating example**.
```csharp
var user = new User(name: "John");
Assert.Equal("John", user.Name); // the constructor just set this value
```

**Clean example**.
```csharp
var user = new User(name: "John");
user.Rename("john"); // normalized to lower case, a real behavior
Assert.Equal("john", user.Name);
```

### 22. testing_trivial_code

**Definition**.
Trivial code, such as a one-line getter or setter, is too simple to break on its own. A test around it gives fast feedback but adds close to no protection against regressions.

**Book reference**.
Chapter 4, "Extreme case #2: Trivial tests," page 104.

**Pillar**.
Hurts maintainability, because the test costs upkeep time without a matching gain in protection against regressions.

**Detection class**.
CONTEXT. Judging triviality needs the whole method body. A short name can still hide real logic.

**Detection signal**.
A test method exists for a property getter, a setter, or a one-line delegation with no branch and no calculation.

**Violating example**.
```csharp
[Fact]
public void UserId_returns_set_value()
{
    var user = new User(1);
    Assert.Equal(1, user.UserId); // a plain getter, nothing to break
}
```

**Clean example**.
```csharp
[Fact]
public void Changing_email_from_non_corporate_to_corporate_upgrades_type()
{
    var sut = new User(1, "user@gmail.com", UserType.Customer);
    sut.ChangeEmail("new@mycorp.com", company);
    Assert.Equal(UserType.Employee, sut.Type);
}
```

### 23. overcomplicated_code_untested

**Definition**.
Overcomplicated code combines high domain significance with many collaborators. It carries the most risk of the four code types. A team often skips a direct test for it, because it is also the hardest to test directly.

**Book reference**.
Chapter 7, "The four types of code," pages 173 to 178.

**Pillar**.
Hurts protection against regressions and maintainability, because the highest-risk code ends up with the weakest test coverage.

**Detection class**.
CONTEXT. Placing a class as overcomplicated needs its full collaborator graph and a judgment of domain significance, not one file.

**Detection signal**.
A class with a large branching method and several out-of-process collaborators, and no unit test anywhere in the suite.

**Violating example**.
```csharp
// OrderProcessor mixes business rules with direct calls to the
// database, the payment gateway, and the email service, all in one
// class, with no test at all.
```

**Clean example**.
```csharp
// The Humble Object pattern splits OrderProcessor into a plain
// PricingRules class, tested directly, and a thin, untested wrapper
// that only calls the database, the gateway, and the email service.
```

### 24. brittle_test_source_string_comparison

**Definition**.
A test can check a string built from formatting logic, such as a normalized name or a rendered message. That check breaks on a harmless wording or formatting change. The string is an implementation detail, not the behavior a client depends on.

**Book reference**.
Chapter 5, "Leaking implementation details: an example with an operation," page 122.

**Pillar**.
Hurts resistance to refactoring, because a cosmetic change to the string breaks the test with no bug present.

**Detection class**.
SEMANTIC. Judging whether a checked string is a client-facing result or an internal formatting detail needs the calling context around it.

**Detection signal**.
A test checks an exact internal message string built by a private helper, instead of a client-visible field or return value.

**Violating example**.
```csharp
Assert.Equal("Error, invalid input at field 3", sut.LastInternalLog);
```

**Clean example**.
```csharp
var result = sut.Validate(input);
Assert.False(result.IsValid);
```

### 25. overspecification_asserting_interactions_with_stubs

**Definition**.
A stub only feeds input to the system under test. A test must not check calls made on a stub. That check ties the test to a call path with no outward, visible effect.

**Book reference**.
Chapter 5, the section on why a test must not assert interactions with stubs, page 118.

**Pillar**.
Hurts resistance to refactoring, because the extra check on a stub breaks on refactors that do not change behavior.

**Detection class**.
SEMANTIC. Telling a stub call from a mock call needs to know whether that dependency only supplies input or also produces a real, outward effect.

**Detection signal**.
A test calls `Verify` on a test double that the system under test only ever reads from, never a call that changes something outside.

**Violating example**.
```csharp
var configStub = new Mock<IConfig>();
configStub.Setup(c => c.MaxItems).Returns(10);
sut.Process(configStub.Object);
configStub.Verify(c => c.MaxItems, Times.Once); // a stub, checked as a mock
```

**Clean example**.
```csharp
var configStub = new Mock<IConfig>();
configStub.Setup(c => c.MaxItems).Returns(10);
var result = sut.Process(configStub.Object);
Assert.Equal(10, result.ItemsProcessed);
```

### 26. mocking_managed_dependency

**Definition**.
A managed dependency is one only your own application reaches. A mock on a call into a managed dependency, such as your own database, ties the test to an internal call path. It does not tie the test to the final, observable state.

**Book reference**.
Chapter 5, the section on which out-of-process dependencies to mock, page 137. Chapter 9, "Mocks are for integration tests only," page 247.

**Pillar**.
Hurts resistance to refactoring, because the mock breaks on a harmless change to how the managed dependency gets called.

**Detection class**.
SEMANTIC. Telling a managed dependency from an unmanaged one needs to know who else can reach it, not the mock syntax alone.

**Detection signal**.
A test mocks a repository or a database gateway that belongs only to this application, instead of reading real state back.

**Violating example**.
```csharp
var repoMock = new Mock<IUserRepository>();
sut.Register(user, repoMock.Object);
repoMock.Verify(r => r.Save(user), Times.Once);
```

**Clean example**.
```csharp
sut.Register(user, realRepository);
var saved = realRepository.GetById(user.Id);
Assert.Equal(user.Email, saved.Email);
```

### 27. mock_chains

**Definition**.
A mock chain is a setup where one mock's method returns another mock, several levels deep, to reach the value a test needs. Each extra level adds setup code that has no direct link to the behavior under test.

**Book reference**.
Chapter 6, "Comparing the three styles of unit testing," page 149.

**Pillar**.
Hurts maintainability, because a chain of mocks grows the arrange section far past the size of the act and assert sections.

**Detection class**.
SEMANTIC. Spotting a harmful mock chain needs to see whether the chained calls model a real collaborator path or only work around a design problem.

**Detection signal**.
A test setup calls `.Setup(...)` on the return value of another `.Setup(...)`, several levels deep.

**Violating example**.
```csharp
storeMock.Setup(s => s.GetCatalog().GetProduct(id).GetPrice()).Returns(9.99m);
```

**Clean example**.
```csharp
decimal price = catalog.GetProduct(id).GetPrice(); // a plain call on a real object
Assert.Equal(9.99m, price);
```

### 28. unnecessary_interface_single_implementation

**Definition**.
Many teams add an interface for an out-of-process dependency, even though only one class ever implements it. If no second implementation exists and no test needs a mock, the interface adds a layer of indirection with no matching benefit.

**Book reference**.
Chapter 8, "Interfaces and loose coupling," page 220.

**Pillar**.
Hurts maintainability, because a reader must jump through an extra file to trace a call that has only one real target.

**Detection class**.
CONTEXT. Checking that an interface has one implementation needs a search across the whole codebase, not the interface file alone.

**Detection signal**.
An interface with exactly one production implementation, and no mock or fake anywhere in the test suite.

**Violating example**.
```csharp
public interface IMessageBus { void Send(Message message); }
public class RabbitMqBus : IMessageBus { /* the only implementation */ }
```

**Clean example**.
```csharp
public class RabbitMqBus { public void Send(Message message) { /* ... */ } }
```

### 29. multiple_act_sections_in_unit_test

**Definition**.
A unit test with more than one act section checks several behaviors at once. When one act fails, a reader must work out which action caused it, and the test name can no longer state one clear scenario.

**Book reference**.
Chapter 3, "Avoid multiple arrange, act, and assert sections," pages 65 to 66. Section 8.5.4 treats a second act section as an accepted trade-off for slow integration tests, not for unit tests.

**Pillar**.
Hurts maintainability, because a failure no longer points at one clear action, and the test name cannot state a single scenario.

**Detection class**.
STATIC. A tool can count separate blocks of calls into the system under test that each get their own assert block right after.

**Detection signal**.
A test method calls the system under test, asserts, calls it again, then asserts again, inside one test method.

**Violating example**.
```csharp
sut.AddItem(item);
Assert.Equal(1, sut.ItemCount);
sut.RemoveItem(item);
Assert.Equal(0, sut.ItemCount);
```

**Clean example**.
```csharp
sut.AddItem(item);
Assert.Equal(1, sut.ItemCount);
// removal covered by its own, separate test method
```

### 30. if_statements_in_tests

**Definition**.
An if statement inside a test method means the test can take more than one path through its own code. A reader cannot tell, from the test alone, which path ran, and a single test method now covers more than one scenario.

**Book reference**.
Chapter 3, the section on conditional logic inside tests, page 66.

**Pillar**.
Hurts maintainability, because a reader must trace branching logic inside the test itself, not only inside the code under test.

**Detection class**.
STATIC. A tool can match an `if`, `switch`, or `for` keyword inside a test method body.

**Detection signal**.
A test method contains a conditional branch that picks between two different assert calls.

**Violating example**.
```csharp
var result = sut.Check(input);
if (input > 0) Assert.True(result);
else Assert.False(result);
```

**Clean example**.
```csharp
[Theory]
[InlineData(5, true)]
[InlineData(-5, false)]
public void Check_returns_expected_result(int input, bool expected)
{
    Assert.Equal(expected, sut.Check(input));
}
```

### 31. test_fixture_reuse_via_constructor

**Definition**.
Placing shared setup code in a test class constructor runs that code before every test in the class, even tests that do not need it. The setup also hides inside a class field, so a reader of one test method cannot see the full arrange step.

**Book reference**.
Chapter 3, "The use of constructors in tests diminishes test readability," pages 74 to 77.

**Pillar**.
Hurts maintainability, because a reader of one test method must open the constructor to see the full arrange step.

**Detection class**.
STATIC. A tool can match object creation inside a test class constructor that a test method later reads as a field.

**Detection signal**.
A test class constructor builds a database connection or a domain object that only some of the test methods in that class use.

**Violating example**.
```csharp
public class OrderTests
{
    private readonly Store _store;
    public OrderTests() { _store = new Store(); _store.AddItem("Shampoo", 10); }

    [Fact]
    public void Purchase_succeeds() { /* uses _store, built for every test */ }
}
```

**Clean example**.
```csharp
public class OrderTests
{
    private Store CreateStoreWithItem(string name, int price)
    {
        var store = new Store();
        store.AddItem(name, price);
        return store;
    }

    [Fact]
    public void Purchase_succeeds()
    {
        var store = CreateStoreWithItem("Shampoo", 10);
    }
}
```

### 32. large_arrange_section

**Definition**.
An arrange section that dwarfs the act and assert sections signals a class with too many collaborators. It can also mean a test that builds more than the scenario needs. A private factory method, not a bigger constructor, is the book's fix.

**Book reference**.
Chapter 3, the section on section size limits, page 67.

**Pillar**.
Hurts maintainability, because a long arrange section takes longer to read than the behavior the test checks.

**Detection class**.
SEMANTIC. Judging whether an arrange section is too large needs to compare its size against the act and assert sections, not a fixed line count.

**Detection signal**.
A test method's setup code runs far longer than its act and assert code combined.

**Violating example**.
```csharp
var address = new Address("Street 1", "City", "12345");
var company = new Company("mycorp.com", address, taxId: "123", founded: 2020);
var user = new User(1, "a@b.com", UserType.Customer, address, company);
var result = user.ChangeEmail("new@mycorp.com", company);
Assert.Equal(UserType.Employee, user.Type);
```

**Clean example**.
```csharp
var user = CreateCustomerWithCompanyEmail();
user.ChangeEmail("new@mycorp.com", company);
Assert.Equal(UserType.Employee, user.Type);
```

### 33. asserting_interactions_not_at_system_edge

**Definition**.
A mock check earns its place only at the outer edge of the system under test, on a call that leaves the whole application. A mock check on a call between two classes inside the same application ties the test to an internal design choice.

**Book reference**.
Chapter 9, the section on checking interactions at the system edges, page 241.

**Pillar**.
When placed at the edge, this serves resistance to refactoring. When placed on an internal call instead, this hurts protection against regressions.

**Detection class**.
CONTEXT. Telling an edge call from an internal call needs the full call graph from the system under test out to the process boundary.

**Detection signal**.
A mock check sits on a call between two in-process classes, with no out-of-process call anywhere near it in the call chain.

**Violating example**.
```csharp
sut.Process(order);
validatorMock.Verify(v => v.Validate(order)); // an internal, in-process call
```

**Clean example**.
```csharp
sut.Process(order);
emailGatewayMock.Verify(g => g.Send(order.CustomerEmail)); // leaves the app
```

### 34. incomplete_mock_call_verification

**Definition**.
A mock check can pass while skipping the arguments passed to a call, and while skipping the call count. That loose check can pass even though the code sends the wrong data or calls the wrong number of times.

**Book reference**.
Chapter 9, the section on checking the number of calls, page 248.

**Pillar**.
Hurts protection against regressions, because a loose check misses a real bug in the arguments or the call count.

**Detection class**.
STATIC. A tool can match a `Verify` call and check whether it names a specific argument matcher and an exact `Times` count.

**Detection signal**.
A `Verify` call uses `It.IsAny<T>()` for every argument, or names no `Times` count at all.

**Violating example**.
```csharp
emailGatewayMock.Verify(g => g.Send(It.IsAny<string>())); // any address, any count
```

**Clean example**.
```csharp
emailGatewayMock.Verify(g => g.Send("john@mycorp.com"), Times.Once);
```

### 35. mocking_types_you_dont_own_violation

**Definition**.
A mock built straight from a third-party type ties every test that uses it to that library's exact interface shape. A new library version, or a switch to a different library, then forces a rewrite across every test that mocked it.

**Book reference**.
Chapter 9, "Only mock types that you own," pages 249 to 251.

**Pillar**.
Hurts resistance to refactoring and maintainability, because a change outside the project's own code still breaks the test suite.

**Detection class**.
SEMANTIC. Spotting the violation needs to see the mocked type's namespace, and needs to see that no project-owned adapter sits in front of it.

**Detection signal**.
A test mocks a class or an interface that comes from a NuGet package or another external library, with no wrapper of its own.

**Violating example**.
```csharp
var httpMock = new Mock<HttpClient>(); // a .NET framework type, mocked directly
```

**Clean example**.
```csharp
public interface IPaymentGateway { Task Charge(decimal amount); }
var gatewayMock = new Mock<IPaymentGateway>(); // the project's own adapter
```

### 36. testing_repositories_directly

**Definition**.
A repository class only forwards calls to a real database, with no business logic of its own. A unit test around a repository checks framework code, such as an ORM, rather than logic the team wrote.

**Book reference**.
Chapter 10, the section on whether to test repositories, pages 275 to 277.

**Pillar**.
Hurts maintainability, because the test costs upkeep time while checking code the team did not write.

**Detection class**.
CONTEXT. Judging whether a repository holds real logic needs its full method bodies, not its name or its interface alone.

**Detection signal**.
A test class targets a repository method that only calls an ORM method and returns its result, with no added logic.

**Violating example**.
```csharp
[Fact]
public void GetById_returns_user()
{
    var repo = new UserRepository(realDb);
    var user = repo.GetById(1); // pure passthrough to the ORM
    Assert.NotNull(user);
}
```

**Clean example**.
```csharp
// The repository is covered through the integration tests that use
// it as part of a real feature, not through a unit test of its own.
```

### 37. in_memory_database_substitute

**Definition**.
An in-memory database swaps in a different engine than the one production code runs against. That swap hides bugs tied to the real engine's exact behavior. The book recommends a real instance of the same database engine for integration tests instead.

**Book reference**.
Chapter 10, "Avoid in-memory databases," pages 268 to 269.

**Pillar**.
Hurts protection against regressions, because a bug specific to the real database engine slips past a test run on a different engine.

**Detection class**.
CONTEXT. Checking the substitution needs the test's database setup code and the production connection string, not the test body alone.

**Detection signal**.
A test suite runs its database tests against an in-memory provider, while production code runs against a different, real database engine.

**Violating example**.
```csharp
services.AddDbContext<AppContext>(o => o.UseInMemoryDatabase("TestDb"));
```

**Clean example**.
```csharp
services.AddDbContext<AppContext>(o => o.UseSqlServer(testConnectionString));
```

### 38. reusing_database_context_across_sections

**Definition**.
A single database connection object reused across the arrange, act, and assert sections of a database test can hide a real bug. A fresh connection catches that bug, such as a change the code never saved.

**Book reference**.
Chapter 10, "Reusing code in arrange sections," pages 268 to 270.

**Pillar**.
Hurts protection against regressions, because a shared connection can mask a save that never reached the real database.

**Detection class**.
STATIC. A tool can match one database context variable read and written across more than one AAA section in the same test method.

**Detection signal**.
The arrange, act, and assert sections of a database test all read and write through the exact same open connection object.

**Violating example**.
```csharp
using var context = new AppContext();
context.Users.Add(user);
context.SaveChanges();
var loaded = context.Users.Find(user.Id); // same context, cached in memory
```

**Clean example**.
```csharp
using (var context = new AppContext()) { context.Users.Add(user); context.SaveChanges(); }
using (var context2 = new AppContext()) { var loaded = context2.Users.Find(user.Id); }
```

### 39. model_database_anti_pattern

**Definition**.
A model database is a separate, hand-maintained instance. A team treats it as the source of truth for the schema, compared against production by a diff tool. It competes with source control as a second, conflicting source of truth for the schema.

**Book reference**.
Chapter 10, "Keeping the database in the source control system," pages 252 to 254.

**Pillar**.
Hurts maintainability, because two competing sources of truth for the schema add ongoing sync work with no matching benefit.

**Detection class**.
CONTEXT. Spotting this anti-pattern needs to know how the team's process defines and updates the schema, not one script file.

**Detection signal**.
A team keeps a live, shared database instance as the reference for schema changes, instead of versioned migration scripts in source control.

**Violating example**.
```csharp
// Schema changes are made by hand against a shared "model" server,
// then compared against production later with a diff tool.
```

**Clean example**.
```csharp
// Schema changes ship as numbered migration scripts in source
// control, and the database applies them in order on deploy.
```

### 40. wrapping_test_in_uncommitted_transaction

**Definition**.
Wrapping a database test in a transaction keeps the database clean between test runs, without a separate cleanup step. The test rolls back that transaction at the end. The rollback must run, even on a path where the test itself fails or throws.

**Book reference**.
Chapter 10, "Managing database transactions in integration tests," page 264.

**Pillar**.
Serves protection against regressions, because a clean, known database state before each test removes a common source of a flaky result.

**Detection class**.
SEMANTIC. Checking that the rollback happens on every path needs to see the transaction setup, beyond the test body's happy path.

**Detection signal**.
A database test opens a transaction but commits it, or closes the connection without a rollback, on at least one exit path.

**Violating example**.
```csharp
using var transaction = connection.BeginTransaction();
context.Users.Add(user);
context.SaveChanges();
transaction.Commit(); // leaves data behind for the next test
```

**Clean example**.
```csharp
using var transaction = connection.BeginTransaction();
context.Users.Add(user);
context.SaveChanges();
// no commit call, so the transaction rolls back when disposed
```

### 41. circular_dependencies

**Definition**.
When class A calls class B, and class B also calls class A either directly or through a longer chain, a circular dependency exists. Integration tests around that chain must run the whole cycle together. A single failure then gives no clue which class caused it.

**Book reference**.
Chapter 8, the section on the problem with a lot of collaborators, pages 223 to 225.

**Pillar**.
Hurts fast feedback and maintainability, because a failure inside a cycle forces a reader to check every class in the cycle to find the cause.

**Detection class**.
CONTEXT. Finding a cycle needs the full call graph across the classes involved, not one file at a time.

**Detection signal**.
Class A calls class B, and a trace from class B, through any number of other classes, leads back to class A.

**Violating example**.
```csharp
class OrderService { void Place(Order o) { _shipping.Notify(o); } }
class ShippingService { void Notify(Order o) { _order.MarkShipped(o); } } // calls back
```

**Clean example**.
```csharp
class OrderService { void Place(Order o) { var status = _shipping.Notify(o); MarkStatus(status); } }
class ShippingService { ShipStatus Notify(Order o) { return ShipStatus.Sent; } } // one direction
```

### 42. excessive_layers_of_indirection

**Definition**.
Excessive layers of indirection means a call passes through several thin classes before it reaches any class with real logic. Each layer only forwards the call to the next one. A reader must open every layer to find where the actual work happens.

**Book reference**.
Chapter 8, the section on the problem with a lot of collaborators, pages 223 to 225.

**Pillar**.
Hurts maintainability, because a reader spends time tracing forwarding calls instead of reading the logic those calls lead to.

**Detection class**.
CONTEXT. Judging excess needs the full call chain from the entry point to the class that holds the real logic.

**Detection signal**.
A call passes through three or more classes that each only forward it, with no branch or calculation along the way.

**Violating example**.
```csharp
class Controller { void Handle(Req r) { _service.Run(r); } }
class Service { void Run(Req r) { _handler.Process(r); } }
class Handler { void Process(Req r) { _worker.Execute(r); } } // still no logic
```

**Clean example**.
```csharp
class Controller { void Handle(Req r) { _pricingRules.Apply(r); } } // one hop to real logic
```

### 43. exposing_private_methods_for_testing

**Definition**.
Making a private method public, or internal, only so a test can call it, ties the test to one specific way of writing the code. It does not tie the test to the class's observable behavior. A caller outside the test never needed that method exposed.

**Book reference**.
Chapter 11, section 11.1, "Exposing private methods for testing," pages 282 to 285.

**Pillar**.
Hurts resistance to refactoring, because a later rewrite of that private method breaks a test that never needed to see it.

**Detection class**.
STATIC. A tool can match a method whose access level changed to public or internal. The method name suggests internal, step-by-step logic, and a test calls it directly.

**Detection signal**.
A production class exposes a method named after an implementation step, such as `CalculateDiscount`, and only a test project calls it.

**Violating example**.
```csharp
public decimal CalculateDiscountInternal(Order o) { /* logic */ } // made public for the test
```

**Clean example**.
```csharp
private decimal CalculateDiscountInternal(Order o) { /* logic */ }
public decimal GetPrice(Order o) { return CalculateDiscountInternal(o); } // test calls this
```

### 44. exposing_private_state_for_testing

**Definition**.
Making a private field public, or adding a getter, only so a test can read it, ties the test to the class's internal storage. It does not tie the test to a result the class already exposes through its normal, public behavior.

**Book reference**.
Chapter 11, section 11.2, "Exposing private state for testing," pages 285 to 288.

**Pillar**.
Hurts resistance to refactoring, because a later change to how the class stores that state breaks a test built around the field, not around behavior.

**Detection class**.
STATIC. A tool can match a getter added to a class whose only caller is a test project, on a field with no other public use.

**Detection signal**.
A class exposes a field or a getter that no production code path reads, and only a test reads it.

**Violating example**.
```csharp
public List<string> _appliedDiscountsInternal; // exposed only for the test to inspect
```

**Clean example**.
```csharp
public Receipt Checkout(Order o) { return new Receipt(o.FinalPrice, o.AppliedDiscounts); }
// the test reads the receipt the checkout call already returns
```

### 45. leaking_domain_knowledge_to_tests

**Definition**.
A test can recompute the production algorithm inside its own assert section, instead of asserting a known input against a known, hardcoded output. That choice forces the same logic to live in two places. A bug in that logic can then hide in both places at once.

**Book reference**.
Chapter 11, section 11.3, "Leaking domain knowledge to tests," pages 288 to 290.

**Pillar**.
Hurts protection against regressions, because a shared bug in the duplicated logic passes the check on both sides.

**Detection class**.
SEMANTIC. Spotting a leaked algorithm needs to compare the test's assert-section code against the production method's logic, not the test's shape alone.

**Detection signal**.
A test's assert section runs a loop, a branch, or a formula that mirrors the production method under test, instead of a plain literal value.

**Violating example**.
```csharp
var result = sut.CalculateDiscount(orders);
var expected = orders.Sum(o => o.Price) * 0.9; // re-runs the same 10% rule
Assert.Equal(expected, result);
```

**Clean example**.
```csharp
var result = sut.CalculateDiscount(orders);
Assert.Equal(27, result); // a fixed, known number for a fixed, known input
```

### 46. code_pollution

**Definition**.
Code pollution is production code changed, or added, only to make a test easier to write. One example is a conditional branch that only runs under a test flag. That extra code ships to every user, yet only the test suite ever takes that branch.

**Book reference**.
Chapter 11, section 11.4, "Code pollution," pages 290 to 292.

**Pillar**.
Hurts maintainability, because the shipped code carries a branch with no production purpose, and every future reader must reason around it.

**Detection class**.
CONTEXT. Task 8b tried a test-side signal, a call passing `testing=True` or a name containing `for_testing`. A search of `hooks/` and its tests found zero matches for that signal, so there is nothing to tune against. Catching the rule needs the paired production branch, not the test call alone, so the rule stays CONTEXT and ADW carries no static check for it.

**Detection signal**.
Production code contains a branch such as `if (isTestMode)`, with logic that exists only to help a test pass.

**Violating example**.
```csharp
public void SendEmail(string to)
{
    if (Environment.GetEnvironmentVariable("IS_TEST") == "true") return; // skips real send
    _smtpClient.Send(to);
}
```

**Clean example**.
```csharp
public interface IEmailGateway { void Send(string to); }
// the test passes a fake IEmailGateway, and production code stays free of test flags
```

### 47. mocking_concrete_classes

**Definition**.
Mocking a concrete class, instead of an interface, forces every method on that class to stay virtual, or the mocking library cannot override it. The production class then carries a design shaped by the test framework, not by its own behavior.

**Book reference**.
Chapter 11, section 11.5, "Mocking concrete classes," pages 292 to 293.

**Pillar**.
Hurts maintainability, because a class carries virtual members it needs only for a mocking library, not for its own design.

**Detection class**.
STATIC. A tool can match a mock built from a class keyword target, and a matching class definition marked with virtual members for no other caller.

**Detection signal**.
A test builds a mock directly from a class, and that class marks its members virtual only so the mock can override them.

**Violating example**.
```csharp
public class PaymentGateway { public virtual void Charge(decimal amount) { /* real call */ } }
var mock = new Mock<PaymentGateway>(); // forces Charge to stay virtual
```

**Clean example**.
```csharp
public interface IPaymentGateway { void Charge(decimal amount); }
public class PaymentGateway : IPaymentGateway { public void Charge(decimal amount) { /* real call */ } }
var mock = new Mock<IPaymentGateway>();
```

### 48. time_as_ambient_context

**Definition**.
Code can read the current time from a static call, such as `DateTime.Now`. That call pulls the value from ambient, global context instead of from an explicit input. A test around that code cannot control the time it runs against, so the test cannot set up a fixed, repeatable scenario.

**Book reference**.
Chapter 11, section 11.6, "Time as an ambient context," pages 293 to 296.

**Pillar**.
Hurts fast feedback, because a test around date-sensitive logic can pass today and fail on a different day, with no code change at all.

**Detection class**.
STATIC. A tool can match a direct call to `DateTime.Now`, `DateTime.UtcNow`, or an equivalent static clock call inside a method under test.

**Detection signal**.
A production method calls a static "now" function directly, instead of receiving the current time as a parameter or through an injected clock.

**Violating example**.
```csharp
public bool IsExpired(Order o) { return DateTime.Now > o.ExpiryDate; } // hidden, ambient input
```

**Clean example**.
```csharp
public bool IsExpired(Order o, DateTime now) { return now > o.ExpiryDate; } // explicit, testable input
```

### 49. hardcoded_name_presence

**Definition**.
A test only checks that a hardcoded literal appears somewhere in the output, such as a substring match on a name or a label. It does not check the behavior that literal represents. The check pins one piece of text, not a real outcome.

**Book reference**.
This rule's origin is the user, not the book. It maps closest to entry 21, tautology_test, and to entry 24, brittle_test_source_string_comparison, since both cover a check that pins surface text instead of behavior.

**Pillar**.
Hurts protection against regressions, because a check on one fixed literal misses a bug in the actual behavior that literal stands for.

**Detection class**.
SEMANTIC. Telling a literal-presence check from a real behavior check needs to read what the assertion checks, not its syntax alone.

**Detection signal**.
An assertion checks that a fixed string, such as a status code or a label, appears in the output. That check skips the surrounding data. The surrounding data proves the behavior ran correctly.

**Violating example**.
```csharp
var result = sut.Process(order);
Assert.Contains("Approved", result.ToString()); // pins the word, not the decision logic
```

**Clean example**.
```csharp
var result = sut.Process(order);
Assert.Equal(OrderStatus.Approved, result.Status);
Assert.Equal(order.Total, result.ApprovedAmount);
```

### 50. hardcoded_literal_in_source

**Definition**.
A test checks that a literal string sits written in source code or in a config file. It does not check behavior driven by a variable input. The test only restates a value the source already states. A change to that value breaks the test without changing any real behavior.

**Book reference**.
This rule's origin is the user, not the book. It maps closest to entry 19, assertion_free_test, and to entry 21, tautology_test. All three cover a check with no real power to catch a behavior bug.

**Pillar**.
Hurts protection against regressions, because the test restates a static fact from the source instead of checking a computed, dynamic result.

**Detection class**.
STATIC. A tool can match a test assertion whose expected value is the same literal already hardcoded in the source or config file it targets.

**Detection signal**.
A test reads a config file or a source constant and asserts that the value equals the literal a human typed into that file.

**Violating example**.
```csharp
// appsettings.json contains: "MaxRetries": 3
Assert.Equal(3, config.MaxRetries); // restates the file, checks no behavior
```

**Clean example**.
```csharp
var attempts = sut.CallWithRetries(failingService);
Assert.Equal(3, attempts); // checks the retry behavior actually ran three times
```

## Rust sample classification

The sample test loops over four `sex` values, rebuilds a profile for each one, and runs the forecast pipeline. For each one, it checks that `response["pathways"][0]["status"]` equals the literal `"ready"`. Against the catalog above, it violates the following entries.

**#16, test_naming_guideline**.
The name `every_sex_the_profile_form_offers_keeps_the_mechanistic_method_ready` names a demographic input list, not the behavior under test. A reader cannot tell from the name what outcome the test protects, such as "forecast pathway stays ready regardless of the sex field."

**#17, parameterized_tests**.
The test uses a plain Rust `for` loop over four literal strings instead of a parameterized-test attribute or macro. Each iteration reports failure only through the `"{sex}: {response}"` panic message. No named, isolated test case marks which scenario failed.

**#21, tautology_test, borderline**.
The assertion checks `status == "ready"` for every one of four different inputs, with no differing expected value between them. This makes the test read like it checks one behavior four times over. It does not check four distinct expected outcomes. That weakens its power to catch a bug that affects only one branch of the `sex` handling.

**#49, hardcoded_name_presence (user rule)**.
The assertion checks only that the string `"ready"` sits inside `response["pathways"][0]["status"]`. It reads no other field on the response, such as a pathway id, a reason code, or the count of pathways returned. A code change that returns `"ready"` for the wrong pathway, or that drops every other pathway from the array, still passes.

**#50, hardcoded_literal_in_source, not applicable as written**.
This rule targets a test that checks a literal already hardcoded in source or config. The sample instead checks a literal returned at runtime from `forecast_pathways`, so this entry does not fit the sample directly. This section lists the rule only to record that this analysis checked it and ruled it out.

**#6 and #22, code quadrants and triviality, open question**.
Whether this test earns its keep depends on where `forecast_pathways` and the sex-branching logic sit in the code quadrants framework. If that logic is domain logic with real branching per `sex` value, the test targets a quadrant worth testing. The complaint then is only about assertion strength, in entries #16, #17, and #49. If the sex field never drives a real branch, and `"ready"` is a constant returned regardless of input, the test falls under #22, testing_trivial_code. The whole loop then adds upkeep cost with no matching protection. Both entries are CONTEXT-class. Answering this needs the body of `forecast_pathways` and `prepare_from_saved`, which is not part of the sample, so this judgment stays open rather than settled.
