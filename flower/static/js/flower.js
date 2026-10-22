/*jslint browser: true */
/*global $, WebSocket, jQuery, bootstrap */

(function () {
    "use strict";

    var toastContainer = document.getElementById('toast-container');

    document.querySelectorAll('[data-flower-tooltip]').forEach(function (element) {
        var tooltip = bootstrap.Tooltip.getOrCreateInstance(element);

        element.addEventListener('show.bs.tooltip', function () {
            document.querySelectorAll('[data-flower-tooltip]').forEach(function (other) {
                if (other !== element) {
                    bootstrap.Tooltip.getInstance(other).hide();
                }
            });
        });

        element.addEventListener('show.bs.dropdown', function () {
            tooltip.hide();
            tooltip.disable();
        });
        element.addEventListener('hidden.bs.dropdown', function () {
            tooltip.enable();
        });
    });

    function show_alert(message, type) {
        var isError = type === 'danger',
            toastElement = document.createElement('div'),
            toastContent = document.createElement('div'),
            toastBody = document.createElement('div'),
            closeButton = document.createElement('button'),
            toast;

        toastElement.className = 'toast align-items-center text-bg-' + type + ' border-0';
        toastElement.setAttribute('role', isError ? 'alert' : 'status');
        toastElement.setAttribute('aria-live', isError ? 'assertive' : 'polite');
        toastElement.setAttribute('aria-atomic', 'true');

        toastContent.className = 'd-flex';
        toastBody.className = 'toast-body';
        toastBody.textContent = message;

        closeButton.type = 'button';
        closeButton.className = 'btn-close btn-close-white me-2 m-auto';
        closeButton.setAttribute('data-bs-dismiss', 'toast');
        closeButton.setAttribute('aria-label', 'Close');

        toastContent.appendChild(toastBody);
        toastContent.appendChild(closeButton);
        toastElement.appendChild(toastContent);
        toastContainer.appendChild(toastElement);

        toastElement.addEventListener('hidden.bs.toast', function () {
            toast.dispose();
            toastElement.remove();
        });

        toast = bootstrap.Toast.getOrCreateInstance(toastElement, {
            autohide: true,
            delay: isError ? 10000 : 5000
        });
        toast.show();
    }

    function url_prefix() {
        var prefix = $('#url_prefix').val();
        if (prefix) {
            prefix = prefix.replace(/\/+$/, '');
            if (prefix.startsWith('/')) {
                return prefix;
            } else {
                return '/' + prefix;
            }
        }
        return '';
    }

    function getCookie(name) {
        var match = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
        return match ? decodeURIComponent(match.pop()) : '';
    }

    // Send the XSRF token on state-changing requests for the server's CSRF check
    $.ajaxSetup({
        beforeSend: function (xhr, settings) {
            if (!/^(GET|HEAD|OPTIONS)$/i.test(settings.type)) {
                xhr.setRequestHeader('X-XSRFToken', getCookie('_xsrf'));
            }
        }
    });

    //https://github.com/DataTables/DataTables/blob/1.10.11/media/js/jquery.dataTables.js#L14882
    function htmlEscapeEntities(d) {
        return typeof d === 'string' ?
            d.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;') :
            d;
    }

    var MISSING_VALUE = '<span class="value-missing">\u2014</span>';

    function tasksPageUrl(filters) {
        var params = ['worker', 'state', 'name'].filter(function (key) {
            return filters[key];
        }).map(function (key) {
            return key + '=' + encodeURIComponent(filters[key]);
        });
        return url_prefix() + '/tasks' + (params.length ? '?' + params.join('&') : '');
    }

    // Per-worker task counters link to the tasks page filtered to that worker
    function taskCountRenderer(state) {
        return function (data, type, full, meta) {
            var count = data || 0;
            if (type !== 'display' || !count) {
                return count;
            }
            return '<a href="' + tasksPageUrl({worker: full.hostname, state: state}) + '">' + count.toLocaleString() + '</a>';
        };
    }

    // DataTables writes cell values straight to innerHTML, so a column that
    // does not build its own markup must be escaped
    function withDefaultRenderer(columnDefs) {
        columnDefs.forEach(function (def) {
            if (!def.render) {
                def.render = htmlEscapeEntities;
            }
        });
        return columnDefs;
    }

    function workerNameLink(workerName) {
        var name = String(workerName),
            escapedName = htmlEscapeEntities(name),
            suffixLength = name.length > 12 ? 12 : 0,
            prefix = htmlEscapeEntities(name.substr(0, name.length - suffixLength)),
            suffix = suffixLength ? htmlEscapeEntities(name.substr(-suffixLength)) : '';

        return '<a class="worker-name-link" href="' + url_prefix() + '/worker/' +
            encodeURIComponent(name) + '" aria-label="Worker ' + escapedName + '" title="' + escapedName + '">' +
            '<span class="worker-name-prefix">' + prefix + '</span>' +
            '<span class="worker-name-suffix">' + suffix + '</span></a>';
    }

    function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }

        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        textarea.remove();
        return Promise.resolve();
    }

    function showCopyConfirmation(button, copiedLabel, defaultLabel) {
        button.classList.add('copied');
        button.setAttribute('title', 'Copied');
        button.setAttribute('aria-label', copiedLabel);
        window.setTimeout(function () {
            button.classList.remove('copied');
            button.setAttribute('title', defaultLabel);
            button.setAttribute('aria-label', defaultLabel);
        }, 1500);
    }

    function active_page(name) {
        var pathname = $(location).attr('pathname');
        if (name === '/') {
            return pathname === (url_prefix() + name);
        }
        else {
            return pathname.startsWith(url_prefix() + name);
        }
    }

    $('#worker-refresh').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        $('.dropdown-toggle').dropdown('hide');

        var workername = $('#workername').text();

        $.ajax({
            type: 'GET',
            url: url_prefix() + '/api/workers',
            dataType: 'json',
            data: {
                workername: unescape(workername),
                refresh: 1
            },
            success: function (data) {
                show_alert(data.message || 'Successfully refreshed', 'success');
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-refresh-all').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        $('.dropdown-toggle').dropdown('hide');

        $.ajax({
            type: 'GET',
            url: url_prefix() + '/api/workers',
            dataType: 'json',
            data: {
                refresh: 1
            },
            success: function (data) {
                show_alert(data.message || 'Refreshed All Workers', 'success');
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-pool-restart').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        $('.dropdown-toggle').dropdown('hide');

        var workername = $('#workername').text();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/worker/pool/restart/' + workername,
            dataType: 'json',
            data: {
                workername: workername
            },
            success: function (data) {
                show_alert(data.message, "success");
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-shutdown').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        $('.dropdown-toggle').dropdown('hide');

        var workername = $('#workername').text();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/worker/shutdown/' + workername,
            dataType: 'json',
            data: {
                workername: workername
            },
            success: function (data) {
                show_alert(data.message, "success");
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-pool-grow').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        var workername = $('#workername').text(),
            grow_size = $('#pool-size').val();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/worker/pool/grow/' + workername,
            dataType: 'json',
            data: {
                'workername': workername,
                'n': grow_size,
            },
            success: function (data) {
                show_alert(data.message, "success");
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-pool-shrink').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        var workername = $('#workername').text(),
            shrink_size = $('#pool-size').val();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/worker/pool/shrink/' + workername,
            dataType: 'json',
            data: {
                'workername': workername,
                'n': shrink_size,
            },
            success: function (data) {
                show_alert(data.message, "success");
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-pool-autoscale').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        var workername = $('#workername').text(),
            min = $('#min-autoscale').val(),
            max = $('#max-autoscale').val();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/worker/pool/autoscale/' + workername,
            dataType: 'json',
            data: {
                'workername': workername,
                'min': min,
                'max': max,
            },
            success: function (data) {
                show_alert(data.message, "success");
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-add-consumer').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        var workername = $('#workername').text(),
            queue = $('#add-consumer-name').val();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/worker/queue/add-consumer/' + workername,
            dataType: 'json',
            data: {
                'workername': workername,
                'queue': queue,
            },
            success: function (data) {
                show_alert(data.message, "success");
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#worker-queues').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        if (!event.target.id.startsWith("worker-cancel-consumer")) {
            return;
        }

        var workername = $('#workername').text(),
            queue = $(event.target).closest("tr").children("td:eq(0)").text();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/worker/queue/cancel-consumer/' + workername,
            dataType: 'json',
            data: {
                'workername': workername,
                'queue': queue,
            },
            success: function (data) {
                show_alert(data.message, "success");
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#limits-table').on('click', function (event) {
        if (event.target.id.startsWith("task-timeout-")) {
            var timeout = parseInt($(event.target).siblings().closest("input").val()),
                type = $(event.target).text().toLowerCase(),
                taskname = $(event.target).closest("tr").children("td:eq(0)").text(),
                post_data = {'workername': $('#workername').text()};

            taskname = taskname.split(' ')[0]; // removes [rate_limit=xxx]
            post_data[type] = timeout;

            if (!Number.isInteger(timeout)) {
                show_alert("Invalid timeout value", "danger");
                return;
            }

            $.ajax({
                type: 'POST',
                url: url_prefix() + '/api/task/timeout/' + taskname,
                dataType: 'json',
                data: post_data,
                success: function (data) {
                    show_alert(data.message, "success");
                },
                error: function (data) {
                    show_alert($(data.responseText).text(), "danger");
                }
            });
        } else if (event.target.id.startsWith("task-rate-limit-")) {
            var taskname = $(event.target).closest("tr").children("td:eq(0)").text(),
                workername = $('#workername').text(),
                ratelimit = parseInt($(event.target).prev().val());

            taskname = taskname.split(' ')[0]; // removes [rate_limit=xxx]

            $.ajax({
                type: 'POST',
                url: url_prefix() + '/api/task/rate-limit/' + taskname,
                dataType: 'json',
                data: {
                    'workername': workername,
                    'ratelimit': ratelimit,
                },
                success: function (data) {
                    show_alert(data.message, "success");
                },
                error: function (data) {
                    show_alert(data.responseText, "danger");
                }
            });
        }
    });

    $('#task-revoke').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        var taskid = $('#taskid').text();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/task/revoke/' + taskid,
            dataType: 'json',
            data: {
                'terminate': false,
            },
            success: function (data) {
                show_alert(data.message, "success");
                document.getElementById("task-revoke").disabled = true;
                setTimeout(function() {location.reload();}, 5000);
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    $('#task-terminate').on('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        var taskid = $('#taskid').text();

        $.ajax({
            type: 'POST',
            url: url_prefix() + '/api/task/revoke/' + taskid,
            dataType: 'json',
            data: {
                'terminate': true,
            },
            success: function (data) {
                show_alert(data.message, "success");
                document.getElementById("task-terminate").disabled = true;
                setTimeout(function() {location.reload();}, 5000);
            },
            error: function (data) {
                show_alert(data.responseText, "danger");
            }
        });
    });

    function sum(a, b) {
        var x = parseInt(a, 10), y = parseInt(b, 10);
        return (isNaN(x) ? 0 : x) + (isNaN(y) ? 0 : y);
    }

    function workerMetricTotal(workers, name) {
        return workers.reduce(function (total, worker) {
            var value = Number(worker[name]);
            return total + (isNaN(value) ? 0 : value);
        }, 0);
    }

    function setWorkerMetric(id, value) {
        document.getElementById(id).textContent = value.toLocaleString();
    }

    function updateWorkerSummary(workers) {
        var online = workers.filter(function (worker) {
            return worker.status;
        }).length;

        setWorkerMetric('workers-online', online);
        setWorkerMetric('workers-active', workerMetricTotal(workers, 'active'));
        setWorkerMetric('workers-succeeded', workerMetricTotal(workers, 'task-succeeded'));
        setWorkerMetric('workers-failed', workerMetricTotal(workers, 'task-failed'));
    }

    function updateWorkerRefreshStatus(succeeded) {
        var indicator = document.getElementById('workers-live-indicator'),
            status = document.getElementById('workers-refresh-status');

        indicator.classList.toggle('status-dot-live', succeeded);
        indicator.classList.toggle('status-dot-error', !succeeded);
        status.textContent = succeeded ?
            'Updated ' + new Date().toLocaleTimeString() :
            'Update failed';
    }

    // Mirrors flower.utils.template.format_duration
    function formatDuration(seconds) {
        seconds = Number(seconds);
        if (seconds < 1) {
            return (seconds * 1000).toFixed(2) + ' ms';
        }
        if (seconds < 60) {
            return seconds.toFixed(2) + ' s';
        }
        var total = Math.round(seconds),
            hours = Math.floor(total / 3600),
            minutes = Math.floor((total % 3600) / 60),
            secs = String(total % 60).padStart(2, '0');
        if (hours) {
            return hours + 'h ' + String(minutes).padStart(2, '0') + 'm ' + secs + 's';
        }
        return minutes + 'm ' + secs + 's';
    }

    function format_time(timestamp) {
        var time = $('#time').val(),
            prefix = time.startsWith('natural-time') ? 'natural-time' : 'time',
            tz = time.substr(prefix.length + 1) || 'UTC';

        if (prefix === 'natural-time') {
            return moment.unix(timestamp).tz(tz).fromNow();
        }
        return moment.unix(timestamp).tz(tz).format('YYYY-MM-DD HH:mm:ss.SSS');
    }

    function usesNaturalTime() {
        return $('#time').val().startsWith('natural-time');
    }

    // 16px glyphs drawn inside a filled circle, keyed by task state
    var TASK_STATE_GLYPHS = {
        SUCCESS: {kind: 'success', path: 'M5 8.2 7.1 10.3 11 6.1'},
        FAILURE: {kind: 'failure', path: 'M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8'},
        STARTED: {kind: 'started', path: 'M8 1.75a6.25 6.25 0 0 1 6.25 6.25'},
        RETRY: {kind: 'retry', path: 'M11.9 9.6A4.2 4.2 0 1 1 11.2 5.2M11.6 2.9v2.6H9'},
        RECEIVED: {kind: 'waiting', path: 'M8 4.8V8l2.2 1.4'},
        PENDING: {kind: 'waiting', path: 'M8 4.8V8l2.2 1.4'},
        REVOKED: {kind: 'revoked', path: 'M4.9 11.1l6.2-6.2'},
        REJECTED: {kind: 'revoked', path: 'M4.9 11.1l6.2-6.2'}
    };

    // Celery reports unknown task-* events as custom states, shown as a dot
    function taskStateIcon(state) {
        var glyph = TASK_STATE_GLYPHS[state] || {kind: 'other', path: 'M8 8h.01'},
            label = htmlEscapeEntities(state);
        return '<span class="task-state-icon task-state-icon-' + glyph.kind + '" role="img" aria-label="' +
            label + '" title="' + label + '"><svg viewBox="0 0 16 16" aria-hidden="true">' +
            '<circle class="task-state-disc" cx="8" cy="8" r="7.25"/>' +
            '<path class="task-state-glyph" d="' + glyph.path + '"/></svg></span>';
    }

    // Column definitions for the tasks table, keyed by column slug
    var taskColumns = {
        name: {
            render: function (data, type, full, meta) {
                // The uuid column opens the task, the name lists its siblings
                return '<a href="' + tasksPageUrl({name: data}) + '">' + htmlEscapeEntities(data) + '</a>';
            }
        },
        uuid: {
            orderable: false,
            className: "text-nowrap",
            render: function (data, type, full, meta) {
                if (type !== 'display') {
                    return data;
                }
                var escapedUuid = htmlEscapeEntities(data);
                // Mobile width shows only the first uuid block, the link keeps the full id
                return '<a href="' + url_prefix() + '/task/' + encodeURIComponent(data) +
                    '" title="' + escapedUuid + '">' +
                    '<span class="task-uuid-full">' + escapedUuid + '</span>' +
                    '<span class="task-uuid-short">' + escapedUuid.slice(0, 8) + '</span></a>';
            }
        },
        state: {
            className: "text-center",
            render: function (data, type, full, meta) {
                if (type !== 'display') {
                    return data;
                }
                return taskStateIcon(data);
            }
        },
        args: {
            className: "text-nowrap overflow-auto",
            render: htmlEscapeEntities
        },
        kwargs: {
            className: "text-nowrap overflow-auto",
            render: htmlEscapeEntities
        },
        result: {
            className: "text-nowrap overflow-auto",
            render: htmlEscapeEntities
        },
        received: {
            className: "text-center text-nowrap",
            width: "1%",
            render: function (data, type, full, meta) {
                if (data) {
                    if (type !== 'display') {
                        return data;
                    }
                    if (usesNaturalTime()) {
                        return format_time(data);
                    }
                    return '<time datetime="' + moment.unix(data).toISOString() +
                        '" title="' + moment.unix(data).fromNow() + '">' +
                        format_time(data) + '</time>';
                }
                return data;
            }
        },
        started: {
            className: "text-center text-nowrap",
            render: function (data, type, full, meta) {
                if (data) {
                    return format_time(data);
                }
                return data;
            }
        },
        runtime: {
            className: "text-center text-nowrap",
            render: function (data, type, full, meta) {
                return data === null || data === undefined ? '' : formatDuration(data);
            }
        },
        worker: {
            render: function (data, type, full, meta) {
                if (!data) {
                    return '';
                }
                return type === 'display' ? workerNameLink(data) : data;
            }
        },
        exchange: {},
        routing_key: {},
        retries: {
            className: "text-center"
        },
        revoked: {
            className: "text-center text-nowrap",
            render: function (data, type, full, meta) {
                if (data) {
                    return format_time(data);
                }
                return data;
            }
        },
        exception: {
            className: "text-nowrap"
        },
        expires: {
            className: "text-center"
        },
        eta: {
            className: "text-center"
        }
    };

    function updateTaskStateButtons(state) {
        $('.task-state-filter').each(function () {
            var selected = $(this).data('task-state') === state;
            $(this).toggleClass('active', selected);
            $(this).attr('aria-pressed', selected);
        });
    }

    function taskStateFromSearch(search) {
        var match = /(?:^|\s)state:(STARTED|SUCCESS|FAILURE|RETRY)(?:\s|$)/i.exec(search);
        return match ? match[1].toUpperCase() : '';
    }

    // Tree layout of the tasks table. The server lists the top-level tasks as
    // the table's records and puts the children of the expanded tasks right
    // after their parent, each row with a `tree` object describing its place.
    var TASK_TREE_STORAGE_KEY = 'flower.tasks.tree',
        TASK_TREE_CHILDREN_PAGE = 50,
        TASK_TREE_MAX_EXPANDED = 500,
        TASK_TREE_MAX_GUIDES = 8,
        TASK_TREE_ACTIVE_STATES = ['PENDING', 'RECEIVED', 'STARTED', 'RETRY'],
        CHEVRON_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">' +
            '<path d="M5.7 2.3a1 1 0 0 0-1.4 1.4L8.6 8l-4.3 4.3a1 1 0 1 0 1.4 1.4l5-5a1 1 0 0 0 0-1.4l-5-5Z"/></svg>',
        EXPAND_ALL_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">' +
            '<path d="M2.3 2.3a1 1 0 0 1 1.4 0L8 6.6l4.3-4.3a1 1 0 1 1 1.4 1.4l-5 5a1 1 0 0 1-1.4 0l-5-5a1 1 0 0 1 0-1.4Z"/>' +
            '<path d="M2.3 7.3a1 1 0 0 1 1.4 0L8 11.6l4.3-4.3a1 1 0 1 1 1.4 1.4l-5 5a1 1 0 0 1-1.4 0l-5-5a1 1 0 0 1 0-1.4Z"/></svg>';

    // Browser storage can be missing or throw (private windows, blocked
    // storage), the table works without it
    function loadTaskTreeSettings() {
        var settings = {view: 'tree', live: false, expanded: {}};
        try {
            var saved = JSON.parse(window.localStorage.getItem(TASK_TREE_STORAGE_KEY));
            if (saved && typeof saved === 'object') {
                settings.view = saved.view === 'flat' ? 'flat' : 'tree';
                settings.live = saved.live === true;
                if (saved.expanded && typeof saved.expanded === 'object') {
                    settings.expanded = saved.expanded;
                }
            }
        } catch (e) {
            // keep the defaults
        }
        return settings;
    }

    function saveTaskTreeSettings(settings) {
        try {
            window.localStorage.setItem(TASK_TREE_STORAGE_KEY, JSON.stringify(settings));
        } catch (e) {
            // the settings last until the page is left
        }
    }

    // Each expanded task maps to how many children to list, 0 keeps a task
    // collapsed inside an expanded subtree, and "all:<count>" also expands
    // every task below it
    function setTaskExpanded(expanded, taskId, value) {
        delete expanded[taskId];
        expanded[taskId] = value;
        // Forget the tasks expanded longest ago, keys keep insertion order
        var ids = Object.keys(expanded);
        ids.slice(0, Math.max(ids.length - TASK_TREE_MAX_EXPANDED, 0)).forEach(function (id) {
            delete expanded[id];
        });
    }

    function taskTreeGuides(tree) {
        var guides = tree.guides || [],
            html = '';
        if (guides.length > TASK_TREE_MAX_GUIDES) {
            // Very deep rows show their level instead of every guide
            html += '<span class="task-tree-depth" title="Level ' + tree.depth + '">L' + tree.depth + '</span>';
            guides = guides.slice(-TASK_TREE_MAX_GUIDES);
        }
        guides.forEach(function (line) {
            html += '<span class="task-tree-guide' + (line ? ' task-tree-guide-line' : '') + '"></span>';
        });
        if (tree.depth) {
            html += '<span class="task-tree-branch' + (tree.last ? ' task-tree-branch-last' : '') + '"></span>';
        }
        return html;
    }

    function taskTreeSummary(tree) {
        var summary = tree.summary,
            total = 0,
            failed = 0,
            active = 0,
            parts = [];
        if (!summary) {
            return '';
        }
        Object.keys(summary).forEach(function (state) {
            total += summary[state];
            parts.push(summary[state] + ' ' + state);
            if (state === 'FAILURE') {
                failed += summary[state];
            } else if (TASK_TREE_ACTIVE_STATES.indexOf(state) !== -1) {
                active += summary[state];
            }
        });
        var title = htmlEscapeEntities(total + ' task' + (total === 1 ? '' : 's') + ' below: ' + parts.join(', '));
        return '<span class="task-tree-summary" title="' + title + '" aria-label="' + title + '">' +
            '<span>' + total.toLocaleString() + ' below</span>' +
            (failed ? '<span class="task-tree-summary-failed">' + failed.toLocaleString() + ' failed</span>' : '') +
            (active ? '<span class="task-tree-summary-active">' + active.toLocaleString() + ' active</span>' : '') +
            '</span>';
    }

    // Wraps the first column's cell with the row's place in the tree
    function taskTreeCell(full, content) {
        var tree = full.tree,
            html = '<span class="task-tree-cell">' + taskTreeGuides(tree);

        if (tree.more !== undefined) {
            return html + '<button type="button" class="task-tree-more" data-parent-id="' +
                htmlEscapeEntities(tree.parent_id) + '" data-limit="' + tree.limit + '">Show ' +
                Math.min(tree.more, TASK_TREE_CHILDREN_PAGE).toLocaleString() + ' more of ' +
                tree.more.toLocaleString() + ' hidden</button></span>';
        }

        var taskName = full.name || full.uuid,
            allExpanded = tree.subtree && tree.expanded;
        if (tree.children) {
            var label = (tree.expanded ? 'Hide ' : 'Show ') + tree.children.toLocaleString() +
                ' child task' + (tree.children === 1 ? '' : 's') + ' of ' + taskName;
            html += '<button type="button" class="task-tree-toggle" data-task-id="' +
                htmlEscapeEntities(full.uuid) + '" data-in-subtree="' + tree.in_subtree + '" aria-expanded="' +
                tree.expanded + '" aria-label="' + htmlEscapeEntities(label) + '" title="' +
                htmlEscapeEntities(label + ' (Alt+click: all levels)') + '">' + CHEVRON_ICON + '</button>';
        } else {
            html += '<span class="task-tree-toggle-spacer"></span>';
        }

        html += '<span class="task-tree-content">' + (content === null || content === undefined ? '' : content) +
            taskTreeSummary(tree);
        if (tree.children) {
            var allLabel = htmlEscapeEntities((allExpanded ? 'Collapse all levels below ' : 'Expand all levels below ') +
                taskName);
            html += '<button type="button" class="task-tree-expand-all" data-task-id="' +
                htmlEscapeEntities(full.uuid) + '" aria-pressed="' + allExpanded + '" aria-label="' + allLabel +
                '" title="' + allLabel + '">' + EXPAND_ALL_ICON + '</button>';
        }
        if (tree.missing_parent_id) {
            var parentTitle = htmlEscapeEntities('Started by task ' + tree.missing_parent_id +
                ', which is no longer in Flower\'s memory');
            html += '<span class="task-tree-missing-parent" title="' + parentTitle + '" aria-label="' +
                parentTitle + '">↰ parent gone</span>';
        }
        return html + '</span></span>';
    }

    // Renders every column of a tree row: the first column carries the tree,
    // the others are empty on rows standing for hidden children
    function withTaskTreeRenderer(columnDefs) {
        return columnDefs.map(function (def, index) {
            var render = def.render;
            def.render = function (data, type, full, meta) {
                var tree = full.tree;
                if (tree && tree.more !== undefined) {
                    return index === 0 && type === 'display' ? taskTreeCell(full) : '';
                }
                var content = render(data, type, full, meta);
                if (tree && index === 0 && type === 'display') {
                    return taskTreeCell(full, content);
                }
                return content;
            };
            return def;
        });
    }

    $.urlParam = function (name) {
        var results = new RegExp('[\\?&]' + name + '=([^&#]*)').exec(window.location.href);
        return (results && results[1]) || 0;
    };

    $(document).ready(function () {
        //https://github.com/twitter/bootstrap/issues/1768
        var shiftWindow = function () {
            scrollBy(0, -50);
        };
        if (location.hash) {
            shiftWindow();
        }
        window.addEventListener("hashchange", shiftWindow);

        $('.task-uuid-copy').on('click', function () {
            var button = this;
            copyText(button.getAttribute('data-task-uuid')).then(function () {
                showCopyConfirmation(button, 'Task UUID copied', 'Copy task UUID');
            });
        });

        $('.task-traceback-copy').on('click', function () {
            var button = this,
                traceback = button.closest('.detail-code-wrapper').querySelector('code').textContent;
            copyText(traceback).then(function () {
                showCopyConfirmation(button, 'Stack trace copied', 'Copy stack trace');
            });
        });

        // Make bootstrap tabs persistent
        $(document).ready(function () {
            if (location.hash !== '') {
                $('a[href="' + location.hash + '"]').tab('show');
            }

            // Listen for tab shown events and update the URL hash fragment accordingly
            $('.nav-tabs a[data-bs-toggle="tab"]').on('shown.bs.tab', function (event) {
                const tabPaneId = $(event.target).attr('href').substr(1);
                if (tabPaneId) {
                    window.location.hash = tabPaneId;
                }
            });
        });
    });

    $(document).ready(function () {
        if (!active_page('/') && !active_page('/workers')) {
            return;
        }

        var workersTable = $('#workers-table').DataTable({
            rowId: 'name',
            createdRow: function (row, data) {
                $(row).toggleClass('worker-offline', !data.status);
            },
            searching: true,
            select: false,
            paging: true,
            lengthChange: false,
            scrollX: true,
            scrollCollapse: true,
            pageLength: 15,
            language: {
                lengthMenu: 'Show _MENU_ workers',
                info: 'Showing _START_ to _END_ of _TOTAL_ workers',
                infoFiltered: '(filtered from _MAX_ total workers)',
                search: '<span class="visually-hidden">Search workers</span>',
                searchPlaceholder: 'celery@hostname or online',
                emptyTable: 'No workers are available.',
                zeroRecords: 'No workers match your search.'
            },
            ajax: {
                url: url_prefix() + '/workers?json=1',
                dataSrc: function (response) {
                    var workers = response.data || [];
                    updateWorkerSummary(workers);
                    updateWorkerRefreshStatus(true);
                    return workers;
                },
                error: function () {
                    updateWorkerRefreshStatus(false);
                }
            },
            order: [
                [1, "des"]
            ],
            footerCallback: function( tfoot, data, start, end, display ) {
                var api = this.api();
                var columns = {2:"STARTED", 3:"", 4:"FAILURE", 5:"SUCCESS"};
                for (const [column, state] of Object.entries(columns)) {
                    var total = api.column(column).data().reduce(sum, 0);
                    var footer = total.toLocaleString();
                    if (total !== 0) {
                        footer = '<a href="' + tasksPageUrl({state: state}) + '">' + footer + '</a>';
                    }
                    $(api.column(column).footer()).html(footer);
                }
            },
            columnDefs: withDefaultRenderer([{
                targets: 0,
                data: 'hostname',
                type: 'natural',
                render: function (data, type, full, meta) {
                    return type === 'display' ? workerNameLink(data) : data;
                }
            }, {
                targets: 1,
                data: 'status',
                className: "text-center",
                width: "10%",
                render: function (data, type, full, meta) {
                    if (data) {
                        return '<span class="badge bg-success">Online</span>';
                    } else {
                        return '<span class="badge bg-secondary">Offline</span>';
                    }
                }
            }, {
                targets: 2,
                data: 'active',
                className: "text-center",
                width: "10%",
                defaultContent: 0,
                render: taskCountRenderer('STARTED')
            }, {
                targets: 3,
                data: 'task-received',
                className: "text-center",
                width: "10%",
                defaultContent: 0,
                render: taskCountRenderer()
            }, {
                targets: 4,
                data: 'task-failed',
                className: "text-center",
                width: "10%",
                defaultContent: 0,
                render: taskCountRenderer('FAILURE')
            }, {
                targets: 5,
                data: 'task-succeeded',
                className: "text-center",
                width: "10%",
                defaultContent: 0,
                render: taskCountRenderer('SUCCESS')
            }, {
                targets: 6,
                data: 'loadavg',
                width: "18%",
                className: "text-center text-nowrap",
                render: function (data, type, full, meta) {
                    if (!full.status) {
                        return type === 'display' ? MISSING_VALUE : '';
                    }
                    if (Array.isArray(data)) {
                        if (type !== 'display') {
                            return data.join(' ');
                        }
                        var periods = ['1m', '5m', '15m'],
                            values = data.slice(0, periods.length).map(function (value) {
                                return '<span class="load-average-value">' +
                                    htmlEscapeEntities(String(value)) + '</span>';
                            });
                        return '<span class="load-average" title="System load averages over 1, 5, and 15 minutes"' +
                            ' aria-label="System load averages: ' + periods.map(function (period, index) {
                                return period + ' ' + htmlEscapeEntities(String(data[index]));
                            }).join(', ') + '">' +
                            values.join('') + '</span>';
                    }
                    if (!data) {
                        return type === 'display' ? MISSING_VALUE : '';
                    }
                    return htmlEscapeEntities(String(data));
                }
            }, ]),
        });

        var autorefresh_interval = $.urlParam('autorefresh') || 1;
        if (autorefresh !== 0) {
            setInterval( function () {
                workersTable.ajax.reload(null, false);
            }, autorefresh_interval * 1000);
        }

    });

    $(document).ready(function () {
        if (!active_page('/tasks')) {
            return;
        }

        var initialSearch = ['state', 'worker', 'name'].map(function (key) {
                var value = decodeURIComponent($.urlParam(key) || '');
                return value ? key + ':' + value : '';
            }).filter(Boolean).join(' '),
            // The server renders the header in the configured order
            headerColumns = $('#tasks-table thead th').map(function () {
                return $(this).data('column');
            }).get(),
            layout = headerColumns.join(','),
            sortColumn = Math.max(headerColumns.indexOf('received'), 0),
            treeSettings = loadTaskTreeSettings(),
            viewParam = $.urlParam('view'),
            liveParam = parseInt($.urlParam('autorefresh'), 10),
            liveInterval = (liveParam > 0 ? liveParam : 3) * 1000,
            liveTimer = null,
            requestPending = false,
            focusAfterDraw = null;

        if (viewParam === 'flat' || viewParam === 'tree') {
            treeSettings.view = viewParam;
        }
        if (liveParam > 0) {
            treeSettings.live = true;
        }

        function treeView() {
            return treeSettings.view === 'tree';
        }

        var tasksTable = $('#tasks-table').DataTable({
            rowId: 'uuid',
            searching: true,
            searchDelay: 300,
            processing: true,
            serverSide: true,
            // A scrolling wrapper rather than scrollX, which splits off the
            // header into a table of its own that expanded rows can outgrow
            dom: "fr<'tasks-table-scroll't><'dt-footer'lip>",
            lengthMenu: [15, 30, 50, 100],
            pageLength: 15,
            stateSave: true,
            stateSaveParams: function (settings, data) {
                data.layout = layout;
            },
            stateLoadParams: function (settings, data) {
                // Sort and visibility saved under another column layout point at the wrong columns
                if (data.layout !== layout) {
                    return false;
                }
                if (initialSearch) {
                    data.search.search = initialSearch;
                }
            },
            initComplete: function () {
                $('#tasks-table_length select').attr('aria-label', 'Tasks per page');
            },
            createdRow: function (row, data) {
                var tree = data.tree;
                if (!tree) {
                    return;
                }
                row.classList.add('task-tree-row');
                row.classList.toggle('task-tree-child', tree.depth > 0);
                row.classList.toggle('task-tree-context', tree.matched === false);
            },
            infoCallback: function (settings, start, end, max, total, pre) {
                // In the tree layout the records are the top-level tasks
                if (!treeView() || !total) {
                    return pre;
                }
                return 'Showing ' + start.toLocaleString() + ' to ' + end.toLocaleString() + ' of ' +
                    total.toLocaleString() + ' top-level tasks' +
                    (total !== max ? ' (filtered from ' + max.toLocaleString() + ')' : '');
            },
            language: {
                lengthMenu: '_MENU_',
                info: 'Showing _START_ to _END_ of _TOTAL_ tasks',
                infoEmpty: 'No tasks to show',
                infoFiltered: '(filtered from _MAX_ total tasks)',
                search: '<span class="visually-hidden">Search tasks</span>',
                searchPlaceholder: 'state:FAILURE worker:celery@hostname',
                emptyTable: 'No tasks have been received.',
                zeroRecords: 'No tasks match your search.'
            },
            ajax: {
                type: 'POST',
                url: url_prefix() + '/tasks/datatable',
                data: function (params) {
                    if (treeView()) {
                        params.tree = 1;
                        params.tree_expanded = JSON.stringify(treeSettings.expanded);
                    }
                },
                dataSrc: function (response) {
                    var searchError = $('#task-search-error'),
                        searchErrorMessage = $('#task-search-error-message');
                    if (response.searchError) {
                        searchErrorMessage.text(response.searchError);
                        searchError.removeClass('d-none');
                    } else {
                        searchErrorMessage.text('');
                        searchError.addClass('d-none');
                    }
                    return response.data;
                }
            },
            order: [
                [sortColumn, "desc"]
            ],
            oSearch: {
                "sSearch": initialSearch
            },
            columns: withTaskTreeRenderer(withDefaultRenderer(headerColumns.map(function (name) {
                return $.extend({data: name}, taskColumns[name]);
            }))),
        });

        function reloadTasks(resetPaging) {
            tasksTable.ajax.reload(null, resetPaging === true);
        }

        function updateViewButtons() {
            $('.task-view-options [data-task-view]').each(function () {
                var selected = $(this).data('task-view') === treeSettings.view;
                $(this).toggleClass('active', selected);
                $(this).attr('aria-pressed', selected);
            });
            $('.task-live-toggle')
                .toggleClass('active', treeSettings.live)
                .attr('aria-pressed', treeSettings.live)
                .find('.status-dot').toggleClass('status-dot-live', treeSettings.live);
        }

        function updateLiveTimer() {
            window.clearInterval(liveTimer);
            liveTimer = null;
            if (!treeSettings.live) {
                return;
            }
            liveTimer = window.setInterval(function () {
                // Skip a beat while the tab is hidden or the last reload is out
                if (document.hidden || requestPending) {
                    return;
                }
                $('.tasks-page').addClass('tasks-live-refresh');
                reloadTasks(false);
            }, liveInterval);
        }

        tasksTable.on('preXhr.dt', function () {
            requestPending = true;
        });
        tasksTable.on('xhr.dt', function () {
            requestPending = false;
            $('.tasks-page').removeClass('tasks-live-refresh');
        });
        tasksTable.on('draw.dt', function () {
            // Rows are rebuilt on each draw, put focus back on the toggle used
            if (focusAfterDraw) {
                var target = document.querySelector(focusAfterDraw);
                focusAfterDraw = null;
                if (target) {
                    target.focus();
                }
            }
        });

        function redrawTree(focusSelector) {
            saveTaskTreeSettings(treeSettings);
            focusAfterDraw = focusSelector;
            reloadTasks(false);
        }

        // Tasks shut inside a subtree only stay shut while it is open: once
        // the subtree closes, or opens fully again, they're forgotten
        function forgetCollapsedBelow(taskId) {
            var rows = tasksTable.rows().data().toArray(),
                index = rows.findIndex(function (row) {
                    return row.uuid === taskId;
                });
            for (var i = index + 1; index !== -1 && i < rows.length && rows[i].tree &&
                    rows[i].tree.depth > rows[index].tree.depth; i += 1) {
                if (treeSettings.expanded[rows[i].uuid] === 0) {
                    delete treeSettings.expanded[rows[i].uuid];
                }
            }
        }

        function toggleTask(button, expand) {
            var taskId = button.getAttribute('data-task-id'),
                expanded = button.getAttribute('aria-expanded') === 'true';
            if (expand === expanded) {
                return;
            }
            if (expanded) {
                forgetCollapsedBelow(taskId);
            }
            if (!expanded) {
                setTaskExpanded(treeSettings.expanded, taskId, TASK_TREE_CHILDREN_PAGE);
            } else if (button.getAttribute('data-in-subtree') === 'true') {
                // A task above expands everything below it, so say this one stays shut
                setTaskExpanded(treeSettings.expanded, taskId, 0);
            } else {
                delete treeSettings.expanded[taskId];
            }
            redrawTree('.task-tree-toggle[data-task-id="' + CSS.escape(taskId) + '"]');
        }

        function toggleSubtree(taskId, focusSelector) {
            var current = String(treeSettings.expanded[taskId] || '');
            forgetCollapsedBelow(taskId);
            if (current.indexOf('all') === 0) {
                delete treeSettings.expanded[taskId];
            } else {
                setTaskExpanded(treeSettings.expanded, taskId, 'all');
            }
            redrawTree(focusSelector + '[data-task-id="' + CSS.escape(taskId) + '"]');
        }

        $('#tasks-table').on('click', '.task-tree-toggle', function (event) {
            if (event.altKey || event.shiftKey) {
                toggleSubtree(this.getAttribute('data-task-id'), '.task-tree-toggle');
            } else {
                toggleTask(this);
            }
        });
        $('#tasks-table').on('keydown', '.task-tree-toggle', function (event) {
            if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                event.preventDefault();
                toggleTask(this, event.key === 'ArrowRight');
            } else if (event.key === '*') {
                event.preventDefault();
                toggleSubtree(this.getAttribute('data-task-id'), '.task-tree-toggle');
            }
        });
        $('#tasks-table').on('click', '.task-tree-expand-all', function () {
            toggleSubtree(this.getAttribute('data-task-id'), '.task-tree-expand-all');
        });
        $('#tasks-table').on('click', '.task-tree-more', function () {
            var parentId = this.getAttribute('data-parent-id'),
                limit = (parseInt(this.getAttribute('data-limit'), 10) || 0) + TASK_TREE_CHILDREN_PAGE,
                current = String(treeSettings.expanded[parentId] || '');
            setTaskExpanded(treeSettings.expanded, parentId,
                current.indexOf('all') === 0 ? 'all:' + limit : limit);
            redrawTree('.task-tree-toggle[data-task-id="' + CSS.escape(parentId) + '"]');
        });

        $('.task-view-options [data-task-view]').on('click', function () {
            var view = $(this).data('task-view');
            if (view === treeSettings.view) {
                return;
            }
            treeSettings.view = view;
            saveTaskTreeSettings(treeSettings);
            updateViewButtons();
            // Pages count different records in each layout
            reloadTasks(true);
        });
        $('.task-live-toggle').on('click', function () {
            treeSettings.live = !treeSettings.live;
            saveTaskTreeSettings(treeSettings);
            updateViewButtons();
            updateLiveTimer();
        });

        updateViewButtons();
        updateLiveTimer();

        updateTaskStateButtons(taskStateFromSearch(tasksTable.search()));
        $('.task-state-filter').on('click', function () {
            var state = $(this).data('task-state');
            tasksTable.search(state ? 'state:' + state : '').draw();
            updateTaskStateButtons(state);
        });

        tasksTable.on('search.dt', function () {
            updateTaskStateButtons(taskStateFromSearch(tasksTable.search()));
        });

    });

}(jQuery));
