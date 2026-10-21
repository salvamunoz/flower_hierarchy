"""Parent/child index of the tasks in Flower's state.

Celery reports where a task comes from in the ``parent_id`` field of its
``task-sent`` and ``task-received`` events: the id of the task that was
executing when it was sent. That covers ``delay``/``apply_async`` called from a
task, a chain's next step (its parent is the previous step), groups and chords
applied from a task, and a chord callback (its parent is the header task, or
``celery.chord_unlock``, that sent it). A task sent from outside a worker has
no parent. Events carry no group or chord id, so members of a group sent from a
client are unrelated roots.

A retry, or a ``Task.replace``, sends the task again under the same id, with
the task itself as parent. Only the first parent a task reports is kept, which
also keeps the index free of cycles.

The index is kept up to date as events arrive. It refers to tasks by id only,
so a task the state evicted can be listed as a parent: callers check presence
in the state's task map, and a task whose parent is not there is shown at the
top level.
"""
import heapq
from collections import Counter

# Children listed per expanded task until the user asks for more
CHILDREN_PAGE_SIZE = 50
MAX_CHILDREN_LIMIT = 10000
# Bounds the rows a single response can expand to
MAX_TREE_ROWS = 2000
# Bounds the descendants visited to summarize the states of collapsed subtrees
SUMMARY_BUDGET = 50000


def _task_map(tasks):
    return getattr(tasks, 'data', tasks)


def chronological_key(task_map, task_id):
    task = task_map.get(task_id)
    if task is None:
        return 0.0, task_id
    when = task.received or task.sent or task.timestamp or 0.0
    try:
        when = float(when)
    except (TypeError, ValueError):
        when = 0.0
    return when, task_id


