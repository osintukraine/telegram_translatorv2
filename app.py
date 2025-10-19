from flask import Flask, Response, render_template_string, jsonify, request
import time
import os
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)

# Paths
TELETHON_LOGFILE = "/tmp/telethon_listener.out.log"
DATABASE_PATH = "src/messages.db"

# Database helper functions
def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

def get_statistics():
    """Get statistics from the database."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Total processed messages
        cursor.execute("SELECT COUNT(*) as count FROM messages")
        total_messages = cursor.fetchone()['count']

        # Check if spam_filtered table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='spam_filtered'")
        spam_table_exists = cursor.fetchone() is not None

        if spam_table_exists:
            # Total spam filtered
            cursor.execute("SELECT COUNT(*) as count FROM spam_filtered")
            total_spam = cursor.fetchone()['count']

            # Spam by type
            cursor.execute("""
                SELECT spam_type, COUNT(*) as count
                FROM spam_filtered
                GROUP BY spam_type
            """)
            spam_by_type = {row['spam_type']: row['count'] for row in cursor.fetchall()}

            # Last 7 days activity
            seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                SELECT DATE(date) as day, COUNT(*) as count
                FROM messages
                WHERE date >= ?
                GROUP BY DATE(date)
                ORDER BY day
            """, (seven_days_ago,))
            messages_per_day = [{'date': row['day'], 'count': row['count']} for row in cursor.fetchall()]

            cursor.execute("""
                SELECT DATE(date) as day, COUNT(*) as count
                FROM spam_filtered
                WHERE date >= ?
                GROUP BY DATE(date)
                ORDER BY day
            """, (seven_days_ago,))
            spam_per_day = [{'date': row['day'], 'count': row['count']} for row in cursor.fetchall()]
        else:
            # Spam table doesn't exist yet
            total_spam = 0
            spam_by_type = {}
            messages_per_day = []
            spam_per_day = []

        return {
            'total_messages': total_messages,
            'total_spam': total_spam,
            'total_translated': total_messages,  # All non-spam messages are translated
            'spam_by_type': spam_by_type,
            'messages_per_day': messages_per_day,
            'spam_per_day': spam_per_day,
            'spam_table_exists': spam_table_exists
        }
    finally:
        conn.close()

