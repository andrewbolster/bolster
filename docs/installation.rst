.. highlight:: shell

============
Installation
============

Stable release
--------------

Install Bolster from PyPI with ``pip``:

.. code-block:: console

    $ pip install bolster

Or with `uv <https://docs.astral.sh/uv/>`_ (recommended for development):

.. code-block:: console

    $ uv add bolster

From sources
------------

Clone the repository and install in editable mode using ``uv``:

.. code-block:: console

    $ git clone https://github.com/andrewbolster/bolster.git
    $ cd bolster
    $ uv sync --all-extras

This installs all runtime and development dependencies (test, docs, cloud
extras) into an isolated virtual environment managed by ``uv``.

To activate the environment or run a one-off command:

.. code-block:: console

    $ uv run pytest tests/ -v
    $ uv run bolster --help

.. _Github repo: https://github.com/andrewbolster/bolster
