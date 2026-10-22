flower-hierarchy
================

.. image:: https://img.shields.io/pypi/v/flower-hierarchy.svg
    :target: https://pypi.org/project/flower-hierarchy/
    :alt: PyPI
.. image:: https://github.com/salvamunoz/flower_hierarchy/workflows/Build/badge.svg
    :target: https://github.com/salvamunoz/flower_hierarchy/actions
    :alt: Build

A fork of `Flower <https://github.com/mher/flower>`_, the web application for
monitoring and managing Celery clusters, that shows each task under the task
that started it.

Flower lists tasks one after the other. In flower-hierarchy, the tasks a task
sends with ``delay``/``apply_async``, the steps of a chain, groups and chords
appear below it as a tree you can expand and collapse, with a summary of what
happened below each task::

    ▼ process_order        SUCCESS   3 below
        ├─ validate_order  SUCCESS
        ├─ charge_card     SUCCESS
        └─ send_email      SUCCESS
    ▼ import_data          SUCCESS   3 below · 1 failed
        └─ download        SUCCESS
            └─ parse       SUCCESS
                └─ persist FAILURE

.. image:: https://raw.githubusercontent.com/salvamunoz/flower_hierarchy/master/docs/screenshots/task-hierarchy.png
    :alt: The tasks page with a chain of tasks expanded

Everything else works as in Flower: same command, options, API and Docker
usage.

What's different from Flower
----------------------------

- **Tree layout of the tasks page**, recursive to any depth, built from the
  ``parent_id`` that Celery puts in its events. No extra setup on the workers
  and any broker works.
- **Expand all levels** of a task at once: the double chevron next to it,
  Alt+click or Shift+click on its toggle, or ``*`` on the keyboard.
- **Subtree summaries**: a task shows how many tasks are below it and how many
  failed or are still running, so a failure deep in a workflow is visible from
  the top.
- **Search keeps the context**: matching tasks are listed under their
  top-level task, with the tasks leading to them dimmed.
- **Live** button that reloads the table every few seconds, and **Tree** /
  **Flat** buttons to switch to Flower's list.
- **Task states as icons**, and a choice of designs: ``--design=classic``,
  ``glass`` or ``terminal``.
- ``GET /api/task/tree/<task-id>``: a task and its descendants as nested JSON.
- Retries and ``Task.replace`` no longer make a task its own child.

See `Task hierarchy <https://github.com/salvamunoz/flower_hierarchy/blob/master/docs/task_hierarchy.rst>`_
for how relations are found, what Celery's events can't tell (for instance
groups sent from outside a task) and the limits on large trees.

Features
--------

.. features-start

- Real-time monitoring using Celery Events
    - View task progress and history
    - View tasks under the task that started them, as an expandable tree
    - View task details (arguments, start time, runtime, and more)
- Remote Control
    - View worker status and statistics
    - Shutdown and restart worker instances
    - Control worker pool size and autoscale settings
    - View and modify the queues a worker instance consumes from
    - View currently running tasks
    - View scheduled tasks (ETA/countdown)
    - View reserved and revoked tasks
    - Apply time and rate limits
    - Revoke or terminate tasks
- Broker monitoring
    - View statistics for all Celery queues
- HTTP Basic Auth, Google, Github, Gitlab and Okta OAuth
- Prometheus integration
- API

.. features-end

.. install-start

Installation
------------

flower-hierarchy replaces Flower: both provide the ``flower`` Python package,
so remove Flower first if it is installed ::

    $ pip uninstall flower
    $ pip install flower-hierarchy

The development version can be installed from GitHub ::

    $ pip install git+https://github.com/salvamunoz/flower_hierarchy.git

In a requirements file, list ``flower-hierarchy`` instead of ``flower``.

Usage
-----

flower-hierarchy is started like Flower. Provide the broker URL ::

    $ celery --broker=amqp://guest:guest@localhost:5672// flower

Or use the configuration of your `celery application <https://docs.celeryq.dev/en/stable/userguide/application.html>`_ ::

    $ celery -A tasks.app flower

Workers must send task events, with ``-E`` or ``worker_send_task_events = True``.

By default, flower runs on port 5555, which can be modified with the `port <https://flower.readthedocs.io/en/latest/config.html#port>`_ option ::

    $ celery -A tasks.app flower --port=5001

The tasks page opens in the tree layout. ``/tasks?view=flat`` opens Flower's
list, and ``/tasks?autorefresh=5`` turns on Live with a 5 second interval.

Designs
-------

The ``--design`` option picks the look of the web interface for everyone who
opens it ::

    $ celery -A tasks.app flower --design=glass

Like Flower's other options, it can also be set with an environment variable,
``FLOWER_DESIGN=terminal``, or in ``flowerconfig.py``.

``classic`` (the default)
    Flower's own look, with task states shown as icons. Light or dark.

    .. image:: https://raw.githubusercontent.com/salvamunoz/flower_hierarchy/master/docs/screenshots/design-classic.png
        :alt: The classic design

``glass``
    Translucent bars and controls over soft color fields. Light or dark.

    .. image:: https://raw.githubusercontent.com/salvamunoz/flower_hierarchy/master/docs/screenshots/design-glass.png
        :alt: The glass design

``terminal``
    A terminal user interface: monospaced text, the Gruvbox palette, the tree
    drawn with box drawing characters and states as colored glyphs. Always dark.

    .. image:: https://raw.githubusercontent.com/salvamunoz/flower_hierarchy/master/docs/screenshots/design-terminal.png
        :alt: The terminal design

Docker
------

Build the image from this repository ::

    $ docker build -t flower-hierarchy https://github.com/salvamunoz/flower_hierarchy.git
    $ docker run -v $(pwd)/examples:/data -p 5555:5555 flower-hierarchy celery --app=tasks.app flower

In this example, Flower is using the `tasks.app` defined in the `examples/tasks.py <https://github.com/salvamunoz/flower_hierarchy/blob/master/examples/tasks.py>`_ file

Options are passed as environment variables too, for instance the design ::

    $ docker run -e FLOWER_DESIGN=terminal -v $(pwd)/examples:/data -p 5555:5555 flower-hierarchy celery --app=tasks.app flower

.. install-end

Versions
--------

Versions are the Flower release the fork is based on, followed by the fork's
own release number: ``2.2.0.1`` is the first release on top of Flower 2.2.0.

API
---

The Flower API lets you manage the cluster over HTTP.

For example you can grow a worker's pool by: ::

    $ curl -X POST -d 'n=1' http://localhost:5555/api/worker/pool/grow/celery@$(hostname)

Or call a task by: ::

    $ curl -X POST -d '{"args":[1,2]}' http://localhost:5555/api/task/async-apply/tasks.add

Or get a task and everything it started by: ::

    $ curl http://localhost:5555/api/task/tree/8a4da87b-e12b-4547-b89a-e92e4d1f8efd

For more info, see Flower's `API Reference`_

.. _API Reference: https://flower.readthedocs.io/en/latest/api.html

Documentation
-------------

Flower's documentation applies to flower-hierarchy, see `Read the Docs`_.
The tree layout is described in `docs/task_hierarchy.rst <https://github.com/salvamunoz/flower_hierarchy/blob/master/docs/task_hierarchy.rst>`_.

.. _Read the Docs: https://flower.readthedocs.io

Credits and license
-------------------

flower-hierarchy is based on `Flower <https://github.com/mher/flower>`_ by
Mher Movsisyan and its contributors, and keeps its BSD 3-Clause License.
See the `License`_ file for the full license text.

.. _`License`: https://github.com/salvamunoz/flower_hierarchy/blob/master/LICENSE
