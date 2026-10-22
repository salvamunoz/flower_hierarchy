import json
import os
import re
import time
from urllib.parse import urlencode

from celery.events import Event

import flower
from flower.events import EventsState
from flower.options import DESIGNS
from flower.views.tasks import visible_task_columns
from tests.unit import AsyncHTTPTestCase
from tests.unit.utils import task_failed_events, task_succeeded_events


class TaskTest(AsyncHTTPTestCase):
    def test_unknown_task(self):
        r = self.get('/task/unknown')
        self.assertEqual(404, r.code)
        self.assertTrue('Unknown task' in str(r.body))

    def test_unknown_task_error_preserves_percent(self):
        r = self.get('/task/foo%25bar')
        self.assertEqual(404, r.code)
        self.assertIn('foo%bar', r.body.decode('utf-8'))
        self.assertNotIn('foo%%bar', r.body.decode('utf-8'))


class TaskControlsTest(AsyncHTTPTestCase):
    def render_task(self, *task_events):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1'), *task_events]
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self._app.events.state = state
        return self.get('/task/123')

    @staticmethod
    def received_event():
        return Event('task-received', uuid='123', name='task1', args='(2, 2)',
                     kwargs="{'foo': 'bar'}", retries=0, eta=None,
                     hostname='worker1')

    @staticmethod
    def started_event():
        return Event('task-started', uuid='123', hostname='worker1')

    def test_task_without_a_name_renders(self):
        # Flower saw this task finish but never saw it received, so it has no name
        r = self.render_task(Event('task-started', uuid='123', hostname='worker1'))
        self.assertEqual(200, r.code)
        body = r.body.decode('utf-8')
        self.assertIn('<title>Task 123 · Flower</title>', body)
        self.assertIn('<span class="value-missing">&mdash;</span>', body)

    def test_task_name_links_to_tasks_with_that_name(self):
        r = self.render_task(self.received_event(), self.started_event())
        self.assertEqual(200, r.code)
        self.assertIn('<a href="/tasks?name=task1">task1</a>', str(r.body))

    def test_task_page_title_has_name_and_short_id(self):
        r = self.render_task(self.received_event(), self.started_event())
        self.assertIn('<title>task1 123 · Flower</title>', r.body.decode('utf-8'))

    def test_started_task_has_terminate_button(self):
        r = self.render_task(self.received_event(), self.started_event())
        self.assertEqual(200, r.code)
        self.assertIn('task-terminate', str(r.body))

    def test_started_task_has_no_terminate_button_in_read_only(self):
        with self.mock_option('read_only', True):
            r = self.render_task(self.received_event(), self.started_event())
        self.assertEqual(200, r.code)
        self.assertNotIn('task-terminate', str(r.body))

    def test_received_task_has_revoke_button(self):
        r = self.render_task(self.received_event())
        self.assertEqual(200, r.code)
        self.assertIn('task-revoke', str(r.body))

    def test_received_task_has_no_revoke_button_in_read_only(self):
        with self.mock_option('read_only', True):
            r = self.render_task(self.received_event())
        self.assertEqual(200, r.code)
        self.assertNotIn('task-revoke', str(r.body))


