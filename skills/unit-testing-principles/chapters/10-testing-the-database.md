# Chapter 10. Testing the database

Book pages 229 to 256.

## Core argument

The last piece of integration testing is the managed dependency, usually the application database. Tests against a real database give the strongest protection against regressions. They take preparation.

The chapter covers four areas.

1. Prerequisites that make database tests possible.
2. Transaction handling in production code and in tests.
3. The life cycle of test data.
4. How to keep database tests short.

The focus is relational databases. Most ideas apply to document stores and even plain text file storage.

## Prerequisites

Chapter 8 said to use managed dependencies as they are in integration tests. That makes them harder to work with than unmanaged ones, because a mock is not an option. Three prerequisites come first. Each also improves the health of the database in general, even without tests.

### Keep the database in source control

Treat the database schema like regular code and store it in source control, such as Git.

The author has seen teams keep a dedicated model database as the reference. All schema changes went into it during development. At deployment, a tool compared the model database with production, generated upgrade scripts, and ran them.

A model database is a poor way to manage schema, for two reasons.

1. No change history. Nobody can trace the schema back to an earlier point, which matters when reproducing production bugs.
2. No single source of truth. The model database competes with Git as the source of truth about development state. Keeping two sources in sync adds a burden.

Keeping every schema change in source control gives one source of truth. Database changes then travel with code changes. No change to the database structure happens outside source control.

### Reference data is part of the schema

The schema covers tables, views, indexes, stored procedures, and anything else that forms the blueprint of the database. SQL scripts represent it. A developer runs those scripts to create a full, current database instance at any time.

One more part belongs to the schema and rarely gets treated that way, reference data. Reference data is data the application needs present to work at all.

Take the billing system. Members are domestic or international. A table of member kinds with a foreign key from `members` guarantees that the application never assigns a nonexistent kind. The rows of that table are reference data. The application relies on them to save members.

The author gives a test for telling them apart. If the application can modify the data, it is regular data. If not, it is reference data.

Reference data is essential, so keep it in source control with the rest of the schema, as SQL insert statements.

Reference data and regular data usually live in separate tables. Sometimes they share one. A flag then marks which rows the application may change, and the application refuses to change the rest.

### A separate instance for every developer

Tests against a real database are hard enough. A database shared between developers makes them harder, for two reasons.

1. Tests run by different developers interfere with each other.
2. A change that breaks backward compatibility blocks other developers.

Give every developer an own instance, ideally on the developer's machine, for the fastest test runs.

### State-based versus migration-based delivery

There are two ways to deliver database changes. The migration-based one costs more at first and works much better over time.

#### The state-based approach

It resembles the model database above. A comparison tool generates scripts that bring production up to date with a model. The difference is that no physical model database exists. SQL scripts that create the model sit in source control. The comparison tool does the heavy work. Whatever state production is in, the tool deletes tables, creates new ones, renames columns, and so on, until production matches.

#### The migration-based approach

Explicit migrations move the database from one version to the next. No tool synchronizes production and development. Developers write the upgrade scripts. A comparison tool still helps to detect undocumented changes in production.

Migrations, not the database state, become the artifacts in source control. They are usually plain SQL scripts. Flyway and Liquibase are popular tools. Some teams write them in a language-level DSL that turns into SQL. In Python, Alembic plays this role.

```python
revision = "0001"
down_revision = None


def upgrade():
    op.create_table("members", sa.Column("id", sa.Integer, primary_key=True))


def downgrade():
    op.drop_table("members")
```

The downgrade step helps when moving back to an older version to reproduce a bug.

#### Prefer migrations

| | Database state | Migration mechanism |
|---|---|---|
| State-based | explicit | implicit |
| Migration-based | implicit | explicit |

Explicit state makes merge conflicts easier. Explicit migrations make data motion easier. Data motion means changing the shape of existing data to fit a new schema.

Both benefits look equal. In most projects, data motion matters far more than merge conflicts. Once the application reaches production, the database holds data that the team cannot discard.

Say a `full_name` column splits into `first_name` and `last_name`. Dropping one column and adding two is not enough. A script has to split every existing name. The state-based approach has no good way to do this. Comparison tools handle data badly. The schema has one interpretation, while data depends on context. No tool guesses the right transformation. Domain rules decide it.

The state-based approach is impractical in most projects. It works for a while before the first release, since test data matters little and gets recreated on every change. After the first release, switch to migrations.

The author's tip. Apply every schema change, including reference data, through migrations. Do not edit a migration once it is in source control. If a migration is wrong, add a new one that fixes it. Break this rule only when the wrong migration causes data loss.

