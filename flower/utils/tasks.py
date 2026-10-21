import datetime
import json
import time
from collections import deque
from dataclasses import dataclass
from itertools import islice

from .hierarchy import CHILDREN_PAGE_SIZE, MAX_CHILDREN_LIMIT


# pylint: disable=too-many-branches,too-many-locals,too-many-arguments
def iter_tasks(events, limit=None, offset=0, type=None, worker=None, state=None,
               sort_by=None, received_start=None, received_end=None,
               search=None):
    descending = False
    if sort_by is not None:
        assert sort_by.lstrip('-') in SORT_KEYS
        descending = sort_by.startswith('-')
        sort_by = sort_by.lstrip('-')

    page = search_tasks(
        events, limit=limit, offset=offset, type=type, worker=worker,
        state=state, sort_by=sort_by, descending=descending,
        received_start=received_start, received_end=received_end,
        search=search)
    task_map = getattr(events.state.tasks, 'data', events.state.tasks)
    for task_id in page.task_ids:
        task = task_map.get(task_id)
        if task is not None:
            yield task_id, task


def search_tasks(events, limit=None, offset=0, type=None, worker=None,
                 state=None, sort_by=None, descending=False,
                 received_start=None, received_end=None, search=None):
    return events.state.search_engine.search(
        events.state.tasks,
        search or '',
        task_type=type,
        worker=worker,
        state=state,
        received_start=_convert_datetime(received_start),
        received_end=_convert_datetime(received_end),
        sort_by=sort_by,
        descending=descending,
        offset=offset,
        limit=limit)


@dataclass(frozen=True)
class TreePage:
    # (task id, tree info) pairs, see TaskHierarchy.flatten
    rows: list
    filtered_count: int
    total_count: int


# pylint: disable=too-many-arguments
def search_task_tree(events, search=None, sort_by=None, descending=False,
                     offset=0, limit=None, expanded=None):
    """A page of top-level tasks with the expanded tasks' children below them.

    With a search, the top level lists the top-most ancestor of each matching
    task, and expanded tasks only list children that match or lead to a match.
    """
    state = events.state
    task_map = getattr(state.tasks, 'data', state.tasks)
    hierarchy = state.hierarchy
    filtering = bool((search or '').strip())

    matched = state.search_engine.filter(state.tasks, search or '')
    top_ids, visible = hierarchy.tops(matched, task_map)
    page = state.search_engine.order(
        task_map, top_ids, sort_by=sort_by, descending=descending,
        offset=offset, limit=limit)
    rows = hierarchy.flatten(
        page, task_map, expanded or {},
        visible=visible if filtering else None,
        matched=matched if filtering else None)
    total = hierarchy.count_tops(task_map) if filtering else len(top_ids)
    return TreePage(rows, len(top_ids), total)


def parse_expanded(value, max_entries=1000):
    """Expanded tasks sent by the tasks page, as {task id: children to list}.

    The page keeps them in the browser, so anything malformed is dropped
    rather than failing the request.
    """
    try:
        expanded = json.loads(value) if value else {}
    except ValueError:
        return {}
    if not isinstance(expanded, dict):
        return {}
    result = {}
    for task_id, count in islice(expanded.items(), max_entries):
        if isinstance(count, bool) or not isinstance(count, int):
            count = CHILDREN_PAGE_SIZE
        result[str(task_id)] = min(max(count, 1), MAX_CHILDREN_LIMIT)
    return result


def task_tree(events, task_id, max_nodes=1000, max_depth=100):
    """Nested dict of task_id and its descendants, children oldest first.

    Returns None for an unknown task. Stops at max_nodes tasks or max_depth
    levels, and says so with "truncated".
    """
    state = events.state
    task_map = getattr(state.tasks, 'data', state.tasks)
    if task_id not in task_map:
        return None
    hierarchy = state.hierarchy
    truncated = False

    def node(node_id):
        task = task_map[node_id]
        worker = getattr(task.worker, 'hostname', None)
        return {
            'uuid': node_id, 'name': task.name, 'state': task.state,
            'parent_id': hierarchy.parents.get(node_id), 'root_id': task.root_id,
            'received': task.received, 'started': task.started,
            'runtime': task.runtime, 'worker': worker, 'children': [],
        }

    root = node(task_id)
    count = 1
    queue = deque([(task_id, root, 0)])
    while queue:
        parent_id, parent, depth = queue.popleft()
        children, parent['children_count'] = hierarchy.ordered_children(
            parent_id, task_map)
        if children and (depth >= max_depth or count >= max_nodes):
            truncated = True
            continue
        for child_id in children:
            if count >= max_nodes:
                truncated = True
                break
            child = node(child_id)
            parent['children'].append(child)
            queue.append((child_id, child, depth + 1))
            count += 1
    return {'tree': root, 'count': count, 'truncated': truncated}


def task_children(events, task_id):
    "Ids of the children of task_id in the state, oldest first"
    state = events.state
    task_map = getattr(state.tasks, 'data', state.tasks)
    return state.hierarchy.ordered_children(task_id, task_map)[0]


def _convert_datetime(value):
    if not value:
        return None
    return time.mktime(
        datetime.datetime.strptime(value, '%Y-%m-%d %H:%M').timetuple())


SORT_KEYS = frozenset({'name', 'state', 'received', 'started'})


def get_task_by_id(events, task_id):
    return events.state.tasks.get(task_id)


def as_dict(task):
    return task.as_dict()
