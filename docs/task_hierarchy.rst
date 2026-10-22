Task hierarchy
==============

The tasks page lists each task under the task that started it. A task with
children has a toggle that shows or hides them, and a summary of the states
below it, so a failure deep in a workflow shows on its top-level task.

To open every level below a task at once, use the double chevron next to it
(shown when the row has the pointer or focus), Alt+click or Shift+click its
toggle, or press ``*`` on the toggle. Collapsing a task inside an opened
subtree keeps it shut until the subtree is closed or opened again.

Use the **Tree** and **Flat** buttons above the table to switch layouts, or
open ``/tasks?view=flat``. **Live** reloads the table every 3 seconds, or every
``N`` seconds with ``/tasks?autorefresh=N``. The layout, the expanded tasks and
the Live setting are kept in the browser.

Where the relations come from
-----------------------------

Flower only uses Celery's events, so it works with any broker and backend.
When a task is sent while another task executes, Celery stores the running
task's id in the message as ``parent_id``, and the id of the first task of the
workflow as ``root_id``. Workers report both in the ``task-received`` event,
and clients in ``task-sent`` (with ``task_send_sent_event``).

=================================== ==========================================
How the task was sent               Shown under
=================================== ==========================================
``delay``/``apply_async`` in a task the task that sent it
chain                               the previous step (steps nest)
group applied in a task             the task that applied it
group applied by a client           nothing: members are separate top-level tasks
chord header                        like a group
chord callback                      the header task that completed last, or
                                    ``celery.chord_unlock`` on backends without
                                    native chord support
retry, ``Task.replace``             the task keeps its first parent
=================================== ==========================================

Events carry no group or chord id, so Flower doesn't show groups or chords as
such, and members of a group sent from outside a task have nothing relating
them. Sending the group from a task gives them a parent.

A task whose parent isn't in Flower's memory (Flower started after it, the
parent was evicted by ``--max-tasks``, or its events were lost) is listed at
the top level, marked *parent gone*. It moves under its parent if the parent's
events arrive later.

Search, sorting and paging
--------------------------

In the tree layout, the records of the table are top-level tasks: paging,
the page length and sorting apply to them. Children are listed oldest first.
With a search, the table lists the top-level task of each match, and expanded
tasks show only the children that match or lead to a match. Tasks listed only
because something below them matched are dimmed.

An expanded task lists 50 children at first, with a row to show more, also
when its whole subtree is opened. A response lists at most 2000 rows: past
that, tasks show collapsed.

API
---

``GET /api/task/tree/<task-id>`` returns a task and its descendants as nested
objects, see :doc:`api`. ``/api/tasks`` and ``/api/task/info`` still report
each task's ``parent_id`` and ``root_id``.
