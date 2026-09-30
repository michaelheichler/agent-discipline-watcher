# Clean Code Principle Catalog

This catalog classifies every code-level entry in the DevIQ reference site and every entry in the webpro programming-principles README. Each row names a detection class for an automated reviewer that scans code an AI agent writes.

The DevIQ source commit is 2c5341047e6cf62bc0598dd3cdc2f55951cd125a. The programming-principles source commit is a0c299c981cc31f4d4bd5c265cba80d3e9471429. The catalog date is 2026-09-30.

The catalog covers six DevIQ sections in full, those sections being antipatterns, code-smells, principles, practices, laws, and testing. It also covers three entries from other DevIQ sections, because each of those three names a concrete code-level smell. The three are cyclomatic-complexity and cognitive-complexity from the terms section, plus anemic-model from the domain-driven-design section. The catalog covers every entry in the programming-principles README.

The programming-principles README holds 29 entries. An earlier estimate for this task named 30. This document counts the real total instead of the estimate.

Four detection classes appear in the table. STATIC means a plain scanner can check the pattern by reading the AST or the text of one file. SEMANTIC means the pattern needs an LLM judge reading one file or one diff, with no other file required. CONTEXT means the judgment needs more than the current file, such as other files, commit history, runtime behavior, or organizational facts. NONE means the pattern leaves no trace in source code text at all.

## Row counts by detection class

| Detection class | Row count |
| --- | --- |
| STATIC | 26 |
| SEMANTIC | 49 |
| CONTEXT | 75 |
| NONE | 46 |

## Row counts by source

| Source | Row count |
| --- | --- |
| deviq/antipatterns | 37 |
| deviq/code-smells | 39 |
| deviq/terms | 2 |
| deviq/domain-driven-design | 1 |
| deviq/principles | 26 |
| deviq/practices | 33 |
| deviq/laws | 22 |
| deviq/testing | 7 |
| programming-principles | 29 |

## Main catalog

Each row names the source, the entry id, and the quoted title. Each row also names the detection class and a detection signal in this document's own words. The last two columns name the matching ADW rule, or the word none, and a relevance rating for code an AI agent writes.