## Transaction management

Transaction management matters in production code and in tests. In production it prevents inconsistent data. In tests it verifies database work in a setting close to production.

### Transactions in production code

In the billing sample, a `Database` class opens a new connection per method call. Each connection runs its own transaction behind the scenes.

```python
class Database:
    def __init__(self, connection_string):
        self._connection_string = connection_string

    def save_member(self, member):
        with connect(self._connection_string) as connection:
            ...

    def save_company(self, company):
        with connect(self._connection_string) as connection:
            ...
```

The controller runs four transactions in one business operation. Reading the member, reading the company, saving the company, and saving the member.

Several transactions are fine for read-only operations, such as returning member data to a client. When the operation changes data, all updates in it have to be atomic. Otherwise the controller saves the company, the connection drops, and the member save fails. The domestic count then disagrees with the members in the database.

Atomic updates run all-or-nothing. Every update in the set completes, or none has any effect.

#### Separate connections from transactions

Two kinds of decisions need to part ways.

1. Which data to update.
2. Whether to keep the updates or roll them back.

The controller cannot make both at once. It knows whether to keep the updates only after every step succeeded. It takes those steps only by reaching the database and trying the updates. Split `Database` into repositories and a transaction.

1. Repositories give access to the data and change it. The sample gets two, one for members and one for companies.
2. A transaction commits or rolls back all updates as one. A small custom class on top of the database's own transactions does the job.

The two also live for different lengths of time. A transaction lives through the whole business operation and ends when the operation ends. A repository is short-lived. It closes as soon as its database call returns. Repositories always work inside the current transaction. On connecting, a repository enlists in the transaction, so the transaction later rolls back anything the repository changed.

```python
class MemberController:
    def __init__(self, transaction, message_bus, domain_logger):
        self._transaction = transaction
        self._members = MemberRepository(transaction)
        self._companies = CompanyRepository(transaction)
        self._dispatcher = EventDispatcher(message_bus, domain_logger)

    def change_billing_country(self, member_id, new_country):
        member = MemberFactory.create(self._members.get(member_id))
        error = member.can_change_billing_country()
        if error:
            return error

        company = CompanyFactory.create(self._companies.get())
        member.change_billing_country(new_country, company)

        self._companies.save(company)
        self._members.save(member)
        self._dispatcher.dispatch(member.events)

        self._transaction.commit()
        return "OK"
```

The transaction has two operations.

1. Commit marks the transaction as successful. The controller calls it only when the operation succeeded and all changes are ready to persist.
2. Close ends the transaction. It always runs at the end of the operation. After a commit, it persists the updates. Without one, it rolls them back.

The pair guarantees the database changes only on the happy path. On any error, a validation error or an unhandled exception, the flow returns early and the commit never runs.

The controller calls commit because committing needs a decision. Closing needs none, so the infrastructure layer does it. The code that creates the controller and hands it dependencies also closes the transaction after the controller finishes.

`MemberRepository` takes the transaction as a constructor parameter. That states in code that repositories always work inside a transaction and never call the database alone.

#### Upgrade the transaction to a unit of work

A unit of work tracks the objects a business operation touches. When the operation ends, it works out all needed updates and runs them as one unit, hence the name.

A unit of work beats a plain transaction because it defers updates. It runs all updates at the end, which keeps the real database transaction short and reduces data congestion. It often reduces the number of database calls too. A database transaction is itself a unit of work.

Most ORMs implement the pattern. In Python, a SQLAlchemy `Session` is a unit of work.

```python
class MemberController:
    def __init__(self, session, message_bus, domain_logger):
        self._session = session
        self._members = MemberRepository(session)
        self._companies = CompanyRepository(session)
        self._dispatcher = EventDispatcher(message_bus, domain_logger)

    def change_billing_country(self, member_id, new_country):
        member = self._members.get(member_id)
        error = member.can_change_billing_country()
        if error:
            return error

        company = self._companies.get()
        member.change_billing_country(new_country, company)

        self._companies.save(company)
        self._members.save(member)
        self._dispatcher.dispatch(member.events)

        self._session.commit()
        return "OK"
```

The ORM maps rows to domain objects, so `MemberFactory` and `CompanyFactory` go away.

#### Non-relational databases

Relational databases make atomic updates easy across any number of rows. Most document stores guarantee atomicity only within one document. An operation that changes several documents risks inconsistency. Document databases answer by design. Shape documents so no operation changes more than one at a time. Documents hold data of any shape, so one document captures the side effects of even complex operations.

Domain-Driven Design has a related rule. Change only one aggregate per business operation. It serves the same goal and applies to document databases, where each document maps to one aggregate.

