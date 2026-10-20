# Recovered LAYA support material

install.sh and install.log came from D:/Coding/laya-serve on 1 October. The log ends in a failed PyTorch download/extraction and does not establish a working server.

ask_laya.py, ports.json and visp.md came from D:/Coding/Tools Utilities/ask Laya on 2 October. The client expects http://127.0.0.1:8000/v1/systemone, overridable with ASK_LAYA_ENDPOINT. Its optional wrapper service on port 8792 still needs that model endpoint; it does not load a model itself. ProgressDesk's separate adapter reads PROGRESSDESK_DECISIONS at import time.

No server startup command or model-weights location was found in the recovered material. During the review port 8000 was not listening. The current VISP parks LAYA-assisted housekeeping; read implementation plan section 0A before making this service a dogfood bootstrap prerequisite.