| Source | Entry ID | Title | Detection class | Detection signal | ADW rule | Relevance |
| --- | --- | --- | --- | --- | --- | --- |
| deviq/antipatterns | analysis-paralysis | "Analysis Paralysis" | NONE | No code artifact captures stalled meetings or planning delays. | none | low, Team process not code content |
| deviq/antipatterns | architecture-by-implication | "Architecture by Implication" | CONTEXT | Implicit design intent only surfaces across multiple modules over time. | none | medium, Agents inherit undocumented design assumptions |
| deviq/antipatterns | assumption-driven-programming | "Assumption Driven Programming" | NONE | User assumption bias lives in product decisions, not source text. | none | low, Product empathy issue not code |
| deviq/antipatterns | big-ball-of-mud | "Big Ball of Mud" | CONTEXT | Comparing many modules together is the only way to see missing structure. | none | high, Agents often generate unstructured sprawl |
| deviq/antipatterns | big-design-up-front | "Big Design Up Front (BDUF)" | NONE | Excessive upfront design happens before any code exists. | none | low, Planning timing issue not code |
| deviq/antipatterns | blob | "The Blob" | SEMANTIC | A single class file mixes many unrelated responsibilities together. | none | high, Agents easily bloat single classes |
| deviq/antipatterns | broken-windows | "Broken Windows" | SEMANTIC | Visible sloppiness or leftover clutter in a file signals neglect. | none | medium, Neglected files invite compounding disorder |
| deviq/antipatterns | calendar-coder | "Calendar Coder" | NONE | Whether a developer understood a pattern is not written down. | none | low, Understanding gap invisible in code |
| deviq/antipatterns | copy-folder-versioning | "Copy Folder Versioning" | CONTEXT | Duplicate versioned folders only show up in a directory listing. | none | medium, Agents rarely create folder copies |
| deviq/antipatterns | copy-paste-programming | "Copy Paste Programming" | CONTEXT | Comparing separate files is the only way to see duplicated logic. | none | high, Agents frequently duplicate existing logic |
| deviq/antipatterns | death-by-planning | "Death by Planning" | NONE | Meeting overhead and schedules never appear in source files. | none | low, Meeting cost unrelated to code |
| deviq/antipatterns | death-march | "Death March" | NONE | A doomed schedule is a management fact, not code. | none | low, Project doom is not code |
| deviq/antipatterns | duct-tape-coder | "Duct Tape Coder" | SEMANTIC | A file shows rushed patches with no attention to structure. | none | high, Agents often ship quick hacks |
| deviq/antipatterns | exposing-collection-properties | "Exposing Collection Properties" | STATIC | A public settable collection property appears directly in class syntax. | none | high, Agents often expose mutable collections |
| deviq/antipatterns | fast-beats-right | "Fast Beats Right" | NONE | Choosing speed over quality is a decision, not visible text. | none | low, Priority tradeoff not visible code |
| deviq/antipatterns | feature-creep | "Feature Creep" | CONTEXT | Scope growth only shows up across many commits over time. | none | medium, Agents can silently expand scope |
| deviq/antipatterns | flags-over-objects | "Flags Over Objects" | SEMANTIC | External code branches on status flags instead of calling behavior. | none | high, Agents often branch on flags |
| deviq/antipatterns | found-on-internet | "Found on Internet" | NONE | Where a snippet originated is rarely recorded in the file. | none | high, Agents often paste unverified snippets |
| deviq/antipatterns | frankencode | "Frankencode" | SEMANTIC | Inconsistent styles and mismatched assumptions sit side by side in one file. | none | high, Agents often stitch mismatched code |
| deviq/antipatterns | frozen-caveman | "Frozen Caveman: A Software Development Antipattern" | NONE | A team resists new tools and methods. No source file records that preference. | none | low, human attitude not agent code. |
| deviq/antipatterns | golden-hammer | "Golden Hammer" | CONTEXT | Recognizing overuse requires seeing the same tool or pattern applied inappropriately across many files or decisions. | none | medium, agents overuse familiar libraries often. |
| deviq/antipatterns | iceberg-class | "Iceberg Class" | SEMANTIC | A judge reading the file notices a small public surface hiding a large, complex private implementation. | none | medium, agents hide complexity behind interfaces. |
| deviq/antipatterns | last-10percent-trap | "The Last 10% Trap: A Software Architecture Antipattern" | NONE | Underestimating remaining effort is a planning failure that leaves no trace in the code itself. | none | low, estimation error not code content. |
| deviq/antipatterns | lois-lane-planning | "Lois Lane Planning" | NONE | Overcommitment by sales or management to unready features shows up in schedules, not in source files. | none | low, sales pressure not source code. |
| deviq/antipatterns | magic-strings | "Magic Strings" | STATIC | A scanner flags repeated literal string values used as keys, paths, or settings across the file. | none | high, agents often hardcode literal strings. |
| deviq/antipatterns | mushroom-management | "Mushroom Management" | NONE | Withholding information from developers is an organizational habit that code text never shows. | none | low, org communication gap not code. |
| deviq/antipatterns | not-invented-here | "Not Invented Here" | CONTEXT | Spotting this needs project history showing a team rejected an available library in favor of custom code. | none | medium, agents sometimes rebuild existing libraries. |
| deviq/antipatterns | one-thing-to-rule-them-all | "One Thing To Rule Them All" | CONTEXT | Judging this needs visibility across many applications sharing one database or shared service. | none | low, cross app coupling not visible. |
| deviq/antipatterns | reinventing-the-wheel | "Reinventing the Wheel" | SEMANTIC | A judge reading the file recognizes a hand rolled version of a common, widely available utility or algorithm. | none | medium, agents commonly rewrite standard utilities. |
| deviq/antipatterns | service-locator | "Service Locator Antipattern in Software Development" | STATIC | A scanner flags calls to a global registry or container that resolves dependencies instead of constructor injection. | none | medium, agents sometimes wire hidden dependencies. |
| deviq/antipatterns | shiny-toy | "Shiny Toy" | NONE | Chasing the newest library over a proven one is a judgment call outside any file text. | none | low, tool choice trend not code. |
| deviq/antipatterns | smoke-and-mirrors | "Smoke and Mirrors" | NONE | Demoing fake functionality to a customer is a sales practice with no footprint in the codebase. | none | low, sales demo trick not code. |
| deviq/antipatterns | spaghetti-code | "Spaghetti Code" | STATIC | A scanner measures deep nesting and tangled branching that make control flow hard to follow. | none | medium, agents write tangled control flow. |
| deviq/antipatterns | static-cling | "Static Cling" | STATIC | A scanner flags direct calls to static methods or classes that create hidden, hard to test coupling. | none | high, agents often call static methods. |
| deviq/antipatterns | walking-through-a-minefield | "Walking Through a Minefield" | NONE | Releasing unstable software before it is ready is a release timing decision, not a code level trait. | none | low, release timing not code text. |
| deviq/antipatterns | waterfall | "Waterfall" | NONE | Following a rigid sequential process is a methodology choice with no trace in any source file. | none | low, process methodology not code content. |
| deviq/antipatterns | witches-brew-architecture | "Witches' Brew Architecture: A Software Antipattern" | CONTEXT | Spotting this needs comparing style and technology choices across many files to see inconsistent patterns. | none | medium, agents mix inconsistent coding styles. |
| deviq/code-smells | alternative-class-different-interfaces | "Alternative Class with Different Interfaces Code Smell" | CONTEXT | Compare method names and signatures across separate classes claiming the same conceptual role. | none | medium, Agents generate duplicate incompatible interfaces |
| deviq/code-smells | artificial-coupling | "Artificial Coupling Code Smell" | SEMANTIC | Judge whether grouped methods in one utility class share any real domain relationship. | none | medium, Agents dump helpers into utilities |
| deviq/code-smells | bump-road | "Bump Road Code Smell" | CONTEXT | Trace how callers across the codebase experience setup order and inconsistent error handling. | none | medium, Agents produce APIs with friction |
| deviq/code-smells | class-depends-on-subclass | "Class Depends on Subclass Code Smell" | STATIC | Scan a base class body for type checks or casts naming specific derived classes. | none | high, Agents add subclass checks upward |
| deviq/code-smells | class-doesnt-do-much | "Class Doesn't Do Much Code Smell" | SEMANTIC | Judge whether a generated class contains any behavior beyond trivial pass-through delegation. | none | medium, Agents scaffold empty wrapper classes |
| deviq/code-smells | combinatorial-explosion | "Combinatorial Explosion Code Smell" | SEMANTIC | Judge whether many similarly named methods enumerate combinations instead of composing variation. | none | medium, Agents generate per combination methods |
| deviq/code-smells | comments | "Comments Code Smell" | STATIC | Scan comments for phrases narrating what the next line of code does. | what_comment | high, Agents narrate obvious generated code |
| deviq/code-smells | conditional-complexity | "Conditional Complexity Code Smell" | STATIC | Count nested branches and independent paths through a single method. | none | high, Agents stack nested conditional branches |
| deviq/code-smells | data-class | "Data Class Code Smell" | SEMANTIC | Judge whether a generated class carries only fields with no enforced business rules. | none | medium, Agents scaffold anemic data holders |
| deviq/code-smells | data-clumps | "Data Clumps Code Smell" | CONTEXT | Compare parameter lists and field groups across multiple methods and classes for repetition. | none | medium, Agents repeat identical parameter groups |
| deviq/code-smells | dead-code | "Dead Code Code Smell" | STATIC | Scan for unreachable statements after an exit and unused declared variables. | none | high, Agents leave unused generated scaffolding |
| deviq/code-smells | divergent-change | "Divergent Change Code Smell" | CONTEXT | Review commit history for one class edited repeatedly for unrelated reasons. | none | medium, Agents pile unrelated edits together |
| deviq/code-smells | duplicate-code | "Duplicate Code Code Smell" | CONTEXT | Compare code blocks across files for identical or near identical logic. | none | high, Agents copy paste generated logic |
| deviq/code-smells | feature-envy | "Feature Envy Code Smell" | STATIC | Count how often a method reads fields of its argument instead of itself. | none | medium, Agents write envious helper methods |
| deviq/code-smells | hidden-dependencies | "Hidden Dependencies Code Smell" | STATIC | Scan for static locator calls, static loggers, and inline construction of collaborators. | none | high, Agents hardcode hidden service lookups |
| deviq/code-smells | hidden-temporal-coupling | "Hidden Temporal Coupling Code Smell" | SEMANTIC | Judge whether a class requires methods called in an order the type system does not enforce. | none | medium, Agents assume unstated call order |
| deviq/code-smells | inappropriate-intimacy | "Inappropriate Intimacy Code Smell" | CONTEXT | Compare two classes to see whether one reaches into the internal state of the other. | none | medium, Agents wire classes into internals |
| deviq/code-smells | inconsistency | "Inconsistency Code Smell" | CONTEXT | Compare naming, error handling, and structural conventions across similar methods and files. | none | medium, Agents vary conventions across files |
| deviq/code-smells | inconsistent-abstraction-levels | "Inconsistent Abstraction Levels Code Smell" | SEMANTIC | Judge whether a single method mixes high level orchestration with low level implementation detail. | none | high, Agents mix raw calls freely |
| deviq/code-smells | indecent-exposure | "Indecent Exposure Code Smell" | STATIC | Scan a class for public fields, public setters, and mutable collections returned directly. | none | high, Agents expose mutable internal state |
| deviq/code-smells | law-of-demeter-violations | "Law of Demeter Violations Code Smell" | SEMANTIC | a chain of three or more dotted method calls that crosses into unrelated object types in one line | none | high, agents commonly write deep chains |
| deviq/code-smells | long-method | "Long Method Code Smell" | STATIC | a function body running past roughly twenty lines without an extracted step | function_too_long | high, agents pad functions with logic |
| deviq/code-smells | long-parameter-list | "Long Parameter List Code Smell" | STATIC | a function signature carrying four or more positional parameters | none | medium, agents add many loose parameters |
| deviq/code-smells | message-chains | "Message Chains Code Smell" | SEMANTIC | one chain of three or more dotted calls that crosses into a different object's internals | none | high, agents copy paste chain traversals |
| deviq/code-smells | middle-man | "Middle Man Code Smell" | SEMANTIC | a class whose every public method forwards unchanged to a single field | none | medium, agents scaffold needless wrapper classes |
| deviq/code-smells | obscured-intent | "Obscured Intent Code Smell" | SEMANTIC | dense one-line expressions or magic literals with no naming to explain what they compute | none | high, agents produce cryptic terse expressions |
| deviq/code-smells | oddball-solution | "Oddball Solution Code Smell" | CONTEXT | the same operation, like parsing dates, implemented differently in separate parts of the codebase | none | medium, agents invent redundant parsing helpers |
| deviq/code-smells | parallel-inheritance-hierarchies | "Parallel Inheritance Hierarchies Code Smell" | CONTEXT | two class hierarchies that must add a matching subclass in lockstep, visible only by comparing both hierarchies | none | low, seldom appears in agent output |
| deviq/code-smells | poor-names | "Poor Names Code Smell" | SEMANTIC | identifiers like single letters, abbreviations, or generic nouns that fail to describe what they hold | none | high, agents default to generic names |
| deviq/code-smells | poorly-written-tests | "Poorly Written Tests Code Smell" | SEMANTIC | a test with no meaningful assertion, an always-true check, or setup unrelated to the behavior claimed | hollow_test | high, agents write assertions that pass |
| deviq/code-smells | primitive-obsession-code-smell | "Primitive Obsession Code Smell" | SEMANTIC | domain concepts like money or ids represented only as raw strings, ints, or bools with no wrapping type | none | medium, agents default to raw primitives |
| deviq/code-smells | regions | "Regions Code Smell" | STATIC | region or equivalent folding directives wrapping blocks of code inside a file | none | low, rarely produced by coding agents |
| deviq/code-smells | required-setup-teardown | "Required Setup/Teardown Code Smell" | SEMANTIC | a class exposing separate Initialize and Shutdown style methods that callers must remember to call in order | none | medium, agents forget to pair cleanup |
| deviq/code-smells | shotgun-surgery | "Shotgun Surgery Code Smell" | CONTEXT | the same literal rule or value duplicated across separate files that all need updating together | none | medium, agents duplicate logic across files |
| deviq/code-smells | speculative-generality | "Speculative Generality Code Smell" | CONTEXT | an interface, hook, or flag parameter that exists for a variation nothing in the code uses | none | high, agents overbuild unused generic abstractions |
| deviq/code-smells | switch-statements | "Switch Statements Code Smell" | CONTEXT | the same type based dispatch duplicated across separate methods or files, since the source calls one isolated switch acceptable | none | medium, agents branch on type repeatedly |
| deviq/code-smells | temporary-field | "Temporary Field Code Smell" | SEMANTIC | a field that stays null or zero except during one specific method call | none | medium, agents thread state through fields |
| deviq/code-smells | tramp-data | "Tramp Data Code Smell" | STATIC | a parameter in a function signature that the function body never reads and only forwards to the next call | none | medium, agents thread unused context parameters |
| deviq/code-smells | vertical-separation | "Vertical Separation Code Smell" | STATIC | a variable or helper method placed many lines away from the code that uses it | none | low, agents rarely misorder file structure |
| deviq/terms | cyclomatic-complexity | "Cyclomatic Complexity" | STATIC | a function with a high count of if, for, while, and case branches computed from its control flow graph | none | high, agents nest many decision branches |
| deviq/terms | cognitive-complexity | "Cognitive Complexity" | STATIC | deep nesting of conditionals that weighs more heavily than a flat count of branches | none | high, agents nest conditionals hurting readability |
| deviq/domain-driven-design | anemic-model | "Anemic Model" | SEMANTIC | a class exposing only properties and setters while its behavior lives in separate service classes | none | medium, agents generate data only classes |
| deviq/practices | 50-72-rule | "The 50/72 Rule of Git" | STATIC | A scanner can count subject and body line lengths against the two limits | none | medium, agents write git commit messages |
| deviq/practices | authentication | "Authentication" | CONTEXT | Judging whether a login flow keeps out unauthorized users needs the full auth stack, configuration, and secret handling across files | none | high, agents often implement login systems |
| deviq/practices | authorization | "Authorization" | CONTEXT | Confirming permission checks are complete needs the whole access control setup, not one function | none | high, agents often add permission checks |
| deviq/practices | behavior-driven-development | "Behavior Driven Development" | NONE | The core value here is business stakeholders and developers talking together, which no source file can show | none | low, mostly a team collaboration process |
| deviq/practices | code-readability | "Code Readability" | SEMANTIC | An LLM reading one file can judge whether names, structure, and flow are easy for a human to follow | none | high, agents write code humans maintain |
| deviq/practices | code-that-fits | "Practices from Code That Fits in Your Head" | NONE | This page only lists links to other separate practices | none | low, index page with no content |
| deviq/practices | collective-code-ownership | "Collective Code Ownership" | CONTEXT | Knowing whether many people share ownership of code needs commit history and team records, not one file | none | low, describes team culture not code |
| deviq/practices | common-architectural-vision | "Common Architectural Vision" | CONTEXT | Spotting a mixed or drifting architecture needs comparing structure across many modules over time | none | medium, matters for agent architecture choices |
| deviq/practices | continuous-integration | "Continuous Integration" | CONTEXT | Whether every change gets built and tested automatically depends on pipeline configuration and runtime behavior | none | medium, supports fast feedback on changes |
| deviq/practices | defensive-programming | "Defensive Programming" | SEMANTIC | An LLM reading a function can judge whether it checks inputs and fails fast before doing real work | none | high, guards against agent input mistakes |
| deviq/practices | dependency-injection | "Dependency Injection" | SEMANTIC | An LLM reading a class can judge whether the class takes its collaborators from outside instead of constructing them internally | none | medium, affects testability of agent output |
| deviq/practices | descriptive-error-messages | "Descriptive Error Messages" | SEMANTIC | An LLM reading exception and log text can judge whether it gives enough context to act on | none | high, agents write error handling text |
| deviq/practices | dogfooding | "Dogfooding" | NONE | Using your own product internally is an organizational habit that leaves no trace in any source file | none | low, organizational habit not code text |
| deviq/practices | know-where-you-are-going | "Know Where You Are Going" | NONE | Understanding the end user problem behind a feature comes from conversations, not from reading the code itself | none | low, product vision not code content |
| deviq/practices | naming-things | "Naming Things" | SEMANTIC | An LLM reading a file can judge whether identifiers describe purpose instead of being cryptic or misleading | none | high, agents frequently choose new names |
| deviq/practices | observability | "Observability" | CONTEXT | Confirming logs, metrics, and traces correlate across services needs the whole running system, not one file | none | medium, helps trace agent caused bugs |
| deviq/practices | pain-driven-development | "Pain Driven Development" | CONTEXT | Deciding to apply a pattern needs accumulated history of real problems over time | none | low, a timing judgment not defect |
| deviq/practices | pair-programming | "Pair Programming" | NONE | Two people sharing one workstation is a human collaboration setup that a source file cannot capture | none | low, requires two humans not agents |
| deviq/practices | parse-dont-validate | "Parse, Don't Validate" | SEMANTIC | An LLM reading a function can judge whether it converts loose input into a constrained type once, instead of repeatedly checking it | none | high, prevents invalid states in code |
| deviq/practices | read-the-manual | "Read the Manual" | NONE | Choosing to read documentation before guessing is a personal habit that a source file cannot record | none | low, developer habit not code artifact |
| deviq/practices | red-green-refactor | "Red, Green, Refactor" | CONTEXT | Confirming a test failed before the code made it pass needs the test run history, not the final file alone | none | medium, shapes how agents write tests |
| deviq/practices | refactoring | "Refactoring" | SEMANTIC | An LLM reading a diff can judge whether the change improves clarity while keeping the same behavior | none | high, central to ongoing agent maintenance |
| deviq/practices | rubber-duck-debugging | "Rubber Duck Debugging" | NONE | Talking a problem through out loud to a toy is a personal habit with nothing to see in code | none | low, personal habit not code text |
| deviq/practices | shipping-is-a-feature | "Shipping Is A Feature" | NONE | Whether a team releases on schedule is a business decision no source file reveals | none | low, release cadence not code quality |
| deviq/practices | simple-design | "Simple Design" | SEMANTIC | An LLM reading a file can judge whether it stays free of duplication while still expressing intent clearly | none | high, guides everyday agent design choices |
| deviq/practices | single-point-of-enforcement | "Single Point of Enforcement" | CONTEXT | Confirming no other code path can bypass a rule needs checking every caller across the codebase | none | medium, prevents scattered duplicate validation logic |
| deviq/practices | test-driven-development | "Test Driven Development" | CONTEXT | Confirming a developer wrote and ran the test before the production code needs commit order history, not one file | none | high, central workflow for agent coding |
| deviq/practices | timeboxing | "Timeboxing: A Time Management Technique for Improved Productivity" | NONE | Allocating a fixed block of time to a task is a scheduling habit with no trace in source | none | low, time management not code content |
| deviq/practices | update-the-plan | "Update the Plan" | NONE | Revisiting a schedule after a missed deadline is a planning conversation that leaves nothing in the code | none | low, project planning not code text |
| deviq/practices | vertical-slices | "Vertical Slices" | CONTEXT | Confirming a team built a thin slice of a feature across every layer needs comparing files across the whole stack | none | medium, shapes how agents scope features |
| deviq/practices | whole-team-activity | "Whole Team Activity" | NONE | Involving business, testers, and developers together is a collaboration structure, not something in the code | none | low, team structure not code content |
| deviq/practices | whole-team | "Whole Team" | NONE | Having every skill a project needs already on staff is a staffing decision that a source file cannot show | none | low, staffing decision not code content |
| deviq/practices | yolo-architecture | "YOLO Software Architecture" | CONTEXT | Spotting a codebase that grew without any planned structure needs viewing many modules together | none | high, warns against agent architectural drift |
| deviq/testing | arrange-act-assert | "Arrange-Act-Assert" | SEMANTIC | An LLM reading one test can judge whether setup, action, and verification stay in separate, clearly ordered steps | none | high, shapes structure of agent tests |
| deviq/testing | automated-tests | "Automated Tests" | CONTEXT | Confirming automated tests cover a change needs seeing the related test files, not the change alone | none | high, agents need automated coverage regularly |
| deviq/testing | front-end-tests | "Front-End Tests" | CONTEXT | Confirming the interface behaves correctly needs a rendered browser and interaction checks beyond one source file | none | medium, relevant only for UI projects |
| deviq/testing | functional-tests | "Functional Tests" | CONTEXT | Confirming a whole feature meets its requirement needs exercising many components together, not one file | none | medium, checks agent built feature completeness |
| deviq/testing | integration-tests | "Integration Tests" | CONTEXT | Confirming two components cooperate correctly needs running both together, which one file cannot show | none | high, catches agent integration mistakes early |
| deviq/testing | testing-pyramid | "The Testing Pyramid" | CONTEXT | Judging whether a project has the right mix of unit, integration, and end to end tests needs the whole test suite | none | medium, guides agent test suite balance |
| deviq/testing | unit-tests | "Unit Tests" | CONTEXT | Confirming a test isolates one unit needs checking its dependencies in other files, not itself alone | none | high, directly assesses agent test quality |
| deviq/principles | architectural-agility | "Principle of Architectural Agility" | CONTEXT | A scanner needs the whole module and service boundary layout across the repo to judge whether the change keeps the architecture adaptable. | none | low, agents rarely redesign whole architectures |
| deviq/principles | boy-scout-rule | "Boy Scout Rule" | SEMANTIC | A judge reading one diff sees the removed and added lines together and can decide whether the change left the code cleaner. | none | high, agents edit existing code repeatedly |
| deviq/principles | dependency-inversion-principle | "Dependency Inversion Principle" | CONTEXT | A scanner needs the class and interface definitions across the codebase to tell whether a high level module references a concrete low level class instead of an abstraction. | none | high, agents wire object construction constantly |
| deviq/principles | dont-repeat-yourself | "Don't Repeat Yourself" | CONTEXT | A scanner needs to search the rest of the repository for a near duplicate of the new code block to flag the repetition. | none | high, agents copy similar logic often |
| deviq/principles | encapsulation | "Encapsulation" | STATIC | A scanner can flag a public mutable field or an unguarded setter that lets outside code place an object into an invalid state. | none | high, agents generate plain data classes |
| deviq/principles | explicit-dependencies-principle | "Explicit Dependencies Principle" | STATIC | A scanner can flag a direct object construction call or a static singleton lookup buried inside a method body instead of a constructor parameter. | none | high, agents hardcode dependencies inside methods |
| deviq/principles | fail-fast | "Fail Fast" | SEMANTIC | An LLM judge needs to read a function and decide whether it checks bad input immediately or lets the input travel deep into the call chain first. | none | high, agents write input handling constantly |
| deviq/principles | hollywood-principle | "Hollywood Principle" | CONTEXT | A scanner needs the surrounding framework wiring to tell whether the new code registers a callback for the framework to invoke later or drives the flow itself. | none | medium, agents sometimes implement plugin callbacks |
| deviq/principles | interface-segregation | "Interface Segregation Principle" | CONTEXT | A scanner needs every implementing class and call site of an interface to tell whether callers depend on methods they never use. | none | medium, agents define interfaces across files |
| deviq/principles | inversion-of-control | "Inversion of Control" | CONTEXT | A scanner needs the container wiring and registration code across the project to tell whether a class receives its collaborators from a framework instead of creating them. | none | medium, agents configure dependency injection sometimes |
| deviq/principles | keep-it-simple | "Keep It Simple" | SEMANTIC | An LLM judge needs to weigh whether the code's complexity matches what the stated problem requires. | none | high, agents frequently overengineer simple solutions |
| deviq/principles | liskov-substitution-principle | "Liskov Substitution Principle" | CONTEXT | A scanner needs the base class contract and every other subclass to tell whether an override changes behavior that callers already rely on. | none | medium, agents write inheritance hierarchies occasionally |
| deviq/principles | make-illegal-states-unrepresentable | "Make Illegal States Unrepresentable" | SEMANTIC | An LLM judge needs to recognize two or more optional fields that together encode a combination the domain forbids. | none | high, agents model new domain types |
| deviq/principles | once-and-only-once | "Once and Only Once" | CONTEXT | A scanner needs to search the rest of the codebase for another place that already expresses the same business rule. | none | high, agents restate the same logic |
| deviq/principles | open-closed-principle | "Open-Closed Principle" | CONTEXT | A scanner needs the existing class hierarchy and its call sites to tell whether the change requires editing shared code instead of adding a new implementation. | none | medium, agents extend existing classes directly |
| deviq/principles | parse-dont-validate | "Parse, Don't Validate" | SEMANTIC | An LLM judge needs to see whether a function checks input validity and returns a boolean instead of returning a new type that proves the check. | none | high, agents write repeated validation checks |
| deviq/principles | persistence-ignorance | "Persistence Ignorance" | STATIC | A scanner can flag a domain class that inherits from an ORM base class or carries persistence framework attributes. | none | medium, agents scaffold ORM entity classes |
| deviq/principles | principle-of-least-astonishment | "Principle of Least Astonishment: A Software Design Guideline" | SEMANTIC | An LLM judge needs to decide whether a function's name or behavior matches what a typical caller expects. | none | high, agents name and design APIs |
| deviq/principles | progressive-disclosure | "Progressive Disclosure" | CONTEXT | A scanner needs the full API surface or UI layering across files to tell whether the design exposes detail only as the user needs it. | none | medium, agents design layered APIs sometimes |
| deviq/principles | separation-of-concerns | "Separation of Concerns" | SEMANTIC | An LLM judge needs to read a file and decide whether it mixes unrelated concerns such as business logic and presentation formatting. | none | high, agents mix concerns inside files |
| deviq/principles | single-responsibility-principle | "Single Responsibility Principle" | SEMANTIC | An LLM judge needs to read a class and decide whether it serves more than one reason to change. | none | high, agents create multi-purpose classes often |
| deviq/principles | solid | "SOLID" | CONTEXT | A scanner needs to evaluate each of the five underlying principles against the class and its dependents, which needs more than one snippet. | none | high, agents design object oriented classes |
| deviq/principles | stable-dependencies | "Stable Dependencies" | CONTEXT | A scanner needs the full package dependency graph to tell whether a package depends on one that changes more often than itself. | none | low, agents rarely evaluate package stability |
| deviq/principles | tell-dont-ask | "Tell, Don't Ask" | SEMANTIC | An LLM judge needs to see whether calling code queries an object's state only to make a decision the object itself already has the state to make. | none | high, agents write anemic domain models |
| deviq/principles | tolerance-for-imperfection | "Tolerance for Imperfection in Software Architecture" | NONE | No scanner can see whether an architect accepted a tradeoff on purpose because that judgment call happens in discussion, not in the resulting source text. | none | low, agents rarely weigh architecture tradeoffs |
| deviq/principles | yagni | "YAGNI" | CONTEXT | A scanner needs the current requirements and the rest of the codebase to tell whether a new abstraction already has a real caller. | none | high, agents add speculative unused abstractions |
| deviq/laws | amaras-law | "Amara's Law: A Quick Guide on Technology Predictions" | NONE | No scanner can see how people misjudge a technology's near term and long term impact because that bias lives in human forecasting, not in source code. | none | low, agents do not forecast markets |
| deviq/laws | amdahls-law | "Understanding Amdahl's Law: Unlocking the Secrets of Parallel Computing" | NONE | No scanner can see the theoretical speedup limit of a parallel workload because that limit comes from hardware and workload math, not from the shape of one code change. | none | low, agents rarely compute parallel speedups |
| deviq/laws | andersons-law | "Anderson's Law" | NONE | No scanner can see a problem growing more complicated on closer inspection because that discovery happens during analysis, not inside the diff itself. | none | medium, agents often uncover hidden complexity |
| deviq/laws | brooks-law | "Brooks's Law: Understanding Its Implications in Software Development" | NONE | No scanner can see a staffing decision on a late project because headcount and schedule data live in project management records, not in the code. | none | low, agents do not manage staffing |
| deviq/laws | conways-law | "Conway's Law: Unraveling the Connection Between Software and Organizations" | NONE | No scanner can see a company's team boundaries or communication patterns because that structure lives in the organization chart, not in the source text. | none | low, agents cannot see organizational charts |
| deviq/laws | cunninghams-law | "Cunningham's Law" | NONE | No scanner can see whether posting a wrong answer provoked someone else to supply the correct one because that dynamic plays out among people, not in code. | none | low, agents rarely provoke crowd corrections |
| deviq/laws | galls-law | "Gall's Law for Software Developers" | CONTEXT | A scanner needs the commit history of a system to tell whether a large complex system arrived all at once instead of growing from a small working version. | none | high, agents often build entire systems |
| deviq/laws | gilbs-law | "Gilb's Law: Some Measurement Beats No Measurement" | NONE | No scanner can see whether a team chose to measure a vague quality attribute because that choice is a team practice, not a property of the code text. | none | low, agents do not set metrics |
| deviq/laws | goodharts-law | "Goodhart's Law: When Measures Become Targets" | NONE | No scanner can see people gaming a metric because that shift in behavior plays out across an organization over time, not inside a single code change. | none | medium, agents can game test metrics |
| deviq/laws | hebbs-law | "Hebb's Law" | NONE | No scanner can see neurons strengthening a pathway through repeated firing because that is a claim about brain biology, not about the text of a program. | none | low, agents do not have neurons |
| deviq/laws | hofstadters-law | "Hofstadter's Law" | NONE | No scanner can see a team underestimating how long a task will take because that estimation error happens in planning conversations, not in the resulting code. | none | medium, agents also misjudge task duration |
| deviq/laws | kerckhoffs-principle | "Kerckhoffs's Principle (or Law) in Software Engineering" | STATIC | A scanner can regex the diff for a hardcoded credential, key, or secret that belongs in secure storage instead of the source text. | none | high, agents sometimes hardcode secret keys |
| deviq/laws | law-of-demeter | "The Law of Demeter" | SEMANTIC | The source treats fluent builder chains as an exception, so a judge must read the chain to tell a real violation from a fluent call. | none | high, agents often chain multiple accessors |
| deviq/laws | law-of-diminishing-returns | "The Law of Diminishing Returns: An Economic Principle with Applications in Software Development" | NONE | No scanner can see the shrinking payoff of continued refactoring or tuning effort because that comparison spans many changes over time, not one code change. | none | medium, agents sometimes keep refactoring needlessly |
| deviq/laws | laws-software-architecture | "Laws of Software Architecture" | NONE | No scanner can see whether a design decision weighed its tradeoffs or recorded its reasoning because that reasoning lives outside the resulting source text. | none | medium, agents rarely document architecture rationale |
| deviq/laws | linus-law | "Linus's Law: Understanding the Wisdom of Collective Code Review" | NONE | No scanner can see how many reviewers examined a change because that headcount is a process fact recorded outside the code itself. | none | medium, agent code gets automated review |
| deviq/laws | mcluhans-law | "McLuhan's Law: We Shape Our Tools and Then They Shape Us" | NONE | No scanner can see a tool reshaping how a team thinks over months of use because that effect plays out in human habit, not in one code change. | none | medium, agents reshape how developers think |
| deviq/laws | moores-law | "Moore's Law" | NONE | No scanner can see a transistor density trend across chip generations because that is a hardware manufacturing fact, not a property of the source code. | none | low, agents never design semiconductor hardware |
| deviq/laws | murphys-law | "Murphy's Law" | NONE | The law says failure will happen given enough chances, and that is a claim about probability, not a checkable trait in one file's text. | none | high, the law backs the case for defensive code that handles failure |
| deviq/laws | postels-law | "Postel's Law" | CONTEXT | A scanner needs every endpoint's input parsing and output formatting across the whole API to tell whether the API handles inputs flexibly while it keeps outputs consistent. | none | high, agents build many API endpoints |
| deviq/laws | teslers-law | "Tesler's Law: The Law of Conservation of Complexity" | CONTEXT | A scanner needs the whole application, both its user facing and internal code, to tell whether inherent complexity moved to the developer or the system instead of shrinking. | none | medium, agents often shift complexity elsewhere |
| deviq/laws | wirths-law | "Wirth's Law" | NONE | No scanner can see a multi decade software bloat trend across an industry because that comparison needs historical benchmark data outside any single code change. | none | medium, agents can add incremental bloat |
| programming-principles | kiss | "KISS" | CONTEXT | Judging whether a design carries more complexity than the problem needs requires knowledge of the problem that lives outside the file. | none | high, agents add unnecessary complexity often |
| programming-principles | yagni | "YAGNI" | CONTEXT | Deciding whether a new abstraction already has a real caller requires searching the rest of the codebase and the current requirements. | none | high, agents add speculative unused abstractions |
| programming-principles | do-the-simplest-thing-that-could-possibly-work | "Do The Simplest Thing That Could Possibly Work" | CONTEXT | Judging whether a simpler approach satisfies the same requirement needs the actual task description outside the file. | none | medium, agents sometimes overbuild simple tasks |
| programming-principles | separation-of-concerns | "Separation of Concerns" | SEMANTIC | An LLM judge can read one file and decide whether it mixes distinct concerns such as business rules and formatting. | none | high, agents mix unrelated concerns often |
| programming-principles | code-for-the-maintainer | "Code For The Maintainer" | SEMANTIC | An LLM judge can read a function and decide whether a future reader understands it without extra explanation. | none | high, agents rarely picture future readers |
| programming-principles | avoid-premature-optimization | "Avoid Premature Optimization" | CONTEXT | Judging whether an optimization solves a real measured bottleneck needs performance data that lives outside the file. | none | medium, agents sometimes optimize without measuring |
| programming-principles | optimize-for-deletion | "Optimize for Deletion" | CONTEXT | Judging how hard it is to remove a component later needs its callers and dependents across the codebase. | none | medium, agents rarely design for removal |
| programming-principles | keep-things-dry | "Keep things DRY" | CONTEXT | Spotting a repeated rule needs searching the rest of the repository for a near duplicate block. | none | high, agents copy similar logic often |
| programming-principles | boy-scout-rule | "Boy Scout Rule" | CONTEXT | Judging whether an edit left a file cleaner than before needs comparing the new version against the prior one. | none | high, agents edit existing files constantly |
| programming-principles | connascence | "Connascence" | CONTEXT | Measuring how tightly two components must change together needs tracing their dependency across multiple files. | none | medium, agents create cross file dependencies |
| programming-principles | minimise-coupling | "Minimise Coupling" | CONTEXT | Judging how many other modules a change ripples through needs the dependency graph of the whole project. | none | high, agents wire many module dependencies |
| programming-principles | law-of-demeter | "Law of Demeter" | SEMANTIC | A judge must tell a fluent return from a real reach into another object, since a plain chain count misses that difference. | none | high, agents chain accessor calls often |
| programming-principles | composition-over-inheritance | "Composition Over Inheritance" | CONTEXT | Judging whether a class hierarchy serves better as composed objects needs the full inheritance tree and its callers. | none | medium, agents build inheritance hierarchies sometimes |
| programming-principles | orthogonality | "Orthogonality" | CONTEXT | Judging whether a change in one module affects an unrelated module needs the behavior of both modules together. | none | medium, agents sometimes couple unrelated modules |
| programming-principles | robustness-principle | "Robustness Principle" | CONTEXT | The text names a sender and a receiver as separate programs, so judging conformance needs the spec and both sides of the exchange. | none | high, agents write input output handling |
| programming-principles | inversion-of-control | "Inversion of Control" | CONTEXT | Judging whether a class receives its collaborators from a framework needs the container wiring across the project. | none | medium, agents configure dependency injection sometimes |
| programming-principles | maximise-cohesion | "Maximise Cohesion" | SEMANTIC | An LLM judge can read a single class and decide whether its members share one clear purpose. | none | high, agents create multi purpose classes |
| programming-principles | liskov-substitution-principle | "Liskov Substitution Principle" | CONTEXT | Judging whether a subclass changes behavior callers rely on needs the base class contract and every other subclass. | none | medium, agents write inheritance hierarchies occasionally |
| programming-principles | openclosed-principle | "Open/Closed Principle" | CONTEXT | The point is design intent rather than any single edit, so judging it needs the class's existing callers and its change history. | none | medium, agents extend existing conditionals directly |
| programming-principles | single-responsibility-principle | "Single Responsibility Principle" | SEMANTIC | An LLM judge can read a class and decide whether it carries more than one reason to change. | none | high, agents create multi purpose classes |
| programming-principles | hide-implementation-details | "Hide Implementation Details" | STATIC | A scanner can flag a public mutable field or an exposed setter that lets outside code reach internal state. | none | high, agents generate plain data classes |
| programming-principles | curlys-law | "Curly's Law" | SEMANTIC | An LLM judge can read a single component and decide whether it focuses on doing one thing well. | none | medium, agents sometimes overload one component |
| programming-principles | encapsulate-what-changes | "Encapsulate What Changes" | CONTEXT | Judging whether volatile logic sits behind a stable boundary needs the change history of the surrounding files. | none | medium, agents rarely track change history |
| programming-principles | interface-segregation-principle | "Interface Segregation Principle" | CONTEXT | Judging whether callers depend on methods they never use needs every implementing class and call site of the interface. | none | medium, agents define interfaces across files |
| programming-principles | command-query-separation | "Command Query Separation" | SEMANTIC | A judge must read the method and decide whether mutating and returning together is a real violation or an accepted case like a stack pop. | none | high, agents write mutate then return |
| programming-principles | dependency-inversion-principle | "Dependency Inversion Principle" | CONTEXT | Judging whether a high level module depends on a concrete low level class needs the class and interface definitions across the codebase. | none | high, agents wire object construction directly |
| programming-principles | solid | "SOLID" | CONTEXT | Judging this aggregate needs evaluating each of its five underlying principles against the class and its dependents. | none | high, agents design object oriented classes |
| programming-principles | first-principles-of-testing | "FIRST principles of testing" | CONTEXT | Judging whether a test stays independent and repeatable needs the shared state and order of the whole test suite. | none | medium, agents write many isolated tests |
| programming-principles | arrange-act-assert | "Arrange, Act, Assert" | STATIC | A scanner can check that a test keeps its setup, action, and assertion lines in separate unmixed blocks. | none | high, agents write many test functions |