### Transactions in integration tests

The guideline. Do not reuse database transactions or units of work across the sections of a test.

```python
def test_moving_away_from_the_home_country():
    with Session(engine) as session:
        members = MemberRepository(session)
        companies = CompanyRepository(session)
        member = Member(0, "DE", MemberKind.DOMESTIC, invoiced=False)
        members.save(member)
        companies.save(Company(home_country="DE", domestic_count=1))
        session.commit()

        bus = BusSpy()
        domain_logger = create_autospec(DomainLoggerProtocol, instance=True)
        sut = MemberController(session, MessageBus(bus), domain_logger)

        result = sut.change_billing_country(member.member_id, "FR")

        assert result == "OK"
        member_from_db = members.get(member.member_id)
        assert member_from_db.country == "FR"
        ...
```

This test uses one session in arrange, act, and assert. That setup does not match production. In production, each operation gets its own session, created right before the controller call and closed right after.

To avoid behavior that differs from production, the act section gets its own session. Arrange and assert also need their own. Chapter 8 said to check the database state independently of the input data. The assert section queries member and company separately, yet a shared session still caches data, and many ORMs do exactly that for performance.

The author's tip. Use at least three transactions or units of work in an integration test, one each for arrange, act, and assert.

The catalog lists the violation as `reusing_database_context_across_sections`.

## Test data life cycle

A shared database raises the problem of isolating integration tests from each other. Two steps solve it.

1. Run integration tests in sequence.
2. Remove leftover data between runs.

Tests do not depend on the state of the database. Each test brings the database into the state it needs.

### Parallel versus sequential execution

Parallel integration tests take a lot of effort. All test data has to be unique so no constraint breaks and no test picks up another test's input. Cleanup gets trickier too. Running integration tests in sequence is more practical than squeezing out more speed.

Most test frameworks let a team group tests and turn off parallelism per group. Make one group for unit tests and one for integration tests, and turn off parallel runs for the integration group. With pytest-xdist, the `xdist_group` marker together with `--dist loadgroup` keeps the integration tests on one worker.

An alternative runs each test against its own container, built from an image of the model database. In practice this adds too much maintenance.

1. Maintain the images.
2. Give each test its own container.
3. Batch the tests, since creating every container at once rarely works.
4. Dispose of used containers.

The author advises against containers per test unless test time must shrink at all costs. One database instance per developer is more practical. That single instance can run in Docker. The advice is against premature parallelism, not against Docker.

### Clearing data between runs

Four options exist.

1. Restore a backup before each test. It solves cleanup but runs far slower than the others. Even with containers, removing one and starting another takes seconds, which adds up.
2. Clean up at the end of each test. It is fast but easy to skip. A crashed build server or a test stopped in the debugger leaves data behind, and it affects later runs.
3. Wrap each test in a transaction that never commits. The database rolls back every change automatically. That fixes skipped cleanup and creates another problem. The extra transaction makes test behavior differ from production. It is the same problem as a shared unit of work. The catalog lists it as `wrapping_test_in_uncommitted_transaction`.
4. Clean up at the start of each test. This is the best option. It is fast, keeps behavior consistent, and nothing skips it.

The author's tip. A separate teardown phase is unnecessary. Cleanup is part of the arrange section.

Deletion has to follow foreign key order. Some teams write clever code that works out the table graph and generates the deletion script, or that turns off constraints and back on. That is unnecessary. A hand-written SQL script is simpler and gives finer control.

Put the deletion script in a base class, or in pytest, in an autouse fixture that applies only to the integration test directory. It then runs at the start of every integration test.

```python
@pytest.fixture(autouse=True)
def clear_database():
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM members"))
        connection.execute(text("DELETE FROM companies"))
```

This is the one legitimate use of shared setup from chapter 3. The code has to run in every test, and it has nothing to do with the arrangement of any single scenario.

The author's tip. The deletion script removes all regular data and no reference data. Migrations alone control reference data, like the rest of the schema.

### Avoid in-memory databases

Another way to isolate tests is an in-memory database, such as SQLite, in place of the real one. It looks attractive for three reasons.

1. No test data to remove.
2. Faster runs.
3. A fresh instance per test.

In-memory databases are not shared dependencies. If the database is the only managed dependency, integration tests turn into unit tests, like the container approach above.

The author still advises against them. Their functionality differs from regular databases. Test and production environments then differ, and tests produce false positives or, worse, false negatives. Such tests never give good protection, and a lot of regression testing ends up manual anyway.

