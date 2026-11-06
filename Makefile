PYTHON ?= .venv/bin/python
CLI ?= .venv/bin/vulnloc
.PHONY: verify reproduce test scan paper
verify:
	$(CLI) verify
reproduce:
	$(CLI) reproduce
verify-results:
	$(CLI) verify-results
test:
	$(PYTHON) -m unittest discover -s tests -v
scan:
	$(PYTHON) scripts/scan_candidate.py
paper:
	latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir="$(CURDIR)/.local/tex-build" -cd paper/main.tex