class TaskHierarchy:
    def __init__(self):
        # child id -> parent id, as first reported
        self.parents = {}
        # parent id -> {child id: None}, in the order the children were linked
        self.children = {}

    def clear(self):
        self.parents.clear()
        self.children.clear()

    def rebuild(self, tasks):
        self.clear()
        for task_id, task in tasks:
            self.link(task_id, getattr(task, 'parent_id', None))

    def accepts(self, task_id, parent_id):
        "Whether parent_id can be recorded as the parent of task_id"
        if not parent_id or parent_id == task_id:
            return False
        known = self.parents.get(task_id)
        if known is not None:
            return known == parent_id
        return not self._is_ancestor(task_id, parent_id)

    def link(self, task_id, parent_id):
        if not task_id or task_id in self.parents or not self.accepts(task_id, parent_id):
            return False
        self.parents[task_id] = parent_id
        self.children.setdefault(parent_id, {})[task_id] = None
        return True

    def remove(self, task_id):
        parent_id = self.parents.pop(task_id, None)
        if parent_id is None:
            return
        siblings = self.children.get(parent_id)
        if siblings is not None:
            siblings.pop(task_id, None)
            if not siblings:
                del self.children[parent_id]
        # The task's own children keep pointing at it: they show at the top
        # level while it is gone, and under it again if it comes back

    def _is_ancestor(self, task_id, node):
        # A task without children is nobody's ancestor. That's every task
        # whose events come before its children's, which spares long chains
        # a walk up to their first step on each link
        if task_id != node and task_id not in self.children:
            return False
        # Parents are only linked when this is false, so the walk ends
        steps = len(self.parents) + 1
        while node is not None and steps:
            if node == task_id:
                return True
            node = self.parents.get(node)
            steps -= 1
        return False

    def parent_in(self, task_id, task_map):
        "Parent of task_id if it is in task_map, else None"
        parent_id = self.parents.get(task_id)
        if parent_id is not None and parent_id in task_map:
            return parent_id
        return None

    def missing_parent(self, task_id, task_map):
        "Reported parent of task_id that is not in task_map, else None"
        parent_id = self.parents.get(task_id)
        if parent_id is not None and parent_id not in task_map:
            return parent_id
        return None

    def children_in(self, task_id, task_map, visible=None):
        "Children of task_id in task_map (and in visible, if given), unordered"
        children = self.children.get(task_id)
        if not children:
            return []
        return [child for child in children
                if child in task_map and (visible is None or child in visible)]

    def ordered_children(self, task_id, task_map, visible=None, limit=None):
        "Children of task_id oldest first, and how many there are in all"
        children = self.children_in(task_id, task_map, visible)

        def key(child):
            return chronological_key(task_map, child)

        if limit is not None and limit < len(children):
            return heapq.nsmallest(limit, children, key=key), len(children)
        return sorted(children, key=key), len(children)

    def tops(self, task_ids, task_map):
        """Top-most ancestor in task_map of each of task_ids.

        Returns the set of top-level ids and the set of every task on the way,
        task_ids included. Each task is walked once however many of task_ids
        are below it.
        """
        top_of = {}
        for task_id in task_ids:
            path = []
            node = task_id
            while node not in top_of:
                path.append(node)
                parent_id = self.parent_in(node, task_map)
                if parent_id is None:
                    top_of[node] = node
                    break
                node = parent_id
            top = top_of[node]
            for visited in path:
                top_of[visited] = top
        return set(top_of.values()), set(top_of)

    def count_tops(self, task_map):
        return sum(1 for task_id in task_map
                   if self.parent_in(task_id, task_map) is None)

    def summaries(self, top_ids, task_map, budget=SUMMARY_BUDGET):
        """Count the states of the descendants of each task below top_ids.

        Returns {task id: Counter} for the tasks that have children. A tree
        that does not fit in the remaining budget gets no summaries.
        """
        result = {}
        for top in top_ids:
            order = []
            stack = [top]
            while stack and len(order) <= budget:
                node = stack.pop()
                order.append(node)
                stack.extend(self.children_in(node, task_map))
            if len(order) > budget:
                continue
            budget -= len(order)
            # Children come after their parent in order, so walking it backwards
            # adds up each subtree before its parent needs it
            for node in reversed(order):
                children = self.children_in(node, task_map)
                if not children:
                    continue
                counts = Counter()
                for child in children:
                    counts[task_map[child].state] += 1
                    counts.update(result.get(child, ()))
                result[node] = counts
        return result

    # pylint: disable=too-many-arguments,too-many-locals
    def flatten(self, top_ids, task_map, expanded, visible=None, matched=None,
                max_rows=MAX_TREE_ROWS):
        """Rows of the trees under top_ids, parents before their children.

        expanded maps the id of each expanded task to how many of its children
        to list. visible, when given, limits the children to those tasks, and
        matched marks the rows that matched a search. Returns a list of
        (task id, tree info) pairs; a task id of None stands for the children
        a limit left out.
        """
        rows = []
        summaries = self.summaries(top_ids, task_map)
        for top in top_ids:
            # Each entry: task id, depth, whether each ancestor below the top
            # has later siblings (to draw guides), whether it's the last child,
            # and for the row standing for children left out, what it stands for
            stack = [(top, 0, (), True, None)]
            while stack:
                task_id, depth, guides, last, more = stack.pop()
                if more is not None:
                    parent_id, hidden, shown = more
                    rows.append((None, {
                        'depth': depth, 'guides': list(guides), 'last': True,
                        'parent_id': parent_id, 'more': hidden, 'limit': shown}))
                    continue
                limit = expanded.get(task_id)
                children, total = self.ordered_children(
                    task_id, task_map, visible, limit)
                is_expanded = (limit is not None and total > 0 and
                               len(rows) < max_rows)
                info = {
                    'depth': depth,
                    'guides': list(guides),
                    'last': last,
                    'children': total,
                    'expanded': is_expanded,
                    'parent_id': self.parent_in(task_id, task_map),
                    'missing_parent_id': self.missing_parent(task_id, task_map),
                    'matched': matched is None or task_id in matched,
                }
                summary = summaries.get(task_id)
                if summary:
                    info['summary'] = dict(summary)
                rows.append((task_id, info))
                if not is_expanded:
                    continue
                child_guides = guides + (not last,) if depth else ()
                hidden = total - len(children)
                if hidden:
                    stack.append((None, depth + 1, child_guides, True,
                                  (task_id, hidden, len(children))))
                for index in range(len(children) - 1, -1, -1):
                    is_last = not hidden and index == len(children) - 1
                    stack.append((children[index], depth + 1, child_guides, is_last, None))
        return rows