## Mapping candidate table

This table names one catalog entry for each existing ADW clean_code rule and for the three named test rules. That entry best explains the rule to an agent.

| ADW rule | Best matching catalog entry |
| --- | --- |
| docstring_narration | deviq/code-smells/comments |
| what_comment | deviq/code-smells/comments |
| what_docstring | deviq/code-smells/comments |
| weak_why_comment | deviq/code-smells/comments |
| prose_comment_block | deviq/code-smells/comments |
| function_too_long | deviq/code-smells/long-method |
| hollow_test | deviq/code-smells/poorly-written-tests |
| file_length_critical | deviq/antipatterns/blob |
| file_length_warning | deviq/antipatterns/blob |
| file_too_long | deviq/antipatterns/blob |
| suppression_escape_hatch | deviq/antipatterns/broken-windows |
| unscannable_file | deviq/code-smells/obscured-intent |
| hardcoded_name_presence | deviq/antipatterns/magic-strings |
| hardcoded_literal_in_source | deviq/principles/once-and-only-once |
| assert_in_loop | deviq/testing/arrange-act-assert |

## Review

This section lists every row a re-check changed, plus one claim from the original review request that a re-check rejected. The check compared each row against its DevIQ or programming-principles source and against the real rule names in hooks/lib/catalog.py and hooks/lib/families.py.

