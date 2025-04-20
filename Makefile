precommit:
	pre-commit run --all-files

test:
	uv run pytest

ready:
	$(MAKE) precommit
	$(MAKE) test

itso:
	$(MAKE) precommit
	$(MAKE) test
	git add -A
	git commit --amend --no-edit
	git push -f

patch:
	$(MAKE) ready || exit 1
	uvx bump-my-version bump patch
	git push origin main --tags --force