The author's tip. Use the same database management system in tests as in production. A different version or edition is usually fine. The vendor stays the same.

The catalog lists the violation as `in_memory_database_substitute`.

## Reusing code in test sections

Integration tests grow large fast and lose maintainability. Keep them as short as possible without coupling them to each other or hurting readability. Even the shortest tests do not depend on each other. They keep the full context of the scenario visible, and a reader does not jump around the test module to understand them.

The best way to shorten integration tests is to move technical, non-business parts into private helpers or helper classes. The helpers are reusable as a bonus.

### The arrange section

With one unit of work per section, the test looks like this.

```python
def test_moving_away_from_the_home_country():
    with Session(engine) as session:
        member = Member(0, "DE", MemberKind.DOMESTIC, invoiced=False)
        MemberRepository(session).save(member)
        CompanyRepository(session).save(Company(home_country="DE", domestic_count=1))
        session.commit()

    bus = BusSpy()
    domain_logger = create_autospec(DomainLoggerProtocol, instance=True)

    with Session(engine) as session:
        sut = MemberController(session, MessageBus(bus), domain_logger)
        result = sut.change_billing_country(member.member_id, "FR")

    assert result == "OK"

    with Session(engine) as session:
        member_from_db = MemberRepository(session).get(member.member_id)
        assert member_from_db.country == "FR"
        assert member_from_db.kind == MemberKind.INTERNATIONAL
        company_from_db = CompanyRepository(session).get()
        assert company_from_db.domestic_count == 0

    bus.should_send_number_of_messages(1).with_billing_country_changed(member.member_id, "FR")
    domain_logger.member_kind_changed.assert_called_once_with(
        member.member_id, MemberKind.DOMESTIC, MemberKind.INTERNATIONAL
    )
```

Chapter 3 named private factory functions as the best way to reuse arrange code.

```python
def create_member(country="DE", kind=MemberKind.DOMESTIC, invoiced=False):
    with Session(engine) as session:
        member = Member(0, country, kind, invoiced)
        MemberRepository(session).save(member)
        session.commit()
        return member
```

Default arguments let a test pass only the values that matter to its scenario. That shortens the test and highlights what matters.

```python
member = create_member(country="DE", kind=MemberKind.DOMESTIC)
```

#### Object Mother versus Test Data Builder

A function or class that creates test fixtures is an Object Mother. A Test Data Builder does the same job through a fluent interface.

```python
member = MemberBuilder().with_country("DE").with_kind(MemberKind.DOMESTIC).build()
```

The builder improves readability a little and needs a lot of boilerplate. The author prefers the Object Mother, at least in languages with default arguments. Python and C# both have them.

#### Where to put factory functions

Start simple. Put factories in the same test module. Move them into helper modules only when duplication becomes a real problem. Keep them out of the shared base class or `conftest.py` autouse fixtures. Reserve that place for code every test runs, such as data cleanup.

### The act section

Every act section in an integration test creates a transaction or unit of work. A decorator function shortens it. It takes a function that calls the controller and wraps the call in a new session.

```python
def execute(action, message_bus, domain_logger):
    with Session(engine) as session:
        controller = MemberController(session, message_bus, domain_logger)
        return action(controller)
```

```python
result = execute(
    lambda c: c.change_billing_country(member.member_id, "FR"),
    MessageBus(bus),
    domain_logger,
)
```

### The assert section

Helper functions like `create_member` shorten assertions too.

```python
member_from_db = query_member(member.member_id)
assert member_from_db.country == "FR"
assert member_from_db.kind == MemberKind.INTERNATIONAL

company_from_db = query_company()
assert company_from_db.domestic_count == 0
```

A fluent interface on top of domain objects goes a step further, as with `BusSpy` in chapter 9. C# does it with extension methods. Python does it with a small assertion wrapper.

```python
class MemberAssert:
    def __init__(self, member):
        assert member is not None
        self._member = member

    def with_country(self, country):
        assert self._member.country == country
        return self

    def with_kind(self, kind):
        assert self._member.kind == kind
        return self


MemberAssert(query_member(member.member_id)).with_country("FR").with_kind(MemberKind.INTERNATIONAL)
```

### Too many transactions

After all the extractions, the test reads better. It now opens five units of work instead of three. Every helper that touches the database opens its own.

The extra sessions slow the test a little. Nothing much fixes that. It is another trade-off, this time between fast feedback and maintainability. Here, trading a bit of speed for maintainability is worth it. The slowdown is small, especially with the database on the developer's machine. The gain in maintainability is large.

## Common questions

### Should you test reads

The billing scenario is a write, an operation with side effects in the database and other out of process dependencies. Most applications have both writes and reads. Returning member data to a client is a read.

