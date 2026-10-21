import pickle
import time
import unittest

from celery.events import Event

from flower.events import EventsState
from flower.utils.hierarchy import TaskHierarchy
from flower.utils.tasks import parse_expanded, search_task_tree, task_tree


class FakeEvents:
    def __init__(self, state):
        self.state = state


class StateMixin:
    """Feeds events shaped like the ones a Celery 5 worker sends.

    Parents are what Celery puts in parent_id: the task that was running when
    the task was sent. All tasks share a name to keep the Prometheus metrics,
    which are global, small.
    """

    def setUp(self):
        super().setUp()
        self.state = EventsState()
        self.clock = 0

    def send(self, *events):
        for event in events:
            self.clock += 1
            event['clock'] = self.clock
            event['local_received'] = time.time()
            self.state.event(event)

    @staticmethod
    def received(task_id, parent=None, root=None, retries=0, worker='worker1'):
        return Event('task-received', uuid=task_id, name='tasks.step', args='()',
                     kwargs='{}', parent_id=parent, root_id=root or parent or task_id,
                     retries=retries, eta=None, expires=None, hostname=worker)

    @staticmethod
    def started(task_id, worker='worker1'):
        return Event('task-started', uuid=task_id, hostname=worker)

    @staticmethod
    def succeeded(task_id, worker='worker1'):
        return Event('task-succeeded', uuid=task_id, result='None',
                     runtime=0.1, hostname=worker)

    @staticmethod
    def failed(task_id, worker='worker1'):
        return Event('task-failed', uuid=task_id, exception="KeyError('x')",
                     traceback='', hostname=worker)

    def execute(self, task_id, parent=None, root=None, worker='worker1'):
        self.send(self.received(task_id, parent, root, worker=worker),
                  self.started(task_id, worker), self.succeeded(task_id, worker))

    def tree(self, search='', expanded=None, expand_all=True, offset=0, limit=None,
             sort_by='received', descending=False):
        if expand_all:
            expanded = {task_id: 1000 for task_id in self.state.tasks.data}
        return search_task_tree(
            FakeEvents(self.state), search=search, sort_by=sort_by,
            descending=descending, offset=offset, limit=limit,
            expanded=expanded or {})

    def outline(self, **kwargs):
        "Rows as (depth, task id), the more-rows as (depth, '+N')"
        return [(info['depth'], task_id if task_id else f"+{info['more']}")
                for task_id, info in self.tree(**kwargs).rows]

    def children(self, task_id):
        task_map = self.state.tasks.data
        return self.state.hierarchy.ordered_children(task_id, task_map)[0]


