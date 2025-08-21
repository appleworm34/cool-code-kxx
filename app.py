from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello World!'

@app.route('/investigate')
def spy():
    networks = {
        "networks": [
            {
            "networkId": "network1",
            "network": [
                {
                "spy1": "Karina",
                "spy2": "Giselle"
                },
                {
                "spy1": "Karina",
                "spy2": "Winter"
                },
                {
                "spy1": "Karina",
                "spy2": "Ningning"
                },
                {
                "spy1": "Giselle",
                "spy2": "Winter"
                }
            ]
            }
        ]
    }
    return 'Hello World!'


if __name__ == '__main__':
    app.run()