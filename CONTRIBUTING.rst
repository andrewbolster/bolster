.. highlight:: shell

============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given.

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/andrewbolster/bolster/issues.

Please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Fix Bugs
~~~~~~~~

Look through the GitHub issues for bugs. Anything tagged with ``bug`` and
``help wanted`` is open to whoever wants to implement it.

Add Data Sources
~~~~~~~~~~~~~~~~

The most common contribution is a new data source module. Open issues labelled
``data-source-candidate`` are evaluated and waiting to be built. See
`Data Source Development`_ below for the full workflow.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub issues for features tagged ``enhancement`` and
``help wanted``.

Write Documentation
~~~~~~~~~~~~~~~~~~~

Bolster can always use more documentation — docstrings, RST pages, or blog
posts. The ``docs/`` directory uses Sphinx.

Submit Feedback
~~~~~~~~~~~~~~~

File an issue at https://github.com/andrewbolster/bolster/issues.

Get Started!
------------

Ready to contribute? Here's how to set up ``bolster`` for local development.

1. Clone the repo directly (no fork needed — branch from ``main``)::

    $ git clone git@github.com:andrewbolster/bolster.git
    $ cd bolster

2. Install all dependencies (runtime + dev) using ``uv``::

    $ uv sync --all-extras --dev

3. Install pre-commit hooks::

    $ uv run pre-commit install

4. Create a branch::

    $ git checkout -b feat/<name>   # new feature
    $ git checkout -b fix/<name>    # bug fix

5. Make your changes, then lint and test::

    $ uv run pre-commit run --all-files
    $ uv run pytest tests/ -q --no-cov        # quick local run
    $ make test                               # full run with coverage

6. Push and open a pull request::

    $ git push -u origin feat/<name>
    $ gh pr create

   Wait for CI to go green before requesting a merge. **Do not** push
   additional commits while other PRs are running CI — NISRA and similar
   upstreams rate-limit concurrent requests and a cache miss in one job
   can cause a 503 in another.

Pull Request Guidelines
-----------------------

Before submitting a pull request:

1. **Tests** — include real-data integrity tests. No mocks. Use
   ``scope="class"`` fixtures so the network call is made once per class.
2. **Coverage** — new code must reach >90%. ``cli.py`` is deliberately
   excluded from coverage checks.
3. **Docs** — if you add a new data source, update ``README.md``
   (coverage table) and ``docs/data_sources.rst``. Add a docstring with
   an ``Example:`` section.
4. **Lint** — ``uv run pre-commit run --all-files`` must be clean before
   push. The ``pre-push`` hook enforces the coverage gate automatically.
5. **Python versions** — CI tests 3.11, 3.12, and 3.13. Check that all
   three matrix jobs pass.

Data Source Development
-----------------------

Adding a new data source follows a three-step agent workflow documented
in ``AGENTS.md``:

``data-explore``
    Evaluates a ``data-source-candidate`` issue — checks accessibility,
    format, PxStat availability, and complexity. Posts a scored evaluation
    comment on the issue.

``data-build``
    Builds the production module, tests, and CLI from a *RECOMMENDED*
    evaluation. Works in phases (core module → tests → CLI → cross-validation)
    and commits after each phase.

``data-review``
    Reviews open data-source PRs for consistency with shared utilities,
    test standards, and documentation completeness.

See ``AGENTS.md`` for the full specification of each agent, including
templates, checklists, and quality gates.

**Key standards** (from ``AGENTS.md``):

* Prefer ``pxstat.read_dataset()`` for NISRA data — no rate limits, no
  auth, no CI flakiness. Only fall back to Excel scraping when the dataset
  is not in PxStat.
* Use ``from bolster.utils.web import session`` for all HTTP — it provides
  retry logic, a default 30 s timeout, and a 24-hour disk cache.
* No mocks in tests.
* Type hints and docstrings on all public functions.

Tips
----

Run only doctests::

    $ uv run pytest src/ --doctest-modules --no-cov

Run a single test file quickly::

    $ uv run pytest tests/test_dva_integrity.py -v --no-cov

See coverage with missing lines::

    $ uv run pytest tests/ --cov=src/bolster --cov-report=term-missing

Deploying
---------

Maintainers only.

1. Update ``CHANGELOG.md`` with the new version entry.
2. Bump the version::

    $ uv run bump-my-version bump patch   # or minor / major

3. Push the resulting commit and tag::

    $ git push --follow-tags

GitHub Actions ``publish.yml`` will then tag, release, and deploy to PyPI
once tests pass.