def get_spam_messages(limit=100, offset=0, spam_type=None):
    """Get paginated spam messages."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Check if spam_filtered table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='spam_filtered'")
        if cursor.fetchone() is None:
            return {'messages': [], 'total': 0, 'has_more': False}

        # Build query
        if spam_type:
            query = """
                SELECT * FROM spam_filtered
                WHERE spam_type = ?
                ORDER BY date DESC
                LIMIT ? OFFSET ?
            """
            params = (spam_type, limit, offset)
            count_query = "SELECT COUNT(*) as count FROM spam_filtered WHERE spam_type = ?"
            count_params = (spam_type,)
        else:
            query = """
                SELECT * FROM spam_filtered
                ORDER BY date DESC
                LIMIT ? OFFSET ?
            """
            params = (limit, offset)
            count_query = "SELECT COUNT(*) as count FROM spam_filtered"
            count_params = ()

        cursor.execute(query, params)
        messages = [dict(row) for row in cursor.fetchall()]

        cursor.execute(count_query, count_params)
        total = cursor.fetchone()['count']

        return {
            'messages': messages,
            'total': total,
            'has_more': (offset + limit) < total
        }
    finally:
        conn.close()

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Translator Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        /* Dark theme customization */
        body { background: #0f172a; }
        .log-line { font-family: 'Courier New', monospace; font-size: 13px; }
        .log-info { color: #4ade80; }
        .log-debug { color: #94a3b8; }
        .log-warning { color: #fbbf24; }
        .log-error { color: #f87171; }
    </style>
</head>
<body class="bg-slate-900 text-slate-100" x-data="dashboard()" x-init="init()">
    <div class="min-h-screen">
        <!-- Header -->
        <header class="bg-slate-800 border-b border-slate-700 p-4">
            <h1 class="text-2xl font-bold text-white">Telegram Translator Dashboard</h1>
            <p class="text-slate-400 text-sm">Monitor messages, spam, and translation activity</p>
        </header>

        <!-- Tab Navigation -->
        <div class="bg-slate-800 border-b border-slate-700">
            <nav class="container mx-auto px-4">
                <ul class="flex space-x-2">
                    <li>
                        <button @click="activeTab = 'logs'"
                                :class="activeTab === 'logs' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'"
                                class="px-6 py-3 font-medium transition-colors">
                            📋 Logs
                        </button>
                    </li>
                    <li>
                        <button @click="activeTab = 'spam'"
                                :class="activeTab === 'spam' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'"
                                class="px-6 py-3 font-medium transition-colors">
                            🚫 Spam Filtered
                            <span x-show="stats.total_spam > 0"
                                  class="ml-2 px-2 py-1 text-xs bg-red-500 rounded-full"
                                  x-text="stats.total_spam"></span>
                        </button>
                    </li>
                    <li>
                        <button @click="activeTab = 'stats'"
                                :class="activeTab === 'stats' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'"
                                class="px-6 py-3 font-medium transition-colors">
                            📊 Statistics
                        </button>
                    </li>
                </ul>
            </nav>
        </div>

        <!-- Tab Content -->
        <div class="container mx-auto p-4">
            <!-- Logs Tab -->
            <div x-show="activeTab === 'logs'" class="space-y-4">
                <div class="bg-slate-800 rounded-lg p-6">
                    <h2 class="text-xl font-semibold mb-4">Real-Time Logs</h2>
                    <div class="bg-slate-900 rounded p-4 h-[600px] overflow-y-auto" id="log-container">
                        <div id="log" class="space-y-1"></div>
                    </div>
                </div>
            </div>

            <!-- Spam Tab -->
            <div x-show="activeTab === 'spam'" class="space-y-4">
                <div class="bg-slate-800 rounded-lg p-6">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-xl font-semibold">Filtered Spam Messages</h2>
                        <div class="flex gap-2">
                            <select x-model="spamFilter" @change="loadSpam()"
                                    class="bg-slate-700 border border-slate-600 rounded px-3 py-2 text-sm">
                                <option value="">All Types</option>
                                <option value="financial">Financial</option>
                                <option value="off-topic">Off-Topic</option>
                            </select>
                            <button @click="loadSpam()"
                                    class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded text-sm">
                                Refresh
                            </button>
                        </div>
                    </div>

                    <div x-show="!stats.spam_table_exists" class="bg-yellow-900/20 border border-yellow-500 rounded p-4 mb-4">
                        <p class="text-yellow-300">⚠️ Spam filtering table not initialized yet. Start the listener to create it.</p>
                    </div>

                    <div x-show="spam.messages.length === 0 && stats.spam_table_exists"
                         class="text-slate-400 text-center py-12">
                        No spam messages filtered yet.
                    </div>

                    <div class="space-y-3">
                        <template x-for="msg in spam.messages" :key="msg.id">
                            <div class="bg-slate-900 rounded p-4 border border-slate-700">
                                <div class="flex justify-between items-start mb-2">
                                    <div>
                                        <span class="text-xs px-2 py-1 rounded"
                                              :class="msg.spam_type === 'financial' ? 'bg-red-900 text-red-300' : 'bg-orange-900 text-orange-300'"
                                              x-text="msg.spam_type.toUpperCase()"></span>
                                        <span class="text-slate-400 text-sm ml-2" x-text="formatDate(msg.date)"></span>
                                    </div>
                                    <a :href="msg.link" target="_blank"
                                       class="text-blue-400 hover:text-blue-300 text-sm">
                                        View on Telegram →
                                    </a>
                                </div>
                                <p class="text-sm text-slate-300 mb-2" x-text="msg.reason"></p>
                                <div class="bg-slate-800 rounded p-3">
                                    <p class="text-xs text-slate-400 mb-1">Content Preview:</p>
                                    <p class="text-sm text-slate-200 font-mono" x-text="msg.content_preview"></p>
                                </div>
                            </div>
                        </template>
                    </div>

                    <div x-show="spam.total > 50" class="mt-4 flex justify-center gap-2">
                        <button @click="spamPage = Math.max(0, spamPage - 1); loadSpam()"
                                :disabled="spamPage === 0"
                                class="bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 px-4 py-2 rounded">
                            Previous
                        </button>
                        <span class="text-slate-400 px-4 py-2">
                            Page <span x-text="spamPage + 1"></span>
                        </span>
                        <button @click="spamPage++; loadSpam()"
                                :disabled="!spam.has_more"
                                class="bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 px-4 py-2 rounded">
                            Next
                        </button>
                    </div>
                </div>
            </div>

            <!-- Statistics Tab -->
            <div x-show="activeTab === 'stats'" class="space-y-4">
                <!-- Summary Cards -->
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div class="bg-slate-800 rounded-lg p-6">
                        <h3 class="text-sm text-slate-400 mb-2">Total Messages Processed</h3>
                        <p class="text-3xl font-bold text-green-400" x-text="stats.total_messages"></p>
                    </div>
                    <div class="bg-slate-800 rounded-lg p-6">
                        <h3 class="text-sm text-slate-400 mb-2">Translated & Forwarded</h3>
                        <p class="text-3xl font-bold text-blue-400" x-text="stats.total_translated"></p>
                    </div>
                    <div class="bg-slate-800 rounded-lg p-6">
                        <h3 class="text-sm text-slate-400 mb-2">Spam Filtered</h3>
                        <p class="text-3xl font-bold text-red-400" x-text="stats.total_spam"></p>
                    </div>
                </div>

                <!-- Spam Breakdown -->
                <div class="bg-slate-800 rounded-lg p-6">
                    <h2 class="text-xl font-semibold mb-4">Spam Breakdown by Type</h2>
                    <div x-show="Object.keys(stats.spam_by_type).length === 0" class="text-slate-400 text-center py-8">
                        No spam data available yet.
                    </div>
                    <div class="grid grid-cols-2 gap-4" x-show="Object.keys(stats.spam_by_type).length > 0">
                        <template x-for="[type, count] in Object.entries(stats.spam_by_type)" :key="type">
                            <div class="bg-slate-900 rounded p-4">
                                <p class="text-sm text-slate-400 capitalize" x-text="type"></p>
                                <p class="text-2xl font-bold text-white" x-text="count"></p>
                            </div>
                        </template>
                    </div>
                </div>

                <!-- Activity Chart -->
                <div class="bg-slate-800 rounded-lg p-6">
                    <h2 class="text-xl font-semibold mb-4">Last 7 Days Activity</h2>
                    <canvas id="activityChart" class="max-h-80"></canvas>
                </div>
            </div>
        </div>
    </div>

    <script>
        function dashboard() {
            return {
                activeTab: 'logs',
                stats: {
                    total_messages: 0,
                    total_spam: 0,
                    total_translated: 0,
                    spam_by_type: {},
                    messages_per_day: [],
                    spam_per_day: [],
                    spam_table_exists: false
                },
                spam: {
                    messages: [],
                    total: 0,
                    has_more: false
                },
                spamFilter: '',
                spamPage: 0,
                chart: null,
                logSource: null,

                init() {
                    this.loadStats();
                    this.loadSpam();
                    this.initLogs();
                },

                async loadStats() {
                    try {
                        const response = await fetch('/api/stats');
                        this.stats = await response.json();
                        this.$nextTick(() => this.updateChart());
                    } catch (error) {
                        console.error('Failed to load stats:', error);
                    }
                },

                async loadSpam() {
                    try {
                        const offset = this.spamPage * 50;
                        const url = `/api/spam?limit=50&offset=${offset}${this.spamFilter ? '&type=' + this.spamFilter : ''}`;
                        const response = await fetch(url);
                        this.spam = await response.json();
                    } catch (error) {
                        console.error('Failed to load spam:', error);
                    }
                },

                initLogs() {
                    this.logSource = new EventSource('/stream_logs');
                    this.logSource.onmessage = (e) => {
                        const line = e.data;
                        const lineElement = document.createElement('div');
                        lineElement.className = 'log-line';

                        if (line.includes('ERROR')) {
                            lineElement.classList.add('log-error');
                        } else if (line.includes('WARNING') || line.includes('WARN')) {
                            lineElement.classList.add('log-warning');
                        } else if (line.includes('INFO')) {
                            lineElement.classList.add('log-info');
                        } else if (line.includes('DEBUG')) {
                            lineElement.classList.add('log-debug');
                        }

                        lineElement.textContent = line;
                        document.getElementById('log').appendChild(lineElement);

                        const container = document.getElementById('log-container');
                        container.scrollTop = container.scrollHeight;
                    };
                },

                updateChart() {
                    const ctx = document.getElementById('activityChart');
                    if (!ctx) return;

                    // Prepare data for chart
                    const dates = this.stats.messages_per_day.map(d => d.date);
                    const messageCounts = this.stats.messages_per_day.map(d => d.count);

                    // Create spam data aligned with message dates
                    const spamMap = new Map(this.stats.spam_per_day.map(d => [d.date, d.count]));
                    const spamCounts = dates.map(date => spamMap.get(date) || 0);

                    if (this.chart) {
                        this.chart.destroy();
                    }

                    this.chart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: dates,
                            datasets: [
                                {
                                    label: 'Messages Processed',
                                    data: messageCounts,
                                    borderColor: '#4ade80',
                                    backgroundColor: 'rgba(74, 222, 128, 0.1)',
                                    tension: 0.3
                                },
                                {
                                    label: 'Spam Filtered',
                                    data: spamCounts,
                                    borderColor: '#f87171',
                                    backgroundColor: 'rgba(248, 113, 113, 0.1)',
                                    tension: 0.3
                                }
                            ]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: true,
                            plugins: {
                                legend: {
                                    labels: { color: '#cbd5e1' }
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: { color: '#94a3b8' },
                                    grid: { color: '#334155' }
                                },
                                x: {
                                    ticks: { color: '#94a3b8' },
                                    grid: { color: '#334155' }
                                }
                            }
                        }
                    });
                },

                formatDate(dateStr) {
                    return new Date(dateStr).toLocaleString();
                }
            }
        }
    </script>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>Real-Time Logs</title>
    <style>
        body {
            background-color: #1E1E1E;   /* Dark theme background */
            color: #CFCFCF;             /* Light text */
            font-family: Consolas, monospace;
            margin: 0;
            padding: 0;
        }
        h1 {
            background-color: #333;
            padding: 10px;
            margin: 0;
        }
        #log-container {
            padding: 10px;
        }
        #log {
            white-space: pre-wrap;       /* Wrap long lines */
            word-wrap: break-word;       /* Break long words */
        }
        /* Example color classes for different log levels */
        .info    { color: #0f0; }  /* green */
        .debug   { color: #999; }  /* grayish */
        .warning { color: #ff0; }  /* yellow */
        .error   { color: #f00; }  /* red */
    </style>
</head>
<body>
    <h1>Telethon Listener Logs</h1>
    <div id="log-container">
      <div id="log"></div>
    </div>

    <script>
        // Connect to the Server-Sent Events endpoint
        const source = new EventSource("/stream_logs");

        source.onmessage = function(e) {
            const line = e.data;
            
            // Create a new div for each log line
            const lineElement = document.createElement('div');

            // Let’s do a simple check for keywords:
            // e.g. if line includes "INFO", "ERROR", etc.
            // You could refine this logic with regex to parse actual log formats.
            if (line.includes("ERROR")) {
                lineElement.className = "error";
            } else if (line.includes("WARNING") || line.includes("WARN")) {
                lineElement.className = "warning";
            } else if (line.includes("INFO")) {
                lineElement.className = "info";
            } else if (line.includes("DEBUG")) {
                lineElement.className = "debug";
            }
            
            // Set the text of this line
            lineElement.textContent = line;
            // Append to our <div id="log">
            document.getElementById("log").appendChild(lineElement);

            // Optionally auto-scroll to bottom
            document.getElementById("log-container").scrollTop = 
                document.getElementById("log-container").scrollHeight;
        };
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    """Redirect to dashboard."""
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route("/api/stats")
def api_stats():
    """Get statistics as JSON."""
    try:
        stats = get_statistics()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/api/spam")
def api_spam():
    """Get spam messages as JSON with pagination."""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        spam_type = request.args.get('type')

        result = get_spam_messages(limit=limit, offset=offset, spam_type=spam_type)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/logs")
def logs_page():
    return render_template_string(HTML_TEMPLATE)

@app.route("/stream_logs")
def stream_logs():
    def generate():
        if not os.path.exists(TELETHON_LOGFILE):
            # Optionally create an empty file
            open(TELETHON_LOGFILE, 'w').close()

        with open(TELETHON_LOGFILE, "r", encoding="utf-8") as f:
            # First, send all existing logs (last 100 lines)
            # Seek to beginning to read existing content
            f.seek(0)
            all_lines = f.readlines()
            # Send last 100 lines of existing logs
            for line in all_lines[-100:]:
                yield f"data: {line.rstrip()}\n\n"

            # Now continue tailing new lines
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                # SSE format: "data: <line>\n\n"
                yield f"data: {line.rstrip()}\n\n"
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    # Run on 0.0.0.0 so Docker/host can see it
    app.run(host="0.0.0.0", port=8080, debug=False)
