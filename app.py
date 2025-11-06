import os
from app import app

if __name__ == '__main__':
    #app.run(debug=True)
    port = int(os.environ.get("PORT", 5000))  # pak PORT van Render, anders 5000 lokaal
    #app.run(host="0.0.0.0", port=port, debug=False)
