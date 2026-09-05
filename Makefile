.PHONY: build test
build:
	python3 scripts/build.py

test:
	python3 -m unittest discover -s tests -v