class TaskRelationsTests(StateMixin, unittest.TestCase):
    def test_task_without_parent_is_a_root(self):
        self.execute('a')
        self.assertEqual([(0, 'a')], self.outline())
        row = self.tree().rows[0][1]
        self.assertEqual(0, row['children'])
        self.assertIsNone(row['parent_id'])
        self.assertIsNone(row['missing_parent_id'])

    def test_parent_with_one_child(self):
        self.execute('parent')
        self.execute('child', parent='parent')
        self.assertEqual([(0, 'parent'), (1, 'child')], self.outline())

    def test_parent_with_many_children_lists_them_oldest_first(self):
        self.execute('parent')
        for task_id in ('c1', 'c2', 'c3'):
            self.execute(task_id, parent='parent')
        self.assertEqual(
            [(0, 'parent'), (1, 'c1'), (1, 'c2'), (1, 'c3')], self.outline())
        rows = dict(self.tree().rows)
        self.assertEqual([False, False, True], [rows[c]['last'] for c in ('c1', 'c2', 'c3')])

    def test_several_levels(self):
        self.execute('root')
        self.execute('child1', parent='root')
        self.execute('child2', parent='root')
        self.execute('grandchild1', parent='child2', root='root')
        self.execute('grandchild2', parent='child2', root='root')
        self.execute('great', parent='grandchild2', root='root')
        self.assertEqual([
            (0, 'root'), (1, 'child1'), (1, 'child2'), (2, 'grandchild1'),
            (2, 'grandchild2'), (3, 'great')], self.outline())
        rows = dict(self.tree().rows)
        # child2 is root's last child, child1 isn't: no guide below child2
        self.assertEqual([False], rows['grandchild1']['guides'])
        self.assertEqual([False, False], rows['great']['guides'])
        self.assertEqual(5, sum(rows['root']['summary'].values()))

    def test_guides_continue_below_children_with_later_siblings(self):
        self.execute('root')
        self.execute('first', parent='root')
        self.execute('nested', parent='first', root='root')
        self.execute('second', parent='root')
        rows = dict(self.tree().rows)
        self.assertEqual([True], rows['nested']['guides'])

    def test_chain_steps_nest_under_the_previous_step(self):
        # chain(a.s(), b.s(), c.s()): each step is sent by the one before it
        self.execute('step1')
        self.execute('step2', parent='step1', root='step1')
        self.execute('step3', parent='step2', root='step1')
        self.assertEqual([(0, 'step1'), (1, 'step2'), (2, 'step3')], self.outline())

    def test_group_applied_by_a_task_is_its_children(self):
        self.execute('spawner')
        self.execute('member1', parent='spawner')
        self.execute('member2', parent='spawner')
        self.assertEqual(
            [(0, 'spawner'), (1, 'member1'), (1, 'member2')], self.outline())

    def test_group_applied_by_a_client_is_unrelated_roots(self):
        # Events carry no group id, and the members have no parent
        self.execute('member1')
        self.execute('member2')
        self.assertEqual({'member1', 'member2'},
                         {task_id for _, task_id in self.outline()})
        self.assertTrue(all(depth == 0 for depth, _ in self.outline()))

    def test_chord_callback_is_a_child_of_the_header_task_that_sent_it(self):
        # The header task finishing last sends the callback (Redis backend)
        self.execute('spawner')
        self.execute('header1', parent='spawner')
        self.execute('header2', parent='spawner')
        self.execute('callback', parent='header2', root='spawner')
        self.assertEqual([
            (0, 'spawner'), (1, 'header1'), (1, 'header2'), (2, 'callback')],
            self.outline())

    def test_child_seen_before_its_parent_moves_under_it(self):
        self.execute('child', parent='parent')
        self.assertEqual([(0, 'child')], self.outline())
        self.assertEqual('parent', self.tree().rows[0][1]['missing_parent_id'])

        self.execute('parent')
        self.assertEqual([(0, 'parent'), (1, 'child')], self.outline())
        self.assertIsNone(dict(self.tree().rows)['child']['missing_parent_id'])

    def test_events_out_of_order_link_the_child_once_received_arrives(self):
        self.execute('parent')
        self.send(self.succeeded('child'), self.started('child'))
        self.assertEqual({(0, 'parent'), (0, 'child')}, set(self.outline()))

        self.send(self.received('child', parent='parent'))
        self.assertEqual([(0, 'parent'), (1, 'child')], self.outline())
        self.assertEqual('SUCCESS', self.state.tasks.data['child'].state)

    def test_parent_finishing_before_its_child(self):
        self.execute('parent')
        self.send(self.received('child', parent='parent'), self.started('child'))
        rows = dict(self.tree().rows)
        self.assertEqual({'STARTED': 1}, rows['parent']['summary'])
        self.send(self.succeeded('child'))
        rows = dict(self.tree().rows)
        self.assertEqual({'SUCCESS': 1}, rows['parent']['summary'])

    def test_retry_keeps_the_parent_the_task_was_sent_with(self):
        # A retry sends the task again with itself as parent
        self.execute('parent')
        self.send(self.received('child', parent='parent'), self.started('child'),
                  Event('task-retried', uuid='child', exception='Retry', hostname='worker1'),
                  self.received('child', parent='child', root='parent', retries=1),
                  self.started('child'), self.succeeded('child'))
        self.assertEqual([(0, 'parent'), (1, 'child')], self.outline())
        self.assertEqual([], self.children('child'))
        self.assertEqual('parent', self.state.tasks.data['child'].parent_id)
        self.assertEqual(1, self.state.tasks.data['child'].retries)

    def test_retry_of_a_root_task_is_not_its_own_child(self):
        self.send(self.received('task'), self.started('task'),
                  Event('task-retried', uuid='task', exception='Retry', hostname='worker1'),
                  self.received('task', parent='task', retries=1))
        self.assertEqual([(0, 'task')], self.outline())
        self.assertIsNone(self.state.tasks.data['task'].parent_id)
        self.assertNotIn(self.state.tasks.data['task'], self.state.tasks.data['task'].children)

    def test_failure_is_counted_in_the_ancestors(self):
        self.execute('root')
        self.execute('child', parent='root')
        self.send(self.received('leaf', parent='child', root='root'),
                  self.started('leaf'), self.failed('leaf'))
        rows = dict(self.tree().rows)
        self.assertEqual({'SUCCESS': 1, 'FAILURE': 1}, rows['root']['summary'])
        self.assertEqual({'FAILURE': 1}, rows['child']['summary'])
        self.assertNotIn('summary', rows['leaf'])

    def test_revoked_child(self):
        self.execute('parent')
        self.send(self.received('child', parent='parent'),
                  Event('task-revoked', uuid='child', terminated=False,
                        signum=None, expired=False, hostname='worker1'))
        self.assertEqual({'REVOKED': 1}, dict(self.tree().rows)['parent']['summary'])

    def test_child_state_updates_show_up(self):
        self.execute('parent')
        self.send(self.received('child', parent='parent'))
        self.assertEqual('RECEIVED', self.state.tasks.data['child'].state)
        self.send(self.started('child'))
        self.assertEqual('STARTED', self.state.tasks.data['child'].state)
        self.assertEqual({'STARTED': 1}, dict(self.tree().rows)['parent']['summary'])

    def test_duplicate_events_do_not_duplicate_children(self):
        self.execute('parent')
        received = self.received('child', parent='parent')
        self.send(received, dict(received), self.started('child'), self.started('child'))
        self.assertEqual(['child'], self.children('parent'))
        self.assertEqual([(0, 'parent'), (1, 'child')], self.outline())

    def test_lost_parent_events_leave_an_orphan_at_the_top(self):
        self.execute('child', parent='never-seen', root='never-seen')
        self.execute('other')
        rows = dict(self.tree().rows)
        self.assertEqual(0, rows['child']['depth'])
        self.assertEqual('never-seen', rows['child']['missing_parent_id'])
        self.assertIsNone(rows['other']['missing_parent_id'])

    def test_children_on_several_workers(self):
        self.execute('parent', worker='worker1')
        self.execute('child1', parent='parent', worker='worker2')
        self.execute('child2', parent='parent', worker='worker3')
        self.assertEqual(
            [(0, 'parent'), (1, 'child1'), (1, 'child2')], self.outline())

    def test_independent_trees(self):
        self.execute('tree1')
        self.execute('tree1-child', parent='tree1')
        self.execute('tree2')
        self.execute('tree2-child', parent='tree2')
        self.assertEqual([(0, 'tree1'), (1, 'tree1-child'), (0, 'tree2'), (1, 'tree2-child')],
                         self.outline())
        page = self.tree()
        self.assertEqual(2, page.filtered_count)
        self.assertEqual(2, page.total_count)

    def test_collapsed_tasks_hide_their_children(self):
        self.execute('parent')
        self.execute('child', parent='parent')
        self.assertEqual([(0, 'parent')], self.outline(expand_all=False))
        row = self.tree(expand_all=False).rows[0][1]
        self.assertEqual(1, row['children'])
        self.assertFalse(row['expanded'])


