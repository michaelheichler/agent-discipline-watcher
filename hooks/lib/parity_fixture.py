"""Built from chr calls because two punctuation rules read raw source, so a fixture written plainly would block its own file."""
from __future__ import annotations


FIXTURE_NAME = "parity-fixture.md"

_LONG_DASH = chr(0x2014)
_TICK = chr(0x27)

FIXTURE_TEXT = (
    "---\n"
    "name: parity-fixture\n"
    "description: Frontmatter must stay silent across every runtime.\n"
    "---\n"
    "\n"
    "# Parity fixture\n"
    "\n"
    "The release slipped " + _LONG_DASH + " nobody had checked the build.\n"
    "We shipped it anyway -- the deadline had already passed.\n"
    "The tests were green; the users disagreed.\n"
    "That failure was entirely it" + _TICK + "s own fault.\n"
    "The pattern goes back to the 1990" + _TICK + "s and has not improved.\n"
    "The reviewer said it plainly - the plan was never written down.\n"
    "One rule matters here: the gate must never guess.\n"
    "\n"
    "It is very clear that this was basically a really simple oversight.\n"
    "There was a decision made by the team to defer the work.\n"
)