class TasksTest(AsyncHTTPTestCase):
    def test_no_task(self):
        r = self.get('/tasks')
        self.assertEqual(200, r.code)
        self.assertTrue('UUID' in str(r.body))
        self.assertIn('<title>Tasks · Flower</title>', r.body.decode('utf-8'))
        self.assertNotIn('<tr id=', str(r.body))
        self.assertIn('tasks_filter.html', str(r.body))

    def test_invalid_search_returns_inline_error(self):
        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = 'ab'
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode('utf-8'))
        self.assertEqual(200, r.code)
        self.assertEqual([], table['data'])
        self.assertEqual(0, table['recordsTotal'])
        self.assertEqual(0, table['recordsFiltered'])
        self.assertEqual(
            'Substring search terms must contain at least 3 characters '
            'at position 0.',
            table['searchError'])

    def test_succeeded_task(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='123')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self._app.events.state = state

        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(1, table['recordsTotal'])
        self.assertEqual(1, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))
        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('123', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])

    def datatable_rows(self, search):
        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = search
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'
        r = self.get('/tasks/datatable?' + urlencode(params))
        self.assertEqual(200, r.code)
        return json.loads(r.body.decode('utf-8'))

    def test_search_with_quoted_phrase(self):
        state = EventsState()
        for uuid, args in (('1', ['hello world']), ('2', ['hello there'])):
            state.event(Event(
                'task-received', uuid=uuid, name='task1', args=args, kwargs={},
                retries=0, eta=None, hostname='worker1', clock=int(uuid),
                local_received=time.time()))
        self._app.events.state = state

        table = self.datatable_rows('args:"hello world"')
        self.assertEqual(['1'], [task['uuid'] for task in table['data']])

    def test_search_with_special_characters(self):
        state = EventsState()
        for uuid, args in (('1', ['<order>']), ('2', ['order'])):
            state.event(Event(
                'task-received', uuid=uuid, name='task1', args=args, kwargs={},
                retries=0, eta=None, hostname='worker1', clock=int(uuid),
                local_received=time.time()))
        self._app.events.state = state

        table = self.datatable_rows('args:<order>')
        self.assertEqual(['1'], [task['uuid'] for task in table['data']])

    def test_search_task_with_list_args(self):
        state = EventsState()
        event = Event(
            'task-received', uuid='123', name='task1',
            args=['needle', 2], kwargs={}, retries=0, eta=None,
            hostname='worker1', clock=1, local_received=time.time())
        state.event(event)
        self._app.events.state = state

        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = 'needle'
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode('utf-8'))
        self.assertEqual(200, r.code)
        self.assertEqual(1, table['recordsTotal'])
        self.assertEqual(1, table['recordsFiltered'])
        self.assertEqual('123', table['data'][0]['uuid'])

    def test_failed_task(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_failed_events(worker='worker1', name='task1',
                                     id='123')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self._app.events.state = state

        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(1, table['recordsTotal'])
        self.assertEqual(1, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))
        self.assertEqual('FAILURE', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('123', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])

    def test_sort_runtime(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='2', runtime=10.0)
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='4', runtime=10000000.0)
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='3', runtime=20.0)
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='1', runtime=2.0)
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self._app.events.state = state

        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'runtime'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(4, table['recordsTotal'])
        self.assertEqual(4, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(4, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('1', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])
        self.assertEqual(2.0, tasks[0]['runtime'])

        self.assertEqual('SUCCESS', tasks[1]['state'])
        self.assertEqual('task1', tasks[1]['name'])
        self.assertEqual('2', tasks[1]['uuid'])
        self.assertEqual('worker1', tasks[1]['worker'])
        self.assertEqual(10.0, tasks[1]['runtime'])

        self.assertEqual('SUCCESS', tasks[3]['state'])
        self.assertEqual('task1', tasks[3]['name'])
        self.assertEqual('4', tasks[3]['uuid'])
        self.assertEqual('worker1', tasks[3]['worker'])
        self.assertEqual(10000000.0, tasks[3]['runtime'])

    def test_sort_incomparable(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='123')
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='456', runtime=None)
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self._app.events.state = state

        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'runtime'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(2, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(2, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('456', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])
        self.assertIsNone(tasks[0]['runtime'])

        self.assertEqual('SUCCESS', tasks[1]['state'])
        self.assertEqual('task1', tasks[1]['name'])
        self.assertEqual('123', tasks[1]['uuid'])
        self.assertEqual('worker1', tasks[1]['worker'])

    def test_pagination(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='123')
        events += task_succeeded_events(worker='worker1', name='task2',
                                        id='456')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self._app.events.state = state

        params = {'draw': 1, 'start': 0, 'length': 10}
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'
        params['start'] = '0'
        params['length'] = '1'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(2, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('123', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])

        params['start'] = '1'
        params['length'] = '1'

        r = self.get('/tasks/datatable?' + '&'.join(
            '{}={}'.format(*x) for x in params.items()))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(2, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task2', tasks[0]['name'])
        self.assertEqual('456', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])


class TaskColumnsTest(AsyncHTTPTestCase):
    def header_columns(self):
        r = self.get('/tasks')
        self.assertEqual(200, r.code)
        return re.findall(r'<th data-column="(\w+)"', r.body.decode('utf-8'))

    def test_listed_columns_keep_the_given_order(self):
        self.assertEqual([('worker', 'Worker'), ('name', 'Name'), ('state', 'State')],
                         visible_task_columns('worker,name,state'))

    def test_unknown_columns_are_dropped(self):
        self.assertEqual([('uuid', 'UUID'), ('name', 'Name')],
                         visible_task_columns(' uuid, bogus,name'))

    def test_header_renders_the_selected_columns_in_order(self):
        with self.mock_option('tasks_columns', 'worker,name,state'):
            self.assertEqual(['worker', 'name', 'state'], self.header_columns())

    def test_default_header(self):
        self.assertEqual(['name', 'uuid', 'state', 'received', 'runtime', 'worker'],
                         self.header_columns())


class TasksTreeTest(AsyncHTTPTestCase):
    def setUp(self):
        super().setUp()
        state = EventsState()
        events = []
        for task_id, parent in (('parent', None), ('child1', 'parent'),
                                ('child2', 'parent'), ('grandchild', 'child2'),
                                ('other', None)):
            for event in task_succeeded_events(worker='worker1', id=task_id, name=task_id):
                event['parent_id'] = parent
                events.append(event)
        for clock, event in enumerate(events):
            event['clock'] = clock
            event['local_received'] = time.time()
            state.event(event)
        self._app.events.state = state

    def datatable(self, search='', expanded=None, tree='1', start=0, length=10):
        params = {
            'draw': 1, 'start': start, 'length': length, 'search[value]': search,
            'order[0][column]': 0, 'columns[0][data]': 'name', 'order[0][dir]': 'asc',
            'tree': tree, 'tree_expanded': json.dumps(expanded or {}),
        }
        r = self.post('/tasks/datatable', body=params)
        self.assertEqual(200, r.code)
        return json.loads(r.body.decode('utf-8'))

    def test_top_level_tasks_are_the_records(self):
        table = self.datatable()
        self.assertEqual(['other', 'parent'], [row['uuid'] for row in table['data']])
        self.assertEqual(2, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        parent = table['data'][1]
        self.assertEqual(2, parent['tree']['children'])
        self.assertFalse(parent['tree']['expanded'])
        self.assertEqual({'SUCCESS': 3}, parent['tree']['summary'])
        self.assertEqual('worker1', parent['worker'])
        self.assertNotIn('children', parent)

    def test_expanded_tasks_list_their_children(self):
        table = self.datatable(expanded={'parent': 50, 'child2': 50})
        self.assertEqual(
            [('other', 0), ('parent', 0), ('child1', 1), ('child2', 1), ('grandchild', 2)],
            [(row['uuid'], row['tree']['depth']) for row in table['data']])
        self.assertEqual(2, table['recordsFiltered'])

    def test_children_limit_adds_a_more_row(self):
        table = self.datatable(expanded={'parent': 1})
        rows = table['data']
        self.assertEqual(['other', 'parent', 'child1', 'parent:more'],
                         [row['uuid'] for row in rows])
        self.assertEqual({'depth': 1, 'guides': [], 'last': True, 'parent_id': 'parent',
                          'more': 1, 'limit': 1}, rows[-1]['tree'])

    def test_search_lists_matches_under_their_top_ancestor(self):
        table = self.datatable(search='grandchild', expanded={'parent': 50, 'child2': 50})
        self.assertEqual([('parent', False), ('child2', False), ('grandchild', True)],
                         [(row['uuid'], row['tree']['matched']) for row in table['data']])
        self.assertEqual(1, table['recordsFiltered'])
        self.assertEqual(2, table['recordsTotal'])

    def test_paging_counts_top_level_tasks(self):
        table = self.datatable(start=1, length=1, expanded={'parent': 50})
        self.assertEqual(['parent', 'child1', 'child2'], [row['uuid'] for row in table['data']])

    def test_malformed_expanded_tasks_are_ignored(self):
        params = {'draw': 1, 'start': 0, 'length': 10, 'search[value]': '',
                  'order[0][column]': 0, 'columns[0][data]': 'name',
                  'order[0][dir]': 'asc', 'tree': '1', 'tree_expanded': '{broken'}
        r = self.post('/tasks/datatable', body=params)
        self.assertEqual(200, r.code)
        self.assertEqual(2, len(json.loads(r.body.decode('utf-8'))['data']))

    def test_invalid_search_returns_inline_error(self):
        table = self.datatable(search='(')
        self.assertEqual([], table['data'])
        self.assertEqual(2, table['recordsTotal'])
        self.assertIn('searchError', table)

    def test_flat_layout_is_unchanged(self):
        table = self.datatable(tree='')
        self.assertEqual(5, table['recordsTotal'])
        self.assertEqual(5, len(table['data']))
        self.assertNotIn('tree', table['data'][0])

    def test_task_page_lists_children_oldest_first(self):
        r = self.get('/task/parent')
        self.assertEqual(200, r.code)
        body = r.body.decode('utf-8')
        self.assertLess(body.index('/task/child1'), body.index('/task/child2'))
        self.assertNotIn('/task/grandchild', body)

    def test_task_page_without_children_has_no_children_row(self):
        r = self.get('/task/other')
        self.assertEqual(200, r.code)
        self.assertNotIn('>Children<', r.body.decode('utf-8'))

    def test_expanding_a_subtree(self):
        table = self.datatable(expanded={'parent': 'all'})
        self.assertEqual(
            [('other', 0), ('parent', 0), ('child1', 1), ('child2', 1), ('grandchild', 2)],
            [(row['uuid'], row['tree']['depth']) for row in table['data']])
        self.assertTrue(table['data'][1]['tree']['subtree'])

        table = self.datatable(expanded={'parent': 'all', 'child2': 0})
        self.assertEqual(['other', 'parent', 'child1', 'child2'],
                         [row['uuid'] for row in table['data']])


class DesignTest(AsyncHTTPTestCase):
    def page(self, design, url='/tasks'):
        with self.mock_option('design', design):
            r = self.get(url)
        self.assertEqual(200, r.code)
        return r.body.decode('utf-8')

    def test_classic_loads_no_design_stylesheet(self):
        body = self.page('classic')
        self.assertIn('<html lang="en">', body)
        self.assertNotIn('design-', body)

    def test_design_marks_the_page_and_loads_its_stylesheet(self):
        for design in ('glass', 'terminal'):
            with self.subTest(design=design):
                for url in ('/tasks', '/workers'):
                    body = self.page(design, url)
                    self.assertIn(f'<html lang="en" data-design="{design}">', body)
                    self.assertRegex(body, rf'href="/static/css/design-{design}\.css\?v=\w+"')
                    other = 'terminal' if design == 'glass' else 'glass'
                    self.assertNotIn(f'design-{other}.css', body)

    def test_every_design_has_a_stylesheet(self):
        static = os.path.join(os.path.dirname(flower.__file__), 'static', 'css')
        for design in DESIGNS[1:]:
            self.assertTrue(os.path.isfile(os.path.join(static, f'design-{design}.css')), design)
