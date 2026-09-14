# Entwicklungs- und Betriebsaufgaben.
# Der Kern laeuft ohne Fremdpakete; "make test" braucht nur Python 3.11 und PyYAML.

PYTHON ?= python3
FLOWS  := config/flows
export PYTHONPATH := src

.PHONY: help test test-schnell pruefen graph spielen lint typen start format clean modelle

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

test:  ## Gesamte Testsuite (Standardbibliothek, keine Installation noetig)
	$(PYTHON) -m unittest discover -s tests -t . -v

test-schnell:  ## Nur die schnellen Tests ohne Gespraechssimulation
	$(PYTHON) -m unittest tests.test_flow_engine tests.test_flow_loader tests.test_nlu_german tests.test_nlu_rules tests.test_audio

pruefen:  ## Alle Entscheidungsbaeume statisch pruefen
	$(PYTHON) -m telefonbot.cli pruefen $(FLOWS)/*.yaml

graph:  ## Mermaid-Diagramme aller Baeume nach var/ schreiben
	@mkdir -p var
	@for f in $(FLOWS)/*.yaml; do \
		$(PYTHON) -m telefonbot.cli graph $$f -o var/$$(basename $$f .yaml).mmd; \
	done

spielen:  ## Dialog im Terminal durchspielen (FLOW=... waehlbar)
	$(PYTHON) -m telefonbot.cli spielen $(or $(FLOW),$(FLOWS)/lehrstuhl_sekretariat.yaml)

start:  ## Dienst starten
	$(PYTHON) -m telefonbot.cli start -c config/config.yaml

lint:  ## ruff (optional installiert)
	ruff check src tests

typen:  ## mypy (optional installiert)
	mypy src

format:  ## ruff format
	ruff format src tests

modelle:  ## Whisper- und Piper-Modelle einmalig herunterladen
	$(PYTHON) scripts/modelle_laden.py

clean:
	rm -rf var/tts-cache var/*.mmd .pytest_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
