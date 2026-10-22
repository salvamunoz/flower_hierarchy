import copy
import logging

from tornado import web

from ..utils.search import QuerySyntaxError
from ..utils.tasks import (as_dict, get_task_by_id, parse_expanded, search_task_tree, search_tasks,
                           task_children)
from ..views import BaseHandler

logger = logging.getLogger(__name__)


class TaskView(BaseHandler):
    @web.authenticated
    def get(self, task_id):
        task = get_task_by_id(self.application.events, task_id)

        if task is None:
            raise web.HTTPError(404, f"Unknown task '{task_id}'")
        task = self.format_task(task)
        self.render(
            "task.html",
            task=task,
            task_children=task_children(self.application.events, task_id),
            read_only=self.application.options.read_only,
        )


class TasksDataTable(BaseHandler):
    @web.authenticated
    # pylint: disable=too-many-locals
    def get(self):
        app = self.application
        draw = self.get_argument('draw', type=int, required=True)
        start = self.get_argument('start', type=int, required=True)
        length = self.get_argument('length', type=int, required=True)
        search = self.get_argument('search[value]', '', escape=False)

        column = self.get_argument('order[0][column]', type=int, required=True)
        sort_by = self.get_argument(f'columns[{column}][data]', '', type=str)
        sort_order = self.get_argument('order[0][dir]', '', type=str) == 'desc'

        if self.get_argument('tree', '') == '1':
            self.write_tree(draw, search, sort_by, sort_order, start, length)
            return

        try:
            page = search_tasks(
                app.events,
                search=search,
                sort_by=sort_by,
                descending=sort_order,
                offset=start,
                limit=length)
        except QuerySyntaxError as exc:
            self.write({
                "draw": draw,
                "data": [],
                "recordsTotal": len(app.events.state.tasks),
                "recordsFiltered": 0,
                "searchError": str(exc)})
            return

        filtered_tasks = []
        task_map = getattr(app.events.state.tasks, 'data', app.events.state.tasks)

        for task_id in page.task_ids:
            task = task_map.get(task_id)
            if task is None:
                continue
            task_dict = as_dict(self.format_task((task_id, task))[1])
            if task_dict.get('worker'):
                task_dict['worker'] = task_dict['worker'].hostname

            filtered_tasks.append(task_dict)

        self.write({"draw": draw, "data": filtered_tasks,
                    "recordsTotal": page.total_count,
                    "recordsFiltered": page.filtered_count})

    # pylint: disable=too-many-arguments
    def write_tree(self, draw, search, sort_by, descending, start, length):
        "Top-level tasks are the records, the expanded tasks' children follow them"
        events = self.application.events
        task_map = getattr(events.state.tasks, 'data', events.state.tasks)
        expanded, subtrees = parse_expanded(
            self.get_argument('tree_expanded', '', escape=False))
        try:
            page = search_task_tree(
                events, search=search, sort_by=sort_by,
                descending=descending, offset=start, limit=length,
                expanded=expanded, subtrees=subtrees)
        except QuerySyntaxError as exc:
            self.write({
                "draw": draw,
                "data": [],
                "recordsTotal": events.state.hierarchy.count_tops(task_map),
                "recordsFiltered": 0,
                "searchError": str(exc)})
            return

        rows = (self.tree_row(task_map, task_id, tree) for task_id, tree in page.rows)
        self.write({"draw": draw, "data": [row for row in rows if row is not None],
                    "recordsTotal": page.total_count,
                    "recordsFiltered": page.filtered_count})

    def tree_row(self, task_map, task_id, tree):
        "A row of the tree layout, None for a task no longer in the state"
        if task_id is None:
            # Stands for the children the limit left out
            return {'uuid': f"{tree['parent_id']}:more", 'tree': tree}
        task = task_map.get(task_id)
        if task is None:
            return None
        task_dict = as_dict(self.format_task((task_id, task))[1])
        if task_dict.get('worker'):
            task_dict['worker'] = task_dict['worker'].hostname
        # The tree info replaces the unordered list of children ids,
        # which a task with many children would make heavy
        task_dict.pop('children', None)
        task_dict['tree'] = tree
        return task_dict

    @web.authenticated
    def post(self):
        return self.get()

    def format_task(self, task):
        uuid, args = task
        custom_format_task = self.application.options.format_task

        if custom_format_task:
            try:
                args = custom_format_task(copy.copy(args))
            except Exception:
                logger.exception("Failed to format '%s' task", uuid)
        return uuid, args


# Every column the tasks page can show, slug to header label
TASK_COLUMNS = {
    'name': 'Name',
    'uuid': 'UUID',
    'state': 'State',
    'args': 'args',
    'kwargs': 'kwargs',
    'result': 'Result',
    'received': 'Received',
    'started': 'Started',
    'runtime': 'Runtime',
    'worker': 'Worker',
    'exchange': 'Exchange',
    'routing_key': 'Routing Key',
    'retries': 'Retries',
    'revoked': 'Revoked',
    'exception': 'Exception',
    'expires': 'Expires',
    'eta': 'ETA',
}


def visible_task_columns(tasks_columns):
    "Slug and label of each column the tasks page shows, in the order tasks_columns lists them"
    return [(name, TASK_COLUMNS[name])
            for name in map(str.strip, tasks_columns.split(',')) if name in TASK_COLUMNS]


class TasksView(BaseHandler):
    @web.authenticated
    def get(self):
        app = self.application
        capp = self.application.capp

        time = 'natural-time' if app.options.natural_time else 'time'
        if capp.conf.timezone:
            time += '-' + str(capp.conf.timezone)

        self.render(
            "tasks.html",
            columns=visible_task_columns(app.options.tasks_columns),
            time=time,
        )
