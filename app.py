from flask import Flask, Response, render_template_string
import time

app = Flask(__name__)

# We'll tail the Telethon log file (adjust the path if needed).
TELETHON_LOGFILE = "/tmp/telethon_listener.log"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>Real-Time Logs</title>
</head>
<body>
    <h1>Telethon Listener Logs</h1>
    <pre id="log"></pre>

    <script>
        const source = new EventSource("/stream_logs");
        source.onmessage = function(e) {
            // Append each new line to the log <pre>
            document.getElementById("log").append(e.data + "\\n");
        };
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return "Hello from Flask! Go to <a href='/logs'>/logs</a> to view real-time logs."

@app.route("/logs")
def logs_page():
    return render_template_string(HTML_TEMPLATE)

@app.route("/stream_logs")
def stream_logs():
    """
    Streams the tail of TELETHON_LOGFILE via SSE.
    """
    def generate():
        # Start at the end of the file
        with open(TELETHON_LOGFILE, "r", encoding="utf-8") as f:
            f.seek(0, 2)  # go to the end of the file

            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.2)  # Polling interval
                    continue
                # SSE "data: <line>\n\n"
                yield f"data: {line.rstrip()}\n\n"

    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    # Run on 0.0.0.0 so Docker/host can see it
    app.run(host="0.0.0.0", port=8080, debug=False)
