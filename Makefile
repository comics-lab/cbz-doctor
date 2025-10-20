.PHONY: venv test clean
    PY?=python3
    PIP?=pip3
    VENV=.venv
    ACTIVATE=$(VENV)/bin/activate
    venv:
    	$(PY) -m venv $(VENV)
    	. $(ACTIVATE) && $(PIP) install -U pip wheel && $(PIP) install -r requirements.txt || true
    test:
    	. $(ACTIVATE) && $(PY) - <<'PY'
print("No tests yet.")
PY
    clean:
    	rm -rf __pycache__ .pytest_cache *.log *.csv
