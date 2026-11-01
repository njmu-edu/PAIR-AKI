PYTHON ?= python3
STATE ?= $(HOME)/.local/state/pair-aki/demo

.PHONY: test demo serve web-install web-dev web-build check

test:
	$(PYTHON) -B -m unittest discover -s tests -v

demo:
	$(PYTHON) -B -m pair_aki.server --state-dir "$(STATE)" --scripted-demo --synthetic-medical --static web/dist

serve:
	$(PYTHON) -B -m pair_aki.server --state-dir "$(STATE)" --synthetic-medical --static web/dist

web-install:
	cd web && npm ci --ignore-scripts

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

check: test
	$(PYTHON) -B tools/check_publication.py
