.PHONY: test eval

test:
	python -m pytest

eval:
	python -m membercare.evals