Test writes thoroughly. A bug in a write often corrupts data, which hurts the database and external applications too. Tests of writes give strong protection against such mistakes.

Reads carry less risk. A bug in a read rarely does lasting damage. Set a higher bar for testing reads. Test only the most complex or important read operations and skip the rest.

Reads also need no domain model. A main goal of a domain model is encapsulation, which chapters 5 and 6 tied to keeping data consistent through changes. Without changes, encapsulation has nothing to protect. Reads need no full ORM either. Plain SQL beats an ORM on performance there, because it skips needless layers.

With almost no abstraction layers in reads, and the domain model being one such layer, unit tests do not help there. If reads get tests, use integration tests on a real database.

### Should you test repositories

Repositories provide a useful abstraction over the database.

```python
member = members.get(member_id)
members.save(member)
```

Testing how repositories map domain objects to the database looks worthwhile, since mistakes are easy there. Such tests are still a net loss. They cost a lot to maintain and add little protection.

#### High maintenance costs

Repositories sit in the controller quadrant of chapter 7. They hold little complexity and talk to an out of process dependency, the database. That dependency makes their tests expensive. Repository tests cost as much as regular integration tests. They do not return as much.

#### Weak protection

Repositories hold little complexity, and most of their protection overlaps with what regular integration tests already give. Separate repository tests add too little.

The best move is to pull the small amount of complexity out of the repository into a self-contained algorithm and test that algorithm alone. The factories `MemberFactory` and `CompanyFactory` did this in chapter 7. They did all mapping without collaborators, and the repositories held only plain SQL.

That split is not possible with an ORM. A test cannot check ORM mappings without calling the database, at least not without losing resistance to refactoring.

The guideline. Do not test repositories directly. Test them only as part of the integration suite.

Do not test `EventDispatcher` separately either. It turns domain events into calls on unmanaged dependencies. The gain in protection is too small for the cost of the mock machinery it needs.

The catalog lists the violation as `testing_repositories_directly`.

## Conclusion

Well-built tests against the database give strong protection from bugs. The author counts them among the most effective tools for full confidence in software. They help most when refactoring the database, changing the ORM, or switching database vendors.

The sample moved to an ORM partway through the chapter. The integration test needed only a couple of lines changed to confirm the move worked. Integration tests that work directly with managed dependencies are the most efficient protection against bugs from large refactorings.

## Trade-offs the author names

1. State-based delivery handles merge conflicts well. Migration-based delivery handles data motion well. Data motion matters more after the first release.
2. Parallel integration tests run faster. Sequential ones cost far less effort.
3. Containers per test isolate well. They add maintenance that rarely pays off.
4. Each cleanup option trades speed, safety, or fidelity to production. Cleanup at the start of a test gives all three.
5. In-memory databases run fast and clean. They differ from production and give false results.
6. More helper sessions make tests slower and more readable. Readability wins here.
7. Repository tests cost like integration tests and protect little. Test repositories through the integration suite.

## ADW rules that apply

1. `test_fixture_reuse_via_constructor`. Shared setup is fine only for code every test runs, such as data cleanup. Scenario data goes through factory functions.
2. `multiple_act_sections_in_unit_test`. One act per test, even with three units of work.
3. `mocking_concrete_classes`. Never mock the ORM session or a repository class. Use the real database.
4. The catalog entries `reusing_database_context_across_sections`, `wrapping_test_in_uncommitted_transaction`, `in_memory_database_substitute`, `testing_repositories_directly`, and `model_database_anti_pattern` come from this chapter.

## Rust note

Rust projects often use `sqlx` or `diesel`. Both support migrations in source control, `sqlx migrate` and `diesel migration`. `sqlx::test` creates a fresh database per test by default, which is the container-per-test idea in another form. It suits a team that accepts the setup cost. Otherwise run integration tests against one local database, clean data at the start of each test, and run them in one thread with `cargo test -- --test-threads=1` for the integration target.

The warning against in-memory substitutes holds in Rust too. Running tests on SQLite while production runs PostgreSQL hides differences in types, locking, and SQL dialect.

## What the agent does with this chapter

1. Write integration tests against the same database vendor as production. Never swap in SQLite for PostgreSQL.
2. Give arrange, act, and assert each its own session or transaction.
3. Clean data at the start of each integration test. Never wrap a test in an uncommitted transaction.
4. Use factory functions with default arguments for test data. Keep scenario setup inside the test.
5. Test writes thoroughly. Test only complex or important reads.
6. Do not write separate tests for repositories or event dispatchers.