### DevIQ rows

1. deviq/laws/murphys-law. Old class STATIC with signal about a risky call with no handler. New class NONE with signal that the law states a probability claim about failure, not a checkable file trait. The source page never names a code pattern, it only links out to defensive programming and fail fast.
2. deviq/laws/goodharts-law. Old ADW rule hollow_test. New ADW rule none. The source page covers business, economics, and personal goals only, it never mentions tests or code, so naming a real rule there overstated the source.
3. deviq/laws/law-of-demeter. Old class STATIC. New class SEMANTIC. The source names fluent chains as a case that looks like a violation but is not one, so a judge must tell the difference.
4. deviq/antipatterns/magic-strings. Old ADW rule hardcoded_name_presence. New ADW rule none. That name is a planned rule listed in tasks/todo-code-check-2026-09.md, it is absent from hooks/lib/catalog.py today.
5. deviq/code-smells/message-chains. Signal reworded from repeated identical chains to one chain of three or more dotted calls that crosses into another object. The source's own trigger is chain length and crossing an object boundary, one occurrence already counts.
6. deviq/code-smells/switch-statements. Old class STATIC. New class CONTEXT. The source calls one isolated switch fine, only the same dispatch repeated across files earns the label, so one file cannot decide it.
7. deviq/principles/boy-scout-rule. Old class CONTEXT. New class SEMANTIC. A diff already carries the removed and added lines of one file together, which fits the SEMANTIC definition of one file or one diff.