class EvictionTests(StateMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.state = EventsState(max_tasks_in_memory=3)

    def assert_consistent(self):
        task_map = self.state.tasks.data
        hierarchy = self.state.hierarchy
        self.assertLessEqual(set(hierarchy.parents), set(task_map))
        linked = {child for children in hierarchy.children.values() for child in children}
        self.assertEqual(set(hierarchy.parents), linked)
        for task_id, info in self.tree().rows:
            parent_id = task_map[task_id].parent_id
            if info['depth'] == 0 and parent_id:
                self.assertNotIn(parent_id, task_map)
                self.assertEqual(parent_id, info['missing_parent_id'])

    def test_evictions_keep_the_index_consistent(self):
        # Celery's cache drops the least recently used task; a child's events
        # also use its parent, so which one goes depends on the event order
        self.execute('parent')
        for index in range(6):
            self.execute(f'child{index}', parent='parent')
            self.assert_consistent()
        for index in range(3):
            self.execute(f'other{index}')
            self.assert_consistent()

    def test_children_of_an_evicted_parent_go_to_the_top(self):
        self.execute('parent')
        self.send(self.received('child', parent='parent'))
        self.execute('x')
        self.execute('y')
        # child was used after parent, so parent is dropped first
        self.assertEqual({'child', 'x', 'y'}, set(self.state.tasks.data))
        rows = dict(self.tree().rows)
        self.assertEqual(0, rows['child']['depth'])
        self.assertEqual('parent', rows['child']['missing_parent_id'])
        # The parent's late events bring it back, with its child under it
        self.send(self.started('child'), self.succeeded('parent'))
        self.assertEqual({'child', 'parent', 'y'}, set(self.state.tasks.data))
        self.assertEqual(['child'], self.children('parent'))

    def test_evicted_task_is_forgotten(self):
        self.execute('parent')
        self.execute('child', parent='parent')
        self.execute('x')
        self.execute('y')
        self.execute('z')
        self.assertEqual({'x', 'y', 'z'}, set(self.state.tasks.data))
        self.assertNotIn('child', self.state.hierarchy.parents)
        self.assertNotIn('parent', self.state.hierarchy.children)

    def test_clearing_tasks_rebuilds_the_hierarchy(self):
        self.execute('parent')
        self.send(self.received('child', parent='parent'), self.started('child'))
        self.state.clear_tasks(ready=True)
        self.assertEqual(['child'], list(self.state.tasks.data))
        self.assertEqual({'child': 'parent'}, self.state.hierarchy.parents)
        self.assertEqual([(0, 'child')], self.outline())


class PersistenceTests(StateMixin, unittest.TestCase):
    def test_hierarchy_is_rebuilt_from_a_pickled_state(self):
        self.execute('parent')
        self.execute('child', parent='parent')
        self.execute('grandchild', parent='child', root='parent')

        restored = pickle.loads(pickle.dumps(self.state))
        self.state = restored
        self.assertEqual([(0, 'parent'), (1, 'child'), (2, 'grandchild')], self.outline())

    def test_state_saved_with_self_parents_restores_without_cycles(self):
        self.execute('task')
        self.state.tasks.data['task'].parent_id = 'task'
        self.state = pickle.loads(pickle.dumps(self.state))
        self.assertEqual([(0, 'task')], self.outline())


class SearchTreeTests(StateMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.execute('root')
        self.execute('ok-child', parent='root')
        self.send(self.received('bad-child', parent='root'), self.failed('bad-child'))
        self.execute('other')

    def test_search_lists_the_top_ancestor_of_matches(self):
        page = self.tree(search='state:FAILURE')
        self.assertEqual([(0, 'root'), (1, 'bad-child')], self.outline(search='state:FAILURE'))
        rows = dict(page.rows)
        self.assertFalse(rows['root']['matched'])
        self.assertTrue(rows['bad-child']['matched'])
        # Children count the matching branches only
        self.assertEqual(1, rows['root']['children'])
        self.assertEqual(1, page.filtered_count)
        self.assertEqual(2, page.total_count)

    def test_matching_root_lists_only_matching_children(self):
        rows = dict(self.tree(search='root').rows)
        self.assertEqual({'root'}, set(rows))
        self.assertEqual(0, rows['root']['children'])

    def test_sort_and_paging_apply_to_top_level_tasks(self):
        self.assertEqual(['other', 'root'], [
            task_id for task_id, info in self.tree(descending=True, expand_all=False).rows])
        page = self.tree(offset=1, limit=1)
        self.assertEqual(['other'], [task_id for task_id, _ in page.rows])
        self.assertEqual(2, page.filtered_count)


class LimitsTests(StateMixin, unittest.TestCase):
    def test_children_beyond_the_limit_are_one_row(self):
        self.execute('parent')
        for index in range(5):
            self.execute(f'child{index}', parent='parent')
        rows = self.tree(expand_all=False, expanded={'parent': 2}).rows
        self.assertEqual([(0, 'parent'), (1, 'child0'), (1, 'child1'), (1, '+3')],
                         [(info['depth'], task_id or f"+{info['more']}") for task_id, info in rows])
        more = rows[-1][1]
        self.assertEqual('parent', more['parent_id'])
        self.assertEqual(2, more['limit'])
        self.assertFalse(rows[2][1]['last'])

    def test_rows_stop_expanding_past_the_limit(self):
        self.execute('parent')
        for index in range(3):
            self.execute(f'child{index}', parent='parent')
            self.execute(f'grandchild{index}', parent=f'child{index}', root='parent')
        task_map = self.state.tasks.data
        expanded = {task_id: 100 for task_id in task_map}
        rows = self.state.hierarchy.flatten(['parent'], task_map, expanded, max_rows=3)
        self.assertEqual(['parent', 'child0', 'grandchild0', 'child1', 'child2'],
                         [task_id for task_id, _ in rows])
        self.assertFalse(dict(rows)['child1']['expanded'])

    def test_deep_chain_does_not_recurse(self):
        self.execute('step0')
        for index in range(1, 2000):
            self.execute(f'step{index}', parent=f'step{index - 1}', root='step0')
        rows = self.tree().rows
        self.assertEqual(2000, len(rows))
        self.assertEqual(1999, rows[-1][1]['depth'])
        self.assertEqual(1999, sum(rows[0][1]['summary'].values()))

    def test_summaries_stop_at_the_budget(self):
        self.execute('parent')
        for index in range(5):
            self.execute(f'child{index}', parent='parent')
        task_map = self.state.tasks.data
        self.assertEqual({}, self.state.hierarchy.summaries(['parent'], task_map, budget=3))
        self.assertEqual({'SUCCESS': 5},
                         self.state.hierarchy.summaries(['parent'], task_map)['parent'])


class TaskTreeTests(StateMixin, unittest.TestCase):
    def test_nested_tree(self):
        self.execute('root')
        self.execute('child', parent='root')
        self.execute('grandchild', parent='child', root='root')
        result = task_tree(FakeEvents(self.state), 'root')
        self.assertEqual(3, result['count'])
        self.assertFalse(result['truncated'])
        tree = result['tree']
        self.assertEqual('root', tree['uuid'])
        self.assertEqual('SUCCESS', tree['state'])
        self.assertEqual('worker1', tree['worker'])
        self.assertEqual(['child'], [c['uuid'] for c in tree['children']])
        self.assertEqual('root', tree['children'][0]['parent_id'])
        self.assertEqual(['grandchild'], [c['uuid'] for c in tree['children'][0]['children']])

    def test_unknown_task(self):
        self.assertIsNone(task_tree(FakeEvents(self.state), 'missing'))

    def test_truncated_tree(self):
        self.execute('root')
        for index in range(5):
            self.execute(f'child{index}', parent='root')
        self.execute('deep', parent='child0', root='root')
        result = task_tree(FakeEvents(self.state), 'root', max_nodes=3)
        self.assertEqual(3, result['count'])
        self.assertTrue(result['truncated'])
        self.assertEqual(5, result['tree']['children_count'])

        result = task_tree(FakeEvents(self.state), 'root', max_depth=1)
        self.assertTrue(result['truncated'])
        self.assertEqual([], result['tree']['children'][0]['children'])
        self.assertEqual(1, result['tree']['children'][0]['children_count'])


class TaskHierarchyTests(unittest.TestCase):
    def test_first_parent_wins(self):
        hierarchy = TaskHierarchy()
        self.assertTrue(hierarchy.link('child', 'parent'))
        self.assertFalse(hierarchy.link('child', 'other'))
        self.assertTrue(hierarchy.accepts('child', 'parent'))
        self.assertFalse(hierarchy.accepts('child', 'other'))
        self.assertEqual({'child': 'parent'}, hierarchy.parents)

    def test_refuses_cycles(self):
        hierarchy = TaskHierarchy()
        self.assertFalse(hierarchy.link('a', 'a'))
        hierarchy.link('b', 'a')
        hierarchy.link('c', 'b')
        self.assertFalse(hierarchy.link('a', 'c'))
        self.assertNotIn('a', hierarchy.parents)

    def test_removed_task_keeps_its_children(self):
        hierarchy = TaskHierarchy()
        hierarchy.link('child', 'parent')
        hierarchy.link('parent', 'grandparent')
        hierarchy.remove('parent')
        self.assertEqual({'child': 'parent'}, hierarchy.parents)
        self.assertEqual({'parent': {'child': None}}, hierarchy.children)
        hierarchy.remove('child')
        self.assertEqual({}, hierarchy.children)

    def test_tops_walks_shared_ancestors_once(self):
        hierarchy = TaskHierarchy()
        task_map = dict.fromkeys(['root', 'a', 'b', 'a1', 'orphan'])
        hierarchy.link('a', 'root')
        hierarchy.link('b', 'root')
        hierarchy.link('a1', 'a')
        hierarchy.link('orphan', 'gone')
        tops, visible = hierarchy.tops(['a1', 'b', 'orphan'], task_map)
        self.assertEqual({'root', 'orphan'}, tops)
        self.assertEqual({'root', 'a', 'a1', 'b', 'orphan'}, visible)
        self.assertEqual(2, hierarchy.count_tops(task_map))


class ParseExpandedTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual({'a': 50, 'b': 1, 'c': 10000, 'd': 50},
                         parse_expanded('{"a": 50, "b": -3, "c": 10000000, "d": "x"}'))

    def test_malformed_values_are_dropped(self):
        for value in ('', 'not json', '[1, 2]', '"text"', 'null'):
            with self.subTest(value=value):
                self.assertEqual({}, parse_expanded(value))

    def test_entries_are_capped(self):
        value = '{' + ','.join(f'"{index}": 1' for index in range(20)) + '}'
        self.assertEqual(5, len(parse_expanded(value, max_entries=5)))
