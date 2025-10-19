from flask import Flask, Response, render_template_string
import time
import os

app = Flask(__name__)

# We'll tail the Telethon log file (adjust the path if needed).
TELETHON_LOGFILE = "/tmp/telethon_listener.out.log"

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
    return (
        "Hello from Flask!<br>"
        "Go to <a href='/logs'>/logs</a> to view real-time logs."
    )

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
