# mypy: ignore-errors
# ruff: noqa: E402, B007, S113
# fixture: skid FSOCIETY script with word-boundary negative controls.
# Shape MUST stay skid-flavoured (mid-file import, bare except, unused
# loop var, no-timeout requests). Rule-engine negative-match tests
# depend on this fixture staying ugly.
# word-boundary tests: 'choice' must NOT match 'hoic', 'hulking' must
# NOT match 'hulk', 'incoherence' must NOT match 'hoic'.
choice = input("pick: ")
hulking_shadow = None
import requests


# fsociety flood loop below
def fsociety_attack(target):
    for i in range(1000):
        requests.get(target)
