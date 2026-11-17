# fixture: skid FSOCIETY script with word-boundary negative controls
# word-boundary tests: 'choice' must NOT match 'hoic', 'hulking' must
# NOT match 'hulk', 'incoherence' must NOT match 'hoic'.
choice = input("pick: ")
hulking_shadow = None
import requests
# fsociety flood loop below
def fsociety_attack(target):
    for i in range(1000):
        requests.get(target)