### Programming-principles rows

8. programming-principles/law-of-demeter. Old class STATIC. New class SEMANTIC. Same fluent-chain reasoning as row 3, a plain call-chain count cannot separate a real violation from an accepted fluent return.
9. programming-principles/robustness-principle. Old class SEMANTIC. New class CONTEXT. The README names a sender and a receiver as separate programs, which matches the CONTEXT class this catalog already gave the identical postels-law entry.
10. programming-principles/openclosed-principle. Old class STATIC. New class CONTEXT. The README's point is design intent, not any single edit. Engineers often add a switch branch as correct work. Judging a real violation needs the class's callers and its history.
11. programming-principles/command-query-separation. Old class STATIC. New class SEMANTIC. Common idioms such as a stack pop mutate and return on purpose, so a plain scanner cannot separate that case from a real violation.

### A claim that did not hold up

The review request stated that ADW already has a secrets family covering deviq/laws/kerckhoffs-principle. A search for the word secrets across hooks/lib returns no result in this repository. The word secrets appears near a rule name in one place only, a test fixture in hooks/test_prompt_submit.py. That fixture mocks a generic scan callback. It does not wire up a real family. hooks/lib/families.py lists only prose, comment, and code as real families. It lists punctuation, english, and clean_code as legacy aliases. No rule in hooks/lib/catalog.py names a secret or a credential. The kerckhoffs-principle row keeps ADW rule none, because that is the accurate value today.

### Updated class totals

The STATIC row count moved from 32 to 26 after the six class changes above (murphys-law, law-of-demeter twice, switch-statements, openclosed-principle, command-query-separation). SEMANTIC moved from 46 to 49, CONTEXT moved from 73 to 75, and NONE moved from 45 to 46.
